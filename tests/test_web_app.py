import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DASHBOARD_PASSWORD", "test-secret")
os.environ.setdefault("DASHBOARD_SESSION_SECRET", "local-session-secret")
import web_app


class DashboardTests(unittest.TestCase):
    def setUp(self):
        web_app.app.config.update(TESTING=True)
        self.client = web_app.app.test_client()

    def test_auth_and_read_only_routes(self):
        self.assertEqual(self.client.get("/api/portfolio").status_code, 401)
        self.assertEqual(self.client.post("/login", data={"password": "bad"}).status_code, 401)
        self.assertEqual(self.client.post("/login", data={"password": "test-secret"}).status_code, 302)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.post("/api/portfolio").status_code, 405)
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_real_metrics_from_records(self):
        meta = {"initial_usdt": "50", "cash_usdt": "39"}
        positions = [{"symbol": "BTCUSDT", "qty": "0.0001", "cost_usdt": "10", "entry_price": "100000", "stop_price": "96000", "opened_ms": 1000}]
        trades = [{"id": 2, "ts_ms": 2000, "symbol": "ETHUSDT", "side": "SELL", "qty": "1", "bid": "11", "ask": "11.1", "fill_price": "11", "gross_usdt": "11", "fee_usdt": "0.01", "pnl_usdt": "1", "reason": "test", "cash_after_usdt": "39", "equity_after_usdt": "49"}]
        snapshots = [{"id": 1, "ts_ms": 1000, "equity_usdt": "50", "cash_usdt": "50", "note": "start"}, {"id": 2, "ts_ms": 2000, "equity_usdt": "49", "cash_usdt": "39", "note": "analiza"}]
        with patch.object(web_app, "read_data", return_value=(meta, positions, trades, snapshots, None)):
            self.client.post("/login", data={"password": "test-secret"})
            data = self.client.get("/api/portfolio").get_json()
        self.assertEqual(data["equity"], 49)
        self.assertEqual(data["total_pnl"], -1)
        self.assertEqual(data["position_value"], 10)
        self.assertEqual(data["realized_pnl"], 1)
        self.assertEqual(data["win_rate"], 100)
        self.assertEqual(data["max_drawdown"], 2)
        self.assertEqual(data["status"], "OFFLINE")


if __name__ == "__main__":
    unittest.main()
