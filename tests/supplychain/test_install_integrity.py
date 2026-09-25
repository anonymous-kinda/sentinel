"""deploy/bundle/install.sh checks the unpacked bundle before installing it,
and the release image runs the same check before it installs anything.

`sha256sum -c SHA256SUMS` checks the files the list names and nothing
else. The installer then copies whole directories (web, fixtures, bin,
systemd) and installs every `wheels/sentinel-*.whl`. So a file added to
the unpacked bundle, one the signed list never named, is installed
unverified unless the installer also refuses what the list does not name.
Both do that through one script the bundle carries, verify_contents.sh.

The installer runs for real here, against a miniature bundle whose `uv` is
a stub, with SYSTEMD=0 and a temporary PREFIX.
"""

import os
import pathlib
import subprocess
import sys

import pytest

from supplychain.bundle import stage_installer
from supplychain.checksums import write_manifest

INSTALL = pathlib.Path(__file__).resolve().parents[2] / "deploy" / "bundle" / "install.sh"
FILES = {
    "VERSION": "0.0.0-test\n",
    "requirements.txt": "",
    "wheels/sentinel-0.0.0-py3-none-any.whl": "not really a wheel",
    "web/index.html": "<!doctype html>",
    "fixtures/README.md": "fixtures",
    "systemd/sentinel.service": "[Unit]\n",
    "bin/uv": "#!/bin/sh\nexit 0\n",
}


def bundle(root: pathlib.Path) -> pathlib.Path:
    for name, text in FILES.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    (root / "bin" / "uv").chmod(0o755)
    stage_installer(INSTALL.parent, root)
    write_manifest(root)
    return root


def install(root: pathlib.Path, prefix: pathlib.Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "PREFIX": str(prefix), "SYSTEMD": "0", "PYTHON": sys.executable}
    return subprocess.run(["bash", "install.sh"], cwd=root, env=env, capture_output=True, text=True, timeout=60)


@pytest.fixture
def unpacked(tmp_path):
    return bundle(tmp_path / "bundle")


def test_a_bundle_exactly_as_listed_installs(unpacked, tmp_path):
    result = install(unpacked, tmp_path / "prefix")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "prefix" / "web" / "index.html").exists()


@pytest.mark.parametrize("added", ["web/assets/injected.js", "bin/nats-server-helper", "wheels/sentinel-9.9.9-py3-none-any.whl"])
def test_a_file_the_signed_list_does_not_name_is_refused_before_anything_is_installed(unpacked, tmp_path, added):
    path = unpacked / added
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("added after signing")

    result = install(unpacked, tmp_path / "prefix")

    assert result.returncode != 0
    assert added in result.stderr
    assert not (tmp_path / "prefix").exists(), "nothing is installed from a bundle that failed its check"


def test_a_symlink_added_to_the_bundle_is_refused(unpacked, tmp_path):
    (unpacked / "web" / "escape").symlink_to("/etc/passwd")
    result = install(unpacked, tmp_path / "prefix")
    assert result.returncode != 0 and "web/escape" in result.stderr


def test_a_file_outside_the_installed_directories_is_refused_too(unpacked, tmp_path):
    """The bundle is exactly its signed list: a top-level or hidden file the
    list does not name is refused wherever it sits, not only under the
    directories install.sh copies."""
    (unpacked / ".injected").write_text("added after signing")
    result = install(unpacked, tmp_path / "prefix")
    assert result.returncode != 0 and ".injected" in result.stderr
    assert not (tmp_path / "prefix").exists()


# ---------------------------------------------------------------- the release image
# deploy/containers/Dockerfile builds from the same unpacked bundle. It
# re-checked SHA256SUMS but not what the list omits, so a file added to the
# build context after signing went into the image unverified.
DOCKERFILE = INSTALL.parents[1] / "containers" / "Dockerfile"
CHECK = "verify_contents.sh"


def build_stage_runs() -> list[str]:
    """The release image's build-stage RUN instructions, continuations joined, in order."""
    text = DOCKERFILE.read_text().replace("\\\n", " ")
    runtime = text.rindex("\nFROM ")
    return [" ".join(line.split()) for line in text[:runtime].splitlines() if line.startswith("RUN ")]


def test_the_release_image_runs_the_installers_bundle_check_before_installing_anything():
    runs = build_stage_runs()
    check = next((i for i, run in enumerate(runs) if run == f"RUN bash {CHECK}"), None)
    assert check is not None, f"the image build runs {CHECK}, the check install.sh runs"
    first_install = next(i for i, run in enumerate(runs) if "pip install" in run)
    assert check < first_install


def test_install_sh_runs_that_same_check():
    assert f'bash "$HERE/{CHECK}"' in INSTALL.read_text()


def test_the_check_the_image_runs_refuses_a_file_the_list_does_not_name(unpacked):
    """What `RUN bash verify_contents.sh` does in the build context."""
    (unpacked / "wheels" / "sentinel-9.9.9-py3-none-any.whl").write_text("added after signing")
    result = subprocess.run(["bash", CHECK], cwd=unpacked, capture_output=True, text=True, timeout=60)
    assert result.returncode != 0
    assert "wheels/sentinel-9.9.9-py3-none-any.whl" in result.stderr


def test_the_check_passes_a_bundle_exactly_as_listed(unpacked):
    result = subprocess.run(["bash", CHECK], cwd=unpacked, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
