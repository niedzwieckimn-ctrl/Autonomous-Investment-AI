# Strategy Lab v4 — 50 forward-paper portfolios

**Status:** code prepared, NOT deployed. This is a separate paper-only worker; no real orders and no exchange keys.

## Changes
- `forward_lab.py` (new): 50 portfolios, 15-minute closed candles, next-candle-open executions, simulated fees/slippage and stops, PostgreSQL persistence.
- `web_app.py` (updated): `/api/strategy-lab` reads live-paper snapshots from PostgreSQL.
- `static/strategy_lab_dashboard.js` (updated): live-paper ranking.
- `tests/test_forward_lab.py` (new): basic forward engine test.
- `bot.py`, `mirror.py`, `render.yaml` and the existing portfolio tables remain untouched.

## Deploy (manual, separate service)
1. Back up the project and deploy dashboard changes to the existing **web service** only after testing. Keep the existing background worker unchanged.
2. In Supabase SQL Editor, create/grant the three tables (see below) or let the new worker create them with a privileged `DATABASE_URL`. Do not use a read-only connection for the worker.
3. Create a **separate Render Background Worker** with the repository and `startCommand: python forward_lab.py --symbol BTCUSDT`. Give it `DATABASE_URL` with write privileges on `paperbot`. Do not replace the existing worker's start command. Ensure the hosting plan supports a persistent worker.
4. The web service must use `DASHBOARD_DATABASE_URL` with `SELECT` on `paperbot.lab_portfolios` and `paperbot.lab_snapshots`. If its role is read-only, a database administrator must grant those privileges after the tables are created.
5. Wait until the next completed 15-minute candle for the first portfolio snapshots. The start time is recorded in `lab_portfolios.started_at`; track at least 30 days.

## Permissions
In the Supabase SQL Editor, once the worker created tables, grant access to the **actual** dashboard DB role (replace `YOUR_DASHBOARD_ROLE`, do not paste literally):

```sql
GRANT USAGE ON SCHEMA paperbot TO YOUR_DASHBOARD_ROLE;
GRANT SELECT ON paperbot.lab_portfolios, paperbot.lab_snapshots TO YOUR_DASHBOARD_ROLE;
```

## Research limitations
- All 50 strategies operate on **BTCUSDT** by default. This is an initial same-market comparison, not a multi-asset engine.
- The existing `strategy_lab.py` has 50 parameter configurations across 5 signal families; it is **not** 50 independently validated trading systems.
- OHLC candle simulation does not reproduce order-book liquidity, bid/ask spread, exchange LOT_SIZE precision, or real execution; minimum 10 USDT is only an approximation.
- Stops are checked against candle lows; intrabar ordering is unknown. Restarted worker replays any missing closed candles within the 500-candle window, which is a historical reconstruction, not truly live fills.
- If the worker is offline longer than 500 candles, it will refuse to resume to avoid silently skipping history; manual recovery is required.
- This is paper trading only, no live orders. A 30-day trial cannot establish future profitability.

## Local verification
```bash
pip install -r requirements.txt
python -m unittest tests.test_forward_lab
python forward_lab.py --once
```
`--once` requires a real `DATABASE_URL` and Binance public REST access. Test in a staging database before production.
