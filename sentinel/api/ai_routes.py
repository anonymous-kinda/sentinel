"""The assistant's HTTP surface (M5, ADR-007).

    GET  /api/ai/status        tier, the reason for it, configured providers
    POST /api/ai/ask           {text} -> answer, question back, or draft
    POST /api/ai/confirm       {draft_id, rationale} -> signed DECISION
    GET  /api/ai/audit         the hash-chained record of asks and confirms
    GET  /api/ai/audit/verify  recompute that chain

A hosted provider is loaded only when its key is set, and its SDK only
then; a bundle without the `ai` extra still serves the local tier.
"""

from __future__ import annotations

import dataclasses
import importlib
import os
import pathlib

from fastapi import FastAPI, HTTPException, Request

from ..ai.assistant import Assistant
from ..ai.tools import ToolError, ToolRegistry
from ..audit import AuditLog
from ..obs import get_logger
from .bodies import json_object, read_only_safe
from .identity import operator_of

log = get_logger(__name__)

MAX_QUESTION_CHARS = 2000
CONFIRM_ERRORS = {"unknown_draft": 404, "stale_draft": 409}
# name -> (key variable, module, class, pinned model constant)
PROVIDERS = {
    "jev": ("TYPESAFE_API_KEY", "sentinel.ai.router_jev", "JevRouter", "JEV_MODEL"),
    "claude": ("ANTHROPIC_API_KEY", "sentinel.ai.narrate_claude", "ClaudeNarrator", "CLAUDE_MODEL"),
}


def _load_provider(name: str) -> tuple[object | None, str | None]:
    key_var, module_name, class_name, model_name = PROVIDERS[name]
    if not os.environ.get(key_var):
        return None, None
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        log.warning("Hosted AI SDK not installed", provider=name, error=type(exc).__name__)
        return None, None
    return getattr(module, class_name).from_env(), getattr(module, model_name)


def _link_state(node) -> tuple:
    """The link hosted AI would cross. An edge measures it (its hub link);
    a hub or standalone node has no upstream link to measure."""
    if node.settings.role == "edge":
        return (lambda: node.link.state.value), "measured on the hub link"
    return (lambda: "CONNECTED"), f"assumed: no upstream link on a {node.settings.role} node"


def _question(body) -> str:
    text = str(body.get("text") or "").strip() if isinstance(body, dict) else ""
    if not 0 < len(text) <= MAX_QUESTION_CHARS:
        raise HTTPException(422, f"a question is 1 to {MAX_QUESTION_CHARS} characters")
    return text


def register(app: FastAPI, node) -> None:
    settings = node.settings
    if not settings.ai:

        @app.get("/api/ai/status")
        def ai_disabled() -> dict:
            return {"enabled": False}

        return

    tools = ToolRegistry(
        node.conjunctions,
        node.ops,
        node.link,
        sync_status=lambda: node.sync_agent.status() if node.sync_agent else {},
    )
    jev, jev_model = _load_provider("jev")
    llm, claude_model = _load_provider("claude")
    link_state, link_source = _link_state(node)
    assistant = Assistant(
        tools,
        link_state=link_state,
        marking=settings.marking,
        cloud_opt_in=settings.ai_cloud,
        audit=AuditLog(pathlib.Path(settings.var_dir) / "ai-audit.jsonl"),
        clock=node.clock,
        jev=jev,
        llm=llm,
    )
    node.extensions["ai"] = assistant
    node.extensions.setdefault("modules", []).append("ai")

    @app.get("/api/ai/status")
    def ai_status() -> dict:
        return {
            "enabled": True,
            "tier": assistant.tier(),
            "link_source": link_source,
            "cloud_opt_in": settings.ai_cloud,
            "providers": {"jev": jev is not None, "claude": llm is not None},
            "models": {"jev": jev_model, "claude": claude_model},
            "min_confidence": assistant.min_confidence,
        }

    @app.post("/api/ai/ask")
    @read_only_safe
    async def ai_ask(request: Request) -> dict:
        text = _question(await json_object(request))
        answer = await assistant.ask(text, operator_of(request, settings.node_id))
        return answer.to_dict()

    @app.post("/api/ai/confirm", status_code=201)
    async def ai_confirm(request: Request) -> dict:
        body = await json_object(request)
        try:
            return await assistant.confirm(
                str(body.get("draft_id", "")),
                operator_of(request, settings.node_id),
                rationale=str(body.get("rationale", ""))[:2000],
            )
        except ToolError as exc:
            raise HTTPException(CONFIRM_ERRORS.get(exc.code, 422), exc.code) from exc

    @app.get("/api/ai/audit")
    def ai_audit(limit: int = 50) -> list[dict]:
        return assistant.audit.entries()[-max(1, min(limit, 500)) :]

    @app.get("/api/ai/audit/verify")
    def ai_audit_verify() -> dict:
        return dataclasses.asdict(assistant.audit.verify())
