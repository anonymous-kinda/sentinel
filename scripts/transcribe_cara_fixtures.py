#!/usr/bin/env python3
"""Transcribe NASA CARA's published expected values into fixtures/cara_cases.json.

Every expected value in the output comes from a file NASA published: the
53-conjunction results spreadsheet, or a literal in one of CARA's MATLAB
unit tests (quoted below with its line number). Nothing here runs
Sentinel. A fixture built from Sentinel's own output would prove only that
Sentinel agrees with itself.

Run:  uv run --with openpyxl python scripts/transcribe_cara_fixtures.py
"""

from __future__ import annotations

import hashlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CARA = ROOT / "fixtures" / "cara"
OUT = ROOT / "fixtures" / "cara_cases.json"
COMMIT = "1c78beb1f7aefc384886c3be1d09e4681acb5d37"
RETRIEVED = "2026-09-23"

UNSUPPORTED_2D_OVERRIDE = {
    "min_relative_speed_m_s": 0.0,
    "max_tca_adjustment_s": None,  # None = no limit
    "max_curvilinear_ratio": None,
}
OVERRIDE_WHY = (
    "Reproduces CARA's Pc2D_Foster unit test, which evaluates the 2D integral "
    "regardless of whether the linear encounter model applies. The default-config "
    "outcome for the same input is asserted separately."
)


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cdm_input(relative: str) -> dict:
    return {"cdm_file": relative, "sha256": sha256(CARA / relative)}


# --- Pc2D_Foster_UnitTest.m, lines 31 and 34-44 -----------------------------
ALFANO_HBR_M = [15, 4, 15, 15, 10, 10, 10, 4, 6, 6, 4]
ALFANO_PC2D = [
    1.46749549e-01, 6.22226700e-03, 1.00351176e-01, 4.93234060e-02,
    4.44873860e-02, 4.33545500e-03, 1.58147000e-04, 3.69480080e-02,
    2.90146291e-01, 2.90146291e-01, 2.67202600e-03,
]
# --- Pc3D_Hall_UnitTest.m, lines 38-49 (cases 01-11 of 12) -----------------
ALFANO_NC3D = [
    2.1680836276e-01, 1.5567748968e-02, 1.0033642320e-01, 7.3640419383e-02,
    4.4489813350e-02, 4.3331309702e-03, 1.6184123020e-04, 3.5250174961e-02,
    2.7983426149e-01, 3.6406379645e-01, 2.4407488450e-03,
]


def alfano_cases() -> list[dict]:
    cases = []
    for i in range(11):
        n = i + 1
        cases.append(
            {
                "case_id": f"ALFANO-{n:02d}",
                "group": "alfano_2009",
                "provenance": {
                    "source_path": "DistributedMatlab/ProbabilityOfCollision/UnitTests/Pc2D_Foster_UnitTest.m",
                    "source_lines": "31 (HBR), 34-44 (Pc2D); Pc3D_Hall_UnitTest.m 38-49 (Nc3D)",
                },
                "inputs": cdm_input(f"SampleCDMs/AlfanoTestCase{n:02d}.cdm"),
                "hbr_m": ALFANO_HBR_M[i],
                "config_override": UNSUPPORTED_2D_OVERRIDE,
                "override_justification": OVERRIDE_WHY,
                "expected": {
                    "pc2d": ALFANO_PC2D[i],
                    "nc3d": ALFANO_NC3D[i],
                    "default_outcome": "REFUSED:LOW_RELATIVE_VELOCITY",
                },
                "tolerance": {
                    "rtol": 1e-3,
                    "justification": "CARA's own RelTol for this test (AlfanoAccuracy, line 33)",
                },
            }
        )
    return cases


