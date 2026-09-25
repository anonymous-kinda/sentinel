#!/usr/bin/env python3
"""One real call per hosted-AI provider whose key is set (`make ai-live-check`).

    TYPESAFE_API_KEY=... ANTHROPIC_API_KEY=... uv run python scripts/ai_live_check.py

Jev routes eval case ass-01 against the exercise scenario `make ai-eval`
uses. Claude phrases the facts that case's labelled tool call returns. A key
that is not set is reported, not failed; a configured call that fails exits
1. Nothing is written: publishing numbers stays with `make ai-eval`. The
logic is in sentinel/ai/live_check.py.
"""

import asyncio
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.ai_eval import EVAL_SET, exercise_service, routing_context  # noqa: E402
from sentinel.ai import live_check  # noqa: E402
from sentinel.ai.evaluation import expected_args, load_cases  # noqa: E402
from sentinel.ai.narrate_claude import ClaudeNarrator  # noqa: E402
from sentinel.ai.router_jev import JevRouter  # noqa: E402
from sentinel.ai.tools import ToolRegistry  # noqa: E402
from sentinel.obs import configure_logging  # noqa: E402

CASE_ID = "ass-01"  # "How risky is the 118 conjunction?": get_assessment on 99118


def checks(jev_transport=None, claude_transport=None) -> list[live_check.Check]:
    case = next(c for c in load_cases(EVAL_SET) if c.id == CASE_ID)
    service = exercise_service()
    context = routing_context(service)
    # get_assessment reads the conjunction service alone; ops, link and sync are never consulted.
    tools = ToolRegistry(service, ops=None, link=None, sync_status=dict)
    facts = tools.execute(case.tool, expected_args(case, context))
    return [
        live_check.jev_check(lambda: JevRouter.from_env(transport=jev_transport), case.text, context),
        live_check.claude_check(
            lambda: ClaudeNarrator.from_env(transport=claude_transport), case.text, case.tool, facts
        ),
    ]


def main(jev_transport=None, claude_transport=None) -> int:
    """The transports are httpx2 mock transports in tests; None makes real calls."""
    results = asyncio.run(live_check.run_checks(checks(jev_transport, claude_transport), os.environ))
    print(live_check.render(results))
    return live_check.exit_code(results)


if __name__ == "__main__":
    configure_logging()
    sys.exit(main())
