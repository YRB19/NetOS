"""NetOS Operator Console read API (Slice 10, ADR-21).

A strictly READ-ONLY, local-only HTTP layer over persisted NetOS artifacts. It imports no strategy, risk, sizing,
broker, simulation, governance or write-path journal code (enforced by the ADR-6 import-graph checker and by tests).
"""