def omitron_cases() -> list[dict]:
    # Pc2D_Foster_UnitTest.m lines 48-60; PcCircle_UnitTest.m lines 48-57.
    inline_1 = {
        "frame": "ECI",
        "units": {"position": "km", "velocity": "km/s", "covariance": "km**2", "hbr": "km"},
        "r1": [378.39559, 4305.721887, 5752.767554],
        "v1": [2.360800244, 5.580331936, -4.322349039],
        "c1": [
            [44.5757544811362, 81.6751751052616, -67.8687662707124],
            [81.6751751052616, 158.453402956163, -128.616921644857],
            [-67.8687662707124, -128.616921644858, 105.490542562701],
        ],
        "r2": [374.5180598, 4307.560983, 5751.130418],
        "v2": [-5.388125081, -3.946827739, 3.322820358],
        "c2": [
            [2.31067077720423, 1.69905293875632, -1.4170164577661],
            [1.69905293875632, 1.24957388457206, -1.04174164279599],
            [-1.4170164577661, -1.04174164279599, 0.869260558223714],
        ],
        "hbr": 0.020,
    }
    # PcCircle_UnitTest.m lines 81-91 (cov1 scaled by 1e-3 on line 87).
    inline_2 = {
        "frame": "ECI",
        "units": {"position": "km", "velocity": "km/s", "covariance": "km**2", "hbr": "km"},
        "r1": [-3239.128337196251, 2404.575152356222, 5703.228541709001],
        "v1": [-3.745768373154199, 5.012339015927846, -4.231864565717194],
        "c1": [
            [0.342072996423899e-3, -0.412677096778269e-3, 0.371500417511149e-3],
            [-0.412677096778269e-3, 0.609905946319294e-3, -0.540401385544286e-3],
            [0.371500417511149e-3, -0.540401385544286e-3, 0.521238634755377e-3],
        ],
        "r2": [-3239.138264917246, 2404.568320465936, 5703.235605231182],
        "v2": [6.110192790100711, -1.767321407894830, 4.140369261741708],
        "c2": [
            [0.028351300975134, -0.008204103437377, 0.019253747960155],
            [-0.008204103437377, 0.002404377774847, -0.005586512197914],
            [0.019253747960155, -0.005586512197914, 0.013289250260317],
        ],
        "hbr": 0.020,
    }
    return [
        {
            "case_id": "OMITRON-01-INLINE",
            "group": "omitron",
            "provenance": {
                "source_path": "DistributedMatlab/ProbabilityOfCollision/UnitTests/PcCircle_UnitTest.m",
                "source_lines": "48-57 (inputs), 62 (expected, RelTol 1e-10 in CARA)",
            },
            "inputs": {"inline": inline_1},
            "hbr_m": 20.0,
            "config_override": None,
            "expected": {"pc2d": 2.706023476569787e-05, "default_outcome": "PC"},
            "tolerance": {
                "rtol": 1e-6,
                "justification": "Two orders tighter than the smallest known modelling difference "
                "(the miss-distance convention, 1.6e-4 on OMITRON-02); looser than CARA's "
                "1e-10 self-regression because the quadratures differ",
            },
        },
        {
            "case_id": "OMITRON-02-INLINE",
            "group": "omitron",
            "provenance": {
                "source_path": "DistributedMatlab/ProbabilityOfCollision/UnitTests/PcCircle_UnitTest.m",
                "source_lines": "79 (expected), 81-91 (inputs)",
            },
            "inputs": {"inline": inline_2},
            "hbr_m": 20.0,
            "config_override": None,
            "expected": {
                "pc2d_full_r_convention": 1.807363058494765e-01,
                "default_outcome": "PC",
                "note": "CARA's unadjusted methods use |r| (including the component along the "
                "relative velocity) as the in-plane miss distance. Sentinel uses the in-plane "
                "miss at the refined TCA. Reproducing CARA's convention must match to rtol.",
            },
            "tolerance": {
                "rtol": 1e-9,
                "justification": "Same Gaussian, same disk, same convention: only quadrature error remains",
            },
        },
        {
            "case_id": "OMITRON-07-NONPD",
            "group": "omitron",
            "provenance": {
                "source_path": "DistributedMatlab/ProbabilityOfCollision/UnitTests/Pc2D_Foster_UnitTest.m",
                "source_lines": "100-112 (CARA remediates the covariance and reports Pc = 0)",
            },
            "inputs": cdm_input("SampleCDMs/OmitronTestCase_Test07_NonPDCovariance.cdm"),
            "hbr_m": 20.0,
            "config_override": None,
            "expected": {
                "default_outcome": "REFUSED:INVALID_COVARIANCE",
                "divergence": "CARA repairs a non-positive-definite covariance and returns Pc = 0. "
                "Sentinel refuses: a repaired covariance is not the one the originator supplied.",
            },
            "tolerance": {"rtol": 0.0, "justification": "categorical outcome"},
        },
        {
            "case_id": "OMITRON-08-3DNC",
            "group": "omitron",
            "provenance": {
                "source_path": "DistributedMatlab/ProbabilityOfCollision/UnitTests/Pc3D_Hall_UnitTest.m",
                "source_lines": "107-121 (HBR 20, Pc2D 2.2660816e-20, Nc3D 1.9271201e-05)",
            },
            "inputs": cdm_input("SampleCDMs/OmitronTestCase_Test08_3DNc.cdm"),
            "hbr_m": 20.0,
            "config_override": UNSUPPORTED_2D_OVERRIDE,
            "override_justification": OVERRIDE_WHY,
            "expected": {
                "pc2d": 2.2660816e-20,
                "nc3d": 1.9271201e-05,
                "default_outcome": "REFUSED:LOW_RELATIVE_VELOCITY",
            },
            "tolerance": {"rtol": 1e-3, "justification": "CARA's own RelTol for this test (line 109)"},
        },
        {
            "case_id": "OMITRON-06-MINRELVEL",
            "group": "omitron",
            "provenance": {
                "source_path": "DataFiles/SampleCDMs/OmitronTestCase_Test06_MinRelVel.cdm",
                "source_lines": "whole file (named by CARA as the minimum-relative-velocity case)",
            },
            "inputs": cdm_input("SampleCDMs/OmitronTestCase_Test06_MinRelVel.cdm"),
            "hbr_m": 20.0,
            "config_override": None,
            "expected": {"default_outcome": "REFUSED:LOW_RELATIVE_VELOCITY"},
            "tolerance": {"rtol": 0.0, "justification": "categorical outcome"},
        },
    ]


