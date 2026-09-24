"""Every environment a deployed node starts from names its writable state dir.

The node writes its Ed25519 key under SENTINEL_VAR (default: `var`, relative
to the working directory). systemd starts it in `/` with ProtectSystem=strict
and only <prefix>/var writable, so without SENTINEL_VAR it fails at start
with "Permission denied: 'var/keys'".
"""

import pathlib
import re

DEPLOY = pathlib.Path(__file__).resolve().parent.parent / "deploy"


def test_install_sh_writes_sentinel_var_under_the_prefix():
    text = (DEPLOY / "bundle" / "install.sh").read_text()
    assert re.search(r"^SENTINEL_VAR=\$PREFIX/var$", text, re.M)


def test_the_ansible_env_template_sets_sentinel_var_under_the_prefix():
    text = (DEPLOY / "ansible" / "roles" / "sentinel" / "templates" / "sentinel.env.j2").read_text()
    assert re.search(r"^SENTINEL_VAR=\{\{ sentinel_prefix \}\}/var$", text, re.M)


def test_the_unit_makes_exactly_that_directory_writable():
    unit = (DEPLOY / "systemd" / "sentinel.service").read_text()
    assert "ReadWritePaths=@PREFIX@/var" in unit


def test_the_public_node_does_not_run_the_assistant():
    """docs/deploy-aws.md: the public node does not run the AI assistant,
    and hosted AI is never opted in there."""
    template = (DEPLOY / "ansible" / "roles" / "sentinel" / "templates" / "sentinel.env.j2").read_text()
    assert re.search(r"^SENTINEL_AI=\{\{ '1' if sentinel_ai else '0' \}\}$", template, re.M)
    assert re.search(r"^SENTINEL_AI_CLOUD=0$", template, re.M)
    defaults = (DEPLOY / "ansible" / "roles" / "sentinel" / "defaults" / "main.yml").read_text()
    assert re.search(r"^sentinel_ai: false", defaults, re.M), "off unless a deployment turns it on"
    site = (DEPLOY / "ansible" / "site.yml").read_text()
    assert re.search(r"^\s+sentinel_ai: false", site, re.M)
