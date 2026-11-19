import tempfile
import unittest
from pathlib import Path

from bot import D, buy, connect, cycle, floor_step, meta, quote_ok, rules, sell, setmeta, universe, valid_order


class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "bot.sqlite3"
        self.db = connect(self.path)
        with self.db:
            setmeta(self.db, "cash_usdt", "12.5")
        self.rule = rules({"filters": [
            {"filterType": "LOT_SIZE", "minQty": "0.01", "maxQty": "100", "stepSize": "0.01"},
            {"filterType": "MARKET_LOT_SIZE", "minQty": "0", "maxQty": "100", "stepSize": "0"},
            {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
        ]})
        self.q = {"bid": "9.9", "ask": "10", "bid_qty": "100", "ask_qty": "100", "received_ms": __import__("time").time_ns() // 1000000}

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_buy_sell_costs_reinvestment_and_restart(self):
        self.assertTrue(buy(self.db, "ABCUSDT", self.q, self.rule, D("12"), D("0.04"), "test"))
        first = self.db.execute("SELECT * FROM trades").fetchone()
        self.assertEqual(D(first["fill_price"]), D("10.005"))
        self.assertEqual(D(first["fee_usdt"]), D(first["gross_usdt"]) * D("0.001"))
        spent = D("12.5") - D(meta(self.db, "cash_usdt"))
        self.assertEqual(spent, D(first["gross_usdt"]) + D(first["fee_usdt"]))
        self.db.close()
        self.db = connect(self.path)
        self.assertEqual(D(meta(self.db, "cash_usdt")), D("12.5") - spent)
        position = self.db.execute("SELECT * FROM positions").fetchone()
        self.assertIsNotNone(position)
        higher = dict(self.q, bid="12", ask="12.1")
        self.assertTrue(sell(self.db, position, higher, self.rule, "test profit"))
        last = self.db.execute("SELECT * FROM trades ORDER BY id DESC").fetchone()
        self.assertEqual(D(last["fill_price"]), D("12") * D("0.9995"))
        self.assertEqual(D(last["pnl_usdt"]), D(last["gross_usdt"]) - D(last["fee_usdt"]) - D(position["cost_usdt"]))
        self.assertEqual(D(meta(self.db, "cash_usdt")), D("12.5") + D(last["pnl_usdt"]))
        self.assertIsNone(self.db.execute("SELECT * FROM positions").fetchone())
        self.assertTrue(buy(self.db, "ABCUSDT", self.q, self.rule, D(meta(self.db, "cash_usdt")) * D("0.95"), D("0.04"), "reinvest"))
        self.assertGreater(D(self.db.execute("SELECT gross_usdt FROM trades ORDER BY id DESC").fetchone()[0]), D(first["gross_usdt"]))

    def test_filters_and_liquidity(self):
        self.assertEqual(floor_step("0.519", "0.01"), D("0.51"))
        self.assertFalse(valid_order(D("0.49"), D("10"), self.rule))
        self.assertFalse(valid_order(D("0.501"), D("10"), self.rule))
        self.assertFalse(buy(self.db, "ABCUSDT", dict(self.q, ask_qty="0.2"), self.rule, D("12"), D("0.04"), "test"))
        self.assertFalse(buy(self.db, "ABCUSDT", self.q, self.rule, D("4"), D("0.04"), "test"))

    def test_bad_quote_rejected(self):
        self.assertFalse(quote_ok(dict(self.q, bid="11")))
        self.assertFalse(quote_ok(dict(self.q, received_ms=1)))
        self.assertFalse(quote_ok(dict(self.q, bid_qty="0")))

    def test_universe_excludes_tokenized_stocks(self):
        class FakeMarket:
            def get(self, *_args):
                return [{"symbol": s, "quoteVolume": "10000000", "priceChangePercent": "1"}
                        for s in ("BTCUSDT", "NVDABUSDT")]
        info = {"symbols": [{"symbol": s, "baseAsset": b, "quoteAsset": "USDT", "status": "TRADING"}
                            for s, b in (("BTCUSDT", "BTC"), ("NVDABUSDT", "NVDAB"))]}
        self.assertEqual(list(universe(FakeMarket(), info)), ["BTCUSDT"])

    def test_portfolio_loss_halts_new_entries(self):
        with self.db:
            setmeta(self.db, "cash_usdt", "39")
            setmeta(self.db, "initial_usdt", "50")
            setmeta(self.db, "peak_usdt", "50")
        cycle(self.db, None, {"symbols": []}, {})
        self.assertEqual(self.db.execute("SELECT note FROM snapshots ORDER BY id DESC").fetchone()[0], "blokada strat")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM trades").fetchone()[0], 0)

    def test_initial_capital_and_stop_loss_cycle(self):
        class FakeMarket:
            def __init__(self, quotes):
                self.quotes = quotes
            def book(self, symbol):
                return self.quotes.get(symbol)
        market = FakeMarket({"ABCUSDT": self.q})
        info = {"symbols": [{"symbol": "ABCUSDT", "filters": [
            {"filterType": "LOT_SIZE", "minQty": "0.01", "maxQty": "100", "stepSize": "0.01"},
            {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
        ]}]}
        with self.db:
            self.db.execute("DELETE FROM meta WHERE key='cash_usdt'")
        cycle(self.db, market, info, {})
        self.assertEqual(D(meta(self.db, "cash_usdt")), D("50"))
        self.assertEqual(D(meta(self.db, "initial_usdt")), D("50"))
        self.assertTrue(buy(self.db, "ABCUSDT", self.q, self.rule, D("12"), D("0.04"), "entry"))
        market.quotes["ABCUSDT"] = dict(self.q, bid="9.5", ask="9.6")
        cycle(self.db, market, info, {})
        self.assertIsNone(self.db.execute("SELECT 1 FROM positions").fetchone())
        self.assertEqual(self.db.execute("SELECT reason FROM trades ORDER BY id DESC").fetchone()[0], "stop-loss")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