def operational_cases() -> list[dict]:
    import openpyxl

    xlsx = CARA / "PcTestCaseCDMs" / "CARA_PcMethod_Test_Conjunctions.xlsx"
    rows = list(openpyxl.load_workbook(xlsx, data_only=True).active.iter_rows(values_only=True))
    header = {name: i for i, name in enumerate(rows[0])}
    cases = []
    for rownum, row in enumerate(rows[1:], start=2):
        cid = row[header["Conjunction_ID"]]
        cases.append(
            {
                "case_id": cid,
                "group": "cara_operational",
                "provenance": {
                    "source_path": "DataFiles/PcTestCaseCDMs/CARA_PcMethod_Test_Conjunctions.xlsx",
                    "source_lines": f"Sheet1 row {rownum}",
                },
                "inputs": cdm_input(f"PcTestCaseCDMs/{cid}.cdm"),
                "hbr_m": row[header["HBR_m"]],
                "config_override": {"min_relative_speed_m_s": 0.0, "max_curvilinear_ratio": None},
                "override_justification": "Pc2D values in the spreadsheet are computed for every "
                "event, including those CARA flags as outside the 2D method's validity. The gate "
                "decision is checked separately against CARA's ViolationsPc2D column.",
                "expected": {
                    "pc2d": row[header["Pc2D"]],
                    "pc2d_no_tca_adjustment": row[header["Pc2D_NoAdj"]],
                    "nc3d": row[header["Nc3D"]],
                    "cara_pc2d_usage_violation": (row[header["ViolationsPc2D"]] or 0) > 0,
                    "cara_comment": row[header["Comment"]],
                    "primary": row[header["PrimaryName"]],
                    "secondary": row[header["SecondaryName"]],
                },
                "tolerance": {
                    "rtol": 1e-6,
                    "justification": "CARA's README reports cross-platform differences at the 1e-8 "
                    "level and below; 1e-6 leaves margin while staying two orders tighter than "
                    "any known modelling difference",
                },
            }
        )
    return cases


def main() -> None:
    cases = alfano_cases() + omitron_cases() + operational_cases()
    payload = {
        "schema": 2,
        "cara_commit_sha": COMMIT,
        "retrieved": RETRIEVED,
        "note": "Expected values transcribed from NASA-published files; never from Sentinel output.",
        "cases": cases,
    }
    OUT.write_text(json.dumps(payload, indent=1) + "\n")
    print(f"wrote {OUT} ({len(cases)} cases)")


if __name__ == "__main__":
    main()
