"""Demonstration-mode screening (ADR-002): element-set geometry, never a Pc.

Public element sets carry kilometre-scale error and no covariance, so they
cannot support a probability of collision. They can still say which
objects pass close to a primary, and when - as long as every output says
what it is. This package finds those close approaches and writes each as a
DERIVED CDM with no covariance, so the risk engine refuses a Pc for it
through its existing NO_COVARIANCE gate. Nothing here imports the engine.
"""
