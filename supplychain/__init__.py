"""Release and supply-chain tooling: pins, checksums, bundle manifest, SBOMs, VEX.

Build-side only. Nothing here ships in the sentinel wheel or runs on a node;
the verifier that runs on a target host is deploy/bundle/verify_signature.sh,
which needs nothing but cosign and coreutils. See docs/supply-chain.md.
"""
