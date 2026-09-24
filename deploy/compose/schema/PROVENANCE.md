# Compose Specification schema

`compose-spec.json` is the Compose Specification's JSON Schema (draft 2020-12),
vendored unmodified so `tests/test_compose_stack.py` can validate
`deploy/compose/compose.yaml` with no network. Apache-2.0, © the Compose
Specification authors.

| Field | Value |
|---|---|
| Repository | https://github.com/compose-spec/compose-spec |
| Path | `schema/compose-spec.json` |
| Commit | `914ec15d1fa498969c0df5c1d672306db3256089` (2026-09-17, "Update compose-spec.json"; the latest commit to touch the file when fetched) |
| Fetched from | https://raw.githubusercontent.com/compose-spec/compose-spec/914ec15d1fa498969c0df5c1d672306db3256089/schema/compose-spec.json |
| Retrieved (UTC) | 2026-09-24T08:33Z |
| Size | 89,808 bytes |
| sha256 | `d61cc3df8c6e6a727043e84f3405c69ffd63d341f629db8480f1d2ee5405b10c` (also in `SHA256SUMS`) |
| Git blob | `c9db4d1cd27cd0353d679b58ab83fa8dfd442aaf`: `git hash-object` of the vendored file equals the blob GitHub's contents API reports for this path at this commit |

To refresh: fetch the file at a newer commit, record the commit, sha256 and
blob here and in `SHA256SUMS`, and run `uv run pytest -q tests/test_compose_stack.py`.
