"""Every third-party action in every workflow is pinned by full commit SHA.

A tag like `@v4` can be moved to different code after review; a commit SHA
cannot (NIST SR-3, SR-11). Local actions (`./...`) are part of this repo.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
MAKEFILE = ROOT / "Makefile"
USES = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)")
PINNED = re.compile(r"@[0-9a-f]{40}$")
EXACT = re.compile(r"==\d")


def unpinned(paths=WORKFLOWS) -> list[str]:
    found = []
    for path in paths:
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            match = USES.match(line)
            if match and not match.group(1).startswith("./") and not PINNED.search(match.group(1)):
                found.append(f"{path.name}:{number} {match.group(1)}")
    return found


def test_every_action_is_pinned_by_commit_sha():
    assert WORKFLOWS, "the workflows exist"
    assert unpinned() == []


def test_the_check_catches_a_tag(tmp_path):
    workflow = tmp_path / "x.yml"
    workflow.write_text("steps:\n  - uses: actions/checkout@v4\n  - uses: ./local\n")
    assert unpinned([workflow]) == ["x.yml:2 actions/checkout@v4"]


def unlocked_installs(paths=WORKFLOWS) -> list[str]:
    """Python installs that resolve fresh instead of installing uv.lock."""
    found = []
    for path in paths:
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if re.search(r"\b(uv pip install|pip install)\b", line):
                found.append(f"{path.name}:{number} {line.strip()}")
    return found


def test_python_dependencies_install_from_the_lock():
    """CI installs exactly uv.lock (`uv sync --locked`), so a new upstream
    release cannot change what CI tests, and a stale lock fails."""
    assert unlocked_installs() == []
    for path in WORKFLOWS:
        text = path.read_text()
        if "setup-uv@" in text:
            assert "uv sync --locked" in text, path.name


def test_the_lock_check_catches_a_fresh_resolve(tmp_path):
    workflow = tmp_path / "x.yml"
    workflow.write_text("steps:\n  - run: uv pip install -e \".[dev]\"\n")
    assert unlocked_installs([workflow]) == ['x.yml:2 - run: uv pip install -e ".[dev]"']


def unlocked_uv_jobs(paths=WORKFLOWS) -> list[str]:
    """Jobs that set up uv but could resolve fresh: no UV_LOCKED in the job
    or workflow env, and no `uv sync --locked` step. `uv run` re-locks
    silently when the lock is stale, so a job must opt into the lock."""
    import yaml

    found = []
    for path in paths:
        workflow = yaml.safe_load(path.read_text())
        workflow_locked = str((workflow.get("env") or {}).get("UV_LOCKED", "")) == "1"
        for name, job in (workflow.get("jobs") or {}).items():
            steps = job.get("steps") or []
            uses_uv = any("setup-uv@" in str(step.get("uses", "")) for step in steps)
            job_locked = str((job.get("env") or {}).get("UV_LOCKED", "")) == "1"
            syncs_locked = any("uv sync --locked" in str(step.get("run", "")) for step in steps)
            if uses_uv and not (workflow_locked or job_locked or syncs_locked):
                found.append(f"{path.name}#{name}")
    return found


def test_every_uv_job_uses_the_lock():
    assert unlocked_uv_jobs() == []


def test_the_job_check_catches_an_unlocked_job(tmp_path):
    workflow = tmp_path / "x.yml"
    workflow.write_text(
        "jobs:\n  build:\n    steps:\n      - uses: astral-sh/setup-uv@" + "a" * 40 + "\n      - run: uv run make x\n"
    )
    assert unlocked_uv_jobs([workflow]) == ["x.yml#build"]


# A repo script a workflow, the Makefile or another such script names by path.
SCRIPT = re.compile(r"(?:scripts|deploy)/[\w./*-]+\.(?:sh|py)\b")


def ci_scripts(sources=(*WORKFLOWS, MAKEFILE)) -> list[pathlib.Path]:
    """Every repo script CI runs: named by path in a workflow or the Makefile,
    or in a script those run (globs expanded), followed to the end."""
    found: set[pathlib.Path] = set()
    queue = list(sources)
    while queue:
        for pattern in SCRIPT.findall(queue.pop().read_text()):
            for path in ROOT.glob(pattern):
                if path.is_file() and path not in found:
                    found.add(path)
                    queue.append(path)
    return sorted(found)


def test_the_scripts_ci_runs_are_found_through_the_scripts_that_run_them():
    found = {path.relative_to(ROOT).as_posix() for path in ci_scripts()}
    assert "deploy/ansible/tests/test_verify.sh" in found, "ci.yml supply-chain runs it"
    assert "deploy/bundle/sign_local.sh" in found, "test_verify.sh runs it"


def uvx_packages(line: str) -> list[str]:
    """The packages a `uvx` call on this line installs: each --from and --with
    value. Options may come before them (`uvx --quiet --from PKG cmd`)."""
    specs = []
    for call in re.finditer(r"\buvx\b", line):
        tokens = re.findall(r"[^\s'\"]+", line[call.end():])
        for option, value in zip(tokens, tokens[1:], strict=False):
            if option in ("--from", "--with"):
                specs.append(value)
    return specs


def unpinned_tools(paths=None) -> list[str]:
    """A `uvx` package without an exact version runs whatever is newest."""
    found = []
    for path in paths if paths is not None else (*WORKFLOWS, MAKEFILE, *ci_scripts()):
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if line.lstrip().startswith("#"):
                continue
            found += [f"{path.name}:{number} {spec}" for spec in uvx_packages(line) if not EXACT.search(spec)]
    return found


def test_every_uvx_tool_ci_runs_is_pinned_to_a_version():
    assert unpinned_tools() == []


def test_each_uvx_package_ci_runs_is_pinned_to_one_version():
    """CI's Ansible syntax check and its signature-gate test run one ansible-core."""
    versions: dict[str, set[str]] = {}
    for path in (*WORKFLOWS, MAKEFILE, *ci_scripts()):
        for line in path.read_text().splitlines():
            for spec in uvx_packages(line):
                name, _, version = spec.partition("==")
                versions.setdefault(name, set()).add(version)
    assert "ansible-core" in versions
    assert {name: found for name, found in versions.items() if len(found) > 1} == {}


def test_the_tool_check_catches_an_unpinned_package_after_other_options(tmp_path):
    script = tmp_path / "x.sh"
    script.write_text(
        "# needs uvx; the comment is not a call\n"
        "uvx --quiet --from ansible-core ansible-playbook site.yml\n"
        "uvx --from ansible-core==2.21.4 ansible-playbook site.yml\n"
    )
    assert unpinned_tools([script]) == ["x.sh:2 ansible-core"]
