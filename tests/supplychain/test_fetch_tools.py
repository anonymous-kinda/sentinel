"""scripts/fetch_tools.py: a failed download is one clear line and a nonzero
exit, never a traceback.

Offline (an air-gapped host, a namespace with no network, a proxy down),
`make tools` used to end in a URLError traceback. The script now exits with
a message naming the tool and the URL it could not reach.
"""

import hashlib
import importlib.util
import pathlib
import urllib.error

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "fetch_tools.py"
URL = "https://example.invalid/toxiproxy-linux-amd64"


def load_script():
    spec = importlib.util.spec_from_file_location("fetch_tools_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def offline(url, timeout):
    raise urllib.error.URLError(OSError(-3, "Temporary failure in name resolution"))


@pytest.fixture
def fetch_tools(tmp_path, monkeypatch):
    script = load_script()
    lock = tmp_path / "tools.lock"
    lock.write_text(f"toxiproxy 2.12.0 x86_64 {hashlib.sha256(b'x').hexdigest()} {URL} -\n")
    monkeypatch.setattr(script, "LOCK", lock)
    monkeypatch.setattr(script, "TOOLS", tmp_path / ".tools")
    return script


def test_offline_the_script_exits_nonzero_naming_the_tool_and_the_url(fetch_tools, tmp_path):
    with pytest.raises(SystemExit) as exited:
        fetch_tools.main(["--arch", "x86_64", "toxiproxy"], opener=offline)

    message = exited.value.code
    assert isinstance(message, str), "sys.exit(<message>): printed to stderr, exit status 1"
    assert "toxiproxy" in message and URL in message and "Temporary failure in name resolution" in message
    assert not (tmp_path / ".tools" / "x86_64" / "toxiproxy").exists()
