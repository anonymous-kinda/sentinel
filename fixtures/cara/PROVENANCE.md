# NASA CARA test data: provenance

| | |
|---|---|
| Source | https://github.com/nasa/CARA_Analysis_Tools |
| Commit | `1c78beb1f7aefc384886c3be1d09e4681acb5d37` (committed 2026-09-08) |
| Retrieved | 2026-09-23 |
| Licence | NASA Open Source Agreement 1.3, copies in `license/` |
| Integrity | `SHA256SUMS`, verified by `tests/test_tier3_cara_validation.py` |

All files are byte-for-byte unmodified.

## What each file is used for

| Path | Upstream path | Used for |
|---|---|---|
| `PcTestCaseCDMs/*.cdm` (53) | `DataFiles/PcTestCaseCDMs/` | Real operational conjunctions (HST, TERRA, SWIFT, ...) run through Sentinel's CDM parser and engine |
| `PcTestCaseCDMs/CARA_PcMethod_Test_Conjunctions.xlsx` | same | CARA's published Pc2D, Nc2D, Nc3D and usage-violation flags for those 53 events. Expected values are transcribed from this file into `../cara_cases.json` by `scripts/transcribe_cara_fixtures.py`, **never from Sentinel output** |
| `PcTestCaseCDMs/README.md` | same | CARA's notes on cross-platform tolerance and TCA adjustment |
| `SampleCDMs/AlfanoTestCase01..11.cdm` | `DataFiles/SampleCDMs/` | Alfano (2009) benchmark cases, as CDM files |
| `SampleCDMs/OmitronTestCase_*.cdm` | same | Omitron cases, including a non-PD covariance (Test07) and a 2D-vs-3D disagreement case (Test08) |
| `SampleCDMs/FrisbeeMaxPcTestCase_Test01.cdm` | same | Reserved for the max-Pc "separate scaling" comparison (not yet claimed) |
| `Pc2D_Foster_UnitTest.m` | `DistributedMatlab/ProbabilityOfCollision/UnitTests/` | Source of the Alfano and Omitron Case 1 expected Pc (lines 31-44, 66) |
| `PcCircle_UnitTest.m` | same | Source of the high-accuracy Omitron Case 1 and Case 2 values (lines 62, 79) |
| `Pc3D_Hall_UnitTest.m` | same | 3D Nc values used to show why the gate refuses (lines 38-49, 110-111) |

## A note on the Alfano cases

The CARA unit test reads the Alfano inputs from spreadsheets
(`DataFiles/AlfanoInputData`). Sentinel reads the **CDM** encodings of the
same cases. Agreement therefore checks two independent routes to the same
number: the CDM files and Sentinel's parser, and CARA's spreadsheets and
CARA's integrator.
