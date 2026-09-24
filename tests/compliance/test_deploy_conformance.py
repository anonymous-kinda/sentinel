"""Deployment configuration conformance: the settings the SSP relies on are in the files that ship.

These check configuration as code, not a running host (that is the STIG
scan's job). Each checker is also run against a copy with the setting
broken, to show it would catch the regression rather than pass by accident.
"""

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    return (ROOT / relative).read_text()


def subjects(conf: str, key: str) -> set[str]:
    match = re.search(rf"{key}:\s*\[([^\]]*)\]", conf)
    return set(re.findall(r'"([^"]+)"', match.group(1))) if match else set()


# ------------------------------------------------------------------ AC-4 OPSEC
def leaf_problems(conf: str) -> list[str]:
    problems = []
    if not {"unit.>", "passes.>", "node.>"} <= subjects(conf, "deny_exports"):
        problems.append("edge may export unit.>, passes.> or node.> to the hub")
    if "node.>" not in subjects(conf, "deny_imports"):
        problems.append("edge may import the hub's node-local subjects")
    return problems


def test_edge_never_exports_unit_passes_or_node_subjects():
    conf = read("deploy/nats/edge.conf.tmpl")
    assert leaf_problems(conf) == []
    assert leaf_problems(conf.replace('"unit.>", ', "")) == ["edge may export unit.>, passes.> or node.> to the hub"]
    assert leaf_problems(conf.replace('deny_imports: ["node.>"]', "")) == ["edge may import the hub's node-local subjects"]


# ------------------------------------------------------- CM-6 NATS DDIL fixes
DDIL_SETTINGS = {
    "deploy/nats/hub.conf.tmpl": [r"no_advertise:\s*true", r"authorization\s*\{\s*timeout:\s*30\s*\}",
                                  r'ping_interval:\s*"5s"', r"ping_max:\s*3"],
    "deploy/nats/edge.conf.tmpl": [r'first_info_timeout:\s*"20s"', r'ping_interval:\s*"5s"', r"ping_max:\s*3"],
}


def missing(text: str, patterns: list[str]) -> list[str]:
    return [p for p in patterns if not re.search(p, text)]


@pytest.mark.parametrize("path", sorted(DDIL_SETTINGS))
def test_nats_settings_carry_the_ddil_fixes(path):
    conf = read(path)
    assert missing(conf, DDIL_SETTINGS[path]) == []
    assert missing(conf.replace("ping_max: 3", "ping_max: 2"), DDIL_SETTINGS[path]) == [r"ping_max:\s*3"]


# --------------------------------------------------------- AC-6 / SC-7 service
SERVICE = [
    r"^User=sentinel$", r"^NoNewPrivileges=yes$", r"^CapabilityBoundingSet=$", r"^AmbientCapabilities=$",
    r"^ProtectSystem=strict$", r"^ReadWritePaths=@PREFIX@/var$", r"^UMask=0077$",
    r"^RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX$", r"^ExecStart=.* --host 127\.0\.0\.1 ",
]


def test_service_runs_unprivileged_sandboxed_and_on_loopback():
    unit = read("deploy/systemd/sentinel.service")
    assert [p for p in SERVICE if not re.search(p, unit, re.MULTILINE)] == []
    exposed = unit.replace("--host 127.0.0.1", "--host 0.0.0.0")
    assert [p for p in SERVICE if not re.search(p, exposed, re.MULTILINE)] == [r"^ExecStart=.* --host 127\.0\.0\.1 "]


# ------------------------------------------------------- AC-17 / IA-2 SSH baseline
SSHD = [r"PasswordAuthentication no", r"KbdInteractiveAuthentication no", r"PermitRootLogin no",
        r"X11Forwarding no", r"ClientAliveCountMax 1", r"MaxAuthTries 3"]


def sshd_problems(tasks: str) -> list[str]:
    problems = missing(tasks, SSHD)
    interval = re.search(r"ClientAliveInterval (\d+)", tasks)
    if not interval or int(interval.group(1)) > 600:
        problems.append("ClientAliveInterval above 600 s")
    return problems


def test_sshd_baseline_accepts_keys_only_and_times_out_idle_sessions():
    tasks = read("deploy/ansible/roles/baseline/tasks/main.yml")
    assert sshd_problems(tasks) == []
    assert sshd_problems(tasks.replace("PasswordAuthentication no", "PasswordAuthentication yes")) == [
        "PasswordAuthentication no"
    ]
    assert sshd_problems(tasks.replace("ClientAliveInterval 300", "ClientAliveInterval 900")) == [
        "ClientAliveInterval above 600 s"
    ]


# ---------------------------------------------------------- AWS hub (SC-7, SC-28, AC-6)
TERRAFORM = [
    r"encrypted\s*=\s*true",
    r'http_tokens\s*=\s*"required"',
    r'var\.admin_cidr != "0\.0\.0\.0/0"',
    r"cidr_ipv4\s*=\s*var\.admin_cidr",
    r"for_each\s*=\s*toset\(var\.leaf_allowed_cidrs\)",
]


def test_hub_infrastructure_encrypts_restricts_admin_and_closes_the_leaf_port():
    code = read("deploy/aws/terraform/main.tf") + read("deploy/aws/terraform/variables.tf")
    assert missing(code, TERRAFORM) == []
    assert re.findall(r'policy_arn\s*=\s*"([^"]+)"', code) == ["arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"]
    assert re.search(r'leaf_allowed_cidrs"\s*\{[^}]*default\s*=\s*\[\]', code, re.DOTALL)
    assert missing(code.replace("encrypted             = true", "encrypted = false"), TERRAFORM) == [r"encrypted\s*=\s*true"]
