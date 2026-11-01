"""Tests for utils.db_backup restore guards (no network, temp dirs)."""

import os
import io
import sys
import time
import sqlite3
import zipfile
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import db_backup


def _make_db_bytes(min_size: int = 2048) -> bytes:
    """Valid SQLite database file bytes, at least min_size large."""
    tf = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tf.close()
    conn = sqlite3.connect(tf.name)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    for _ in range(max(20, min_size // 100)):
        conn.execute("INSERT INTO t (v) VALUES (?)", ("x" * 200,))
    conn.commit()
    conn.close()
    with open(tf.name, "rb") as f:
        data = f.read()
    os.unlink(tf.name)
    return data


def _zip_with_member(member_name: str, content: bytes, date_time=(2020, 1, 1, 0, 0, 0)) -> bytes:
    buf = io.BytesIO()
    info = zipfile.ZipInfo(member_name, date_time=date_time)
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr(info, content)
    return buf.getvalue()


class DbBackupNewerGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old_bot_dir = db_backup.BOT_DIR
        db_backup.BOT_DIR = self.tmp.name

    def tearDown(self):
        db_backup.BOT_DIR = self._old_bot_dir
        self.tmp.cleanup()

    def test_newer_local_db_not_overwritten(self):
        """A healthy local DB newer than the backup member must win."""
        rel = os.path.join("db", "users.db")
        target = os.path.join(self.tmp.name, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        local = _make_db_bytes()
        with open(target, "wb") as f:
            f.write(local)
        # Backup member is OLD (2020); local mtime is now.
        archive = _zip_with_member("db/users.db", _make_db_bytes(),
                                   date_time=(2020, 1, 1, 0, 0, 0))
        result = db_backup._extract_validated(archive)
        self.assertEqual(result["restored"], 0)
        self.assertEqual(result.get("skipped_newer"), 1)
        with open(target, "rb") as f:
            self.assertEqual(f.read(), local)  # untouched

    def test_missing_local_db_restored(self):
        archive = _zip_with_member("db/fresh.db", _make_db_bytes(),
                                   date_time=(2020, 1, 1, 0, 0, 0))
        result = db_backup._extract_validated(archive)
        self.assertEqual(result["restored"], 1)
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "db", "fresh.db")))

    def test_single_file_recovery_overwrites_even_if_newer(self):
        """Single-file recovery targets a quarantined/missing path; the
        newer-guard is scoped to full restores only."""
        rel = os.path.join("db", "bad.db")
        target = os.path.join(self.tmp.name, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        # Target exists but this is an explicit single-file recovery.
        archive = _zip_with_member("db/bad.db", _make_db_bytes(),
                                   date_time=(2020, 1, 1, 0, 0, 0))
        result = db_backup._extract_validated(archive, only_file="bad.db")
        self.assertEqual(result["restored"], 1)
        self.assertTrue(os.path.exists(target))

    def test_corrupt_archive_member_untouched(self):
        target = os.path.join(self.tmp.name, "db", "keep.db")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        local = _make_db_bytes()
        with open(target, "wb") as f:
            f.write(local)
        # Staged file is not valid SQLite -> restore aborts before replace.
        archive = _zip_with_member("db/keep.db", b"not a sqlite database at all",
                                   date_time=(2035, 1, 1, 0, 0, 0))
        result = db_backup._extract_validated(archive)
        self.assertEqual(result["restored"], 0)
        with open(target, "rb") as f:
            self.assertEqual(f.read(), local)


if __name__ == "__main__":
    unittest.main()
