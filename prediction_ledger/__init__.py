"""Neutral, read-only prediction-ledger contracts (Slice 13, ADR-26): record models and the verifying
reader. No writer lives here, so `research` may import it without gaining any write path. The append-only
WRITER is `observability.prediction_ledger.ledger`."""
