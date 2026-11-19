"""Public-data-only Binance Spot paper trader. No order or account endpoints."""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

import requests
from websocket import WebSocketApp

REST = "https://data-api.binance.vision"
WS = "wss://stream.binance.com:9443/stream?streams="
FEE = Decimal("0.001")
SLIPPAGE = Decimal("0.0005")
ZERO = Decimal("0")
LOG = logging.getLogger("paperbot")
CRYPTO_BASES = {
    "BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "TRX", "AVAX", "LINK",
    "LTC", "BCH", "DOT", "NEAR", "SUI", "APT", "UNI", "ETC", "XLM", "ATOM",
    "FIL", "ARB", "OP", "INJ", "TON", "PEPE", "SHIB", "TAO", "ICP", "HBAR",
    "ALGO", "AAVE", "CRV", "MKR", "RENDER", "FET", "WLD", "SEI", "TIA", "JUP",
    "PYTH", "ENA", "ONDO", "PENDLE", "RUNE", "IMX", "GRT", "SAND", "MANA", "AXS",
}


def D(value):
    return Decimal(str(value))


def now_ms():
    return int(time.time() * 1000)


def floor_step(value, step):
    value, step = D(value), D(step)
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step if step > 0 else value


def rules(info):
    filters = {f["filterType"]: f for f in info["filters"]}
    lot = filters.get("LOT_SIZE", {})
    market = filters.get("MARKET_LOT_SIZE", {})
    # Market quantities must satisfy both applicable filters.
    steps = [D(f["stepSize"]) for f in (lot, market) if D(f.get("stepSize", "0")) > 0]
    minimum = max((D(f.get("minQty", "0")) for f in (lot, market)), default=ZERO)
    maximum = min((D(f.get("maxQty", "1e30")) for f in (lot, market) if D(f.get("maxQty", "0")) > 0), default=D("1e30"))
    notional = max(D(filters.get("MIN_NOTIONAL", {}).get("minNotional", "0")), D(filters.get("NOTIONAL", {}).get("minNotional", "0")))
    return {"step": max(steps, default=ZERO), "min_qty": minimum, "max_qty": maximum, "min_notional": notional}


def valid_order(qty, price, rule):
    qty, price = D(qty), D(price)
    return (qty > 0 and rule["min_qty"] <= qty <= rule["max_qty"]
            and qty * price >= rule["min_notional"]
            and (rule["step"] == 0 or qty % rule["step"] == 0))


def quote_ok(q, max_age_ms=10000):
    if not q:
        return False
    try:
        bid, ask, bid_qty, ask_qty = (D(q[k]) for k in ("bid", "ask", "bid_qty", "ask_qty"))
        return (0 < bid <= ask and bid_qty > 0 and ask_qty > 0
                and (ask - bid) / ask <= D("0.015")
                and 0 <= now_ms() - int(q["received_ms"]) <= max_age_ms)
    except (KeyError, ValueError, ArithmeticError):
        return False


def ema(values, period):
    alpha = 2 / (period + 1)
    result = float(values[0])
    out = []
    for value in values:
        result = alpha * float(value) + (1 - alpha) * result
        out.append(result)
    return out


def rsi(closes, period=14):
    changes = [float(b - a) for a, b in zip(closes, closes[1:])]
    gains = [max(c, 0) for c in changes]
    losses = [max(-c, 0) for c in changes]
    avg_gain, avg_loss = sum(gains[:period]) / period, sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    return 100 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)


