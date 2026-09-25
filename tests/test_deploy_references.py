"""Deployment files point at things that exist.

The unit's Documentation= and the STIG release named in the Ansible roles
are read by operators, and nothing ran them: a placeholder URL and a stale
benchmark name survived review. The repository itself stays the OWNER
placeholder the rest of the repo uses until the user chooses it.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
UNIT = ROOT / "deploy" / "systemd" / "sentinel.service"
ANSIBLE = ROOT / "deploy" / "ansible"
DISA = ROOT / "compliance" / "vendor" / "disa"
RELEASE = re.compile(r"V\d+R\d+")


def test_the_unit_documentation_names_a_document_in_this_repo():
    (url,) = re.findall(r"^Documentation=(\S+)$", UNIT.read_text(), re.M)
    match = re.fullmatch(r"https://github\.com/OWNER/sentinel/blob/main/(\S+)", url)
    assert match, f"{url} is not a document in this repo"
    assert (ROOT / match[1]).is_file(), match[1]


def test_every_stig_release_the_deploy_files_name_is_the_vendored_one():
    (xccdf,) = DISA.glob("U_CAN_Ubuntu_24-04_LTS_STIG_*_Manual-xccdf.xml")
    (vendored,) = RELEASE.findall(xccdf.name)
    named = {
        f"{path.relative_to(ROOT)}:{number} {release}"
        for path in sorted(ANSIBLE.rglob("*"))
        if path.is_file()
        for number, line in enumerate(path.read_text().splitlines(), start=1)
        for release in RELEASE.findall(line)
        if release != vendored
    }
    assert named == set(), f"the role targets {vendored}"
