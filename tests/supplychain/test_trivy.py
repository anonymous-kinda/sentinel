"""Reading Trivy JSON reports, and the one place Trivy's argv is built."""

from supplychain.trivy import FINDINGS_EXIT, Finding, findings, trivy_command

REPORT = {
    "SchemaVersion": 2,
    "Results": [
        {"Target": "uv.lock", "Type": "uv", "Vulnerabilities": None},
        {
            "Target": "x86_64/nats-server",
            "Type": "gobinary",
            "Vulnerabilities": [
                {
                    "VulnerabilityID": "GO-2026-5932",
                    "PkgName": "golang.org/x/crypto",
                    "PkgIdentifier": {"PURL": "pkg:golang/golang.org/x/crypto@v0.57.0"},
                    "InstalledVersion": "v0.57.0",
                    "Severity": "UNKNOWN",
                }
            ],
        },
    ],
}


def test_findings_carry_the_id_the_package_url_the_target_and_severity():
    assert findings(REPORT) == [
        Finding("GO-2026-5932", "pkg:golang/golang.org/x/crypto@v0.57.0", "x86_64/nats-server", "UNKNOWN")
    ]


def test_a_clean_report_has_no_findings():
    assert findings({"SchemaVersion": 2}) == []
    assert findings({"SchemaVersion": 2, "Results": [{"Target": "a", "Vulnerabilities": []}]}) == []


def test_a_raw_scan_neither_applies_vex_nor_gates():
    argv = trivy_command("trivy", "fs", ".", fmt="json", output="out.json")
    assert argv[:2] == ["trivy", "fs"]
    assert "--vex" not in argv and "--exit-code" not in argv
    assert argv[-1] == "."
    # never phone home from a build that may run inside an enclave
    assert "--disable-telemetry" in argv and "--skip-version-check" in argv
    assert argv[argv.index("--scanners") + 1] == "vuln"


def test_a_gating_scan_applies_vex_and_fails_on_any_remaining_finding():
    argv = trivy_command("trivy", "rootfs", "bin", fmt="sarif", output="o.sarif", vex="v.json", gate=True)
    assert argv[argv.index("--vex") + 1] == "v.json"
    assert argv[argv.index("--exit-code") + 1] == str(FINDINGS_EXIT)
    assert argv[argv.index("--format") + 1] == "sarif"


def test_findings_exit_differs_from_trivys_own_error_exit():
    # Trivy exits 1 when it fails; a crashed scan must never read as "findings"
    assert FINDINGS_EXIT not in (0, 1)


def test_later_scans_reuse_the_database_the_first_scan_downloaded():
    argv = trivy_command("trivy", "fs", ".", fmt="json", output="o", skip_db_update=True)
    assert "--skip-db-update" in argv
