"""Automated tests for utils.dbhealth (temp directories, real sqlite files)."""

import os
import sys
import json
import time
import sqlite3
import tempfile
import shutil
import asyncio
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import dbhealth


def _make_db(path, data=True):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, v TEXT)")
    if data:
        conn.execute("INSERT INTO t (v) VALUES ('hello')")
    conn.commit()
    conn.close()


class DbHealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self._old = (dbhealth.BOT_DIR, dbhealth.DB_DIR, dbhealth.JSONDB_DIR,
                     dbhealth.SCHEMA_VERSION_FILE, dbhealth.MIGRATIONS)
        dbhealth.BOT_DIR = self.root
        dbhealth.DB_DIR = os.path.join(self.root, "db")
        dbhealth.JSONDB_DIR = os.path.join(self.root, "jsondb")
        dbhealth.SCHEMA_VERSION_FILE = os.path.join(dbhealth.DB_DIR, ".schema_version")
        dbhealth.MIGRATIONS = {}
        os.makedirs(dbhealth.DB_DIR, exist_ok=True)
        os.makedirs(dbhealth.JSONDB_DIR, exist_ok=True)

    def tearDown(self):
        (dbhealth.BOT_DIR, dbhealth.DB_DIR, dbhealth.JSONDB_DIR,
         dbhealth.SCHEMA_VERSION_FILE, dbhealth.MIGRATIONS) = self._old
        self.tmp.cleanup()

    # 1. Missing databases on first startup: healthy, zero files
    def test_missing_dbs_first_startup(self):
        health = asyncio.run(dbhealth.validate_all())
        self.assertEqual(health["status"], "healthy")
        self.assertEqual(health["databases"], 0)

    # 2. Valid database passes
    def test_valid_db_healthy(self):
        _make_db(os.path.join(dbhealth.DB_DIR, "good.db"))
        health = asyncio.run(dbhealth.validate_all())
        self.assertEqual(health["status"], "healthy")
        self.assertEqual(health["corrupt"], [])

    # 3. Corrupted database detected and quarantined (original preserved)
    def test_corrupt_db_quarantined(self):
        path = os.path.join(dbhealth.DB_DIR, "bad.db")
        with open(path, "wb") as f:
            f.write(b"this is definitely not a sqlite database" * 10)
        health = asyncio.run(dbhealth.validate_all())
        self.assertEqual(health["status"], "degraded")
        self.assertEqual(len(health["corrupt"]), 1)
        # Quarantined copy preserves the bytes; the live path is freed.
        self.assertFalse(os.path.exists(path))
        quarantined = [n for n in os.listdir(dbhealth.DB_DIR) if ".corrupt-" in n]
        self.assertEqual(len(quarantined), 1)
        with open(os.path.join(dbhealth.DB_DIR, quarantined[0]), "rb") as f:
            self.assertIn(b"definitely not", f.read())

    # 4. Corrupt DB recovered via restore callback, then validated
    def test_corrupt_db_restored_from_backup(self):
        path = os.path.join(dbhealth.DB_DIR, "recoverable.db")
        with open(path, "wb") as f:
            f.write(b"garbage" * 100)

        async def fake_restore(filename):
            _make_db(path)  # "restore" a valid file
            return True

        health = asyncio.run(dbhealth.validate_all(restore_callback=fake_restore))
        self.assertEqual(health["status"], "healthy")
        self.assertEqual(len(health["repaired"]), 1)
        ok, _ = dbhealth.quick_check_file(path)
        self.assertTrue(ok)

    # 5. Failed restore leaves degraded state, never an empty healthy claim
    def test_failed_restore_degraded(self):
        path = os.path.join(dbhealth.DB_DIR, "unrecoverable.db")
        with open(path, "wb") as f:
            f.write(b"garbage" * 100)

        async def failing_restore(filename):
            return False

        health = asyncio.run(dbhealth.validate_all(restore_callback=failing_restore))
        self.assertEqual(health["status"], "degraded")

    # 6. Invalid JSON detected but NOT deleted
    def test_invalid_json_preserved(self):
        path = os.path.join(dbhealth.JSONDB_DIR, "cfg.json")
        with open(path, "w") as f:
            f.write("{not json")
        health = asyncio.run(dbhealth.validate_all())
        self.assertEqual(health["status"], "degraded")
        self.assertTrue(os.path.exists(path))  # preserved for inspection

    # 7. Migration applies once and bumps version
    def test_migration_forward_only(self):
        db_path = os.path.join(dbhealth.DB_DIR, "m.db")
        _make_db(db_path, data=False)

        def migration(conn):
            conn.execute("CREATE TABLE IF NOT EXISTS extra (x INTEGER)")

        dbhealth.MIGRATIONS = {1: [("m.db", migration)]}
        applied = asyncio.run(dbhealth.apply_migrations())
        self.assertEqual(applied, ["v1:m.db"])
        self.assertEqual(dbhealth.current_schema_version(), 1)
        conn = sqlite3.connect(db_path)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(extra)")]
        conn.close()
        self.assertIn("x", cols)
        # Re-run: idempotent, no second application
        applied2 = asyncio.run(dbhealth.apply_migrations())
        self.assertEqual(applied2, [])

    # 8. Failed migration does not advance the version
    def test_failed_migration_version_not_advanced(self):
        db_path = os.path.join(dbhealth.DB_DIR, "m2.db")
        _make_db(db_path, data=False)

        def bad_migration(conn):
            raise RuntimeError("boom")

        dbhealth.MIGRATIONS = {1: [("m2.db", bad_migration)]}
        applied = asyncio.run(dbhealth.apply_migrations())
        self.assertEqual(applied, [])
        self.assertEqual(dbhealth.current_schema_version(), 0)

    # 9. Pre-migration copy is made
    def test_premigration_copy(self):
        db_path = os.path.join(dbhealth.DB_DIR, "m3.db")
        _make_db(db_path)
        dbhealth.MIGRATIONS = {1: [("m3.db", lambda c: None)]}
        asyncio.run(dbhealth.apply_migrations())
        copies = [n for n in os.listdir(dbhealth.DB_DIR) if ".premigration-" in n]
        self.assertEqual(len(copies), 1)

    # 10. Temp cleanup removes expired files, keeps recent ones
    def test_cleanup_temp_files(self):
        old_tmp = os.path.join(dbhealth.DB_DIR, "x.tmp")
        with open(old_tmp, "w") as f:
            f.write("junk")
        ancient = time.time() - 100 * 3600
        os.utime(old_tmp, (ancient, ancient))
        fresh_tmp = os.path.join(dbhealth.DB_DIR, "y.tmp")
        with open(fresh_tmp, "w") as f:
            f.write("keep")
        removed = asyncio.run(dbhealth.cleanup_temp_files(max_age_hours=48))
        self.assertGreaterEqual(removed, 1)
        self.assertFalse(os.path.exists(old_tmp))
        self.assertTrue(os.path.exists(fresh_tmp))

    # 11. Resettable set is empty: validate_all never deletes valid data
    def test_no_valid_db_deleted(self):
        path = os.path.join(dbhealth.DB_DIR, "precious.db")
        _make_db(path)
        asyncio.run(dbhealth.validate_all())
        self.assertTrue(os.path.exists(path))
        self.assertEqual(dbhealth.RESETTABLE_FILES, frozenset())

    # 12. Database integrity during REST reconnect cycles: repeated
    # validations while the edge ban is active never touch healthy DBs.
    def test_integrity_survives_reconnect_cycles(self):
        from utils import cloudbreaker
        path = os.path.join(dbhealth.DB_DIR, "stable.db")
        _make_db(path)
        cloudbreaker._reset_for_tests()
        try:
            cloudbreaker.report_ban(3076)
            for _ in range(3):
                health = asyncio.run(dbhealth.validate_all())
                self.assertEqual(health["status"], "healthy")
                self.assertTrue(os.path.exists(path))
            ok, _ = dbhealth.quick_check_file(path)
            self.assertTrue(ok)
        finally:
            cloudbreaker._reset_for_tests()


if __name__ == "__main__":
    unittest.main()
