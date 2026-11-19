"""Idempotent SQLite -> PostgreSQL read mirror; SQLite remains the worker's source of truth."""
import argparse
import logging
import os
import sqlite3

import psycopg

LOG = logging.getLogger(__name__)
TABLES = {
    "meta": ("key", "value"),
    "positions": ("symbol", "qty", "cost_usdt", "entry_price", "stop_price", "opened_ms"),
    "trades": ("id", "ts_ms", "symbol", "side", "qty", "bid", "ask", "fill_price", "gross_usdt", "fee_usdt", "pnl_usdt", "reason", "cash_after_usdt", "equity_after_usdt"),
    "snapshots": ("id", "ts_ms", "equity_usdt", "cash_usdt", "note"),
    "events": ("id", "ts_ms", "level", "message"),
}
SCHEMA = """
CREATE SCHEMA IF NOT EXISTS paperbot;
CREATE TABLE IF NOT EXISTS paperbot.meta (key text PRIMARY KEY, value text NOT NULL);
CREATE TABLE IF NOT EXISTS paperbot.positions (symbol text PRIMARY KEY, qty text NOT NULL, cost_usdt text NOT NULL, entry_price text NOT NULL, stop_price text NOT NULL, opened_ms bigint NOT NULL);
CREATE TABLE IF NOT EXISTS paperbot.trades (id bigint PRIMARY KEY, ts_ms bigint NOT NULL, symbol text NOT NULL, side text NOT NULL, qty text NOT NULL, bid text NOT NULL, ask text NOT NULL, fill_price text NOT NULL, gross_usdt text NOT NULL, fee_usdt text NOT NULL, pnl_usdt text, reason text NOT NULL, cash_after_usdt text NOT NULL, equity_after_usdt text NOT NULL);
CREATE TABLE IF NOT EXISTS paperbot.snapshots (id bigint PRIMARY KEY, ts_ms bigint NOT NULL, equity_usdt text NOT NULL, cash_usdt text NOT NULL, note text NOT NULL);
CREATE TABLE IF NOT EXISTS paperbot.events (id bigint PRIMARY KEY, ts_ms bigint NOT NULL, level text NOT NULL, message text NOT NULL);
REVOKE ALL ON SCHEMA paperbot FROM PUBLIC;
"""


def sync(source, dsn):
    """One consistent SQLite read transaction, one PostgreSQL write transaction."""
    with sqlite3.connect(f"file:{os.path.abspath(source)}?mode=ro", uri=True, timeout=15) as local:
        local.row_factory = sqlite3.Row
        local.execute("BEGIN")
        copied = {name: [tuple(row[c] for c in columns) for row in local.execute(f"SELECT {','.join(columns)} FROM {name} ORDER BY {columns[0]}")]
                  for name, columns in TABLES.items()}
        with psycopg.connect(dsn, connect_timeout=10) as remote:
            with remote.transaction():
                remote.execute(SCHEMA)
                for name, columns in TABLES.items():
                    rows = copied[name]
                    if not rows:
                        continue
                    placeholders = ",".join("%s" for _ in columns)
                    updates = ",".join(f"{c}=EXCLUDED.{c}" for c in columns[1:])
                    statement = f"INSERT INTO paperbot.{name} ({','.join(columns)}) VALUES ({placeholders}) ON CONFLICT ({columns[0]}) DO UPDATE SET {updates}"
                    with remote.cursor() as cur:
                        cur.executemany(statement, rows)
                # Remove only stale open positions; historical rows remain append-only.
                symbols = [row[0] for row in copied["positions"]]
                if symbols:
                    remote.execute("DELETE FROM paperbot.positions WHERE NOT (symbol = ANY(%s))", (symbols,))
                else:
                    remote.execute("DELETE FROM paperbot.positions")
                remote.execute("CREATE TABLE IF NOT EXISTS paperbot.sync_status (id int PRIMARY KEY CHECK (id=1), synced_at timestamptz NOT NULL, latest_snapshot_id bigint)")
                latest = copied["snapshots"][-1][0] if copied["snapshots"] else None
                remote.execute("INSERT INTO paperbot.sync_status VALUES (1, now(), %s) ON CONFLICT (id) DO UPDATE SET synced_at=EXCLUDED.synced_at,latest_snapshot_id=EXCLUDED.latest_snapshot_id", (latest,))
    LOG.info("Mirror updated: %s", {name: len(rows) for name, rows in copied.items()})
    return {name: len(rows) for name, rows in copied.items()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    sync(args.source, os.environ["DATABASE_URL"])
