# 2. The risk engine

## What you will learn

- What a conjunction is, and what a probability of collision (Pc) measures.
- How two states and two covariances become one 2D problem on the encounter plane, and how the code integrates it.
- Why a low Pc can mean "we know too little" rather than "we are safe", and how the engine detects that (dilution).
- Every reason the engine refuses to give a number, and why refusing beats approximating.
- How the engine is held to NASA CARA's published results, and what rule keeps that comparison honest.

## Why it exists

An operator gets a warning that a tracked object will pass close to their satellite. Before the maneuver commit point they must decide whether to burn propellant. The number they decide on is the Pc.

That number can mislead in two ways. First, it can be plausible and wrong: a unit slip, a bad frame rotation, or a numerical integral that stepped over its own answer all produce a value that looks fine. Second, it can be right and still misleading: when the position uncertainty is large, the Pc goes *down* as the data gets *worse*. A tiny Pc from bad tracking looks like a tiny Pc from good tracking.

`sentinel/risk/` answers both. It returns a Pc only when the method applies and the integral is proven resolved, with the method attached. It also returns the worst case over covariance scaling and a flag when the Pc sits in the region where ignorance lowers it. When it cannot give a trustworthy number, it says so, names the reason and records the value that tripped the check. It never falls back to a guess.

## Concepts

### A conjunction

A conjunction is a predicted close approach between two tracked objects. A screening service propagates both orbits, finds the time of closest approach (TCA), and issues a Conjunction Data Message (CDM, chapter 3). For each object the CDM gives:

- its position (km) and velocity (km/s) at TCA, in an inertial frame;
- a position covariance (m²): a 3×3 matrix describing how uncertain that position is;
- optionally, its size.

The first object is the *primary* (usually the satellite you operate), the second the *secondary*. Updates arrive as tracking improves, so one event is a sequence of CDMs.

### Probability of collision

Neither position is known exactly. Model the secondary's position relative to the primary as a Gaussian random vector: its mean is the predicted miss vector, its covariance is the two objects' covariances combined. Treat each object as a sphere. They collide if, at closest approach, their centres are closer than the sum of their radii. Pc is the probability of that.

### Two frames, and why the covariances cannot simply be added

A CDM gives each covariance in that object's own RTN frame:

```
          R  radial: along the position vector, away from the Earth's centre
          ^
          |
          o----->  T  along-track: roughly the direction of motion
         /
        C   cross-track: along the orbit normal, r x v
```

The primary's RTN axes and the secondary's RTN axes point in different directions, because each is built from that object's own position and velocity. Adding the two matrices as given would add numbers expressed in different coordinates. So each covariance is rotated into the common inertial frame (ECI) first, `C_eci = M C_rtn Mᵀ` with `M = [R̂ T̂ Ĉ]`, and only then added:

```
C = C1_eci + C2_eci      valid when the two orbit determinations are independent
```

Independence is an assumption. The engine records it in every result (`independence_assumed`).

### The encounter plane

Low-orbit objects meet at kilometres per second. Around TCA the encounter lasts a fraction of a second, and over that time both objects move in straight lines at constant velocity. The relative motion is a straight line along the relative velocity `dv`. The question "do the spheres touch?" is then two-dimensional: where does that line cross the plane perpendicular to `dv`? That plane is the encounter plane.

Looking down the relative velocity, with the primary at the origin:

```
                    y
                    ^             .-~~~~~-.
                    |           /           \      the secondary's position:
          .--.      |          |      *      |     a 2D Gaussian centred on the
         (  o )-----+----------|-----mu------|---> x   miss vector mu (x points
          '--'      |          |             |         along the miss)
     hard-body disk |           \           /
     of radius HBR  |             '-~~~~~-'
     at the origin
```

Pc is the probability mass of that Gaussian that falls inside the disk. The code builds the plane from three unit vectors: `ẑ` along `dv`, `x̂` along the part of the miss vector perpendicular to `dv`, and `ŷ = ẑ × x̂`. Projecting the combined covariance and the miss vector onto `x̂` and `ŷ` gives a 2×2 covariance `C₂d` and a 2-vector `μ`.

Two details matter:

