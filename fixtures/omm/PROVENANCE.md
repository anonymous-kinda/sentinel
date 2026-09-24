# Element-set snapshots

Public General Perturbations (GP) element sets from [CelesTrak](https://celestrak.org),
in CCSDS OMM JSON form, as published. CelesTrak redistributes the public
catalog maintained by the U.S. Space Force; data courtesy of CelesTrak.

Element sets carry kilometre-scale error. Sentinel uses them for
**pass timing** (where a kilometre is a fraction of a second) and for
demonstration-mode screening geometry, and **never for a probability of
collision** (ADR-002).

Snapshots are written by `scripts/fetch_omm.py` and verified by `SHA256SUMS`.

| File | Source | Retrieved (UTC) | Objects | sha256 |
|---|---|---|---|---|
| `celestrak-resource-20260924.json` | https://celestrak.org/NORAD/elements/gp.php?GROUP=resource&FORMAT=json | 2026-09-24T05:35:08+00:00 | 167 | `a9b87ca1e130cedf` |
