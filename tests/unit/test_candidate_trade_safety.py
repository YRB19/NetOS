"""CandidateTrade is the single most load-bearing interface in the system
(Stage 3 §3.2). This file exhaustively tests every rejection case the
implementation prompt calls out by name, plus the boundary invariant that
`size_hint` can never become an authoritative order quantity.
"""

import unittest

from domain.models import Action, CandidateTrade
from tests.unit._helpers import NAIVE_DATETIME, utc


def _valid_kwargs(**overrides):
    kwargs = dict(
        instrument_id="INE002A01018",
        timestamp=utc(),
        action=Action.BUY,
        size_hint=0.5,
        confidence=0.5,
        rationale="a valid, non-empty rationale",
        input_snapshot_id="snap-1",
        strategy_version_id="strat-1",
    )
    kwargs.update(overrides)
    return kwargs


class TestCandidateTradeSafety(unittest.TestCase):
    def test_valid_construction_succeeds(self):
        CandidateTrade(**_valid_kwargs())  # must not raise

    def test_missing_rationale_rejected(self):
        kwargs = _valid_kwargs()
        del kwargs["rationale"]
        with self.assertRaises(TypeError):  # missing required positional/keyword arg
            CandidateTrade(**kwargs)

    def test_empty_rationale_rejected(self):
        with self.assertRaises(ValueError):
            CandidateTrade(**_valid_kwargs(rationale=""))

    def test_whitespace_only_rationale_rejected(self):
        with self.assertRaises(ValueError):
            CandidateTrade(**_valid_kwargs(rationale="   "))

    def test_invalid_confidence_type_rejected(self):
        with self.assertRaises(ValueError):
            CandidateTrade(**_valid_kwargs(confidence="high"))

    def test_confidence_below_zero_rejected(self):
        with self.assertRaises(ValueError):
            CandidateTrade(**_valid_kwargs(confidence=-0.01))

    def test_confidence_above_one_rejected(self):
        with self.assertRaises(ValueError):
            CandidateTrade(**_valid_kwargs(confidence=1.01))

    def test_confidence_boundary_zero_accepted(self):
        CandidateTrade(**_valid_kwargs(confidence=0.0))  # must not raise

    def test_confidence_boundary_one_accepted(self):
        CandidateTrade(**_valid_kwargs(confidence=1.0))  # must not raise

    def test_invalid_action_rejected(self):
        with self.assertRaises(ValueError):
            CandidateTrade(**_valid_kwargs(action="BUY"))  # string, not Action enum member

    def test_missing_instrument_id_rejected(self):
        with self.assertRaises(ValueError):
            CandidateTrade(**_valid_kwargs(instrument_id=""))

    def test_missing_snapshot_reference_rejected(self):
        with self.assertRaises(ValueError):
            CandidateTrade(**_valid_kwargs(input_snapshot_id=""))

    def test_missing_strategy_version_rejected(self):
        with self.assertRaises(ValueError):
            CandidateTrade(**_valid_kwargs(strategy_version_id=""))

    def test_naive_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            CandidateTrade(**_valid_kwargs(timestamp=NAIVE_DATETIME))

    def test_invalid_size_hint_type_rejected(self):
        with self.assertRaises(ValueError):
            CandidateTrade(**_valid_kwargs(size_hint="a lot"))

    def test_size_hint_none_is_valid(self):
        CandidateTrade(**_valid_kwargs(action=Action.HOLD, size_hint=None))  # must not raise

    def test_invalid_uncertainty_band_rejected(self):
        with self.assertRaises(ValueError):
            CandidateTrade(**_valid_kwargs(uncertainty_band="LOW"))  # string, not enum member

    def test_uncertainty_band_none_is_valid(self):
        CandidateTrade(**_valid_kwargs(uncertainty_band=None))  # must not raise

    def test_hold_action_is_first_class_not_special_cased(self):
        # TR-4: HOLD must be constructible with the exact same rigor as BUY/SELL —
        # it is not a degraded/optional path.
        ct = CandidateTrade(**_valid_kwargs(action=Action.HOLD))
        self.assertEqual(ct.action, Action.HOLD)

    # --- The boundary invariant: size_hint is NEVER a quantity ------------

    def test_no_authoritative_quantity_field_exists(self):
        """CandidateTrade must never define a field that could be read as a
        binding order quantity (Stage 3 §3.2). This directly guards the
        Plane 2 / Plane 3 boundary: Plane 2 proposes, Plane 3 decides.
        """
        field_names = set(CandidateTrade.__dataclass_fields__.keys())
        forbidden = {"quantity", "order_quantity", "shares", "order_size", "qty"}
        self.assertFalse(
            field_names & forbidden,
            f"CandidateTrade must not define any of {forbidden}; found "
            f"overlap: {field_names & forbidden}",
        )
        self.assertIn("size_hint", field_names)

    def test_size_hint_is_advisory_only_by_naming_contract(self):
        # This test documents the contract rather than testing runtime
        # behavior that doesn't exist yet (sizing logic is Plane 3 / a
        # later slice) — it fails loudly if `size_hint` is ever renamed
        # to something that implies a bound quantity, since that rename
        # would be exactly the boundary violation this class exists to
        # prevent.
        ct = CandidateTrade(**_valid_kwargs(size_hint=0.9))
        self.assertTrue(hasattr(ct, "size_hint"))
        self.assertFalse(hasattr(ct, "quantity"))


if __name__ == "__main__":
    unittest.main()
