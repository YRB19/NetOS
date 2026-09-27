"""Tests for PermittedUniverse — versioning, diffing, non-dynamic behavior."""

import unittest
from datetime import UTC, datetime

from data.features.universe import compute_universe_version, make_permitted_universe

UTC = UTC


class TestPermittedUniverse(unittest.TestCase):
    def test_empty_universe_rejected(self):
        with self.assertRaises(ValueError):
            make_permitted_universe([], effective_from=datetime(2026, 1, 1, tzinfo=UTC))

    def test_version_deterministic_regardless_of_order(self):
        u1 = make_permitted_universe(
            ["A", "B", "C"], effective_from=datetime(2026, 1, 1, tzinfo=UTC)
        )
        u2 = make_permitted_universe(
            ["C", "B", "A"], effective_from=datetime(2026, 1, 1, tzinfo=UTC)
        )
        self.assertEqual(u1.version, u2.version)

    def test_different_membership_different_version(self):
        u1 = make_permitted_universe(["A", "B"], effective_from=datetime(2026, 1, 1, tzinfo=UTC))
        u2 = make_permitted_universe(
            ["A", "B", "C"], effective_from=datetime(2026, 1, 1, tzinfo=UTC)
        )
        self.assertNotEqual(u1.version, u2.version)

    def test_diff_initial_universe_all_added(self):
        u = make_permitted_universe(["A", "B"], effective_from=datetime(2026, 1, 1, tzinfo=UTC))
        added, removed = u.diff(None)
        self.assertEqual(added, frozenset({"A", "B"}))
        self.assertEqual(removed, frozenset())

    def test_diff_addition(self):
        u1 = make_permitted_universe(["A", "B"], effective_from=datetime(2026, 1, 1, tzinfo=UTC))
        u2 = make_permitted_universe(
            ["A", "B", "C"], effective_from=datetime(2026, 1, 2, tzinfo=UTC)
        )
        added, removed = u2.diff(u1)
        self.assertEqual(added, frozenset({"C"}))
        self.assertEqual(removed, frozenset())

    def test_diff_removal(self):
        u1 = make_permitted_universe(
            ["A", "B", "C"], effective_from=datetime(2026, 1, 1, tzinfo=UTC)
        )
        u2 = make_permitted_universe(["A", "B"], effective_from=datetime(2026, 1, 2, tzinfo=UTC))
        added, removed = u2.diff(u1)
        self.assertEqual(added, frozenset())
        self.assertEqual(removed, frozenset({"C"}))

    def test_diff_no_change(self):
        u1 = make_permitted_universe(["A", "B"], effective_from=datetime(2026, 1, 1, tzinfo=UTC))
        u2 = make_permitted_universe(["A", "B"], effective_from=datetime(2026, 1, 2, tzinfo=UTC))
        added, removed = u2.diff(u1)
        self.assertEqual(added, frozenset())
        self.assertEqual(removed, frozenset())
        self.assertEqual(u1.version, u2.version)

    def test_naive_effective_from_rejected(self):
        with self.assertRaises(ValueError):
            make_permitted_universe(["A"], effective_from=datetime(2026, 1, 1))

    def test_contains(self):
        u = make_permitted_universe(["A", "B"], effective_from=datetime(2026, 1, 1, tzinfo=UTC))
        self.assertTrue(u.contains("A"))
        self.assertFalse(u.contains("Z"))

    def test_compute_universe_version_matches_constructor(self):
        ids = frozenset({"A", "B"})
        u = make_permitted_universe(ids, effective_from=datetime(2026, 1, 1, tzinfo=UTC))
        self.assertEqual(u.version, compute_universe_version(ids))


if __name__ == "__main__":
    unittest.main()
