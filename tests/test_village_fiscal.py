"""Gini helper tests (formula matches scripts/village/orchestrator.py)."""

from __future__ import annotations

import unittest


def gini_coefficient(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    xs = sorted(max(0.0, float(x)) for x in values)
    n = len(xs)
    cum = s = 0.0
    for i, x in enumerate(xs, start=1):
        s += x
        cum += i * x
    if s <= 0:
        return 0.0
    return (2.0 * cum / (n * s)) - (n + 1.0) / n


class TestGini(unittest.TestCase):
    def test_equal(self):
        self.assertEqual(gini_coefficient([10.0, 10.0, 10.0]), 0.0)

    def test_inequality(self):
        g = gini_coefficient([0.0, 0.0, 100.0])
        self.assertGreater(g, 0.5)
        self.assertLess(g, 0.67)

    def test_empty(self):
        self.assertEqual(gini_coefficient([]), 0.0)


if __name__ == "__main__":
    unittest.main()
