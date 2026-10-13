import hashlib
import inspect
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.repositories.sqlite_trend_intelligence_repository import (
    ReadOnlyRepositoryError,
    ReadOnlyStoreUnavailable,
    SQLiteTrendIntelligenceRepository,
)
from backend.trend_intelligence.models import TrendDomain
from backend.trend_intelligence.service import TrendIntelligenceService
from database.connection import get_readonly_connection


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ReadOnlyModeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "trends.db"

    def tearDown(self):
        self.tmp.cleanup()

    def _files(self):
        return sorted(p.name for p in self.dir.iterdir())

    def _populate(self):
        service = TrendIntelligenceService(SQLiteTrendIntelligenceRepository(self.db))
        service.ensure_schema()
        service.create_domain(code="GENERIC_DOMAIN", name="Generic Domain")
        service.create_topic(topic_key="TOPIC_A", name="Topic A", domain_codes=("GENERIC_DOMAIN",))

    def test_default_construction_unchanged_and_writable(self):
        signature = inspect.signature(SQLiteTrendIntelligenceRepository)
        self.assertEqual(list(signature.parameters), ["db_path", "readonly"])
        self.assertIs(signature.parameters["readonly"].default, False)
        self.assertEqual(signature.parameters["readonly"].kind, inspect.Parameter.KEYWORD_ONLY)
        repository = SQLiteTrendIntelligenceRepository(self.db)
        self.assertFalse(repository.readonly)
        self._populate()
        self.assertEqual(repository.get_domain_by_code("GENERIC_DOMAIN").name, "Generic Domain")
        with repository.window_transaction():
            repository.save_domain(TrendDomain(id=None, code="SECOND", name="Second"))
        self.assertIsNotNone(repository.get_domain_by_code("SECOND"))

    def test_default_mode_still_creates_database_as_before(self):
        # Backward compatibility: existing RW consumers keep create-if-missing.
        SQLiteTrendIntelligenceRepository(self.db).ensure_schema()
        self.assertTrue(self.db.exists())

    def test_readonly_absent_file_is_never_created(self):
        repository = SQLiteTrendIntelligenceRepository(self.db, readonly=True)
        for read in (lambda: repository.get_domain_by_code("GENERIC_DOMAIN"),
                     lambda: repository.missing_tables(("ti_domains",))):
            with self.assertRaises(ReadOnlyStoreUnavailable):
                read()
        self.assertEqual(self._files(), [])

    def test_readonly_file_removed_after_construction_is_not_recreated(self):
        self._populate()
        repository = SQLiteTrendIntelligenceRepository(self.db, readonly=True)
        self.assertIsNotNone(repository.get_domain_by_code("GENERIC_DOMAIN"))
        self.db.unlink()
        with self.assertRaises(ReadOnlyStoreUnavailable):
            repository.get_domain_by_code("GENERIC_DOMAIN")
        self.assertEqual(self._files(), [])

    def test_readonly_reads_match_default_reads(self):
        self._populate()
        rw = SQLiteTrendIntelligenceRepository(self.db)
        ro = SQLiteTrendIntelligenceRepository(self.db, readonly=True)
        domain = rw.get_domain_by_code("GENERIC_DOMAIN")
        self.assertEqual(ro.get_domain_by_code("GENERIC_DOMAIN"), domain)
        self.assertEqual(ro.list_topics_for_domain(domain.id), rw.list_topics_for_domain(domain.id))
        self.assertEqual(ro.list_domain_trend_snapshots(domain.id), [])
        self.assertEqual(ro.missing_tables(("ti_domains", "ti_trend_snapshots")), ())

    def test_readonly_rejects_writes_ddl_and_schema_without_touching_file(self):
        self._populate()
        before = _digest(self.db)
        repository = SQLiteTrendIntelligenceRepository(self.db, readonly=True)
        with self.assertRaises(sqlite3.OperationalError):
            repository.save_domain(TrendDomain(id=None, code="SECOND", name="Second"))
        with self.assertRaises(ReadOnlyRepositoryError):
            repository.ensure_schema()
        with self.assertRaises(ReadOnlyRepositoryError):
            with repository.window_transaction():
                pass
        with self.assertRaises(sqlite3.OperationalError):
            with repository._connection() as conn:
                conn.execute("CREATE TABLE intruder (id INTEGER)")
        self.assertEqual(_digest(self.db), before)
        self.assertIsNone(SQLiteTrendIntelligenceRepository(self.db).get_domain_by_code("SECOND"))

    def test_readonly_missing_table_stays_missing(self):
        conn = sqlite3.connect(str(self.db))
        conn.execute("CREATE TABLE unrelated (id INTEGER)")
        conn.commit()
        conn.close()
        before = _digest(self.db)
        repository = SQLiteTrendIntelligenceRepository(self.db, readonly=True)
        self.assertEqual(repository.missing_tables(("ti_domains", "unrelated")), ("ti_domains",))
        with self.assertRaises(sqlite3.OperationalError):
            repository.get_domain_by_code("GENERIC_DOMAIN")
        self.assertEqual(_digest(self.db), before)
        self.assertEqual(repository.missing_tables(("ti_domains",)), ("ti_domains",))

    def test_readonly_connection_helper(self):
        with self.assertRaises(sqlite3.OperationalError):
            get_readonly_connection(self.db)
        self.assertEqual(self._files(), [])
        self._populate()
        conn = get_readonly_connection(self.db)
        try:
            self.assertEqual(conn.execute("PRAGMA query_only").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT code FROM ti_domains").fetchone()["code"], "GENERIC_DOMAIN")
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM ti_domains")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
