import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from mirror import ensure_backup, pooler_connection


class BackupTests(unittest.TestCase):
    def test_pooler_user_is_completed_only_for_expected_host(self):
        short = "postgresql://postgres:example@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"
        self.assertIn("postgres.smzzzpdhvbjnfuzsgygf", pooler_connection(short, "smzzzpdhvbjnfuzsgygf"))
        self.assertEqual(pooler_connection(short, None), short)
        self.assertEqual(pooler_connection("postgresql://postgres:example@other.example.com/db", "ref"), "postgresql://postgres:example@other.example.com/db")

    def test_backup_is_consistent_and_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "paperbot.sqlite3"
            with closing(sqlite3.connect(source)) as db:
                db.execute("CREATE TABLE trades (id integer PRIMARY KEY, value text)")
                db.execute("INSERT INTO trades(value) VALUES ('first')")
                db.commit()
            copy = ensure_backup(source)
            with closing(sqlite3.connect(source)) as db:
                db.execute("INSERT INTO trades(value) VALUES ('second')")
                db.commit()
            self.assertEqual(copy, ensure_backup(source))
            with closing(sqlite3.connect(copy)) as db:
                self.assertEqual(db.execute("SELECT value FROM trades").fetchall(), [("first",)])


if __name__ == "__main__":
    unittest.main()
