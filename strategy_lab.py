"""Independent research-only backtester. Never sends orders or changes live bot DB.

CSV columns: timestamp,open,high,low,close,volume. timestamp ISO UTC or epoch ms.
Signals use fully closed candles; fills happen at the NEXT candle open.
"""
import argparse
import csv
import json
import math
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

INITIAL = 50.0
FEE = 0.001
SLIPPAGE = 0.0005

@dataclass(frozen=True)
class Strategy:
    name: str
    family: str
    fast: int
    slow: int
    entry: float
    exit: float
    stop: float


def strategies():
    result = []
    for family in ('trend', 'reversion', 'momentum', 'breakout', 'hybrid'):
        for i in range(10):
            result.append(Strategy(f'{family.upper()}-{i+1:02}', family,
                                   8 + (i % 5)*4, 40 + (i % 5)*12,
                                   0.005 + (i // 5)*0.005 + (i % 5)*0.001,
                                   0.002 + (i % 5)*0.001,
                                   0.025 + (i % 5)*0.005))
    return result


def load_csv(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    data = []
    for row in rows:
        t = row['timestamp']
        ts = float(t) / 1000 if t.isdigit() and len(t) >= 13 else (float(t) if t.isdigit() else datetime.fromisoformat(t.replace('Z', '+00:00')).timestamp())
        o, h, l, c, v = (float(row[k]) for k in ('open','high','low','close','volume'))
        if not (0 < l <= min(o,c) <= max(o,c) <= h and v >= 0 and all(map(math.isfinite,(o,h,l,c,v)))):
            raise ValueError('Invalid candle: '+str(row))
        data.append((ts,o,h,l,c,v))
    if len(data) < 150 or any(data[i][0] >= data[i+1][0] for i in range(len(data)-1)):
        raise ValueError('Need at least 150 strictly time-ordered candles')
    return data


def ema(series, period):
    out=[]; value=series[0]; alpha=2/(period+1)
    for x in series:
        value=alpha*x+(1-alpha)*value; out.append(value)
    return out


def features(data, fast, slow):
    close=[r[4] for r in data]
    a,b=ema(close,fast),ema(close,slow)
    return a,b


def decision(s, i, data, fast, slow, holding):
    # At index i, only candles <= i are used. Execution is at i+1 open.
    c=data[i][4]; prev=data[i-1][4]
    high=max(x[2] for x in data[i-20:i]); low=min(x[3] for x in data[i-20:i])
    ma=slow[i]; trend=fast[i] > ma
    change=c / data[i-10][4]-1
    deviation=c/ma-1
    if s.family=='trend':
        return (trend and deviation>s.entry) if not holding else (not trend or deviation < -s.exit)
    if s.family=='reversion':
        return (deviation < -s.entry and c>prev) if not holding else (deviation > s.exit)
    if s.family=='momentum':
        return (trend and change>s.entry) if not holding else (change < -s.exit)
    if s.family=='breakout':
        return (c>high*(1+s.entry/5)) if not holding else (c<low*(1-s.exit/5))
    return (trend and c>high and change>s.entry) if not holding else (not trend or change < -s.exit)


def simulate(s, data, fee=FEE, slippage=SLIPPAGE):
    fast,slow=features(data,s.fast,s.slow)
    cash=INITIAL; qty=0.; entry_cost=0.; stop=0.; peak=INITIAL; drawdown=0.; closed=[]; equity_curve=[]
    for i in range(max(s.slow+2,30),len(data)-1):
        o=data[i+1][1]
        sold_this_bar=False
        if qty:
            # Conservative stop gap handling; next bar low can trigger stop after open.
            triggered = data[i+1][3] <= stop
            exit_signal = decision(s,i,data,fast,slow,True)
            if triggered or exit_signal:
                price=(min(o,stop) if triggered else o)*(1-slippage)
                proceeds=qty*price*(1-fee)
                closed.append(proceeds-entry_cost)
                cash+=proceeds; qty=0.; entry_cost=0.; sold_this_bar=True
        if not qty and not sold_this_bar and decision(s,i,data,fast,slow,False):
            # All-in within this *virtual* strategy; no leverage. Min-notional is not enforced here.
            price=o*(1+slippage)
            qty=cash/(price*(1+fee)); entry_cost=cash; cash=0.
            stop=price*(1-s.stop)
        equity=cash+qty*data[i+1][4]*(1-fee-slippage)
        peak=max(peak,equity); drawdown=max(drawdown,1-equity/peak)
        equity_curve.append(round(equity,6))
    final=cash+qty*data[-1][4]*(1-fee-slippage)
    return {'strategy':s.name,'family':s.family,'initial_usdt':INITIAL,'final_usdt':round(final,4),
            'return_pct':round((final/INITIAL-1)*100,3),'max_drawdown_pct':round(drawdown*100,3),
            'closed_trades':len(closed),'win_rate_pct':round(100*sum(p>0 for p in closed)/len(closed),2) if closed else None,
            'open_position':bool(qty),'equity_curve':equity_curve}


def run(data, output):
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    results=[simulate(s,data) for s in strategies()]
    with open(output/'ranking.csv','w',newline='',encoding='utf-8') as f:
        cols=['strategy','family','initial_usdt','final_usdt','return_pct','max_drawdown_pct','closed_trades','win_rate_pct','open_position']
        writer=csv.DictWriter(f,fieldnames=cols);writer.writeheader()
        for result in sorted(results,key=lambda x:x['return_pct'],reverse=True):writer.writerow({k:result[k] for k in cols})
    (output/'results.json').write_text(json.dumps({'disclaimer':'Research only; no live execution; OHLC approximation, no order-book or exchange min-notional simulation',
          'candles':len(data),'first_timestamp':int(data[0][0]*1000),'last_timestamp':int(data[-1][0]*1000),'strategies':results},ensure_ascii=False),encoding='utf-8')
    print(f'Completed {len(results)} strategies. Results: {output / "ranking.csv"}')


if __name__=='__main__':
    p=argparse.ArgumentParser(description='50-strategy historical paper-trading laboratory')
    p.add_argument('--csv',required=True,help='OHLCV CSV: timestamp,open,high,low,close,volume')
    p.add_argument('--output',default='strategy_lab_results')
    a=p.parse_args();run(load_csv(a.csv),a.output)
