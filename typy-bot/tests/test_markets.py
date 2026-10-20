"""Testy rozliczania rynków i spójności prawdopodobieństw.  Uruchom: python -m unittest"""
import unittest
from datetime import date, datetime

from typy import data
from typy.markets import BY_KEY, MARKETS, MarketEval, evaluate, settle
from typy.model import CountPred, Prediction, market_lambdas, score_matrix


def fixture(odds=None):
    return data.Fixture("E0", datetime(2026, 10, 24, 16, 0, tzinfo=data.PL), "A", "B", None, odds or {})


def match(hg, ag, hthg=None, htag=None, **stats):
    return data.Match("E0", date(2026, 10, 1), "A", "B", hg, ag, hthg, htag, **stats)


class SettleTest(unittest.TestCase):
    def test_1x2_and_double_chance(self):
        self.assertEqual(settle("1", match(2, 1)), (1.0, 0.0))
        self.assertEqual(settle("X", match(2, 1)), (0.0, 1.0))
        self.assertEqual(settle("1X", match(1, 1)), (1.0, 0.0))
        self.assertEqual(settle("12", match(0, 0)), (0.0, 1.0))

    def test_draw_no_bet_refunds_on_draw(self):
        self.assertEqual(settle("DNB1", match(1, 1)), (0.0, 0.0))
        self.assertEqual(settle("DNB2", match(0, 1)), (1.0, 0.0))

    def test_asian_lines(self):
        self.assertEqual(settle("AH1-1", match(2, 1)), (0.0, 0.0))
        self.assertEqual(settle("AH1-1", match(3, 1)), (1.0, 0.0))
        self.assertEqual(settle("AH2+1", match(1, 2)), (1.0, 0.0))
        self.assertEqual(settle("AH1-0.75", match(1, 0)), (0.5, 0.0))
        self.assertEqual(settle("AH1-0.25", match(0, 0)), (0.0, 0.5))
        self.assertEqual(settle("AH1-1.25", match(2, 1)), (0.0, 0.5))

    def test_european_handicap(self):
        self.assertEqual(settle("EH-1_X", match(2, 1)), (1.0, 0.0))
        self.assertEqual(settle("EH-1_1", match(3, 1)), (1.0, 0.0))
        self.assertEqual(settle("EH+1_2", match(0, 2)), (1.0, 0.0))

    def test_goals_and_specials(self):
        self.assertEqual(settle("O2.5", match(2, 1)), (1.0, 0.0))
        self.assertEqual(settle("G=3", match(2, 1)), (1.0, 0.0))
        self.assertEqual(settle("G2-3", match(2, 1)), (1.0, 0.0))
        self.assertEqual(settle("ODD", match(2, 1)), (1.0, 0.0))
        self.assertEqual(settle("CS2:1", match(2, 1)), (1.0, 0.0))
        self.assertEqual(settle("CS_INNY", match(5, 0)), (1.0, 0.0))
        self.assertEqual(settle("WTNH", match(2, 0)), (1.0, 0.0))
        self.assertEqual(settle("CLEANA", match(2, 0)), (0.0, 1.0))
        self.assertEqual(settle("MARGINH2", match(3, 1)), (1.0, 0.0))
        self.assertEqual(settle("1&BTTS_T", match(2, 1)), (1.0, 0.0))
        self.assertEqual(settle("X2&U2.5", match(1, 1)), (1.0, 0.0))

    def test_halves(self):
        m = match(3, 1, 0, 1)  # do przerwy 0:1, w 2. połowie 3:0
        self.assertEqual(settle("HT_2", m), (1.0, 0.0))
        self.assertEqual(settle("2H_1", m), (1.0, 0.0))
        self.assertEqual(settle("2H_O2.5", m), (1.0, 0.0))
        self.assertEqual(settle("HTFT_2/1", m), (1.0, 0.0))
        self.assertEqual(settle("HSH_2", m), (1.0, 0.0))
        self.assertEqual(settle("BH_O0.5", m), (1.0, 0.0))
        self.assertEqual(settle("WEHH", m), (1.0, 0.0))
        self.assertEqual(settle("WBHH", m), (0.0, 1.0))
        self.assertEqual(settle("SBHA", m), (0.0, 1.0))
        self.assertIsNone(settle("HT_2", match(3, 1)))  # brak wyniku do przerwy

    def test_stats(self):
        m = match(0, 0, hcards=3, acards=2, hc=6, ac=3, hst=5, ast=2, hf=12, af=9, hr=1, ar=0, hs=15, as_=7)
        self.assertEqual(settle("C_O4.5", m), (1.0, 0.0))
        self.assertEqual(settle("CA_U1.5", m), (0.0, 1.0))
        self.assertEqual(settle("K_O9.5", m), (0.0, 1.0))
        self.assertEqual(settle("K_AH1-2.5", m), (1.0, 0.0))
        self.assertEqual(settle("S_O6.5", m), (1.0, 0.0))
        self.assertEqual(settle("T_O20.5", m), (1.0, 0.0))
        self.assertEqual(settle("F_O20.5", m), (1.0, 0.0))
        self.assertEqual(settle("R_Y", m), (1.0, 0.0))
        self.assertIsNone(settle("K_O9.5", match(0, 0)))

    def test_every_market_key_is_unique(self):
        self.assertEqual(len(MARKETS), len(BY_KEY))


class ProbabilityTest(unittest.TestCase):
    def test_score_matrix_sums_to_one(self):
        self.assertAlmostEqual(score_matrix(1.6, 1.1).sum(), 1.0, places=9)

    def test_complementary_markets_sum_to_one(self):
        counts = {"cards": CountPred((2.0, 2.2), 1.3, 1.9, 2.1), "corners": CountPred((5.0, 4.5), 1.2, 5.2, 4.6),
                  "sot": CountPred((4.5, 3.5), 1.2, 4.3, 3.7), "reds": CountPred((0.1, 0.12), 1.0, 0.1, 0.1)}
        pred = Prediction(fixture(), (1.5, 1.2), None, (1.5, 1.2), counts=counts)
        ev = {e.market.key: e for e in evaluate(pred)}
        for a, b in [("O2.5", "U2.5"), ("C_O4.5", "C_U4.5"), ("K_O9.5", "K_U9.5"), ("S_O7.5", "S_U7.5"),
                     ("R_Y", "R_N"), ("ODD", "EVEN"), ("HT_O0.5", "HT_U0.5"), ("BTTS_Y", "BTTS_N")]:
            self.assertAlmostEqual(ev[a].prob + ev[b].prob, 1.0, places=6, msg=a)
        self.assertAlmostEqual(ev["1"].prob + ev["X"].prob + ev["2"].prob, 1.0, places=6)
        self.assertAlmostEqual(sum(ev[f"HTFT_{a}/{b}"].prob for a in "1X2" for b in "1X2"), 1.0, places=4)
        self.assertAlmostEqual(sum(e.prob for k, e in ev.items() if k.startswith("CS")), 1.0, places=6)
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
