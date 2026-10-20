"""Testy rozliczania rynków i spójności prawdopodobieństw.  Uruchom: python -m unittest"""
import unittest
from datetime import datetime

from typy import data
from typy.markets import BY_KEY, MarketEval, evaluate, settle
from typy.model import Prediction, market_lambdas, score_matrix


def fixture(odds=None):
    return data.Fixture("E0", datetime(2026, 10, 24, 16, 0, tzinfo=data.PL), "A", "B", None, odds or {})


class SettleTest(unittest.TestCase):
    def test_1x2_and_double_chance(self):
        self.assertEqual(settle("1", 2, 1), (1.0, 0.0))
        self.assertEqual(settle("X", 2, 1), (0.0, 1.0))
        self.assertEqual(settle("1X", 1, 1), (1.0, 0.0))
        self.assertEqual(settle("12", 0, 0), (0.0, 1.0))

    def test_draw_no_bet_refunds_on_draw(self):
        self.assertEqual(settle("DNB1", 1, 1), (0.0, 0.0))
        self.assertEqual(settle("DNB2", 0, 1), (1.0, 0.0))

    def test_asian_whole_line_push(self):
        self.assertEqual(settle("AH1-1", 2, 1), (0.0, 0.0))
        self.assertEqual(settle("AH1-1", 3, 1), (1.0, 0.0))
        self.assertEqual(settle("AH2+1", 1, 2), (1.0, 0.0))

    def test_asian_quarter_lines_split_stake(self):
        self.assertEqual(settle("AH1-0.75", 1, 0), (0.5, 0.0))   # pół wygrane, pół zwrot
        self.assertEqual(settle("AH1-0.25", 0, 0), (0.0, 0.5))   # pół przegrane, pół zwrot
        self.assertEqual(settle("AH2+0.25", 0, 0), (0.5, 0.0))
        self.assertEqual(settle("AH1-1.25", 2, 1), (0.0, 0.5))

    def test_goals_btts_halves(self):
        self.assertEqual(settle("O2.5", 2, 1), (1.0, 0.0))
        self.assertEqual(settle("U2.5", 2, 1), (0.0, 1.0))
        self.assertEqual(settle("BTTS_Y", 1, 0), (0.0, 1.0))
        self.assertEqual(settle("HO1.5", 2, 0), (1.0, 0.0))
        self.assertEqual(settle("HT_O0.5", 3, 0, 0, 0), (0.0, 1.0))
        self.assertIsNone(settle("HT_O0.5", 3, 0))  # brak wyniku do przerwy

    def test_cards_and_corners(self):
        self.assertEqual(settle("C_O4.5", 0, 0, hcards=3, acards=2), (1.0, 0.0))
        self.assertEqual(settle("CA_U1.5", 0, 0, hcards=3, acards=2), (0.0, 1.0))
        self.assertEqual(settle("K_O9.5", 0, 0, hc=6, ac=3), (0.0, 1.0))
        self.assertIsNone(settle("K_O9.5", 0, 0))

    def test_every_market_key_is_unique(self):
        self.assertEqual(len(BY_KEY), len({m.key for m in BY_KEY.values()}))


class ProbabilityTest(unittest.TestCase):
    def test_score_matrix_sums_to_one(self):
        self.assertAlmostEqual(score_matrix(1.6, 1.1).sum(), 1.0, places=9)

    def test_complementary_markets_sum_to_one(self):
        pred = Prediction(fixture(), (1.5, 1.2), None, (1.5, 1.2), cards=(2.0, 2.2), cards_dispersion=1.3,
                          cards_league_avg=4.0, corners=(5.0, 4.5), corners_dispersion=1.2,
                          corners_league_avg=10.0)
        ev = {e.market.key: e for e in evaluate(pred)}
        self.assertAlmostEqual(ev["1"].prob + ev["X"].prob + ev["2"].prob, 1.0, places=6)
        self.assertAlmostEqual(ev["O2.5"].prob + ev["U2.5"].prob, 1.0, places=6)
        self.assertAlmostEqual(ev["C_O4.5"].prob + ev["C_U4.5"].prob, 1.0, places=6)
        self.assertAlmostEqual(ev["K_O9.5"].prob + ev["K_U9.5"].prob, 1.0, places=6)
        # handicap 0 bez remisu = zakład bez remisu
        self.assertAlmostEqual(ev["DNB1"].prob, ev["1"].prob / (ev["1"].prob + ev["2"].prob), places=6)

    def test_market_lambdas_reproduce_odds(self):
        odds = {"1": 2.0, "X": 3.5, "2": 4.0, "O2.5": 1.9, "U2.5": 1.95}
        lh, la = market_lambdas(odds)
        m = score_matrix(lh, la)
        p_home = sum(m[i, j] for i in range(11) for j in range(11) if i > j)
        implied = (1 / 2.0) / (1 / 2.0 + 1 / 3.5 + 1 / 4.0)
        self.assertAlmostEqual(p_home, implied, delta=0.01)
        self.assertGreater(lh, la)

    def test_fair_odds_with_push(self):
        e = MarketEval(BY_KEY["DNB1"], "x", win=0.5, lose=0.25)
        self.assertAlmostEqual(e.fair_odds, 1.5)
        self.assertAlmostEqual(e.ev(1.5), 0.0)


if __name__ == "__main__":
    unittest.main()
