from pathlib import Path
import tempfile
import unittest

from pm_btc.local_runtime import component_specs, local_status, validate_local_runtime
from pm_btc.storage import SQLiteStore


class LocalRuntimeTests(unittest.TestCase):
    def test_research_stack_has_no_paper_or_live_execution_component(self) -> None:
        specs = component_specs(Path.cwd(), "data/live.sqlite3")
        names = {spec.name for spec in specs}
        self.assertIn("polymarket-books", names)
        self.assertIn("chainlink-rtds", names)
        self.assertIn("research", names)
        self.assertIn("api", names)
        self.assertIn("web", names)
        self.assertNotIn("paper", names)
        self.assertNotIn("live", names)

    def test_component_database_path_is_absolute(self) -> None:
        root = Path.cwd()
        specs = component_specs(root, "data/live.sqlite3")
        books = next(spec for spec in specs if spec.name == "polymarket-books")
        database = books.command[books.command.index("--database") + 1]
        self.assertEqual(Path(database), (root / "data/live.sqlite3").resolve())

    def test_status_is_not_started_without_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            status = local_status(Path(directory))
        self.assertEqual(status["status"], "NOT_STARTED")

    def test_validation_reports_missing_project_parts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            errors = validate_local_runtime(Path(directory))
        self.assertIn("data directory missing", errors)
        self.assertIn("web/package.json missing", errors)

    def test_store_waits_for_short_lived_writer_contention(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = SQLiteStore(str(Path(directory) / "busy.sqlite3"))
            try:
                timeout_ms = store.connection.execute("PRAGMA busy_timeout").fetchone()[0]
            finally:
                store.close()
        self.assertEqual(timeout_ms, 30_000)


if __name__ == "__main__":
    unittest.main()
