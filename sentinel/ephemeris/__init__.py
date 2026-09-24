"""Tabulated ephemerides: Earth-fixed state tables, their codecs and admission.

A state table is the input of the tabulated-ephemeris pass provider. It can
come from a CCSDS Orbit Ephemeris Message (oem.py), from a source adapter
(sentinel.adapters), or from sampling a propagator (tabulate.py). Whatever
the source, the table is admitted by one policy (table.py): input that
would make an answer wrong raises EphemerisRejected with a stable code;
input that only makes it incomplete is admitted with an EphemerisWarning.
"""
