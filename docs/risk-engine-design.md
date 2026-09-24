# Sentinel — Risk Engine Design & Pseudocode v0.1

**Module:** `sentinel.risk`
**Implements:** ADR-002 (two modes), ADR-003 (Foster-Estes 2D Pc, Orekit as oracle)
**Status:** Implemented and validated against NASA CARA published cases (see `docs/validation-report.md`).

This document is written to be implemented test-first. Section 7 is the test ladder; work down it in order. Do not write engine code ahead of the test that demands it.

---

## 1. Scope and the Assumption That Defines It

The engine implements the **2D probability of collision** under the linear relative-motion (rectilinear) encounter model. This is the workhorse method — it is what CARA's 2D Pc tools implement and what most operational screening uses.

The model assumes that, through the brief window around closest approach, the two objects move in straight lines at constant relative velocity, and that position uncertainty does not meaningfully evolve across that window. Under those assumptions the 3D collision integral collapses to a 2D integral over a plane, which is the entire reason the method is tractable.

**Where this breaks, stated plainly:**

- **Low relative velocity.** As relative speed drops, the encounter window lengthens, curvature matters, and the linear assumption fails. This is common in geostationary conjunctions and in repeating-geometry encounters between objects in similar orbits.
- **Very large covariance relative to encounter geometry.** The frozen-uncertainty assumption stops holding.
- **Multiple close approaches in one event.** The 2D method assesses a single TCA.

When the engine detects these conditions it must **refuse to return a Pc** and flag the event as requiring 3D numerical assessment, rather than returning a number the model does not support. Implementing 3D Nc is explicitly deferred — see Section 8. Detecting that it is needed is not deferred, because returning a silently invalid number is the failure mode this whole project is arguing against.

---

## 2. Data Contract

### Input

A normalized CDM (per ADR-001) providing, for each of two objects:

| Quantity | Symbol | CDM source | Units |
|---|---|---|---|
| Position at TCA | `r₁, r₂` | state vector | km |
| Velocity at TCA | `v₁, v₂` | state vector | km/s |
| Position covariance | `C₁, C₂` | covariance matrix, RTN frame | m² |
| Object radius | `R₁, R₂` | derived from `AREA_PC`, or default | m |

**Unit mismatch is the single most likely source of a wrong answer in this module.** The CDM standard carries state in kilometres and covariance in metres squared. Every test in the ladder that touches real CDM data must assert units explicitly.

### Output

```
AssessedConjunction:
    pc                  float | None      # None when model inapplicable
    pc_max              float | None      # worst-case over covariance scaling
    dilution_flag       bool
    dilution_margin     float             # how far into/out of dilution
    miss_distance       float             # km
    relative_speed      float             # km/s
    hbr                 float             # m
    method              enum              # FOSTER_ESTES_2D | REFUSED
    refusal_reason      enum | None
    inputs_hash         str               # traceability, per Principle 2
    diagnostics         dict              # conditioning, eigenvalues, k*
```

`pc` and `method` travel together always. A consumer must never be able to obtain a probability without also obtaining how it was computed and whether it is trustworthy.

---

## 3. Algorithm

### Step 1 — Frame unification

Each object's covariance arrives in its **own** RTN (radial / along-track / cross-track) frame. These are different frames — they are defined relative to each object's own position and velocity. They cannot be added until both are expressed in a common inertial frame.

For each object, build the rotation from its RTN basis to inertial:

```
R̂ = r / |r|
Ĉ = (r × v) / |r × v|        # cross-track (orbit normal)
T̂ = Ĉ × R̂                   # along-track, completes right-handed set
M  = [R̂ T̂ Ĉ]                 # columns; RTN → ECI
```

Then `C_eci = M · C_rtn · Mᵀ`.

*This is the step most often gotten wrong by rotating only one object, or by assuming both share a frame. The test ladder pins it down early.*

### Step 2 — Combine

```
dr = r₂ - r₁                 # relative position at TCA
dv = v₂ - v₁                 # relative velocity at TCA
C  = C₁_eci + C₂_eci         # valid only if the two OD solutions are independent
HBR = R₁ + R₂
```

The additive combination assumes uncorrelated errors between the two objects' orbit determinations. This is standard and normally sound, but it is an assumption, and it should be recorded in diagnostics rather than left implicit.

### Step 3 — Construct the encounter plane

The plane is normal to relative velocity.