def signal(candles):
    """Only closed candles; returns score, stop distance and explanation."""
    if len(candles) < 80:
        return None
    if int(candles[-1][6]) < now_ms() - 30 * 60 * 1000:
        return None
    closes = [D(c[4]) for c in candles]
    highs = [D(c[2]) for c in candles]
    lows = [D(c[3]) for c in candles]
    volumes = [D(c[7]) for c in candles]  # quote-asset volume
    if min(closes + highs + lows) <= 0 or min(volumes[-21:]) <= 0:
        return None
    fast, slow = ema(closes, 12), ema(closes, 26)
    macd = [a - b for a, b in zip(fast, slow)]
    macd_signal = ema(macd, 9)
    strength = rsi(closes)
    ranges = [max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1])) for i in range(1, len(closes))]
    atr_pct = sum(ranges[-14:]) / D(14) / closes[-1]
    volume_ratio = volumes[-1] / (sum(volumes[-21:-1]) / D(20))
    trend = closes[-1] > D(str(ema(closes, 20)[-1])) > D(str(ema(closes, 50)[-1]))
    momentum = macd[-1] > macd_signal[-1] > 0 and macd[-1] >= macd[-2]
    acceptable = D("0.002") <= atr_pct <= D("0.045") and D("48") <= D(str(strength)) <= D("68")
    if not (trend and momentum and acceptable and volume_ratio >= D("1.15")):
        return None
    score = float(volume_ratio) + (strength - 50) / 30 + (macd[-1] - macd_signal[-1]) / float(closes[-1]) * 100
    stop_pct = max(D("0.025"), min(D("0.07"), atr_pct * 2))
    reason = f"trend EMA20>EMA50, RSI {strength:.1f}, MACD dodatni, wolumen {volume_ratio:.2f}x, ATR {atr_pct:.2%}"
    return score, stop_pct, reason


