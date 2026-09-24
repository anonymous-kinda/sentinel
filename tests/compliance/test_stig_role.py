"""The STIG role against DISA's text and against stig.toml.

The role cannot run here (no Ubuntu host, no root). What can be proven
without one is proven: every rule id it names is real and decided, every
applied rule is implemented, and the values it writes are DISA's values,
compared with the vendored XCCDF rather than retyped.
"""

import pathlib
import re

import pytest

from compliance.sources import load_sources
from compliance.stig import load_benchmark

ROOT = pathlib.Path(__file__).resolve().parents[2]
ROLE = ROOT / "deploy/ansible/roles/stig"
XCCDF = ROOT / "compliance/vendor/disa/U_CAN_Ubuntu_24-04_LTS_STIG_V1R6_Manual-xccdf.xml"
STIG_ID = re.compile(r"UBTU-24-\d{6}")


@pytest.fixture(scope="module")
def decisions():
    return load_sources(ROOT / "compliance" / "sources").stig


@pytest.fixture(scope="module")
def fixes():
    import xml.etree.ElementTree as ET

    ns = {"x": "http://checklists.nist.gov/xccdf/1.1"}
    root = ET.parse(XCCDF).getroot()
    return {
        g.find("x:Rule", ns).findtext("x:version", namespaces=ns): (
            g.find("x:Rule", ns).findtext("x:fixtext", namespaces=ns),
            g.find("x:Rule", ns).findtext("x:check/x:check-content", namespaces=ns),
        )
        for g in root.findall("x:Group", ns)
    }


def role_text() -> str:
    return "\n".join(p.read_text() for p in sorted(ROLE.rglob("*")) if p.is_file())


def test_every_rule_the_role_names_is_a_decided_v1r6_rule(decisions):
    named = set(STIG_ID.findall(role_text()))
    benchmark = load_benchmark(XCCDF)
    assert named - set(benchmark.rules) == set(), "the role names rules that are not in V1R6"
    assert named - set(decisions.decided()) == set(), "the role names rules stig.toml does not decide"


def test_every_applied_rule_is_implemented_by_the_role(decisions):
    named = set(STIG_ID.findall(role_text()))
    assert [r for r in decisions.applied if r not in named] == []


def test_the_role_does_not_claim_a_not_applicable_rule(decisions):
    named = set(STIG_ID.findall(role_text()))
    assert [r for n in decisions.not_applicable for r in n.rules if r in named] == []


def defaults_value(key: str) -> str:
    text = (ROLE / "defaults" / "main.yml").read_text()
    return re.search(rf"^\s+{key}: (\S+)$", text, re.MULTILINE).group(1)


@pytest.mark.parametrize(
    ("stig_id", "keyword"),
    [("UBTU-24-100820", "Ciphers"), ("UBTU-24-100830", "MACs"), ("UBTU-24-100840", "KexAlgorithms")],
)
def test_ssh_algorithms_are_exactly_disas(fixes, stig_id, keyword):
    fix, _ = fixes[stig_id]
    required = re.search(rf"^{keyword} (\S+)", fix, re.MULTILINE | re.IGNORECASE).group(1)
    assert defaults_value(keyword) == required


@pytest.mark.parametrize(
    "stig_id",
    ["UBTU-24-200280", "UBTU-24-200290", "UBTU-24-200300", "UBTU-24-200310", "UBTU-24-200320",
     "UBTU-24-900070", "UBTU-24-900170", "UBTU-24-900340", "UBTU-24-900350", "UBTU-24-900510",
     "UBTU-24-900520"],
)
def test_audit_rules_are_the_fix_text_rules(fixes, stig_id):
    fix, _ = fixes[stig_id]
    required = [line.strip() for line in fix.splitlines() if re.match(r"^\s*-[wa] ", line)]
    installed = [line.strip() for line in (ROLE / "files" / "stig.rules").read_text().splitlines()]
    assert required and all(rule in installed for rule in required)


def test_audit_rules_end_immutable():
    rules = [line for line in (ROLE / "files" / "stig.rules").read_text().splitlines() if line.startswith("-")]
    assert rules[-1] == "-e 2"


def verbatim(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines()).strip("\n") + "\n"


def test_dod_banner_is_the_stig_text(fixes):
    fix, _ = fixes["UBTU-24-200640"]
    start = fix.index('"You are accessing') + 1
    end = fix.index('See User Agreement for details."') + len("See User Agreement for details.")
    assert (ROLE / "files" / "dod-banner.txt").read_text() == verbatim(fix[start:end])


def test_ssh_acknowledgement_script_is_the_stig_script(fixes):
    fix, _ = fixes["UBTU-24-200680"]
    start = fix.index("#!/bin/bash")
    end = fix.index("\nfi", start) + len("\nfi")
    assert (ROLE / "files" / "ssh_confirm.sh").read_text() == verbatim(fix[start:end])


def yaml_single_quoted(task_file: str, key: str, after: str) -> str:
    """A single-quoted YAML scalar from a task file, unescaped ('' -> ')."""
    text = (ROLE / "tasks" / task_file).read_text()
    block = text[text.index(after):]
    raw = re.search(rf"^\s+{key}: '(.*)'$", block, re.MULTILINE).group(1)
    return raw.replace("''", "'")


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ('GRUB_CMDLINE_LINUX=""', 'GRUB_CMDLINE_LINUX=" audit=1"'),
        ('GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"', 'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash audit=1"'),
        ('GRUB_CMDLINE_LINUX_DEFAULT="quiet audit=1 splash"', 'GRUB_CMDLINE_LINUX_DEFAULT="quiet audit=1 splash"'),
        ('GRUB_CMDLINE_LINUX="noaudit=1"', 'GRUB_CMDLINE_LINUX="noaudit=1 audit=1"'),
        ('GRUB_TIMEOUT=0', 'GRUB_TIMEOUT=0'),
    ],
)
def test_grub_edit_adds_audit_once_and_only_to_the_command_lines(before, after):
    # ansible.builtin.replace compiles regexp with re.MULTILINE and calls subn.
    regexp = yaml_single_quoted("audit.yml", "regexp", "Auditing starts at boot")
    replace = yaml_single_quoted("audit.yml", "replace", "Auditing starts at boot")
    once = re.compile(regexp, re.MULTILINE).sub(replace, before)
    assert once == after
    assert re.compile(regexp, re.MULTILINE).sub(replace, once) == once
