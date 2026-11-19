import tempfile
import unittest
from pathlib import Path
from download_history import download, save, utc_ms, INTERVAL_MS
from strategy_lab import load_csv

class DownloadTests(unittest.TestCase):
    def test_date(self):
        self.assertEqual(utc_ms('2024-01-01'), 1704067200000)

    def test_pagination_and_csv(self):
        step = INTERVAL_MS['15m']
        candles = [[i * step, '100', '101', '99', '100', '10'] for i in range(180)]
        def fake(symbol, interval, start, end):
            return [x for x in candles if start <= x[0] < end][:100]
        rows = download('BTCUSDT', '15m', 0, 180 * step, fetch=fake)
        self.assertEqual(len(rows), 180)
        with tempfile.TemporaryDirectory() as directory:
            path = save(rows, Path(directory) / 'test.csv')
            self.assertEqual(len(load_csv(path)), 180)

    def test_gap_rejected(self):
        step = INTERVAL_MS['15m']
        candles = [[i * step, '100', '101', '99', '100', '10'] for i in range(180) if i != 50]
        with self.assertRaisesRegex(ValueError, 'gaps'):
            download('BTCUSDT', '15m', 0, 180 * step,
                     fetch=lambda symbol, interval, start, end: [x for x in candles if start <= x[0] < end])

if __name__ == '__main__':
    unittest.main()