class Market:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "local-paperbot/1.0"
        self.quotes = {}
        self.lock = threading.Lock()
        self.symbols = []
        self.ws = None
        self.running = False

    def get(self, path, **params):
        for attempt in range(4):
            try:
                response = self.session.get(REST + path, params=params, timeout=10)
                if response.status_code in (418, 429):
                    delay = min(int(response.headers.get("Retry-After", 10)), 120)
                    time.sleep(delay)
                    continue
                response.raise_for_status()
                return response.json()
            except (requests.RequestException, ValueError) as exc:
                if attempt == 3:
                    raise RuntimeError(f"REST {path}: {exc}") from exc
                time.sleep(2 ** attempt)
        raise RuntimeError(f"REST {path}: limit zapytań")

    def set_symbols(self, symbols):
        symbols = sorted(set(symbols))
        if symbols != self.symbols:
            self.symbols = symbols
            if self.ws:
                self.ws.close()

    def start(self):
        self.running = True
        threading.Thread(target=self._ws_loop, daemon=True).start()

    def _ws_loop(self):
        while self.running:
            if not self.symbols:
                time.sleep(2)
                continue
            streams = "/".join(s.lower() + "@bookTicker" for s in self.symbols)
            def on_message(_ws, message):
                try:
                    data = json.loads(message).get("data", {})
                    q = {"bid": data["b"], "bid_qty": data["B"], "ask": data["a"], "ask_qty": data["A"], "received_ms": now_ms()}
                    with self.lock:
                        self.quotes[data["s"]] = q
                except (KeyError, ValueError):
                    pass
            self.ws = WebSocketApp(WS + streams, on_message=on_message, on_error=lambda _w, e: LOG.warning("WebSocket: %s", e))
            self.ws.run_forever(ping_interval=20, ping_timeout=10)
            time.sleep(3)

    def book(self, symbol):
        with self.lock:
            q = self.quotes.get(symbol)
        if quote_ok(q):
            return q
        data = self.get("/api/v3/ticker/bookTicker", symbol=symbol)
        q = {"bid": data["bidPrice"], "bid_qty": data["bidQty"], "ask": data["askPrice"], "ask_qty": data["askQty"], "received_ms": now_ms()}
        return q if quote_ok(q) else None


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS positions (symbol TEXT PRIMARY KEY, qty TEXT NOT NULL, cost_usdt TEXT NOT NULL, entry_price TEXT NOT NULL, stop_price TEXT NOT NULL, opened_ms INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY, ts_ms INTEGER NOT NULL, symbol TEXT NOT NULL, side TEXT NOT NULL, qty TEXT NOT NULL, bid TEXT NOT NULL, ask TEXT NOT NULL, fill_price TEXT NOT NULL, gross_usdt TEXT NOT NULL, fee_usdt TEXT NOT NULL, pnl_usdt TEXT, reason TEXT NOT NULL, cash_after_usdt TEXT NOT NULL, equity_after_usdt TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS snapshots (id INTEGER PRIMARY KEY, ts_ms INTEGER NOT NULL, equity_usdt TEXT NOT NULL, cash_usdt TEXT NOT NULL, note TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, ts_ms INTEGER NOT NULL, level TEXT NOT NULL, message TEXT NOT NULL);
    """)
    return db


def meta(db, key, default=None):
    row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def setmeta(db, key, value):
    db.execute("INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def event(db, level, message):
    db.execute("INSERT INTO events(ts_ms,level,message) VALUES(?,?,?)", (now_ms(), level, message))
    db.commit()


def equity(db, market):
    total = D(meta(db, "cash_usdt", "0"))
    for p in db.execute("SELECT * FROM positions"):
        q = market.book(p["symbol"])
        if not q:
            return None
        total += D(p["qty"]) * D(q["bid"]) * (1 - SLIPPAGE) * (1 - FEE)
    return total


def record_snapshot(db, value, note):
    db.execute("INSERT INTO snapshots(ts_ms,equity_usdt,cash_usdt,note) VALUES(?,?,?,?)", (now_ms(), str(value), meta(db, "cash_usdt"), note))
    db.commit()


def buy(db, symbol, q, rule, budget, stop_pct, reason):
    if not quote_ok(q):
        return False
    cash = D(meta(db, "cash_usdt"))
    budget = min(D(budget), cash)
    fill = D(q["ask"]) * (1 + SLIPPAGE)
    qty = floor_step(budget / (fill * (1 + FEE)), rule["step"])
    gross, fee = qty * fill, qty * fill * FEE
    if not valid_order(qty, fill, rule) or qty > D(q["ask_qty"]) or gross + fee > cash:
        return False
    # Reject a position which would be unsellable at the current bid.
    if not valid_order(qty, D(q["bid"]) * (1 - SLIPPAGE), rule):
        return False
    cash -= gross + fee
    stop = fill * (1 - D(stop_pct))
    with db:
        setmeta(db, "cash_usdt", cash)
        db.execute("INSERT INTO positions VALUES(?,?,?,?,?,?)", (symbol, str(qty), str(gross + fee), str(fill), str(stop), now_ms()))
        value = equity(db, _FixedMarket({symbol: q}))
        db.execute("INSERT INTO trades(ts_ms,symbol,side,qty,bid,ask,fill_price,gross_usdt,fee_usdt,pnl_usdt,reason,cash_after_usdt,equity_after_usdt) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (now_ms(), symbol, "BUY", str(qty), q["bid"], q["ask"], str(fill), str(gross), str(fee), None, reason, str(cash), str(value)))
    return True


class _FixedMarket:
    def __init__(self, quotes):
        self.quotes = quotes
    def book(self, symbol):
        return self.quotes.get(symbol)


def sell(db, position, q, rule, reason):
    if not quote_ok(q):
        return False
    qty = D(position["qty"])
    fill = D(q["bid"]) * (1 - SLIPPAGE)
    if not valid_order(qty, fill, rule) or qty > D(q["bid_qty"]):
        return False
    gross, fee = qty * fill, qty * fill * FEE
    pnl = gross - fee - D(position["cost_usdt"])
    cash = D(meta(db, "cash_usdt")) + gross - fee
    with db:
        setmeta(db, "cash_usdt", cash)
        db.execute("DELETE FROM positions WHERE symbol=?", (position["symbol"],))
        value = cash
        db.execute("INSERT INTO trades(ts_ms,symbol,side,qty,bid,ask,fill_price,gross_usdt,fee_usdt,pnl_usdt,reason,cash_after_usdt,equity_after_usdt) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (now_ms(), position["symbol"], "SELL", str(qty), q["bid"], q["ask"], str(fill), str(gross), str(fee), str(pnl), reason, str(cash), str(value)))
    return True


def universe(market, info):
    rows = market.get("/api/v3/ticker/24hr")
    eligible = {}
    for item in info["symbols"]:
        name = item["symbol"]
        base = item["baseAsset"]
        if item["status"] != "TRADING" or item["quoteAsset"] != "USDT" or not item.get("isSpotTradingAllowed", True):
            continue
        if base not in CRYPTO_BASES:
            continue
        eligible[name] = item
    ranked = sorted((r for r in rows if r["symbol"] in eligible and D(r["quoteVolume"]) >= D("1000000") and abs(D(r["priceChangePercent"])) < 25),
                    key=lambda r: D(r["quoteVolume"]), reverse=True)
    return {r["symbol"]: eligible[r["symbol"]] for r in ranked[:15]}


def cycle(db, market, info, picks):
    if meta(db, "cash_usdt") is None:
        with db:
            setmeta(db, "cash_usdt", 50)
            setmeta(db, "initial_usdt", 50)
        event(db, "INFO", "Start: wirtualne 50 USDT (nominalny odpowiednik 50 USD)")
    value = equity(db, market)
    if value is None:
        event(db, "WARN", "Brak wiarygodnej ceny pozycji; cykl pominięty")
        return
    today = datetime.now(timezone.utc).date().isoformat()
    if meta(db, "day") != today:
        with db:
            setmeta(db, "day", today)
            setmeta(db, "day_start_usdt", value)
    peak = max(D(meta(db, "peak_usdt", "0")), value)
    with db:
        setmeta(db, "peak_usdt", peak)
    halted = value <= D(meta(db, "initial_usdt", "50")) * D("0.8") or value <= D(meta(db, "day_start_usdt")) * D("0.92") or value <= peak * D("0.85")
    positions = db.execute("SELECT * FROM positions").fetchall()
    for p in positions:
        q = market.book(p["symbol"])
        if not q:
            continue
        rule = rules(next(s for s in info["symbols"] if s["symbol"] == p["symbol"]))
        if halted or D(q["bid"]) <= D(p["stop_price"]):
            reason = "limit straty portfela" if halted else "stop-loss"
            if not sell(db, p, q, rule, reason):
                event(db, "WARN", f"Nie można sprzedać {p['symbol']}: minimalna wartość, lot lub płynność")
    # A sell can change available cash but a halted cycle never opens a new position.
    if not halted and not db.execute("SELECT 1 FROM positions").fetchone():
        candidates = []
        for symbol, symbol_info in picks.items():
            try:
                raw = market.get("/api/v3/klines", symbol=symbol, interval="15m", limit=121)
                candles = [c for c in raw if int(c[6]) < now_ms()]
                result = signal(candles)
                if result:
                    candidates.append((result[0], symbol, symbol_info, result))
            except (RuntimeError, ValueError, ArithmeticError) as exc:
                LOG.warning("Analiza %s: %s", symbol, exc)
        for _, symbol, symbol_info, result in sorted(candidates, reverse=True):
            q = market.book(symbol)
            if q and buy(db, symbol, q, rules(symbol_info), D(meta(db, "cash_usdt")) * D("0.95"), result[1], result[2]):
                LOG.info("Wirtualny zakup %s", symbol)
                break
    final = equity(db, market)
    if final is not None:
        record_snapshot(db, final, "blokada strat" if halted else "analiza")
    LOG.info("Kapitał: %s USDT; cash: %s USDT", final, meta(db, "cash_usdt"))


def run(db_path, once=False):
    db = connect(db_path)
    market = Market()
    market.start()
    info, picks, refreshed = None, {}, 0
    try:
        while True:
            start = time.monotonic()
            try:
                if time.time() - refreshed > 3600:
                    info = market.get("/api/v3/exchangeInfo")
                    picks = universe(market, info)
                    held = [r[0] for r in db.execute("SELECT symbol FROM positions")]
                    market.set_symbols(list(picks) + held)
                    refreshed = time.time()
                cycle(db, market, info, picks)
            except Exception as exc:
                LOG.exception("Cykl przerwany: %s", exc)
                event(db, "ERROR", str(exc))
            if once:
                break
            time.sleep(max(0, 60 - (time.monotonic() - start)))
    finally:
        market.running = False
        if market.ws:
            market.ws.close()
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/paperbot.sqlite3")
    parser.add_argument("--once", action="store_true", help="Wykonaj jeden cykl")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(args.db, args.once)
