"""Read-only portfolio dashboard. Requires a PostgreSQL read-only role."""
import hmac
import json
from pathlib import Path
import logging
import os
import time
from datetime import datetime, timezone
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

LOG = logging.getLogger(__name__)
app = Flask(__name__)
app.secret_key = os.environ.get("DASHBOARD_SESSION_SECRET", "")
app.config.update(SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")


def authorized():
    return bool(session.get("authorized"))


def read_data():
    dsn = os.environ["DASHBOARD_DATABASE_URL"]
    with psycopg.connect(dsn, connect_timeout=5, row_factory=dict_row) as db:
        with db.transaction():
            db.execute("SET TRANSACTION READ ONLY")
            meta = {r["key"]: r["value"] for r in db.execute("SELECT key,value FROM paperbot.meta")}
            positions = list(db.execute("SELECT * FROM paperbot.positions ORDER BY symbol"))
            trades = list(db.execute("SELECT * FROM paperbot.trades ORDER BY id DESC"))
            snapshots = list(db.execute("SELECT * FROM paperbot.snapshots ORDER BY id"))
            sync = db.execute("SELECT synced_at FROM paperbot.sync_status WHERE id=1").fetchone()
    return meta, positions, trades, snapshots, sync


@app.get("/health")
def health():
    return "ok", 200


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        expected = os.environ.get("DASHBOARD_PASSWORD", "")
        supplied = request.form.get("password", "")
        if expected and hmac.compare_digest(supplied, expected):
            session.clear()
            session["authorized"] = True
            return redirect(url_for("index"))
        time.sleep(0.5)
        return render_template("login.html", error="Nieprawidłowe hasło"), 401
    return render_template("login.html", error=None)


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
def index():
    if not authorized():
        return redirect(url_for("login"))
    return render_template("dashboard.html")


@app.get("/api/portfolio")
def portfolio():
    if not authorized():
        return jsonify(error="unauthorized"), 401
    try:
        meta, positions, trades, snapshots, sync = read_data()
        if not snapshots:
            return jsonify(status="WAITING", message="Oczekiwanie na pierwszą wycenę", positions=[], trades=[], snapshots=[])
        equity = Decimal(snapshots[-1]["equity_usdt"])
        initial = Decimal(meta.get("initial_usdt", "50"))
        cash = Decimal(meta.get("cash_usdt", "0"))
        today = datetime.now(timezone.utc).date().isoformat()
        start = next((Decimal(s["equity_usdt"]) for s in snapshots if datetime.fromtimestamp(s["ts_ms"] / 1000, timezone.utc).date().isoformat() == today), equity)
        closed = [t for t in trades if t["side"] == "SELL" and t["pnl_usdt"] is not None]
        peak = Decimal("0")
        max_dd = Decimal("0")
        for s in snapshots:
            value = Decimal(s["equity_usdt"])
            peak = max(peak, value)
            if peak:
                max_dd = max(max_dd, (peak - value) / peak * 100)
        last_ts = snapshots[-1]["ts_ms"]
        online = bool(sync and (datetime.now(timezone.utc) - sync["synced_at"]).total_seconds() < 180 and time.time() * 1000 - last_ts < 180000)
        return jsonify(status="ONLINE" if online else "OFFLINE", last_update_ms=last_ts,
            equity=float(equity), initial=float(initial), cash=float(cash), position_value=float(equity-cash),
            total_pnl=float(equity-initial), total_pct=float((equity/initial-1)*100) if initial else 0,
            day_pnl=float(equity-start), day_pct=float((equity/start-1)*100) if start else 0,
            realized_pnl=float(sum(Decimal(t["pnl_usdt"]) for t in closed)),
            fees=float(sum(Decimal(t["fee_usdt"]) for t in trades)),
            trade_count=len(trades), closed_count=len(closed), win_rate=float(sum(Decimal(t["pnl_usdt"])>0 for t in closed)/len(closed)*100) if closed else 0,
            max_drawdown=float(max_dd), best=max(closed,key=lambda t: Decimal(t["pnl_usdt"])) if closed else None,
            worst=min(closed,key=lambda t: Decimal(t["pnl_usdt"])) if closed else None,
            positions=positions, trades=trades, snapshots=snapshots, source="Binance Spot REST/WebSocket · SQLite workera → PostgreSQL")
    except (psycopg.Error, KeyError, ValueError) as exc:
        LOG.exception("Dashboard read failed: %s", exc)
        return jsonify(error="Baza danych jest chwilowo niedostępna"), 503


@app.get("/api/strategy-lab")
def strategy_lab_results():
    if not authorized():
        return jsonify(error="unauthorized"), 401
    try:
        with psycopg.connect(os.environ["DASHBOARD_DATABASE_URL"], connect_timeout=5, row_factory=dict_row) as db:
            with db.transaction():
                db.execute("SET TRANSACTION READ ONLY")
                rows=list(db.execute("SELECT * FROM paperbot.lab_portfolios ORDER BY strategy"))
                last=db.execute("SELECT MAX(candle_ms) AS ts FROM paperbot.lab_snapshots").fetchone()["ts"]
        strategies=[]
        for r in rows:
            # The last snapshot is the latest marked-to-market equity.
            # No snapshot means this portfolio has not started trading yet.
            strategies.append({"strategy":r["strategy"],"family":r["family"],
                "initial_usdt":50,"final_usdt":round(float(r["cash_usdt"]),4) if not r["qty"] else None,
                "return_pct":None,"max_drawdown_pct":round(float(r["max_drawdown_pct"]),2),
                "closed_trades":r["closed_trades"],"win_rate_pct":round(100*r["wins"]/r["closed_trades"],2) if r["closed_trades"] else None,
                "open_position":bool(r["qty"]),"last_candle_ms":r["last_candle_ms"]})
        # Fetch last persisted equity per strategy (snapshot is written on each closed candle).
        with psycopg.connect(os.environ["DASHBOARD_DATABASE_URL"], connect_timeout=5, row_factory=dict_row) as db:
            with db.transaction():
                db.execute("SET TRANSACTION READ ONLY")
                latest={r["strategy"]:r["equity_usdt"] for r in db.execute("""
                    SELECT DISTINCT ON (strategy) strategy,equity_usdt
                    FROM paperbot.lab_snapshots ORDER BY strategy,candle_ms DESC""")}
        for r in strategies:
            if r["strategy"] in latest:
                r["final_usdt"]=round(latest[r["strategy"]],4)
                r["return_pct"]=round((latest[r["strategy"]]/50-1)*100,3)
        return jsonify(status="FORWARD" if last else "WAITING",last_update_ms=last,
                       strategies=strategies,message="Oczekiwanie na pierwszą zamkniętą świecę" if not last else None)
    except (psycopg.Error, KeyError, ValueError) as exc:
        LOG.warning("Forward lab unavailable: %s",exc)
        return jsonify(status="NOT_CONFIGURED",strategies=[],
                       message="Laboratorium nie jest jeszcze uruchomione lub brakuje uprawnień do tabel.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
