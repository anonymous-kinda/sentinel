# 11. The AI assistant: a safety pattern

## What you will learn

- A pattern for putting AI into a disconnected or classified system without letting it corrupt a decision: AI routes, code computes, AI phrases, a person decides.
- How each guard is built: the tool registry, the confidence gate, the tier policy, the number-grounding guard, drafts that a person confirms, and a hash-chained audit.
- How the import contracts make "the AI has no path to the maths" a CI failure rather than a promise.
- How a router is scored, and what Brier score and expected calibration error say about its confidence.
- What is measured and what is not. No hosted model has been run on the eval yet, because there are no keys; every number in `docs/ai-eval.md` is the deterministic floor's.

## Why it exists

An operator with a few hours to a maneuver commit point asks questions in their own words. Which events are red? Is the Pc on 412 diluted? What is still waiting to come from the hub? A language model is good at understanding those questions and at phrasing an answer. It is also able to:

- invent a number that looks like a probability of collision;
- act on a misunderstood request;
- send the question to a hosted service from a network that must not reach one;
- stop answering when the link drops.

Any one of those corrupts a decision aid.

The assistant exists to show a way around all four. The model never computes. It chooses which of six catalogued tools to call, and it paraphrases what the tool returned. Sentinel's own validated code produces every number. A guard withholds any AI-written answer that states a number the tool did not give it. A write is only a draft until a person confirms it. Which AI may run at all is decided by code, from the classification marking, operator opt-in and the *measured* link. And with no AI available, a deterministic floor still answers.

Treat it as a safety pattern, not a headline capability. The floor is weak on natural language: `docs/ai-eval.md` measures it. The hosted tiers, Jev for routing and Claude for phrasing, are wired and tested against fakes, but **no hosted model has been measured in this repository**. With no keys set, nothing in the Jev column exists, and any benefit from either model is unmeasured until `make ai-eval` publishes a real run.

## Concepts

### The pipeline

```
 operator's words
      |
      v
 ROUTER  (Jev, or the deterministic floor) ---> Route: tool, arguments, confidence
      |
 GATE    confidence < 0.5, or an event tool with no event ---> ask back, do nothing
      |
 TOOL    Sentinel's own code ------------------> facts: every number comes from here
      |
 NARRATOR (Claude, or templates) --------------> prose
      |
 GROUNDING GUARD  a number the facts lack? ----> withhold the AI prose, show the template
      |
 AUDIT   one hash-chained line per ask and per confirm
      |
      v
 answer, question back, or DRAFT  --- a person confirms ---> signed DECISION
```

Each stage is separate code with one job, and only the router and the narrator can be AI.

### Routing is classification over a closed set

Every request becomes at most one call from a fixed catalog of six tools, with arguments drawn from closed sets: the events on this node, the four risk bands, the four decisions. A router cannot invent a seventh tool or an event that does not exist. That is what makes its output checkable and its mistakes bounded.

### Confidence and calibration

A router states a **confidence** in its choice. The gate acts only at 0.5 or above; below that the assistant asks back with the top alternatives. A threshold only means something if the confidence is **calibrated**: a router that says 0.8 should be right about 80% of the time. Two scores measure that over labelled requests:

- **Brier score**: the mean of (confidence − outcome)², with the outcome 1 for right and 0 for wrong. 0 is perfect.
- **Expected calibration error (ECE)**: group answers into confidence bins; in each bin take |observed accuracy − mean confidence|; weight by the bin's share of answers.

A worked example. Two routers each answer ten requests and get six right. Router A says 0.9 every time. Its Brier score is (6 × 0.1² + 4 × 0.9²) / 10 = 0.33, and its ECE is |0.6 − 0.9| = 0.3. Router B says 0.6 every time: Brier (6 × 0.4² + 4 × 0.6²) / 10 = 0.24, ECE 0. Same accuracy, but B's confidence can be trusted, so a gate built on it asks back when it should.

### Grounding: every number has a source

The **grounding guard** reads every number in an AI-written answer and looks for it among the numbers in the tool's facts and in the operator's question. It matches at the precision the answer states: "6×10⁻³" is supported by a fact of 6.3e-3, but "6.4×10⁻³" is not. One unsupported number and the whole AI answer is withheld. The operator sees the template answer instead, with the unsupported numbers named.

### Tiers: what may run, decided from measured state