- **TCA refinement.** A CDM's TCA is rounded to the millisecond, so its states are slightly off the true closest approach (at 15 km/s, 1 ms is 15 m). The engine moves both states to the linear closest approach, `dt = −(dr·dv)/|dv|²`, as CARA's `FindNearbyCA` does. That shift is along `ẑ`, so it does not change the 2D Pc, but it corrects the miss distance. A shift beyond 10 ms cannot be rounding, and the engine refuses (`TCA_INCONSISTENT`).
- **Curvature.** The straight-line picture fails when the encounter is slow (co-orbiting pairs, GEO) or when an object's along-track uncertainty is so large that it follows the curved orbit rather than a line. Both are refusal gates.

### The hard-body radius

Each object is modelled as a sphere. Only the sum of the two radii enters the 2D integral: the combined hard-body radius, HBR. Pc is very sensitive to it. When the disk is small against the uncertainty, Pc grows with HBR².

The radius comes from the CDM (chapter 3 gives the precedence: an explicit override, then a `COMMENT HBR = ...` line, then each object's `AREA_PC`). If none is available the engine refuses with `NO_HBR`. It invents a radius only when `AssessmentConfig.default_radius_m` is set, and it records `hbr_defaulted` when it does. A node sets no default.

### The Foster-Estes 2D integral

The Pc is the Gaussian's mass over the disk:

```
Pc = 1 / (2π √det C₂d)  ∬_{|u| ≤ HBR}  exp(−½ (u−μ)ᵀ C₂d⁻¹ (u−μ)) du
```

There is no closed form for an offset, anisotropic Gaussian over a disk, so it is integrated numerically. The code reduces it to one dimension:

```
      rotate to the covariance's principal axes (x narrow, y wide)

            ______            for each x across the disk, the chord runs
          /   |    \          from y = −h(x) to y = +h(x), h = √(HBR² − x²);
         /    | h   \         the Gaussian's integral along y over the chord
        |-----+------|        is exact: a difference of two erf values.
         \    |     /
          \___|____/          what is left is a 1D integral over x,
        −HBR  x   +HBR        done numerically with x = HBR cos θ.
```

The substitution `x = HBR cos θ` removes the infinite slope of `h(x)` at the disk's edge. The remaining integral over `θ ∈ [0, π]` is smooth and is done with composite Gauss-Legendre quadrature: the interval is cut into panels, and each panel gets a 16-point rule.

The hard case is a disk much larger than the uncertainty. The integrand is then a narrow spike, about `σ/HBR` wide in `θ`. A grid that steps over the spike returns a plausible, wrong number. The code has two rules and checks whichever one ran:

- **Uniform rule.** `4·HBR/σ_min` equal panels over `[0, π]` (at least 16), about 0.8 σ per panel. It is used whenever that count fits within `quadrature_panels_cap` (4096). Every CARA case at `k = 1` runs here.
- **Windowed rule.** Beyond the cap, the integral is taken only where the integrand can be represented at all. More than 40 σ from its centre the Gaussian is below `exp(−800)`, smaller than any float64. The window is split where the erf factor turns over, into at most five pieces, and each piece gets 640 panels. The cost no longer grows with `HBR/σ`.
- **The self-check.** On the same nodes the code also integrates the Gaussian factor alone: the probability that a 1D normal `N(m_x, σ_x²)` lands in `[−HBR, HBR]`, which has a closed form. A grid that missed the spike misses that mass too. If the two disagree beyond `1e-6` relative plus `1e-15` absolute, the integrator raises `UnresolvedIntegral` instead of returning a number. That happens only when σ is so far below HBR (around 10⁻¹³ of it) that the spike fits inside one float64 step.

### Dilution

Scale the covariance by a factor `k` and watch the Pc:

```
   Pc
    ^                 Pc_max at k*
    |                  _.--._
    |               .-'      '-.
    |             .'            '-._
    |           .'                  '--.__
    |  ______.-'                          '---.______
    +-----------------------------------------------------> log k
               ^                        ^
        k = 1 here: k* > 1,       k = 1 here: k* < 1,
        more uncertainty would    more uncertainty would
        raise Pc. Not diluted.    lower Pc. DILUTED.
```

At small `k` the Gaussian is a tight spot away from the disk and catches almost no mass. At large `k` it is spread so thin that the disk again catches almost none. In between is a peak at `k*`, with `Pc_max = Pc(k*)`. The operating point is `k = 1`. If `k* < 1` the operator is on the falling side: better data would *raise* the Pc. That Pc says more about the tracking than about the risk, and the engine sets `dilution_flag` and reports `dilution_margin = ln k*`.

For an isotropic covariance `σ²I`, miss distance `d` and a small disk, `Pc ≈ (HBR²/2σ²)·exp(−d²/2σ²)`. Maximising over `σ²` gives `k* = d²/(2σ²)` and `Pc_max = HBR²/(e·d²)`. So the boundary is `σ = d/√2`, and `Pc_max` depends on the geometry only, not on how well anyone tracked the objects. Deep in the diluted region `Pc ∝ 1/σ²`: ten times more uncertainty gives a hundred times lower Pc.

One special case: if the miss vector is inside the disk, `Pc(k)` never rises as `k` grows. The disk is convex, so the probability of landing in it only shrinks as the Gaussian spreads. The maximum is at the smallest `k` searched. The code returns that bound with `k_star_at_search_bound` set, rather than searching a flat plateau.

### Refusing

The engine checks, in this order, whether the model applies. The first failing check returns `Method.REFUSED` with a `RefusalReason`, `pc = None`, and the tripping value in `diagnostics`:

| # | Reason | Trips when | Default |
|---|---|---|---|
| 1 | `NO_COVARIANCE` | either object has no covariance | |
| 2 | `NO_HBR` | no radius for an object, and no configured default | |
| 3 | `INVALID_COVARIANCE` | a supplied covariance is not positive definite, or cannot be decomposed (`stage: input_covariance`) | |
| 4 | `LOW_RELATIVE_VELOCITY` | relative speed below the threshold | 100 m/s |
| 5 | `TCA_INCONSISTENT` | the refinement shift `abs(dt)` exceeds the threshold | 10 ms |
| 6 | `INVALID_COVARIANCE` | the projected `C₂d` is not positive definite (`stage: projected_covariance`) | |
| 7 | `ILL_CONDITIONED_COVARIANCE` | `C₂d`'s condition number exceeds the threshold | 1e12 |
| 8 | `CURVILINEAR_UNCERTAINTY` | an object's 1-σ along-track sagitta, `σ_T²/(2|r|)`, exceeds a fraction of the smallest σ in the plane | 0.1 |
| 9 | `UNRESOLVED_INTEGRAL` | the Pc at `k = 1` cannot be resolved (`stage: pc`) | |
| 10 | `UNRESOLVED_INTEGRAL` | a scale the worst-case search needs cannot be resolved (`stage: max_pc_search`) | |

The sagitta in gate 8 is how far an arc of length `s` on a circle of radius `r` bows away from its chord, `s²/(2r)`. When the along-track uncertainty bends by a tenth of the plane's tightest σ, the flat Gaussian no longer describes where the object can be. The threshold was calibrated against CARA's own verdicts; the calibration is in-sample, and the report says so.

A refusal still reports what can be derived without the model: the miss distance, the relative speed, the HBR and the inputs hash.

## Code walkthrough

Read the files in this order. Each builds on the one before.

### `sentinel/risk/types.py`

The engine's vocabulary. `ObjectState` holds one object at TCA, with its units in its field names: `position_km`, `velocity_km_s`, `covariance_rtn_m2`, `radius_m`. `Conjunction` holds two states and is the engine's only input shape, whatever the data source (ADR-001). `Method` and `RefusalReason` are the enums above. `AssessmentConfig` holds every threshold, because the right value depends on the regime: a GEO operator and a LEO operator disagree on what counts as slow. `AssessedConjunction` is the output, and `to_dict()` is its JSON form for the decision log and the API.

`Conjunction.inputs_hash()` is a SHA-256 over the ids, states, covariances and radii. It lets anyone check later that a number came from exactly these inputs.

*Easy to get wrong:* the hash covers inputs, not configuration and not the TCA. The same states under a different threshold hash the same. The node records configuration separately, in its engine version (chapter 3).

### `sentinel/risk/frames.py`

`rtn_to_eci_matrix(position, velocity)` returns `M = [R̂ T̂ Ĉ]` as columns, and `rotate_covariance_rtn_to_eci` returns `M C Mᵀ`. `M` is orthonormal with determinant +1, so the rotation preserves trace and determinant, which the tier 1 tests check.

*Easy to get wrong:* rotating only one object, or assuming the two share a frame. Each covariance is rotated with its *own* object's position and velocity. The function raises `ValueError` when the position is zero or the velocity is parallel to it, because RTN is then undefined.

### `sentinel/risk/geometry.py`

`encounter_plane_basis(dr, dv)` returns `(x̂, ŷ, ẑ)`. `x̂` is the component of `dr` perpendicular to `dv`, normalised, so the projected miss is `(|r_perp|, 0)` by construction. For a direct hit (`r_perp` near zero) any perpendicular direction serves, and `_any_unit_perpendicular_to` picks one. `tca_residual` is the component of `dr` along `ẑ`: zero at a true closest approach.

*Easy to get wrong:* assuming `dr` is already perpendicular to `dv`. At a rounded TCA it is not quite, so the code computes the perpendicular part rather than normalising `dr`.

### `sentinel/risk/encounter.py`

The geometry the integral runs on. Nothing here decides whether the model applies; `engine.py` does.

- `relative_state` gives secondary minus primary, converted to metres. This is where the states' km become m.
- `linear_tca_adjustment_s` and `refine_to_tca` implement the TCA refinement.
- `combined_covariance_eci_m2` rotates each object's covariance and adds them.
- `build_encounter_plane` returns an `EncounterPlane`: `cov_2d_m2`, `mu_m`, `hbr_m`, the basis, the relative state at the refined TCA and the shift `tca_adjustment_s`. Forming `C₂d` from a covariance near the float64 limit can overflow; the code silences that warning with `np.errstate` and lets the non-finite matrix reach the engine's gate, which refuses it.
- `EncounterPlane.pc(scale)` and `pc_curve` call the same integrator the engine uses. The console's encounter plot and dilution curve (chapter 5) are drawn from them.
- `curvilinear_check` computes gate 8's ratio and names the object whose arc bends most.

*Easy to get wrong:* the covariances are not moved across the refinement shift `dt`. For a sub-millisecond shift the change is far below the covariance's own precision, and CARA's reference computation makes the same choice. That is why a large `dt` is refused rather than handled.

### `sentinel/risk/integrate.py`

The maths that has to be right. `gaussian_mass_over_disk(covariance_2d, mean, radius, panel_cap)`:

1. symmetrises the matrix, raises `ValueError` if it is not positive definite (it is never repaired);
2. eigendecomposes it; `eigh` sorts ascending, so the first axis, the one integrated numerically, is the narrow one;
3. picks nodes with `_quadrature_nodes`: `_uniform_nodes` when `4·radius/σ_min` fits in `panel_cap`, otherwise `_windowed_nodes`, whose pieces come from `_window_breaks`;
4. evaluates the erf chord integral and the Gaussian factor at each node;
5. calls `_require_resolved`, which integrates the Gaussian factor alone on the same nodes and compares it with the closed form from `_normal_mass`. On disagreement it raises `UnresolvedIntegral(sigma_min)`;
6. returns the sum, clipped to `[0, 1]`.

`maximize_pc_over_scale` finds `k*` with SciPy's bounded scalar minimiser over `log k ∈ [ln 10⁻¹², ln 10¹²]`. It returns `(k_star, pc_max, hit_bound)`. When the miss is inside the disk it skips the search and returns the lower bound, for the reason given under Concepts.

*Easy to get wrong:* `_require_resolved` is written so that a NaN fails it (`not abs(a − b) <= tol`). Rewriting it as `abs(a − b) > tol` would let a NaN through, because every comparison with NaN is false. Also, `hit_bound` is diagnostic, not an answer: at the upper bound, `pc_max` is only the largest value inside the search range.

### `sentinel/risk/engine.py`

`assess(conjunction, config)` is the entry point, and it is orchestration only:

1. It computes the geometry that needs no covariance (miss distance and relative speed at the supplied TCA) and the inputs hash. A refusal carries these.
2. `_resolve_hbr` sums the two radii, applying the configured default if there is one.
3. It runs gates 1 to 5 from the table. `finite_eigenvalues` returns `None` for a matrix that cannot be decomposed into finite numbers; the gate treats `None` as invalid, so it fails closed.
4. It builds the encounter plane and runs gates 6 to 8.
5. It integrates at `k = 1`, then runs the worst-case search. Each is wrapped in `try/except UnresolvedIntegral`, which becomes gate 9 or 10.
6. It sets `dilution_flag = k* < 1` and fills `diagnostics` with `k_star`, `k_star_at_search_bound`, the projected eigenvalues, the condition number, the TCA shift and residual, the curvilinear ratio and the projected miss vector.

*Easy to get wrong:* if the worst-case search fails, the whole result is refused, not just `pc_max`. Without `k*` there is no dilution answer, and a Pc without one is the half-truth the flag exists to prevent. Also note that a computed result reports `miss_distance_m` at the refined TCA, while a refusal reports it at the supplied TCA (the refined value is in `diagnostics` as well). The two can differ by a metre or so.

### `sentinel/risk/synthetic.py`

`make_conjunction(miss_m, sigma_m, radius_m)` builds a head-on encounter whose projected covariance is exactly `sigma_m² · I` and whose projected miss is exactly `(miss_m, 0)`. The tests, `scripts/dilution_demo.py` and the closed-form sections of the validation report use it, so analytic answers are available.

*Easy to get wrong:* `radius_m` is per object, so HBR is `2 · radius_m`. And when `sigma_secondary_m` is passed, `sigma_m` stops meaning the combined sigma and becomes the primary's own.

### Validation: `fixtures/cara/`, `sentinel/validation/cara.py`, `scripts/validation_report.py`

NASA's Conjunction Assessment Risk Analysis (CARA) team publishes its tools with test data. `fixtures/cara/` vendors that data byte for byte at a pinned commit, with `fixtures/cara/PROVENANCE.md` and `fixtures/cara/SHA256SUMS`. It holds real operational CDMs with a spreadsheet of CARA's own Pc, 3D result and "2D is not valid here" verdict for each, the Alfano benchmark CDMs, the Omitron cases, and the MATLAB unit tests that state expected values.

`scripts/transcribe_cara_fixtures.py` writes `fixtures/cara_cases.json`. It reads the spreadsheet, and it quotes MATLAB literals by file and line number. It never imports Sentinel. That is the hand-transcription rule: **every expected value comes from a file NASA published, never from running this code.** A fixture built from Sentinel's output would only prove that Sentinel agrees with itself.

`sentinel/validation/cara.py` turns each case into a `Conjunction`. Cases with a CDM file go through Sentinel's own parser (`CaraCase.conjunction`). `CaraCase.override_config` relaxes the gates to match CARA's "compute regardless" setting for the Pc comparison; each case's default-configuration outcome is checked separately. `tests/test_tier3_cara_validation.py` asserts every case, the gate's agreement with CARA's verdicts, and the checksums. `scripts/validation_report.py` prints the same comparison, with closed-form checks, into `docs/validation-report.md`. A running node repeats the comparison with its own engine the first time it is asked (`GET /api/validation`), so a node built with a different engine shows it.

*Easy to get wrong:* when a case disagrees, the rule is to investigate, not to loosen the tolerance or edit the expected value. The report's section 8 records two divergences that were investigated and explained.

## Try it

All commands run from the repository root.

**1. Watch dilution happen.** The script holds the geometry fixed (1 km miss, 1 m HBR) and changes only the covariance.

```bash
uv run python scripts/dilution_demo.py
```

Read the Pc column top to bottom: it rises, peaks at σ ≈ 707 m (`d/√2`), then falls. `k*` passes through 1 at the peak, and every row after it says DILUTED. `Pc max` is the same in every row: the worst case belongs to the geometry, not to the tracking.

**2. Assess real CARA events.** One computed, one diluted, one refused for curvature.

```bash
uv run sentinel assess fixtures/cara/PcTestCaseCDMs/000020580_conj_000022015_20210315_212955_20210313_065123.cdm
uv run sentinel assess fixtures/cara/PcTestCaseCDMs/000025994_conj_000037558_20210324_151047_20210323_154356.cdm
uv run sentinel assess fixtures/cara/PcTestCaseCDMs/000032060_conj_000044396_20221004_061656_20221003_054027.cdm
```

- HST against a Delta 2 rocket body: a Pc with `(FOSTER_ESTES_2D)` beside it, `Pc max` above it and `k*` above 1. The originator's own Pc is printed on its own line, marked as not Sentinel's. Compare the two.
- TERRA against Iridium 33 debris: `k*` below 1 and the line `DILUTED: this Pc may reflect ignorance rather than safety; see Pc max`.
- WORLDVIEW 1 against LEMUR 2: `REFUSED CURVILINEAR_UNCERTAINTY`, then the diagnostics: the ratio, the sagitta, the smallest encounter-plane sigma, the object that bends, the threshold, and what assessment it would need instead. This is one of the events CARA would compute; section 6 of `docs/validation-report.md` lists every such conservative refusal.

**3. See other gates trip.**

```bash
uv run sentinel assess fixtures/cara/SampleCDMs/AlfanoTestCase01.cdm
uv run sentinel assess fixtures/cara/SampleCDMs/OmitronTestCase_Test07_NonPDCovariance.cdm
```

The Alfano case is a slow encounter: `LOW_RELATIVE_VELOCITY`, with the measured speed and the 100 m/s threshold. It also prints `UNIT_LABEL_ANOMALY` warnings: NASA's file labels relative velocity in metres, which chapter 3 explains. The Omitron case is refused `INVALID_COVARIANCE` with `stage: input_covariance`, the object id and its negative eigenvalue. CARA repairs this covariance and reports Pc = 0; Sentinel does not. Both commands exit 0, because a refusal is an assessment.

**4. Read the full result.**

```bash
uv run sentinel assess --json fixtures/cara/PcTestCaseCDMs/000025994_conj_000037558_20210324_151047_20210323_154356.cdm
```

Find `hbr_source` (`cdm_comment_hbr`), the `inputs_hash`, and in `diagnostics` the `tca_adjustment_s` (well under a millisecond), `k_star` and `k_star_at_search_bound`, and the second component of `projected_miss_m` (zero to rounding). Then add `--hbr 5` to the same command: `hbr_source` becomes `override`, the Pc changes, and so does `inputs_hash`, because the radius is an input.

**5. Refuse an integral that cannot be resolved.**

```bash
uv run python - <<'EOF'
from sentinel.risk import assess
from sentinel.risk.synthetic import make_conjunction

for sigma_m in (50.0, 1e-17):
    r = assess(make_conjunction(miss_m=3.0, sigma_m=sigma_m, radius_m=5.0))
    print(sigma_m, r.method.value, r.pc, r.refusal_reason, r.diagnostics.get("stage"))
EOF
```

The first line is a normal result. The second has σ = 10⁻¹⁷ m against a 10 m hard body. Every other gate passes, but no float64 grid can resolve the integrand, and the engine answers `REFUSED`, `UNRESOLVED_INTEGRAL`, `stage` `pc`.

**6. Re-run the validation.**

```bash
uv run pytest -q tests/test_tier1_geometry.py tests/test_tier2_integration.py tests/test_tier3_cara_validation.py tests/test_tier4_dilution.py tests/test_tier5_refusal.py tests/test_tier6_contract.py
make report
git status --short docs/validation-report.md
```

The six tiers are the test ladder of `docs/risk-engine-design.md`, section 7. `make report` rewrites `docs/validation-report.md`, and `git status` prints nothing: the report regenerated byte for byte. If you change `sentinel/risk/` and the report moves, the diff shows exactly which number moved. The numbers themselves are in the report; read sections 5 to 8 there.

## Design choices

**Port CARA's 2D method in Python; validate against CARA's published values** ([ADR-003](../system-design.md#adr-003--reimplement-foster-estes-2d-pc-in-python-nasa-caras-published-cases-as-the-oracle)).
- *Buys:* every line of the maths is readable and testable in this repository, and the oracle is the organisation whose method it is.
- *Costs:* the 3D method is not built, so some events get no number; the console tells the operator they need a 3D assessment.
- *Rejected:* Orekit at runtime (someone else's code, and a JVM at the edge); Orekit as a test oracle (CARA's own results are a stronger reference); calling MATLAB (not deployable); a third-party Python Pc library (none has comparable provenance).

**Refuse rather than approximate** (ADR-003, design principle 3).
- *Buys:* no number reaches an operator that the model does not support. For a non-positive-definite covariance, CARA repairs it and reports Pc = 0; Sentinel refuses, because a repaired covariance is not the one the originator supplied, and zero is a strong claim to make on its behalf.
- *Costs:* a few events that CARA would compute are refused by the curvature gate, and the operator must get those assessed elsewhere.
- *Rejected:* returning a number with a caveat. A caveat does not travel with a number the way `method` does.

**No Pc from element sets** ([ADR-002](../system-design.md#adr-002--two-screening-modes-explicitly-labeled)). Public element sets carry no covariance, so a CDM derived from them reaches the engine with none and is refused `NO_COVARIANCE`. There is no screening branch in the engine; the gate that already exists does the work.

**Report the worst case and a flag, not a replacement number.** `pc` stays the Pc; `pc_max` and `dilution_flag` sit beside it. The worst case drives attention, not action on its own (chapter 3's policy), because CARA's research finds maximum Pc is not sufficient as a stand-alone risk parameter. The cost is extra work: each assessment runs a 1D optimisation of the integral.

**One input shape, units in the names** ([ADR-001](../system-design.md#adr-001--cdm-as-the-canonical-internal-data-contract)). The engine sees only `Conjunction`. It does not know CDMs exist, so a new source is an adapter, not an engine change. Units ride in field names because unit confusion is the most likely source of a wrong answer here. Kilometres become metres in one module, `sentinel/risk/encounter.py`: in `relative_state`, and for the orbit radius in `curvilinear_check`. The frame rotations need no conversion, because a rotation matrix has no units.

**Two node rules and a self-check, not adaptive quadrature** (`docs/risk-engine-design.md`, step 5).
- *Buys:* an integral that is exact in float64 by construction and proven, not assumed, on every call. The CARA cases still run on the uniform rule, so the validated path did not change.
- *Rejected:* adaptive quadrature, which estimates its error from its own nodes and can step over a spike as cleanly as a fixed grid; an asymptotic edge formula, which is approximate and fails for needle-shaped covariances; a bigger panel cap, which moves the cliff without removing it.

**A calibrated curvature screen, not CARA's usage-violation algorithm.** The screen is a few lines of geometry. It catches every event CARA flags in the published set, at the cost of some conservative refusals, and its threshold was tuned on that same set. Porting CARA's algorithm, and the 3D method it hands off to, is recorded as deferred work in section 8 of `docs/risk-engine-design.md`.

## How it fails

- **Bad data never raises; it refuses.** Every gate returns an `AssessedConjunction` with `Method.REFUSED`, a reason, the tripping value and the threshold. Serialisation is safe: a refusal from a covariance near the float64 limit still produces valid JSON (tier 5 checks this with `allow_nan=False`).
- **The integrator proves itself or refuses.** `UnresolvedIntegral` never escapes `assess()`; it becomes `UNRESOLVED_INTEGRAL` with the stage and `sigma_min_m`. The console explains each reason in words (`REFUSAL_TEXT` in `web/src/lib/format.ts`). `tests/test_refusal_reasons_mirrored.py` fails if a new `RefusalReason` is missing from the console's types, its text, or the system model.
- **A Pc never travels alone.** `pc` is `None` whenever `method` is `REFUSED`, and consumers read both from one object. The console renders a Pc only through a component that takes the whole assessment (chapter 5), so a refusal cannot display as zero.
- **What the engine does not detect.** It assumes the supplied covariance is realistic (CARA's covariance-realism tools are out of scope) and that the two objects' errors are independent. A covariance that is valid but wrong gives a wrong Pc, and dilution is judged against it. When `k_star_at_search_bound` is set at the upper bound, `pc_max` is a lower bound on the worst case; nothing in the console shows that flag today.
- **A state with no RTN frame is refused, not raised.** A velocity of zero, or one along the position, leaves no orbital plane, so `rtn_to_eci_matrix` cannot build the frame the covariance is written in. `assess()` catches that around `build_encounter_plane` and refuses with `INVALID_COVARIANCE` at stage `rtn_frame` (`tests/test_tier5_refusal.py`). Ingest quarantines such a state before it gets here (chapter 3); the engine's refusal is the second layer.

## Check yourself

1. A colleague adds the two RTN covariances first and then rotates the sum into ECI with the primary's frame. Why is that wrong, and which test tier would catch it?
   <details><summary>Answer</summary>Each covariance is expressed in its own object's RTN axes, and the two objects' axes point in different directions. Adding them first adds numbers in different coordinates, and rotating with the primary's frame treats the secondary's matrix as if it used the primary's axes. The rotation must use each object's own position and velocity before the sum. Tier 1 (<code>tests/test_tier1_geometry.py</code>) pins the frames, and every anisotropic CARA case in tier 3 would disagree with NASA's value.</details>

2. Two CDMs for the same geometry differ only in the secondary's covariance: one is ten times wider in every direction. The wider one has the lower Pc. When does that mean the event is safer, and what in the result tells you?
   <details><summary>Answer</summary>It is not safer in any sense the data supports if the operating point is past the peak of <code>Pc(k)</code>. There, more uncertainty spreads the probability so thin that less of it falls on the disk. The result says so: <code>k_star</code> is below 1, <code>dilution_flag</code> is true and <code>dilution_margin</code> is negative. Look at <code>pc_max</code>, which does not depend on the covariance's scale. If <code>k*</code> is above 1 for both, the lower Pc does reflect the geometry.</details>

3. Why does TCA refinement change the reported miss distance but not the Pc?
   <details><summary>Answer</summary>The refinement moves both states by the same time step <code>dt</code> along their velocities, so the relative position moves along the relative velocity, which is <code>ẑ</code>. The projection onto the encounter plane discards the <code>ẑ</code> component, so <code>μ</code> and <code>C₂d</code> are unchanged and so is the Pc. The miss distance is the full length of the relative position, which does change.</details>

4. With a 20 m hard body and a smallest principal σ of 5 cm, which quadrature rule runs, and why is the result still trusted?
   <details><summary>Answer</summary><code>4 × 20 / 0.05 = 1600</code> panels fit within the cap of 4096, so the uniform rule runs. It is trusted because <code>_require_resolved</code> integrates the Gaussian factor alone on the same nodes and compares it with the closed-form normal mass; a grid that missed the spike would miss that mass too, and the integrator would raise instead of returning.</details>

5. The worst-case search raises <code>UnresolvedIntegral</code>, but the Pc at <code>k = 1</code> was fine. Why does the engine throw the good Pc away?
   <details><summary>Answer</summary>Without <code>k*</code> the engine cannot say whether the Pc is diluted. Returning the Pc without that answer would let a low number that reflects ignorance pass as reassurance, which is the failure the flag exists to prevent. So the whole result is refused with <code>stage: max_pc_search</code>.</details>

6. A new expected value is needed for a regression test. Someone proposes running the current engine and saving its output as the fixture. What is wrong with that, and where should the value come from?
   <details><summary>Answer</summary>A value produced by the code under test can only show that the code agrees with itself; any bug it has is frozen into the fixture. Expected values come from an independent source: a closed form derived by hand, or a value in a file NASA published, recorded with its file, line and checksum (<code>scripts/transcribe_cara_fixtures.py</code>, <code>fixtures/cara/PROVENANCE.md</code>).</details>

7. You want GEO operators to get a Pc for encounters at 50 m/s. What would you change, and what must you check before calling it done?
   <details><summary>Answer</summary>The threshold is <code>AssessmentConfig.min_relative_speed_m_s</code>, so the change is configuration, not code. Before trusting it, check that the linear model holds at that speed. Section 6 of the validation report shows the 2D Pc understating CARA's 3D result by many orders of magnitude on the slow operational events. Lowering the gate without evidence for the new regime would print numbers the method does not support. The node's engine version includes a hash of the configuration, so stored results would be re-assessed.</details>

8. Why is <code>CURVILINEAR_UNCERTAINTY</code>'s calibration described as "in-sample", and why does that matter?
   <details><summary>Answer</summary>The 0.1 threshold was chosen on the same set of CARA events it is then scored against, so zero missed events there is agreement with the data it was fitted to, not a held-out result. It matters because a new kind of event could fall on the wrong side. The report states this, and replacing the screen with CARA's usage-violation algorithm is the recorded next step.</details>

## Where next

- [Chapter 3: CDMs, ingest and events](03-cdm-and-events.md): how a CDM becomes the `Conjunction` this engine consumes, and how its result is banded for an operator.
- [Chapter 5: The operator console](05-console.md): how the encounter plane and the dilution curve are drawn from `pc_curve`, and why a Pc renders only one way.
- [Chapter 13: Keeping it honest](13-guardrails-compliance-mbse.md): the doc guard that ties quoted numbers to `docs/validation-report.md`.
- `docs/risk-engine-design.md`: the algorithm, the numerical hazards and the full test ladder.
- `docs/validation-report.md`: every comparison with CARA, with the measured errors.
- [ADR-003](../system-design.md#adr-003--reimplement-foster-estes-2d-pc-in-python-nasa-caras-published-cases-as-the-oracle) and [ADR-002](../system-design.md#adr-002--two-screening-modes-explicitly-labeled) in `docs/system-design.md`.
