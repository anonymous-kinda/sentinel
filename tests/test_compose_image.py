"""deploy/compose/Dockerfile: the Compose stack's sentinel image, built from
this checkout with nothing but Docker.

The release image (deploy/containers/Dockerfile) builds from an unpacked,
signature-verified air-gap bundle, which needs Node, uv and every wheel
downloaded on the host first. This one builds the same image from source.
They must not drift where it matters: the same digest-pinned bases, the
dependency set exported and installed exactly as the bundle does, and a
runtime stage identical line for line.
"""

import re
import subprocess

import yaml

from harness.compose import COMPOSE_DIR, ROOT
from supplychain import bundle

COMPANION = COMPOSE_DIR / "Dockerfile"
RELEASE = ROOT / "deploy" / "containers" / "Dockerfile"
IGNORE = COMPOSE_DIR / "Dockerfile.dockerignore"
FROM = re.compile(r"^FROM\s+(\S+)", re.M)


def instructions(path) -> list[str]:
    """Logical lines: comments dropped, continuations joined."""
    text = re.sub(r"\\\n", " ", path.read_text())
    return [" ".join(line.split()) for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def runtime_stage(path) -> list[str]:
    lines = instructions(path)
    last_from = max(i for i, line in enumerate(lines) if line.startswith("FROM "))
    return lines[last_from:]


def bases(path) -> list[str]:
    return FROM.findall(path.read_text())


def test_every_base_image_is_pinned_by_digest():
    assert all(re.search(r"@sha256:[0-9a-f]{64}$", image) for image in bases(COMPANION)), bases(COMPANION)


def test_the_python_bases_are_the_release_images_bases_at_the_same_digests():
    assert [b for b in bases(COMPANION) if "chainguard/python" in b] == bases(RELEASE)


def test_the_runtime_stage_is_the_release_runtime_stage_line_for_line():
    assert runtime_stage(COMPANION) == runtime_stage(RELEASE)


def test_the_console_is_built_with_the_node_major_ci_uses():
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    (setup_node,) = [s for s in ci["jobs"]["web"]["steps"] if "setup-node" in s.get("uses", "")]
    (node,) = [b for b in bases(COMPANION) if b.startswith("node:")]
    assert node.split(":")[1].split(".")[0] == str(setup_node["with"]["node-version"])


def test_the_dependency_set_is_exported_exactly_as_the_bundle_exports_it(monkeypatch):
    seen = []
    monkeypatch.setattr(bundle.subprocess, "run",
                        lambda cmd, **kw: seen.append(cmd) or subprocess.CompletedProcess(cmd, 0, stdout=""))
    bundle.export_requirements(ROOT)
    (command,) = seen
    assert f"{' '.join(command)} -o requirements.txt" in " ".join(instructions(COMPANION))


def test_dependencies_install_hash_locked_and_binary_only_as_in_the_release():
    install = "pip install --no-cache-dir --disable-pip-version-check --require-hashes --only-binary=:all: -r requirements.txt"
    assert install in " ".join(instructions(RELEASE))
    assert install in " ".join(instructions(COMPANION))


def test_the_image_carries_what_a_hub_serves_where_the_release_image_puts_it():
    text = " ".join(instructions(COMPANION))
    for source in ("fixtures/cara", "fixtures/cara_cases.json", "fixtures/omm"):
        assert f"COPY {source} /opt/sentinel/fixtures/" in text, source
    assert "COPY --from=console /web/dist /opt/sentinel/web" in text
    assert "COPY LICENSE /opt/sentinel/" in text


def test_the_trust_mount_point_exists_owned_by_the_node_user():
    """A new named volume takes the ownership of the image directory it is
    mounted over; the enrolment containers (uid 65532) write the trust file."""
    assert "mkdir -p /var/lib/sentinel/trust" in " ".join(instructions(COMPANION))
    assert "COPY --from=build --chown=65532:65532 /var/lib/sentinel /var/lib/sentinel" in runtime_stage(COMPANION)


def test_the_build_context_is_an_allowlist_that_admits_every_copied_path():
    patterns = [line.strip() for line in IGNORE.read_text().splitlines() if line.strip() and not line.startswith("#")]
    assert patterns[0] == "*", "exclude everything, then admit what the build copies"
    admitted = [p[1:].rstrip("/") for p in patterns if p.startswith("!")]
    copied = []
    for line in instructions(COMPANION):
        if line.startswith("COPY ") and "--from=" not in line:
            copied += line.split()[1:-1]
    assert copied
    for source in copied:
        assert any(source.rstrip("/") == a or source.startswith(f"{a}/") for a in admitted), source
    assert "web/node_modules" in patterns and "web/dist" in patterns
