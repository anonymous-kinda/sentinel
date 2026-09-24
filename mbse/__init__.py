"""Sentinel's SysML v2 model and the tools that trace it.

    requirements.sysml   what Sentinel must do, with stable ids (REQ-<AREA>-NNN)
    sentinel.sysml       parts, ports, items and states; `satisfy` relations
    verification.sysml   verification cases naming the evidence (`verify`)

    sysml.py             reads the subset of the textual notation used here
    evidence.py          where each kind of evidence can be found
    trace.py             requirement -> satisfied by -> verified by -> status
    generate.py          wires the repository together for scripts/trace.py
    syntax.py            full-grammar syntax check (scripts/sysml_check.py)
"""
