"""Independent 50-strategy, public-data-only forward paper lab.

One symbol per experiment, 15m closed Binance candles. PostgreSQL is shared
with dashboard but existing paperbot tables and bot.py are never modified.
"""
import argparse
import logging
import os
import time
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

from bot import Market
from strategy_lab import INITIAL, FEE, SLIPPAGE, decision, features, strategies

LOG = logging.getLogger('forward_lab')
INTERVAL_MS = 15 * 60 * 1000


def initialize(db):
    with db.transaction():
        db.execute('''CREATE TABLE IF NOT EXISTS paperbot.lab_portfolios (
            strategy TEXT PRIMARY KEY, family TEXT NOT NULL,
            cash_usdt DOUBLE PRECISION NOT NULL, qty DOUBLE PRECISION NOT NULL DEFAULT 0,
            entry_cost DOUBLE PRECISION NOT NULL DEFAULT 0,
            stop_price DOUBLE PRECISION NOT NULL DEFAULT 0,
            closed_trades INTEGER NOT NULL DEFAULT 0,
            wins INTEGER NOT NULL DEFAULT 0,
            realized_pnl DOUBLE PRECISION NOT NULL DEFAULT 0,
            peak_usdt DOUBLE PRECISION NOT NULL DEFAULT 50,
            max_drawdown_pct DOUBLE PRECISION NOT NULL DEFAULT 0,
            last_candle_ms BIGINT NOT NULL DEFAULT 0,
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW())''')
        db.execute('''CREATE TABLE IF NOT EXISTS paperbot.lab_trades (
            id BIGSERIAL PRIMARY KEY, strategy TEXT NOT NULL,
            candle_ms BIGINT NOT NULL, side TEXT NOT NULL,
            price DOUBLE PRECISION NOT NULL, qty DOUBLE PRECISION NOT NULL,
            fee_usdt DOUBLE PRECISION NOT NULL, pnl_usdt DOUBLE PRECISION,
            UNIQUE(strategy,candle_ms,side))''')
        db.execute('''CREATE TABLE IF NOT EXISTS paperbot.lab_snapshots (
            strategy TEXT NOT NULL, candle_ms BIGINT NOT NULL,
            equity_usdt DOUBLE PRECISION NOT NULL,
            PRIMARY KEY(strategy,candle_ms))''')
        for s in strategies():
            db.execute('''INSERT INTO paperbot.lab_portfolios(strategy,family,cash_usdt)
                VALUES (%s,%s,%s) ON CONFLICT DO NOTHING''', (s.name,s.family,INITIAL))


def get_closed_candles(market, symbol):
    raw=market.get('/api/v3/klines',symbol=symbol,interval='15m',limit=500)
    now=int(time.time()*1000)
    rows=[]
    for c in raw:
        if int(c[6]) >= now: continue
        rows.append((int(c[0]),float(c[1]),float(c[2]),float(c[3]),float(c[4]),float(c[5])))
    if len(rows)<150 or any(rows[i+1][0]-rows[i][0]!=INTERVAL_MS for i in range(len(rows)-1)):
        raise ValueError('Brak kompletnych kolejnych świec 15m; cykl wstrzymany')
    return rows


