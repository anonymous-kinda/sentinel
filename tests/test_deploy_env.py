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