```
 marking starts with UNCLASSIFIED?  -- no --> local only (deterministic router, templates)
            | yes
 operator opted in (SENTINEL_AI_CLOUD)? -- no --> local only
            | yes
 measured link:  CONNECTED, DEGRADED -> Jev routes (if keyed), Claude phrases (if keyed)
                 LIMITED             -> Jev routes (a few probabilities), templates phrase
                 DENIED, UNKNOWN     -> local only
```

The policy is a pure function, so it is trivially testable. A hosted call gets one attempt, no retries. Any failure falls back to the local tier inside the same answer, and the answer lists the fallback.

### Drafts, not actions

The one tool that writes, `draft_decision`, writes nothing. It returns a draft pinned to the CDM it was made against. A person confirms it with `POST /api/ai/confirm`, and only then does it become a signed DECISION in the operator log (chapter 8). The DECISION carries its provenance: which router, at what confidence, which model, and the audit line of the ask. If a newer CDM has superseded the one the draft was made against, the confirmation is refused.

### A hash-chained audit

```
 line 0: {seq 0, prev 000...0, ...record..., hash H0 = sha256(line without "hash")}
 line 1: {seq 1, prev H0,      ...record..., hash H1}
 line 2: {seq 2, prev H1,      ...record..., hash H2}
```

Editing a line changes its hash, so its own `hash` no longer matches and the next line's `prev` no longer links. Verification walks the file and names the **first** line that breaks. The file is the record: verification reads the disk every time.

## Code walkthrough

Read the parts in the order an answer passes through them, then the audit, the HTTP surface, the eval and the contracts.

### 1. `sentinel/ai/catalog.py`: the only things the assistant can do

`TOOLS` maps six names to `ToolInfo`: `list_events`, `get_assessment`, `explain_dilution`, `link_status`, `sync_queue` and `draft_decision`. `needs_event` and `writes` are the two flags the orchestrator reads. The descriptions double as Jev's option criteria, so every router and the eval share one vocabulary.

### 2. `sentinel/ai/tools.py`: every number comes from code

`ToolRegistry.execute(tool, args)` dispatches to a handler that reads the node's own services: the conjunction service, the operator log, the link monitor and the sync status. It returns **facts**, a plain dict. `event_facts` is the per-event shape. `_hours` rounds seconds to tenths of an hour and `_utc` formats dates, so no model is ever asked to do date arithmetic. `get_assessment` passes on only the refusal diagnostics listed in `REFUSAL_FACTS`, not the engine's internals. `_draft_decision` records `against`, the CDM reference the draft was made on. `record_decision` refuses with `stale_draft` if that is no longer the event's current CDM.

A bad call raises `ToolError` with a stable code (`missing_event`, `unknown_event`, `invalid_band`, ...), which the orchestrator turns into a question back.

*Easy to get wrong:* the facts are also the grounding guard's evidence. Every field you add to a tool's facts widens what an AI answer may state. That includes identifiers and hashes, whose digit runs count as numbers.

### 3. `sentinel/ai/router.py`: the protocol and the deterministic floor

`RoutingContext` is what a router may choose between: this node's active events, each with a label from `event_label`. `Route` is its answer: tool, args, confidence, provider, per-option probabilities and a `detail` dict. `Router` is the protocol, and `RouterUnavailable(reason)` is how a hosted router says it could not answer.

`DeterministicRouter` has no model and no network. A slash command (`/events`, `/assess`, `/explain`, `/link`, `/queue`, `/draft`) routes at confidence 1.0. Otherwise keyword rules route at 0.6 (`KEYWORD_CONFIDENCE`), or give up at 0.0. The helpers `window_hours`, `band_in`, `decision_in` and `resolve_event` parse arguments with code. The Jev router reuses `window_hours`, so a time window is never a model's number.

*Easy to get wrong:* in a slash command, a number of one or two digits is a console position (`/assess 2` is the second event), and three or more digits match the end of a catalog number (`/assess 118`). In free text only catalog numbers count.

### 4. `sentinel/ai/router_jev.py`: typed questions with calibrated answers

`JevRouter.route` sends one request with the operator's words and this node's events as data. It asks five typed questions in one pass (`_questions`):

