import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from mirror import ensure_backup


class BackupTests(unittest.TestCase):
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