```
ẑ = dv / |dv|                            # normal to the encounter plane
r_perp = dr - (dr · ẑ) ẑ                 # component of miss ⊥ to relative velocity
x̂ = r_perp / |r_perp|
ŷ = ẑ × x̂
```

At a true TCA, `dr · ẑ ≈ 0` by definition of closest approach, so `r_perp ≈ dr` and `x̂ ≈ dr̂`. **Do not assume this - compute it.**

In practice a CDM's TCA is rounded to the millisecond, so the states are slightly off closest approach: half a millisecond at 15 km/s is 7.5 m. Both states are refined to the linear-motion closest approach, as CARA's `FindNearbyCA` does:

```
dt   = -(dr · dv) / |dv|²          # |dt| ≤ ~0.5 ms for real CDMs
r_i' = r_i + v_i · dt
```

The refinement leaves the 2D Pc unchanged, because it moves the states only along `ẑ`, which the projection discards. It does correct the reported miss distance (CARA's MinMiss case goes from 3.88 m to 3.35 m) and makes the geometry self-consistent. A shift larger than `max_tca_adjustment_s` (default 10 ms, 20× the rounding bound) is not rounding. It means the states and the TCA disagree, which is upstream corruption, and the engine refuses with `TCA_INCONSISTENT`.

### Step 4 — Project

```
P    = [x̂ᵀ ; ŷᵀ]             # 2×3 projection matrix
C₂d  = P · C · Pᵀ            # 2×2 projected covariance
μ    = P · dr                # projected miss vector; μ = (|r_perp|, 0) by construction
```

`μ`'s second component being ~0 is a free internal consistency check. Assert it.

### Step 5 — Integrate

Probability of collision is the 2D Gaussian mass over the hard-body disk:

```
Pc = (1 / (2π √det C₂d)) ∬       exp( -½ (u - μ)ᵀ C₂d⁻¹ (u - μ) ) du
                        |u| ≤ HBR
```

Implementation: eigendecompose `C₂d` to principal axes, giving `σ_a, σ_b` and the miss vector in that rotated basis. Then reduce to a one-dimensional quadrature over the disk rather than a naive 2D grid — this is what CARA's Gauss-Chebyshev approach buys, and it is both faster and better behaved numerically.

Keep the integration method behind an interface. Starting with a straightforward well-tested quadrature and swapping in Gauss-Chebyshev later is fine; having the tests already in place makes that swap safe.

### Step 6 — Maximum Pc

Scale the combined covariance by a factor `k` and find the worst case:

```
Pc(k) = Pc computed with C₂d → k · C₂d
k*    = argmax over k > 0 of Pc(k)
pc_max = Pc(k*)
```

`Pc(k)` is unimodal in `k`: at very small `k` the uncertainty ellipse is tight and, if the miss vector is outside it, almost no probability mass falls on the disk; at very large `k` the mass is smeared so thin that the disk catches little of it. Between the two there is a maximum. A bounded 1D optimizer over `log k` is appropriate and robust.

### Step 7 — Dilution detection

This is the feature ADR-002 exists for.

The operating point is `k = 1`. The question is which side of the peak it sits on.

```
if k* > 1:     operating point is left of peak   → NOT diluted
               (more uncertainty would raise Pc — Pc is bounded from above here)

if k* < 1:     operating point is right of peak  → DILUTED
               (more uncertainty LOWERS Pc — the low number may reflect
                ignorance rather than safety)
```

Report `dilution_margin = log(k*)`. Negative means diluted, and magnitude indicates how deeply.

**Why this matters, in one sentence for the white paper:** in the dilution region, degrading your data quality makes the collision probability go down, which means a low Pc is not by itself evidence of safety.

When `dilution_flag` is set, the consumer must surface `pc_max` alongside `pc`, never `pc` alone.

### Step 8 — Model applicability gate

Run **before** returning any Pc. If any condition trips, return `method = REFUSED` with a reason:

| Condition | Reason |
|---|---|
| Relative speed below threshold | `LOW_RELATIVE_VELOCITY` |
| `C₂d` not positive definite | `INVALID_COVARIANCE` |
| `C₂d` condition number above threshold | `ILL_CONDITIONED_COVARIANCE` |
| Covariance absent from CDM | `NO_COVARIANCE` |
| TCA refinement shift `abs(dt)` above `max_tca_adjustment_s` | `TCA_INCONSISTENT` |
| 1-σ along-track sagitta `σ_T²/(2‖r‖)` above `max_curvilinear_ratio` × smallest encounter-plane σ | `CURVILINEAR_UNCERTAINTY` |
| HBR unavailable and no default policy | `NO_HBR` |

Thresholds are configuration, not constants, and every refusal records the value that tripped it.

---

## 4. Pseudocode

```
function assess(cdm, config) -> AssessedConjunction:

    # --- extract & normalize units (km, km/s, m², m) -----------------
    r1, v1 = cdm.object1.state
    r2, v2 = cdm.object2.state
    C1_rtn = cdm.object1.covariance      # may be absent
    C2_rtn = cdm.object2.covariance
    hbr    = resolve_hbr(cdm, config)

    if C1_rtn is absent or C2_rtn is absent:
        return refused(NO_COVARIANCE)
    if hbr is None:
        return refused(NO_HBR)

    # --- step 1: frame unification ----------------------------------
    C1 = rotate_rtn_to_eci(C1_rtn, r1, v1)
    C2 = rotate_rtn_to_eci(C2_rtn, r2, v2)

    # --- step 2: combine --------------------------------------------
    dr = r2 - r1
    dv = v2 - v1
    C  = C1 + C2

    rel_speed = norm(dv)
    if rel_speed < config.min_relative_speed:
        return refused(LOW_RELATIVE_VELOCITY)

    # --- step 3: encounter plane ------------------------------------
    z_hat  = dv / rel_speed
    along  = dot(dr, z_hat)
    if abs(along) > config.max_tca_residual:
        return refused(TCA_INCONSISTENT)

    r_perp = dr - along * z_hat
    x_hat  = r_perp / norm(r_perp)
    y_hat  = cross(z_hat, x_hat)

    # --- step 4: project --------------------------------------------
    P    = matrix_from_rows(x_hat, y_hat)
    C2d  = P @ C @ transpose(P)
    mu   = P @ dr
    assert abs(mu[1]) < tolerance          # internal consistency

    if not is_positive_definite(C2d):
        return refused(INVALID_COVARIANCE)
    if condition_number(C2d) > config.max_condition:
        return refused(ILL_CONDITIONED_COVARIANCE)

    # --- step 5: integrate ------------------------------------------
    pc = integrate_gaussian_over_disk(C2d, mu, hbr)

    # --- steps 6 & 7: max Pc and dilution ---------------------------
    k_star  = maximize_over_log_k(k -> integrate_gaussian_over_disk(k*C2d, mu, hbr))
    pc_max  = integrate_gaussian_over_disk(k_star * C2d, mu, hbr)
    diluted = (k_star < 1.0)

    return AssessedConjunction(
        pc              = pc,
        pc_max          = pc_max,
        dilution_flag   = diluted,
        dilution_margin = log(k_star),
        miss_distance   = norm(dr),
        relative_speed  = rel_speed,
        hbr             = hbr,
        method          = FOSTER_ESTES_2D,
        inputs_hash     = hash_of(cdm_relevant_fields),
        diagnostics     = { k_star, eigenvalues(C2d), condition_number(C2d),
                            tca_residual: along, independence_assumed: true }
    )
```

---

## 5. Numerical Hazards

Each of these has a test in the ladder.

1. **Units.** km vs m, m² vs km². Assert at the boundary.
2. **Covariance symmetry.** Real CDM covariances arrive slightly asymmetric from serialization. Symmetrize as `(C + Cᵀ)/2` before eigendecomposition, and record the asymmetry magnitude — a large value means bad upstream data, not a rounding artifact.
3. **Non-positive-definite covariance.** Occurs in real data. Refuse; do not repair silently.
4. **Underflow.** Pc values below 1e-15 are routine. Compute in log space where the quadrature allows, and never test small probabilities for equality.
5. **Near-zero `r_perp`.** A direct hit makes `x̂` undefined. Handle the degenerate case explicitly — any perpendicular basis works when the miss vector is zero.
6. **Optimizer bounds.** `k*` search must be bounded and must not silently return an endpoint. If it hits a bound, that is diagnostic information, not an answer.

---

## 6. Validation Against CARA

CARA publishes test cases alongside their MATLAB tools. The port is validated against those cases — do not invent expected values.

Procedure:
1. Transcribe CARA's published cases into a fixture file, recording provenance for each.
2. Assert agreement to a stated relative tolerance, chosen and justified rather than tuned until green.
3. Where Sentinel disagrees, investigate before adjusting tolerance. A disagreement is information.
4. Where Orekit is available in CI, cross-check as an independent third opinion. Orekit is never a runtime dependency (ADR-003).

The validation report — cases, tolerances, results — goes in the repo as a first-class artifact. It converts "I implemented a method" into "I implemented a method and demonstrated it correct," which is the difference that matters to a technical evaluator.

---

## 7. TDD Test Ladder

Work down in order. Each rung fails before the code that satisfies it exists.

**Tier 1 — Geometry, no probability yet.**
1. RTN→ECI rotation matrix is orthonormal, determinant +1.
2. Known position/velocity produces known RTN basis vectors.
3. Rotating a diagonal covariance and rotating back recovers the original.
4. Encounter plane basis is orthonormal and `ẑ` is parallel to `dv`.
5. Projected miss vector has a near-zero second component.
6. A TCA-inconsistent input is refused, not processed.

**Tier 2 — Integration, analytically checkable.**
7. Isotropic covariance with zero miss integrates to the known closed-form disk mass.
8. Pc decreases monotonically as miss distance increases, covariance fixed.
9. Pc increases monotonically as HBR increases, everything else fixed.
10. Pc over a disk of radius ≫ σ approaches 1.
11. Pc over a disk of radius → 0 approaches 0.

**Tier 3 — Against CARA.** *(implemented: `tests/test_tier3_cara_validation.py`)*
12. Each published CARA case within its stated tolerance: 53 operational events (rtol 1e-6, worst observed 1.5e-8), Alfano 01–11 read from CDM files (CARA's rtol 1e-3), and Omitron Case 1 (rtol 1e-6, observed 1.9e-8).
13. Anisotropic covariance cases specifically. Every operational event is anisotropic, and a naive isotropic shortcut fails them.
13a. Every event CARA flags as outside 2D validity is refused by the default gate (zero false negatives). False positives are bounded and listed.
13b. The Omitron Case 2 difference is explained to 1e-14 by the miss-distance convention.
13c. The vendored NASA files match their recorded SHA-256.

**Tier 4 — Max Pc and dilution.**
14. `Pc(k)` is unimodal over a wide `k` sweep for a representative case.
15. `pc_max ≥ pc` always.
16. Constructed tight-covariance case: `k* > 1`, dilution flag clear.
17. Constructed inflated-covariance case: `k* < 1`, dilution flag set.
18. **The headline test:** take a case with the flag clear, inflate the covariance by an order of magnitude, assert Pc *falls* and the dilution flag now sets. This test is the direct executable demonstration of the pathology the whole project argues about — it belongs in the white paper by name.

**Tier 5 — Refusal gates.**
19. Low relative velocity refuses with correct reason.
20. Non-positive-definite covariance refuses.
21. Missing covariance refuses, and does not fall back to a TLE-derived guess (ADR-002).
22. Ill-conditioned covariance refuses.
23. Every refusal carries the tripping value in diagnostics.

**Tier 6 — Contract.**
24. `pc` is never returned without `method`.
25. `dilution_flag` set implies `pc_max` is populated.
26. `inputs_hash` is stable across runs and changes when any input changes.

---

## 8. Deferred

**3D Nc (numerical collision rate).** The correct method when the linear model fails. Deferred deliberately: implementing it well is a substantial effort, and the project's argument does not require it. Detecting that it is *needed* — the Step 8 gate — is implemented, which is the part that demonstrates judgment. The white paper should state this as a scoping decision with reasoning, not omit it.

**CARA's Pc2D usage-violation algorithm.** `CURVILINEAR_UNCERTAINTY` is a geometric screen whose threshold was calibrated against CARA's published verdicts. CARA's `UsageViolationPc2D` propagates equinoctial covariances along curvilinear trajectories to measure how extended, offset and inaccurate the 2D approximation is. Porting it would replace a calibrated heuristic with the reference algorithm, and it is the natural companion to 3D Nc.

**Covariance realism assessment.** CARA has whole toolsets for judging whether a supplied covariance is trustworthy at all. Sentinel assumes the supplied covariance is what it claims to be and flags dilution downstream of that assumption. Worth naming as a known limitation.

**Maneuver planning.** Out of scope per the design's non-goals.
