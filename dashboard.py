"""Read-only local dashboard for the paper trading database."""
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Bot inwestycyjny — symulacja", layout="wide")
st.title("Bot inwestycyjny · symulacja")
st.caption("Wirtualny handel na danych Binance Spot. Dane odświeżają się co 60 sekund.")

db_path = Path("data/paperbot.sqlite3")
if not db_path.exists():
    st.info("Uruchom najpierw `python bot.py`. Baza danych jeszcze nie istnieje.")
    st.stop()

@st.fragment(run_every="60s")
def view():
    try:
        with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True, timeout=5) as db:
            db.row_factory = sqlite3.Row
            meta = {r["key"]: r["value"] for r in db.execute("SELECT * FROM meta")}
            snapshots = pd.read_sql_query("SELECT ts_ms,equity_usdt,cash_usdt,note FROM snapshots ORDER BY id", db)
            positions = pd.read_sql_query("SELECT symbol,qty,cost_usdt,entry_price,stop_price,opened_ms FROM positions", db)
            trades = pd.read_sql_query("SELECT ts_ms,symbol,side,qty,fill_price,gross_usdt,fee_usdt,pnl_usdt,reason,cash_after_usdt,equity_after_usdt FROM trades ORDER BY id DESC LIMIT 200", db)
            events = pd.read_sql_query("SELECT ts_ms,level,message FROM events ORDER BY id DESC LIMIT 30", db)
    except sqlite3.Error as exc:
        st.error(f"Nie można odczytać bazy: {exc}")
        return
    if snapshots.empty:
        st.info("Oczekiwanie na pierwszą analizę.")
        if not events.empty:
            st.dataframe(events, hide_index=True)
        return
    equity = float(snapshots.iloc[-1]["equity_usdt"])
    initial = float(meta.get("initial_usdt", 50))
    a, b, c = st.columns(3)
    a.metric("Wartość portfela", f"{equity:.2f} USDT", f"{equity-initial:+.2f} USDT")
    b.metric("Zwrot", f"{(equity/initial-1)*100:+.2f}%")
    c.metric("Gotówka", f"{float(snapshots.iloc[-1]['cash_usdt']):.4f} USDT")
    snapshots["Czas"] = pd.to_datetime(snapshots["ts_ms"], unit="ms", utc=True).dt.tz_convert("Europe/Warsaw")
    snapshots["USDT"] = pd.to_numeric(snapshots["equity_usdt"])
    st.subheader("Wartość portfela w USDT")
    st.line_chart(snapshots.set_index("Czas")["USDT"])
    st.caption(f"Ostatni zapis: {snapshots.iloc[-1]['Czas']:%Y-%m-%d %H:%M:%S} · {snapshots.iloc[-1]['note']}")
    st.subheader("Otwarte pozycje")
    if positions.empty:
        st.write("Brak otwartych pozycji")
    else:
        positions["otwarcie"] = pd.to_datetime(positions.pop("opened_ms"), unit="ms", utc=True).dt.tz_convert("Europe/Warsaw")
        st.dataframe(positions, hide_index=True, width="stretch")
    st.subheader("Historia transakcji")
    if trades.empty:
        st.write("Brak transakcji")
    else:
        trades["czas"] = pd.to_datetime(trades.pop("ts_ms"), unit="ms", utc=True).dt.tz_convert("Europe/Warsaw")
        st.dataframe(trades, hide_index=True, width="stretch")
    with st.expander("Zdarzenia i błędy"):
        st.dataframe(events, hide_index=True, width="stretch")

view()
