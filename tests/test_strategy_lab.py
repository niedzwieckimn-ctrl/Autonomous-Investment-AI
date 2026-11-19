import math
import unittest
from strategy_lab import strategies, simulate

class LabTests(unittest.TestCase):
    def test_fifty_unique(self):
        s=strategies()
        self.assertEqual(len(s),50)
        self.assertEqual(len({x.name for x in s}),50)
    def test_flat_prices_do_not_make_money(self):
        data=[(i*900,100.,100.,100.,100.,1000.) for i in range(200)]
        for s in strategies():
            r=simulate(s,data)
            self.assertLessEqual(r['final_usdt'],50.00001)
            self.assertTrue(math.isfinite(r['return_pct']))
    def test_rising_market(self):
        data=[]
        for i in range(300):
            c=100+i*.1
            data.append((i*900,c,c+.2,c-.2,c,1000.))
        for s in strategies():
            self.assertGreaterEqual(simulate(s,data)['final_usdt'],0)
if __name__=='__main__': unittest.main()
