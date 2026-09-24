# Sentinel

A DDIL-resilient conjunction assessment decision aid for satellite operators.

**Status: risk engine, CDM codec and operator console implemented; engine validated against NASA CARA published cases. Sync and edge layers in progress.**

![Sentinel operator console](docs/img/console.png)

---

## What this is

A satellite operator receives warnings that a tracked object may pass close
to one of their assets, and must decide - before the maneuver commit point -
whether to spend propellant avoiding it. Sentinel is a decision aid for that
call, built around two claims.

**Claim one: a low probability of collision is not by itself evidence of safety.**

Collision probability is computed by integrating position uncertainty over
the combined hard-body radius. Past a certain point, *more* uncertainty
produces a *lower* probability - the mass gets smeared thin and less of it
lands on the disk. So a reassuring number can mean either "we know precisely
that these will miss" or "we barely know where either object is."

Sentinel computes where the operating point sits relative to that peak and
says so. Run `python3 scripts/dilution_demo.py`:

```
 sigma (m)            Pc        Pc max        k*                 verdict
------------------------------------------------------------------------
       100     9.656e-27     3.679e-07    50.000           bounded above
       300     2.148e-08^    3.679e-07     5.556           bounded above
       500     2.707e-07^    3.679e-07     2.000           bounded above
       646     3.614e-07^    3.679e-07     1.200           bounded above
       707     3.679e-07^    3.679e-07     1.000           bounded above
     1,000     3.033e-07v    3.679e-07     0.500  DILUTED - Pc unreliable
     2,041     1.065e-07v    3.679e-07     0.120  DILUTED - Pc unreliable
     5,000     1.960e-08v    3.679e-07     0.020  DILUTED - Pc unreliable
```

Geometry is identical on every row. Only the quality of the orbit solution
changes. The first row and the last row both report a probability below
1e-7; one is a precise measurement and the other is near-total ignorance.

The boundary has a closed form: dilution begins once the 1-sigma uncertainty
exceeds the miss distance over root two.

**Claim two: the tooling assumes connectivity it will not always have.**

Conjunction assessment tooling is overwhelmingly cloud-hosted. An operator
on a deployed ground station, a ship, or any denied or degraded link loses
the decision aid exactly when the decision still has to be made. The commit
point does not move because the network went down. The architecture for this
is designed (see `docs/system-design.md`, ADR-004 through ADR-006) and not
yet implemented.

---

## The operator console

`make serve`, then open http://127.0.0.1:8000. One process serves the API and the console.

- **Operations.** Active conjunctions sorted by time to the maneuver commit point, which is when a decision is due, not when a message arrived. A scripted exercise scenario plays out live: CDM updates arrive on schedule and the list re-ranks as they do.
- **The two plots that carry the argument.** The encounter-plane view and the Pc-vs-covariance-scale curve share one slider. Drag it and the uncertainty ellipse grows past the hard-body disk while Pc climbs, peaks, then *falls*. That is dilution, shown rather than described.
- **Refusals are first-class.** A refused event shows why, the value that tripped the gate, and the threshold. It is never shown as a zero.
- **Provenance on every number.** Inputs hash, engine version, source CDM hash, and the originator's own Pc labelled as theirs.
- **NASA reference.** The 53 CARA operational events, ingested through the same parser.
- **Validation.** The node re-runs the NASA comparison with the engine it is actually running and shows the agreement.