def apply_candle(state, strategy, candles, idx):
    """Use candle idx-1 for signal; execute at idx open; mark at idx close.
    State is a dict copied from a locked DB row; returns (state, optional trade).
    """
    fast,slow=features(candles[:idx],strategy.fast,strategy.slow)
    cash=float(state['cash_usdt']); qty=float(state['qty']); cost=float(state['entry_cost'])
    stop=float(state['stop_price']); price=float(candles[idx][1]); trade=None
    exit_signal=bool(qty and decision(strategy,idx-1,candles,fast,slow,True))
    stopped=bool(qty and candles[idx][3]<=stop)
    if qty and (exit_signal or stopped):
        fill=(min(price,stop) if stopped and not exit_signal else price)*(1-SLIPPAGE)
        proceeds=qty*fill*(1-FEE); fee=qty*fill*FEE; pnl=proceeds-cost
        cash+=proceeds
        state['closed_trades']+=1; state['wins']+=int(pnl>0)
        state['realized_pnl']+=pnl
        trade=('SELL',fill,qty,fee,pnl)
        qty=0.;cost=0.;stop=0.
    elif not qty and decision(strategy,idx-1,candles,fast,slow,False):
        fill=price*(1+SLIPPAGE)
        # Conservative simulated minimum notional; no real orders are submitted.
        if cash>=10.0:
            qty=cash/(fill*(1+FEE)); fee=qty*fill*FEE
            cost=cash; cash=0.; stop=fill*(1-strategy.stop)
            trade=('BUY',fill,qty,fee,None)
    equity=cash+qty*candles[idx][4]*(1-FEE-SLIPPAGE)
    peak=max(float(state['peak_usdt']),equity)
    state.update(cash_usdt=cash,qty=qty,entry_cost=cost,stop_price=stop,
                 peak_usdt=peak,max_drawdown_pct=max(float(state['max_drawdown_pct']),
                 (1-equity/peak)*100 if peak else 0),last_candle_ms=candles[idx][0])
    return state,equity,trade


def process(db,candles):
    for strategy in strategies():
        with db.transaction():
            row=db.execute('SELECT * FROM paperbot.lab_portfolios WHERE strategy=%s FOR UPDATE',(strategy.name,)).fetchone()
            if row is None: raise RuntimeError('Missing strategy portfolio: '+strategy.name)
            state=dict(row)
            # Do not backfill from old candles on first launch: forward test starts now.
            if not state['last_candle_ms']:
                db.execute('UPDATE paperbot.lab_portfolios SET last_candle_ms=%s, updated_at=NOW() WHERE strategy=%s',
                           (candles[-1][0],strategy.name))
                continue
            pending=[i for i in range(max(strategy.slow+3,31),len(candles)) if candles[i][0]>state['last_candle_ms']]
            if pending and candles[pending[0]][0]-state['last_candle_ms']!=INTERVAL_MS:
                LOG.error('%s: missing candles since last run; skipping to prevent false execution',strategy.name)
                continue
            for i in pending:
                state,equity,trade=apply_candle(state,strategy,candles,i)
                if trade:
                    db.execute('''INSERT INTO paperbot.lab_trades(strategy,candle_ms,side,price,qty,fee_usdt,pnl_usdt)
                                  VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
                               (strategy.name,candles[i][0],*trade))
                db.execute('''INSERT INTO paperbot.lab_snapshots(strategy,candle_ms,equity_usdt)
                              VALUES(%s,%s,%s) ON CONFLICT DO NOTHING''',
                           (strategy.name,candles[i][0],equity))
            if pending:
                db.execute('''UPDATE paperbot.lab_portfolios SET cash_usdt=%s,qty=%s,entry_cost=%s,
                    stop_price=%s,closed_trades=%s,wins=%s,realized_pnl=%s,peak_usdt=%s,
                    max_drawdown_pct=%s,last_candle_ms=%s,updated_at=NOW() WHERE strategy=%s''',
                    tuple(state[k] for k in ('cash_usdt','qty','entry_cost','stop_price','closed_trades',
                    'wins','realized_pnl','peak_usdt','max_drawdown_pct','last_candle_ms'))+(strategy.name,))


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--symbol',default=os.environ.get('LAB_SYMBOL','BTCUSDT'))
    p.add_argument('--once',action='store_true')
    args=p.parse_args()
    logging.basicConfig(level=logging.INFO)
    dsn=os.environ['DATABASE_URL'];market=Market()
    with psycopg.connect(dsn,row_factory=dict_row,autocommit=False) as db:
        initialize(db)
        while True:
            try:
                candles=get_closed_candles(market,args.symbol)
                process(db,candles)
                LOG.info('Forward lab checked %s: %s',args.symbol,datetime.now(timezone.utc))
            except Exception:
                LOG.exception('Forward lab cycle failed')
                db.rollback()
                if args.once: raise
            if args.once: break
            time.sleep(60)


if __name__=='__main__':main()
