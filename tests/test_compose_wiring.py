"""How the Compose stack is driven: the Makefile targets and the CI job.

The CI job (ci.yml, compose-smoke) is where the stack runs live: it builds
the image, waits for both nodes to be healthy, runs the smoke test, and
dumps every container's log if anything failed. Its actions reuse pins
already reviewed in this repository's workflows; nothing new is trusted.
"""

import re

import yaml

from harness.compose import ROOT

MAKEFILE = (ROOT / "Makefile").read_text()
CI_TEXT = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
COMPOSE = "docker compose -f deploy/compose/compose.yaml"


def block(text: str, begin: str, end: str) -> str:
    match = re.search(re.escape(begin) + r"(.*?)" + re.escape(end), text, re.S)
    assert match, f"missing delimited block {begin!r}"
    return match.group(1)


def recipe(makefile_block: str, target: str) -> str:
    match = re.search(rf"^{target}:[^\n]*\n((?:\t[^\n]*\n)+)", makefile_block, re.M)
    assert match, target
    return match.group(1)


MAKE_BLOCK = block(MAKEFILE, "# --- Docker Compose stack (begin)", "# --- Docker Compose stack (end)")


def test_the_make_targets_live_in_one_delimited_block():
    targets = set(re.findall(r"^([a-z-]+):", MAKE_BLOCK, re.M))
    assert targets == {"compose-config", "compose-up", "compose-down", "compose-smoke", "compose-link"}


def test_compose_up_builds_and_waits_until_both_nodes_are_healthy():
    assert "$(COMPOSE) up --build --detach --wait" in recipe(MAKE_BLOCK, "compose-up")
    assert f"COMPOSE ?= {COMPOSE}" in MAKE_BLOCK


def test_compose_down_removes_the_volumes_so_the_next_run_starts_fresh():
    assert "$(COMPOSE) down --volumes" in recipe(MAKE_BLOCK, "compose-down")


def test_the_smoke_and_link_targets_run_the_harness_modules():
    assert "python -m harness.compose_smoke" in recipe(MAKE_BLOCK, "compose-smoke")
    assert "python -m harness.compose_link $(PRESET)" in recipe(MAKE_BLOCK, "compose-link")
    assert "python scripts/compose_config.py" in recipe(MAKE_BLOCK, "compose-config")


# ----------------------------------------------------------------------- CI
def ci_job() -> dict:
    block(CI_TEXT, "# >>> compose (begin) >>>", "# <<< compose (end) <<<")
    return yaml.safe_load(CI_TEXT)["jobs"]["compose-smoke"]


def run_steps(job: dict) -> dict[str, dict]:
    return {s["run"].strip(): s for s in job["steps"] if "run" in s}


def test_the_ci_job_runs_on_ubuntu_24_04_with_read_only_contents():
    job = ci_job()
    assert job["runs-on"] == "ubuntu-24.04"
    assert job["permissions"] == {"contents": "read"}
    assert job["timeout-minutes"] <= 45


def test_the_ci_job_checks_the_file_builds_starts_smokes_and_always_stops():
    steps = run_steps(ci_job())
    order = [s["run"].strip() for s in ci_job()["steps"] if "run" in s]
    for command in (f"{COMPOSE} config --quiet", "make compose-up", "make compose-smoke", "make compose-down"):
        assert command in steps, command
    assert order.index("make compose-up") < order.index("make compose-smoke") < order.index("make compose-down")
    assert steps["make compose-down"]["if"] == "${{ always() }}"


def test_the_ci_job_dumps_every_log_on_failure():
    (logs,) = [s for s in ci_job()["steps"] if " logs " in s.get("run", "")]
    assert logs["if"] == "${{ failure() }}"
    assert f"{COMPOSE} ps --all" in logs["run"] and f"{COMPOSE} logs" in logs["run"]


def test_the_ci_job_uses_only_action_pins_already_reviewed_here():
    uses = [s["uses"] for s in ci_job()["steps"] if "uses" in s]
    assert uses and all(re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", u) for u in uses)
    elsewhere = CI_TEXT.replace(block(CI_TEXT, "# >>> compose (begin) >>>", "# <<< compose (end) <<<"), "")
    for other in (ROOT / ".github" / "workflows").glob("*.yml"):
        if other.name != "ci.yml":
            elsewhere += other.read_text()
    assert all(u in elsewhere for u in uses)
