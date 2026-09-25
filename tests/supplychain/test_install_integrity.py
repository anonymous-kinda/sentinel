"""deploy/bundle/install.sh checks the unpacked bundle before installing it.

`sha256sum -c SHA256SUMS` checks the files the list names and nothing
else. The installer then copies whole directories (web, fixtures, bin,
systemd) and installs every `wheels/sentinel-*.whl`. So a file added to
the unpacked bundle, one the signed list never named, is installed
unverified unless the installer also refuses what the list does not name.

The installer runs for real here, against a miniature bundle whose `uv` is
a stub, with SYSTEMD=0 and a temporary PREFIX.
"""

import os
import pathlib
import shutil
import subprocess
import sys

import pytest

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
    shutil.copy2(INSTALL, root / "install.sh")
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
