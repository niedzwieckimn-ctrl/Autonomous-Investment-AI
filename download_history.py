"""Download public Binance Spot 15m OHLCV to a validated CSV. No API keys or orders."""
import argparse
import csv
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = 'https://data-api.binance.vision/api/v3/klines'
INTERVAL_MS = {'15m': 900_000, '1h': 3_600_000, '4h': 14_400_000, '1d': 86_400_000}


def utc_ms(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def fetch_page(symbol, interval, start_ms, end_ms, attempts=5):
    query = urlencode({'symbol': symbol, 'interval': interval, 'startTime': start_ms,
                       'endTime': end_ms - 1, 'limit': 1000})
    for attempt in range(attempts):
        try:
            req = Request(BASE + '?' + query, headers={'User-Agent': 'StrategyLabResearch/1.0'})
            with urlopen(req, timeout=25) as response:
                result = json.load(response)
            if not isinstance(result, list):
                raise ValueError('Unexpected Binance response')
            return result
        except HTTPError as exc:
            if exc.code == 451:
                raise RuntimeError('Binance HTTP 451: access restricted from this network') from exc
            if exc.code not in (418, 429, 500, 502, 503, 504) or attempt == attempts - 1:
                raise
            retry = exc.headers.get('Retry-After', '')
            time.sleep(min(60, int(retry) if retry.isdigit() else 2 ** attempt))
        except (URLError, TimeoutError):
            if attempt == attempts - 1:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError('History download failed')


def download(symbol, interval, start_ms, end_ms, fetch=fetch_page):
    if interval not in INTERVAL_MS:
        raise ValueError('Unsupported interval')
    if not re.fullmatch(r'[A-Z0-9]{5,20}', symbol):
        raise ValueError('Invalid trading symbol')
    step = INTERVAL_MS[interval]
    if end_ms <= start_ms:
        raise ValueError('End must be after start')
    # Never include an unfinished candle.
    end_ms = min(end_ms, (int(time.time() * 1000) // step) * step)
    rows = []
    cursor = start_ms
    while cursor < end_ms:
        page = fetch(symbol, interval, cursor, end_ms)
        if not page:
            break
        latest = cursor - 1
        for candle in page:
            opened = int(candle[0])
            latest = max(latest, opened)
            if opened < start_ms or opened + step > end_ms:
                continue
            rows.append((opened, *[candle[k] for k in (1, 2, 3, 4, 5)]))
        if latest < cursor:
            raise ValueError('API returned no forward progress')
        cursor = latest + step
    rows.sort(key=lambda r: r[0])
    if not rows:
        raise ValueError('No historical candles returned')
    if len({r[0] for r in rows}) != len(rows):
        raise ValueError('Duplicate candle timestamps')
    gaps = [(a[0], b[0]) for a, b in zip(rows, rows[1:]) if b[0] - a[0] != step]
    if gaps:
        raise ValueError(f'Historical data contains {len(gaps)} gaps; first: {gaps[0]}')
    if rows[0][0] > start_ms + step:
        raise ValueError('Missing candles at requested beginning (or symbol not yet listed)')
    if rows[-1][0] + step < end_ms - step:
        raise ValueError('Missing candles at requested end')
    return rows


def save(rows, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(('timestamp', 'open', 'high', 'low', 'close', 'volume'))
        writer.writerows(rows)
    return path


def main():
    parser = argparse.ArgumentParser(description='Download Binance public historical candles')
    parser.add_argument('--symbol', default='BTCUSDT')
    parser.add_argument('--interval', choices=INTERVAL_MS, default='15m')
    parser.add_argument('--start', default='2024-01-01')
    parser.add_argument('--end', default='2026-11-01', help='Exclusive UTC end date')
    parser.add_argument('--output', default=None)
    args = parser.parse_args()
    symbol = args.symbol.upper()
    output = args.output or f'data/history/{symbol}_{args.interval}_{args.start}_{args.end}.csv'
    rows = download(symbol, args.interval, utc_ms(args.start), utc_ms(args.end))
    save(rows, output)
    print(f'Saved {len(rows)} complete {args.interval} candles to {output}')


if __name__ == '__main__':
    main()