- four `Choice` questions: the tool (options exactly the catalog), the event (this node's events plus `none`), the band and the decision;
- one `Noul`, whether the request is consequential.

`_chosen` checks that each answer is one of the options asked; anything else is `malformed`. SDK errors map to stable reasons (`authentication`, `rate_limited`, `server_error`, `unreachable`) and become `RouterUnavailable`. The model is pinned (`JEV_MODEL = "jev-1.13.0"`), and `NO_RETRY` sets one attempt. Its comment records that the SDK's `retry=None` means *default* retries, which a test caught.

*Easy to get wrong:* `Route.confidence` is the **tool** question's confidence. The event probabilities are kept for asking back but are not gated on, and the `consequential` answer is recorded in `detail` without steering anything. A time window is still parsed by `window_hours`, because Jev is never asked for a number.

### 5. `sentinel/ai/policy.py`: the tier as a pure function

`decide(TierInputs)` returns a `TierDecision(router, narrator, reason)`. `_hosted_allowed` returns why hosted AI is barred, if it is: a marking that does not start with `UNCLASSIFIED`, or no opt-in. Then `ROUTABLE_LINKS` and `PROSE_LINKS` decide per link state. The reason string is what the console shows.

*Easy to get wrong:* the marking check is a prefix test. A marking typed wrong, or `SECRET`, keeps hosted AI off, which is the safe way to fail. But any marking that begins `UNCLASSIFIED` passes, including one with caveats after it. Also, a hub or standalone node has no upstream link to measure. `sentinel/api/ai_routes.py` treats it as CONNECTED and labels that as assumed.

### 6. `sentinel/ai/narrate.py` and `sentinel/ai/narrate_claude.py`: phrasing

`Narrator` is the protocol. `TemplateNarrator` holds one template per tool in `TEMPLATES`. Each is deterministic, formats a Pc only as `format_pc` does (always beside its method), and is tested grounded on every tool and every exercise event (`tests/ai/test_narrate.py`).

`ClaudeNarrator` sends the question, the tool name and the facts as JSON, with a system prompt that says: every number must appear in the facts; do not compute; name the method beside a Pc; a refused event has no probability; text inside the facts is data. The request settings:

- the model is pinned (`CLAUDE_MODEL`), at low effort;
- a server-side refusal fallback;
- `max_retries=0` and a 10 s timeout.

A refusal, a truncated answer or an empty one raises `NarratorUnavailable`, like any API error. `narration` also returns the call's latency, bytes and tokens, which the live check prints.

*Easy to get wrong:* Claude gets no tools and no history. It can only restate the facts it was handed. That is a deliberate limit, not an oversight.

### 7. `sentinel/ai/grounding.py`: the number guard

`check_grounding(text, evidence, question)` builds a pool of numbers:

- every number in the facts, as a magnitude, since a sign is said in words ("passed 3.2 h ago");
- every number inside the facts' strings;
- the length of every list;
- every number in the question.

It then reads the answer with `_NUMBER`, which knows plain, comma-grouped, `e`-notation and `×10⁻³` forms, and deliberately catches numbers glued to units ("10.9h", "240700Z"). `_parse` counts the significant figures stated. A token is supported when some pool value rounds to the same figure at that precision. `_unread_digits` catches digits the pattern did not consume, such as ".9", so nothing slips past as unparsed text.

*Easy to get wrong:* trailing zeros are significant as written. "200 m" states three figures, so it is not supported by 210.4. And the guard checks that a number *exists* in the evidence, not that it is attached to the right quantity. How it fails, below, shows what that allows.

### 8. `sentinel/ai/assistant.py`: the orchestrator

`gate(route)` returns `"unsure"` when the tool is not in the catalog or the confidence is not within [0.5, 1.0]. That includes NaN, so it fails closed. It returns `"which_event"` when an event tool has no event, and `None` to act.

`Assistant.ask(text, author)`:

1. `tier()` asks the policy, with the link state read at that moment.
2. `_answer` builds the routing context from `list_events`. It routes, and falls back to the deterministic router on `RouterUnavailable`. Then the checks run in this order: the gate's "unsure"; a write asked of a read-only node; a missing event. Next the tool executes, a `ToolError` becoming a question back. The narrator phrases the facts; if the AI prose fails grounding, the template is used and `withheld` names the unsupported numbers.
3. One audit line is appended: question, tier, route, narrator, grounding, withheld, fallbacks, answer text, and the sha256 of the facts (not the facts themselves).
4. A draft is held under a random `draft_id`, capped at `MAX_DRAFTS` (100), oldest evicted with the log line `Assistant draft evicted`.

`Assistant.confirm(draft_id, author, rationale)` pops the draft. It builds the provenance (router, confidence, model, ask sequence) and calls `record_decision`, which may refuse `stale_draft`. Then it appends a `confirm` audit line carrying the DECISION's digest.

*Easy to get wrong:* the draft is popped *before* `record_decision` runs, so a refused confirmation consumes the draft. The operator must ask again, which drafts against the current CDM. That is intended: a draft is good once, on the CDM it was made against.

### 9. `sentinel/audit/chain.py`: the record

`AuditLog.append` builds `{**record, seq, at, prev}`, hashes its canonical JSON (`_digest` excludes the `hash` field) and appends one line. `_known` holds the hash of every line this process has loaded or written. `verify` re-reads the file, then `_first_bad` walks it. The first line that cannot be parsed, does not link to the one before, or differs from what this process knows at that position is reported. So is a file shorter than the lines it knows. `_report` logs `Audit chain broken` once per new break, not on every verify.

A torn write, from a power cut mid-line, leaves bytes with no final newline. `_end_a_torn_line` ends that line before the next append, so the torn bytes stay as evidence on their own line. The next entry links to the last readable line, and the chain never verifies across the tear again.

*Easy to get wrong:* the chain has no key and no anchor outside the file. Holding the file against `_known` catches an edit, deletion or truncation *while the node runs*. Lines removed from the end while it is stopped leave a shorter chain that verifies after a restart. `SECURITY.md` lists this as gap 3 (AU-9).

### 10. `sentinel/api/ai_routes.py`: the HTTP surface

`register` builds the `ToolRegistry` over the node's services. It calls `_load_provider` for Jev and Claude: a provider loads only when its key variable is set, and its SDK is imported only then. With no key, no SDK is ever imported, which is how an air-gapped bundle without the `ai` extra runs. With a key but no SDK, the node logs `Hosted AI SDK not installed` and serves the local tier. `_link_state` returns the measured hub link on an edge and an assumed CONNECTED elsewhere. The audit lives at `<SENTINEL_VAR>/ai-audit.jsonl`. The routes:

- `GET /api/ai/status`: the tier in force and why;
- `POST /api/ai/ask`: allowed on a read-only node, where it answers but drafts nothing;
- `POST /api/ai/confirm`: 201 with the DECISION; 404 `unknown_draft`; 409 `stale_draft`;
- `GET /api/ai/audit` and `GET /api/ai/audit/verify`.

### 11. `sentinel/ai/evaluation.py`, `sentinel/ai/calibration.py`, `evals/` and `scripts/ai_eval.py`: the eval

`evals/routing.jsonl` holds 60 operator requests, each labelled with the call a careful operator would expect. Out-of-scope requests are labelled `"tool": null`, meaning the assistant should not act. `evals/README.md` says how the labels were written and why they are a comparison set, not field accuracy.

`evaluation.score` runs each route through the assistant's own `gate`, so a router is scored on what the assistant would *do*. `summarize` reports right tool, right call, coverage, selective accuracy and abstention, plus `brier`, `ece` and the reliability bins from `calibration.py`. `run_eval` counts a service failure as unavailable, never as a wrong answer.

`scripts/ai_eval.py` builds the exercise scenario at T+1 h on a fixed clock, so the routing context is the same every run. It always scores the deterministic router. It scores Jev only when `TYPESAFE_API_KEY` is set, and then saves the raw run beside the report, as `ai-eval-jev.json` with the model, date and eval-set hash. That file does not exist yet, because no keyed run has been made. A later run without a key reuses that file. If the eval set has changed since, it leaves the saved run out and says it is stale. Then it writes `docs/ai-eval.md` and its reliability diagram.

### 12. `sentinel/ai/live_check.py` and `scripts/ai_live_check.py`: one real call each

`make ai-live-check` makes at most one real call per provider whose key is set, in the shell or in `.env`, through the production adapters. Jev routes one eval question; Claude phrases one tool's facts, and the grounding guard checks the result. A key that is not set is reported as `not configured`, not failed. A configured call that fails prints its stable reason and a hint, never exception text, because a service's error body can echo a key. The SDKs' DEBUG wire logs are held at INFO while the calls run. It writes nothing; publishing is `make ai-eval`'s job.

### 13. `.importlinter`: the boundaries CI enforces

Two contracts carry this chapter:

- `ai-does-no-math` forbids `sentinel.ai` from importing `sentinel.risk`, `sentinel.cdm`, numpy and scipy. Import-linter checks indirect imports too. `sentinel.ai` therefore cannot import `sentinel.conjunction` either, which imports all of them. The tools get the conjunction service by injection, in `ToolRegistry.__init__`, not by import.
- `hosted-ai-at-the-edges` forbids the Jev and Anthropic SDKs in the seven modules it lists: the orchestrator, catalog, grounding guard, templates, policy, router protocol and tools. That leaves the SDKs in `router_jev.py` and `narrate_claude.py`. `live_check.py` also keeps to protocols, with the script injecting the adapters, but by convention: it is not on the contract's list.

## Try it

Start with no keys set. Keys can come from two places: your shell, or a gitignored `.env` in the repository root (its template is `.env.example`). `make ai-live-check`, `make ai-eval` and `make demo-local` read `.env` themselves through `sentinel/localenv.py`, and an exported variable wins. If your `.env` holds a key, the first command below makes a real call, and `make ai-eval` runs Jev and rewrites the report. Keep that in mind before running them. First, the readiness check:

```bash
export PATH=$HOME/.local/bin:$PATH
make ai-live-check
```

Both providers report `not configured`, with what each call *would* do once its key is set. Near the end it says `No key is set, so no call was made. A key that is not set is not a failure.` The exit code is 0.

The tier policy is a pure function, so you can see what it would do with keys you do not have:

```bash
uv run python - <<'EOF'
from sentinel.ai.policy import TierInputs, decide
for marking in ("UNCLASSIFIED // EXERCISE", "SECRET // EXERCISE"):
    for link in ("CONNECTED", "DEGRADED", "LIMITED", "DENIED", "UNKNOWN"):
        d = decide(TierInputs(link, marking, jev_configured=True, claude_configured=True, cloud_opt_in=True))
        print(f"{marking[:12]:<12} {link:<9} {d.router:<13} {d.narrator:<8} {d.reason}")
EOF
```

Jev and Claude both appear only for UNCLASSIFIED on CONNECTED or DEGRADED. On LIMITED, Jev routes and templates phrase. Every SECRET row is local, whatever the link.

Probe the grounding guard directly:

```bash
uv run python - <<'EOF'
from sentinel.ai.grounding import check_grounding
facts = {"miss_distance_m": 210.4, "pc": 6.3e-3, "time_to_mcp_h": 11.0, "cdm_sha256": "41ad6862baba2840"}
for text in ("Miss 210 m, Pc 6.3×10⁻³.", "Pc about 6×10⁻³.", "Pc 6.4×10⁻³.", "Miss 200 m.", "MCP in 11.0h.",
             "MCP in 12h.", "Miss 41 m."):
    result = check_grounding(text, facts)
    print(f"{text:28} ok={result.ok!s:5} unsupported={result.unsupported}")
EOF
```

The first two pass. "6.4×10⁻³", "200" (three significant figures as written) and "12" fail. The last line passes, which should bother you: "41" is not a distance anywhere in the facts, but it is a digit run inside the hash. How it fails, below, comes back to this.

Now a node of your own. A live demo runs on ports 8000 and 8001: never post to it. This uses port 8124 and a standalone node, which runs the exercise scenario. `sentinel serve` does not read `.env`, so it sees a key only if your shell exports one:

```bash
SENTINEL_NODE_ID=ch11 SENTINEL_VAR=/tmp/sentinel-ch11 uv run sentinel serve --port 8124
```

In a second terminal, read the tier, then define a small helper that asks a question and prints the parts worth reading:

```bash
curl -s http://127.0.0.1:8124/api/ai/status | python3 -m json.tool
ask() {
  curl -s -X POST http://127.0.0.1:8124/api/ai/ask -H 'Content-Type: application/json' \
    -d "$(python3 -c 'import json, sys; print(json.dumps({"text": sys.argv[1]}))' "$1")" |
  python3 -c 'import json, sys; a = json.load(sys.stdin); r = a["route"]; print(a["status"], r["tool"], r["args"], r["confidence"], a["narrated_by"], a["grounding"], a["draft_id"], "audit", a["audit_seq"]); print(" ", a["text"])'
}
```

The status shows `router: deterministic`, `narrator: template` and the reason `Hosted AI not approved on this node`. `link_source` says the link is *assumed*, because a standalone node has none to measure. Now ask:

```bash
ask "/events"
ask "How risky is the 118 conjunction?"
ask "What conjunctions do we have right now?"
ask "/assess"
ask "Recompute the Pc for 118 with a 5 m hard-body radius"
ask "/draft 118 monitor"
```

What to look for:

- `/events` is answered at confidence 1.0 by a template. Every Pc appears with its method, and every refused event says why.
- The natural-language question about 118 routes to `get_assessment` at 0.6, a keyword match.
- "What conjunctions do we have right now?" gets `clarify` at 0.0. The floor has no rule for it, so it lists the commands instead of guessing. The eval counts misses like this one.
- `/assess` with no event is `clarify` with "Which event?" and three candidates.
- "Recompute the Pc ... 5 m" is out of scope, and the floor mis-routes it to `get_assessment`. Look at the answer: it reports the engine's existing assessment, with its own HBR of 20 m. Nothing was recomputed, because no tool can. A wrong route can only read.
- `/draft 118 monitor` returns `draft` with a `draft_id`, and text that ends "This is not recorded until you confirm it." Note which CDM it says it is `against`.

The exercise releases a new CDM for 118 about 144 s after the node starts. If your draft was made against `EX-RED-03`, wait until `ask "/assess 118"` reports 4 CDMs, then confirm it. (If it already says `EX-RED-04`, the update arrived first and the confirmation below succeeds; restart the node and draft sooner to see the refusal.)

```bash
curl -s -X POST http://127.0.0.1:8124/api/ai/confirm -H 'Content-Type: application/json' \
  -H 'X-Sentinel-Operator: you@ch11' -d '{"draft_id": "<draft_id>", "rationale": "watch the next update"}' -w '\nHTTP %{http_code}\n'
```

That is `409 stale_draft`: the draft was made on a CDM that is no longer current. Confirm the same id again and it is `404 unknown_draft`, because the refusal consumed it. Draft again, confirm the new id, and you get `201` with a DECISION whose `body.drafted_by` names the router, its confidence and the `ask_seq` of the audit line.

Now the audit. Verify it, then simulate a power cut mid-write: stop the node with Ctrl-C, leave a torn final line, and start it again with the same command:

```bash
curl -s http://127.0.0.1:8124/api/ai/audit/verify                    # {"ok": true, ...}
printf '{"kind":"ask","que' >> /tmp/sentinel-ch11/ai-audit.jsonl       # with the node stopped
```

At start-up the node logs `ERROR sentinel.audit.chain Audit chain broken first_bad=N`, where N is the torn line, and it serves normally. `ask "/link"` still works and is recorded after the torn line. `/api/ai/audit/verify` keeps reporting the same `first_bad`: the chain never verifies across the tear. Now edit the first line while the node runs:

```bash
sed -i '1s|"question":"/events"|"question":"/EVENTS"|' /tmp/sentinel-ch11/ai-audit.jsonl
curl -s http://127.0.0.1:8124/api/ai/audit/verify                    # first_bad: 0
```

Finally, the boundaries. Add `import numpy` under the imports at the top of `sentinel/ai/tools.py`, and run the contracts:

```bash
uv run lint-imports
git checkout -- sentinel/ai/tools.py
```

The contract "The AI layer has no path to the maths" is `BROKEN`, naming `sentinel.ai.tools -> numpy`. Import `sentinel.conjunction.service` instead and it is broken again, through the chain that module imports. The `git checkout` puts the file back. Then the tests and the eval:

```bash
uv run pytest -q tests/ai
make ai-eval
git diff --stat docs/ai-eval.md
```

With no key, `make ai-eval` says `wrote docs/ai-eval.md (deterministic)` and the diff is empty: the floor's numbers are deterministic. Read them in [`docs/ai-eval.md`](../ai-eval.md), including its list of misses; they are not repeated here.

## Design choices

All of these are in [ADR-007](../system-design.md#adr-007--ai-that-cannot-corrupt-the-decision-jev-routes-code-computes-claude-phrases-the-operator-decides).

**Tools compute; AI routes and phrases.** It buys numbers that come only from code the validation report covers, and an AI failure mode limited to "wrong tool" or "bad phrasing". It costs flexibility: the assistant can answer only what six tools can. Rejected: a model that computes or "checks" a Pc, and free-form query generation against the store (unbounded and unauditable).

**A typed-choice router, Jev, rather than an LLM tool-calling loop.** It buys a probability for every option, which makes the 0.5 gate principled. The answer is small enough for a LIMITED link, and the behaviour can be measured on `evals/routing.jsonl`. It costs a hosted dependency with no on-premises option, pinned to one model version. Rejected: a tool-calling loop, whose answers are larger and carry no calibrated probability, for requests that need only one call.

**A deterministic floor rather than a local model.** It buys an assistant that always works with no keys, no link and no GPU, and is exact on commands. It costs weak natural-language routing, measured in `docs/ai-eval.md`. That gap is what any model must earn its place against, through the same gate. The ADR replaced an earlier proposal, a local quantized model as the only tier. A local model could still slot in behind the `Router` protocol (open question 4 in `docs/system-design.md`); it is not built. Rejected: hosted-only AI, which fails with the link.

**The grounding guard withholds; it does not repair.** It buys a simple, testable rule: an AI answer is shown whole or not at all, and the template is always there. It costs some correct paraphrases: a unit conversion such as "0.21 km" for a 210 m miss is withheld, because 0.21 is not in the facts. Nothing tries to repair a withheld answer; a repair would be one more model call with only the same guard to check it.

**One attempt, no retries, on hosted calls.** The local answer already exists, and backoff on a degraded link only delays the operator. The cost is that a transient error loses the hosted tier for that one answer.

**The measured hub link stands in for the WAN.** It buys a tier decision from something the node actually measures. The cost is an assumption: an edge reaches hosted AI over the same link it uses to reach its hub. A hub or standalone node assumes CONNECTED and says so.

**Drafts confirmed by a person, refused when stale.** It buys a human decision on every write, with provenance, made against the data the person saw. It costs a click, and a redraft when a CDM arrives in between.

**An audit chain in a file that verification re-reads.** It buys detection of edits, deletions and truncations while the node runs, and a node that keeps working after a torn write. It costs the known gap: truncation while the node is stopped is not detected until the head is anchored outside the file (`SECURITY.md`, gap 3).

## How it fails

- **A hosted service fails** (authentication, rate limit, server error, unreachable, timeout, refusal, truncation, empty answer): the local tier answers in the same request. `fallbacks` lists `{from, to, reason}`, and the log says `AI router unavailable` or `AI narrator unavailable` with the reason.
- **Jev answers outside the options it was given**: `Jev answer malformed`, treated like an outage.
- **A confidence that is not a probability** (NaN, above 1) fails the gate and asks back (`tests/ai/test_review_edges.py`).
- **An AI answer states an unsupported number**: `AI answer withheld` is logged, the template answer is shown, and `withheld.unsupported` names the numbers.
- **A mis-route** reaches a tool that only reads, or a draft that does nothing until confirmed. The worst a wrong route can do alone is show the wrong facts, and the answer says which event and tool it used.
- **A tool cannot serve the call** (no event, unknown event, invalid band or decision): a question back, never an exception.
- **A stale, unknown or evicted draft**: 409 or 404 on confirm. Eviction is logged. A refused confirmation is not written to the audit; only asks and successful confirms are.
- **A read-only node** is asked to draft: it answers that it records nothing, so it drafts nothing.
- **An SDK is missing** although its key is set: `Hosted AI SDK not installed`, and the local tier serves.
- **The audit file** is edited, cut short while running, or torn: `verify` names the first bad line, `Audit chain broken` is logged once per new break, and appends continue.

Three limits are worth knowing precisely, because they are not bugs the code hides:

- **The guard checks presence, not meaning.** A number is supported if it appears anywhere in the facts at the stated precision, including digit runs inside identifiers and hashes. An answer that swaps two numbers of similar size, or borrows one from a hash (the "41" above), passes. The guard bounds invention; the operator, the template beside it and the audit still matter.
- **Only the tool choice is gated.** Jev's event choice is taken as given, even if its probability is low. For a read the answer names the event; for a write a person confirms it.
- **The question text leaves the node** when hosted AI is on, and it is always written to the audit file. Nothing stops an operator from typing something sensitive, such as a unit's position (chapter 10). The pass module keeps that position out of the assistant entirely; the operator should too.

## Check yourself

1. The deterministic router routes "Recompute the Pc for 118 with a 5 m hard-body radius" to `get_assessment` and acts. Why is that a tolerable failure here, and what would make it intolerable?

   <details><summary>Answer</summary>

   The tool only reads, so the operator sees the engine's existing assessment, with its HBR of 20 m, not a fabricated recomputation. It would be intolerable if a tool could compute on the router's arguments, or if a write took effect without a person. Both are ruled out: the catalog has no such tool, and `draft_decision` only drafts.

   </details>

2. Router A is right 60% of the time and always states 0.9. Router B is right 60% of the time and always states 0.6. Which is better behind a 0.5 gate, and which scores show it?

   <details><summary>Answer</summary>

   B. Its confidence matches its accuracy (ECE 0, Brier 0.24), so the gate's threshold means what it says. A over-claims (ECE 0.3, Brier 0.33): it would act confidently on answers that are wrong 40% of the time. Same accuracy, different trustworthiness.

   </details>

3. A new tool returns an object's full CDM text in its facts, "for context". What does that do to the grounding guard?

   <details><summary>Answer</summary>

   Every number in the CDM, including states, covariance terms and timestamps, joins the evidence pool. An AI answer could then state almost any figure and pass. Keep facts to what the answer needs. The guard is only as tight as the evidence it is given.

   </details>

4. An edge's measured link is LIMITED, the marking is UNCLASSIFIED, the operator opted in, and both keys are set. Who routes, who phrases, and why the split?

   <details><summary>Answer</summary>

   Jev routes and the templates phrase. A Jev answer is a few probabilities, small enough for a LIMITED link. Prose is kilobytes, and on a thin link it would compete with urgent conjunction data, so Claude runs only on CONNECTED or DEGRADED links.

   </details>

5. Why does `Assistant.confirm` refuse a draft whose CDM has been superseded, instead of recording it with a warning?

   <details><summary>Answer</summary>

   A decision is only meaningful against the data the person saw. A draft made on EX-RED-03 and confirmed after EX-RED-04 arrived records a judgement on numbers that are no longer current. Refusing forces a redraft against the current CDM, which the person then sees. The DECISION's `event_ref` names that CDM.

   </details>

6. `sentinel/ai/tools.py` needs the conjunction service. Why does it not import `sentinel.conjunction`, and what would CI say if it did?

   <details><summary>Answer</summary>

   `sentinel.conjunction` imports numpy, scipy, `sentinel.risk` and `sentinel.cdm`. Import-linter checks indirect imports, so `ai-does-no-math` would fail, naming each chain. The registry receives the service as a constructor argument instead: dependency inversion keeps the AI layer with no path to the maths.

   </details>

7. An attacker with shell access truncates the last ten lines of `ai-audit.jsonl`. When is that detected, and when not?

   <details><summary>Answer</summary>

   While the node runs, `verify` holds the file against the hashes this process wrote and reports the file ending early. If the node is stopped first, the shorter chain is consistent and verifies after a restart. That is the documented AU-9 gap, closed only by anchoring the head outside the file.

   </details>

8. The eval scores routers through `gate`, not on raw accuracy. Why does that matter for comparing Jev with the floor?

   <details><summary>Answer</summary>

   The operator experiences what the assistant *does*: act, or ask back. A router that is often right but under-confident would ask back constantly. One that is over-confident would act on wrong routes. Scoring through the same gate measures coverage, selective accuracy and abstention as deployed, so a model has to beat the floor on behaviour, not just on a leaderboard metric.

   </details>

## Where next

- [12. Supply chain and deployment](12-supply-chain-and-deploy.md): how the `ai` extra is left out of an air-gapped bundle, and why the node still answers.
- [13. Keeping it honest](13-guardrails-compliance-mbse.md): the import contracts, the doc checks, and how a generated report such as `docs/ai-eval.md` stays in step with the code.
- [8. Operator data: signed CRDTs](08-operator-data.md), for the DECISION a confirmed draft becomes, and [10. Passes and screening](10-passes-and-screening.md), for the one fact the assistant must never be given.
- Reference: ADR-007 in [`docs/system-design.md`](../system-design.md), "The AI assistant pipeline" in [`docs/technical-guide.md`](../technical-guide.md), [`docs/ai-eval.md`](../ai-eval.md), [`evals/README.md`](../../evals/README.md), and gap 3 in [`SECURITY.md`](../../SECURITY.md).
