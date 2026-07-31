import unittest
from unittest.mock import patch

from scripts.runners import (
    box_watch_scan_runner as runner,
)


class BoxWatchSemanticRunnerTest(
    unittest.TestCase
):
    def job(self):
        return {
            "id": 50,
            "route_ids": [1],
        }

    def routes(self):
        return [
            {
                "id": 1,
                "ruta_box": "TEST",
            }
        ]

    def results(self):
        return [
            {
                "run_id": 10,
                "scan_mode": "NORMAL",
                "estado": "OK",
                "total_archivos": 2,
                "total_carpetas": 1,
            }
        ]

    @patch.object(
        runner,
        "configure_sqlite_runtime",
    )
    @patch.object(
        runner.box_watch_job_service,
        "mark_job_running",
    )
    @patch.object(
        runner.box_watch_job_service,
        "finish_job",
    )
    @patch.object(
        runner.box_watch_job_service,
        "get_job",
    )
    @patch.object(
        runner.box_watch_service,
        "get_configured_box_routes",
    )
    @patch.object(
        runner.box_watch_service,
        "scan_configured_routes",
    )
    @patch.object(
        runner.document_semantic_scan_service,
        "process_box_scan_results",
    )
    def test_runner_attaches_semantic_summary(
        self,
        process_semantic,
        scan_routes,
        get_routes,
        get_job,
        finish_job,
        mark_running,
        configure_runtime,
    ):
        get_job.return_value = self.job()
        get_routes.return_value = self.routes()
        scan_routes.return_value = self.results()
        process_semantic.return_value = {
            "enabled": True,
            "scan_runs_detected": 1,
            "scan_runs_processed": 1,
            "processed": 1,
            "errors": 0,
        }

        exit_code = runner.run_job(50)

        self.assertEqual(exit_code, 0)

        process_semantic.assert_called_once()
        call = process_semantic.call_args

        self.assertEqual(
            call.kwargs[
                "source_scan_job_id"
            ],
            50,
        )

        stored_results = (
            finish_job.call_args.args[1]
        )

        self.assertEqual(
            len(stored_results),
            1,
        )
        self.assertIn(
            "semantic_processing",
            stored_results[0],
        )
        self.assertEqual(
            stored_results[0][
                "semantic_processing"
            ]["processed"],
            1,
        )

    @patch.object(
        runner,
        "configure_sqlite_runtime",
    )
    @patch.object(
        runner.box_watch_job_service,
        "mark_job_running",
    )
    @patch.object(
        runner.box_watch_job_service,
        "finish_job",
    )
    @patch.object(
        runner.box_watch_job_service,
        "get_job",
    )
    @patch.object(
        runner.box_watch_service,
        "get_configured_box_routes",
    )
    @patch.object(
        runner.box_watch_service,
        "scan_configured_routes",
    )
    @patch.object(
        runner.document_semantic_scan_service,
        "process_box_scan_results",
    )
    def test_semantic_failure_does_not_fail_box_job(
        self,
        process_semantic,
        scan_routes,
        get_routes,
        get_job,
        finish_job,
        mark_running,
        configure_runtime,
    ):
        get_job.return_value = self.job()
        get_routes.return_value = self.routes()
        scan_routes.return_value = self.results()
        process_semantic.side_effect = (
            RuntimeError(
                "Fallo semántico simulado"
            )
        )

        exit_code = runner.run_job(50)

        self.assertEqual(exit_code, 0)
        finish_job.assert_called_once()

        stored_results = (
            finish_job.call_args.args[1]
        )
        semantic = stored_results[0][
            "semantic_processing"
        ]

        self.assertEqual(
            semantic["errors"],
            1,
        )
        self.assertIn(
            "Fallo semántico simulado",
            semantic["runner_error"],
        )

    @patch.object(
        runner,
        "configure_sqlite_runtime",
    )
    @patch.object(
        runner.box_watch_job_service,
        "mark_job_running",
    )
    @patch.object(
        runner.box_watch_job_service,
        "finish_job",
    )
    @patch.object(
        runner.box_watch_job_service,
        "get_job",
    )
    @patch.object(
        runner.box_watch_service,
        "get_configured_box_routes",
    )
    @patch.object(
        runner.box_watch_service,
        "scan_configured_routes",
    )
    @patch.object(
        runner.document_semantic_scan_service,
        "process_box_scan_results",
    )
    def test_semantic_errors_do_not_change_box_error_count(
        self,
        process_semantic,
        scan_routes,
        get_routes,
        get_job,
        finish_job,
        mark_running,
        configure_runtime,
    ):
        get_job.return_value = self.job()
        get_routes.return_value = self.routes()
        scan_routes.return_value = self.results()
        process_semantic.return_value = {
            "enabled": True,
            "errors": 5,
        }

        exit_code = runner.run_job(50)

        self.assertEqual(exit_code, 0)

        stored_results = (
            finish_job.call_args.args[1]
        )

        box_errors = sum(
            1
            for result in stored_results
            if str(
                result.get("estado") or ""
            ).upper() == "ERROR"
            or str(
                result.get("scan_mode") or ""
            ).upper() == "ERROR"
        )

        self.assertEqual(box_errors, 0)


if __name__ == "__main__":
    unittest.main()