The globe is CesiumJS (Wayfinder's rendering engine) using imagery bundled with the application, with no ion token, geocoder or CDN. A headless-browser check confirms that loading the full console makes **zero requests beyond the node**: the console works on a network with no route to the internet, or it is not a field tool.

![Validation tab](docs/img/validation.png)

---

## What is deliberately *not* here

**No probability of collision without covariance.** Element sets alone do not
support a Pc, and the engine refuses rather than producing one. NASA CARA's
position is that two-line elements are not sufficient for conjunction
assessment - kilometre-scale theory error is too large for maneuver planning,
and no covariance is available to compute a probability from. Screening on
element sets and printing a Pc anyway is the most common way to get this
wrong.

**No number where the model does not apply.** Low relative velocity breaks
the rectilinear encounter assumption - the geostationary and similar-orbit
case. The engine detects it and refuses with a reason and the value that
tripped the gate, rather than returning something that looks authoritative.
Implementing the 3D numerical method that *would* handle those cases is
deferred; detecting that it is needed is not.

**No Pc where NASA's own reference says the 2D method is wrong.** CARA publishes 53 real operational conjunctions with its verdict on whether the 2D method applies. Sentinel's gate refuses **every one** of the 29 that CARA flags. On those events CARA's 3D result differs from the 2D value by up to 60,000× at orbital speeds, and by up to 162 orders of magnitude at low relative velocity. The threshold was calibrated on that same set, and the validation report states this next to the result.

---

## Validation

`docs/validation-report.md` is generated from two kinds of expected value: closed forms, and numbers NASA CARA published. None comes from running this code.

| check | reference | result |
|---|---|---|
| 53 real operational conjunctions (HST, TERRA, SWIFT, ...) | CARA's published Pc2D | worst relative error **1.5e-8** |
| Gate vs CARA's "2D invalid" verdicts | CARA's `ViolationsPc2D` | **29/29 refused, 0 missed**, 5 conservative refusals |
| Alfano (2009) benchmark, read from CDM files | CARA unit test | all within CARA's rtol 1e-3 |
| Omitron Case 1 | CARA `PcCircle` high-accuracy | 1.9e-8 |
| Omitron Case 2 | CARA `PcCircle` | difference explained to 1e-14 by miss-distance convention |
| Isotropic zero-miss integral | `1 - exp(-R²/2σ²)` | 2.2e-12 |
| Pc-maximising scale factor | `k* = (d²/2)/σ²` | 5.2e-07 |
| Maximum Pc | `Pc_max = R²/(e·d²)` | 4.2e-14 |

The NASA files are vendored **unmodified** under `fixtures/cara/`, with NOSA 1.3 agreements, provenance and SHA-256 checksums verified by the test suite. The quadrature is also cross-checked against `scipy.integrate.dblquad` in Cartesian coordinates (a different algorithm over a different parameterisation) at `rtol=1e-8`.

---

## Running it

```bash
uv venv && uv pip install -e ".[dev]"
uv run pytest -q                      # full ladder, network disabled, 0 skipped
uv run pytest -q -m tier3             # NASA CARA published cases
uv run sentinel assess fixtures/cara/PcTestCaseCDMs/000025994_conj_000037558_20210324_151047_20210323_154356.cdm
uv run python scripts/dilution_demo.py      # the demonstration above
uv run python scripts/validation_report.py  # regenerate docs/validation-report.md
```

The `assess` example is TERRA against a fragment of Iridium 33, a real 2021 event. Sentinel reproduces the originator's Pc of 2.1e-2 and flags it **diluted**: the covariance sits past the Pc peak, and the worst case over covariance scaling is 3.5e-2.

The test suite is organised as the ladder in `docs/risk-engine-design.md`
section 7, each tier a pytest marker:

| tier | what it establishes |
|---|---|
| 1 | frame rotation and encounter-plane geometry, no probability |
| 2 | the collision integral, against closed forms and an independent oracle |
| 3 | agreement with NASA CARA published cases, including the gate against CARA's own verdicts |
| 4 | maximum Pc and dilution detection |
| 5 | the applicability gate - every refusal path |
| 6 | the output contract |

---

## Layout

```
sentinel/cdm/          CCSDS 508.0-B-1 KVN codec and admission policy (ADR-001 seam)
sentinel/risk/
  types.py             result contract, refusal reasons, unit conventions
  frames.py            RTN to ECI rotation (each object has its own RTN frame)
  geometry.py          encounter-plane basis and projection
  encounter.py         TCA refinement, encounter plane, Pc(k) curve, curvature check
  integrate.py         the 2D collision integral and the maximum-Pc search
  engine.py            orchestration and the applicability gate
sentinel/validation/   loads NASA CARA published cases for tests and the report
fixtures/cara/         NASA CARA data, unmodified, with licence, provenance, checksums
docs/
  system-design.md        architecture decision records
  risk-engine-design.md   algorithm, pseudocode, test ladder
  validation-report.md    generated: closed forms and NASA CARA comparisons
```

---

## Design documents

The architecture decisions, including the ones rejected and why, are in
`docs/system-design.md`. The rejected alternatives are recorded deliberately:
anyone can choose a message bus, the useful part is being able to say why not
the other one.
