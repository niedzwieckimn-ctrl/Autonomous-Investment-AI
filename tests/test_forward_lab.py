import unittest
from forward_lab import apply_candle
from strategy_lab import strategies

class ForwardLabTest(unittest.TestCase):
    def test_initial_no_trade(self):
        s=strategies()[0]
        candles=[(i*900000,100.,101.,99.,100.,1000.) for i in range(160)]
        state=dict(cash_usdt=50.,qty=0.,entry_cost=0.,stop_price=0.,
                   closed_trades=0,wins=0,realized_pnl=0.,peak_usdt=50.,max_drawdown_pct=0.,last_candle_ms=0)
        result,equity,trade=apply_candle(state,s,candles,159)
        self.assertEqual(equity,50.)
        self.assertIsNone(trade)
        self.assertEqual(result['last_candle_ms'],candles[-1][0])

if __name__=='__main__':unittest.main()
