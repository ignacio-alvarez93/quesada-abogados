"""Contract for the independent Document Viewer CI workflow (WO-DV22A); reads files only."""
import ast
from pathlib import Path
import re
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
WORKFLOW_PATH = WORKFLOWS / "document-viewer-ci.yml"
GATE_STEP_NAME = "Document viewer regression and CI contract without skipped tests"
SUITES = (
    "scripts.tests.test_document_viewer_foundation",
    "scripts.tests.test_document_viewer_cache",
    "scripts.tests.test_document_viewer_cancellation",
    "scripts.tests.test_document_viewer_stress",
    "scripts.tests.test_document_viewer_pdf_toolbar",
    "scripts.tests.test_document_viewer_runtime_scroll",
    "scripts.tests.test_document_viewer_ci_contract",
)
CORE_SOURCES = (
    "backend/services/document_viewer_service.py",
    "backend/services/document_preview_session.py",
    "frontend/components/document_viewer_modal.py",
)
PDF_ADAPTER = "frontend/components/pdf_tools_toolbar_adapter.py"
CONSUMER_VIEWS = (
    "frontend/views/expedients_view.py",
    "frontend/views/document_inbox_view.py",
    "frontend/views/client_detail_view.py",
)
TRIGGER_PATHS = CORE_SOURCES + (PDF_ADAPTER,) + CONSUMER_VIEWS + (
    "scripts/tests/test_document_viewer_*.py",
    "requirements.txt",
    ".github/workflows/document-viewer-ci.yml",
)
PROTECTED_WORKFLOWS = ("fabric-ci.yml", "fabric-p0-regression.yml", "fcp11-control-plane.yml", "fcp12-self-dogfood.yml")
VIEWER_FRONTEND = ("frontend/components/document_viewer_modal.py", PDF_ADAPTER)
DB_MODULES = ("sqlite3", "database", "sqlalchemy", "psycopg2", "pyodbc", "pymysql")


def read(path):
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def trigger_block(workflow, event):
    match = re.search(rf"(?ms)^  {event}:\n(.*?)(?=^  \S|^\S)", workflow)
    return match.group(1) if match else ""


def gate_command(workflow):
    match = re.search(rf"(?m)^      - name: {re.escape(GATE_STEP_NAME)}\n        run: \|\n          (.+)$", workflow)
    return match.group(1) if match else ""


def imported_modules(path):
    modules = set()
    for node in ast.walk(ast.parse(read(path))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def is_db_module(name):
    return any(name == db or name.startswith(db + ".") for db in DB_MODULES)


class DocumentViewerCiContractTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(WORKFLOW_PATH.is_file(), WORKFLOW_PATH)
        self.workflow = read(WORKFLOW_PATH)

    def test_workflow_runs_on_windows_python_311_with_read_only_permissions(self):
        self.assertRegex(self.workflow, r"(?m)^name: Document Viewer CI$")
        self.assertRegex(self.workflow, r"(?m)^  pull_request:\n    branches: \[develop, main\]$")
        self.assertRegex(self.workflow, r"(?m)^  push:\n    branches: \[develop\]$")
        for event in ("pull_request", "push"):
            block = trigger_block(self.workflow, event)
            for path in TRIGGER_PATHS:
                self.assertIn(f'      - "{path}"\n', block, (event, path))
        self.assertRegex(self.workflow, r"(?m)^permissions:\n  contents: read\n\n")
        self.assertNotRegex(self.workflow, r"(?i):\s*write\b")
        self.assertEqual(self.workflow.count("runs-on:"), 1)
        self.assertRegex(self.workflow, r"(?m)^    runs-on: windows-latest$")
        self.assertIn("uses: actions/checkout@v4\n        with:\n          persist-credentials: false\n", self.workflow)
        self.assertIn('uses: actions/setup-python@v5\n        with:\n          python-version: "3.11"\n', self.workflow)
        self.assertIn("python -m pip install --disable-pip-version-check -r requirements.txt", self.workflow)

    def test_seven_suites_appear_exactly_once_behind_a_strict_gate(self):
        for module in SUITES:
            self.assertEqual(self.workflow.count(f"'{module}'"), 1, module)
            self.assertTrue((REPO_ROOT / (module.replace(".", "/") + ".py")).is_file(), module)
        listed = re.findall(r"scripts\.tests\.test_document_viewer_\w+", self.workflow)
        self.assertEqual(tuple(listed), SUITES)
        command = gate_command(self.workflow)
        self.assertTrue(command.startswith('python -c "import sys,time,unittest;'), command)
        for fragment in ("r.wasSuccessful()", "r.testsRun == sum(c)", "r.testsRun >= 71", "len(c) == len(m)",
                         "all(x >= y for x, y in zip(c, m))", "not r.skipped", "not r.expectedFailures",
                         "not r.unexpectedSuccesses", "else 2)\""):
            self.assertIn(fragment, command)
        minimums = re.search(r"m=\(([\d,]+)\)", command)
        self.assertIsNotNone(minimums)
        self.assertEqual(len(minimums.group(1).split(",")), len(SUITES))
        self.assertGreaterEqual(sum(int(x) for x in minimums.group(1).split(",")), 71)
        for forbidden in ("|| true", "continue-on-error", "always()", "exit 0", "-k ", "skipTest"):
            self.assertNotIn(forbidden, self.workflow)

    def test_viewer_sources_and_tests_are_compiled_before_the_gate(self):
        compile_line = next(line for line in self.workflow.splitlines() if "python -m py_compile" in line)
        targets = compile_line.split("python -m py_compile", 1)[1].split()
        for path in CORE_SOURCES + (PDF_ADAPTER,) + CONSUMER_VIEWS:
            self.assertIn(path, targets)
        for module in SUITES:
            self.assertIn(module.replace(".", "/") + ".py", targets)
        for path in targets:
            self.assertTrue((REPO_ROOT / path).is_file(), path)
        self.assertLess(self.workflow.index("python -m py_compile"), self.workflow.index(GATE_STEP_NAME))

    def test_protected_fabric_workflows_do_not_host_the_viewer_gate(self):
        for name in PROTECTED_WORKFLOWS:
            text = read(WORKFLOWS / name)
            self.assertNotIn("document_viewer", text, name)
            self.assertNotIn("Document Viewer", text, name)
            self.assertNotIn(name, self.workflow)
        self.assertEqual(read(WORKFLOWS / "fabric-ci.yml").splitlines()[0], "name: Fabric CI")
        self.assertEqual(read(WORKFLOWS / "fabric-p0-regression.yml").splitlines()[0], "name: Fabric P0 Hardening CI")

    def test_ci_locks_legacy_flet_and_canonical_windows_temp(self):
        # Pre-1.0 Flet retains the CRM's existing button and padding APIs.
        self.assertIn('python -m pip install --disable-pip-version-check -r requirements.txt \"flet==0.82.2\"', self.workflow)
        self.assertNotIn('      TEMP: ${{ runner.temp }}\n', self.workflow)
        self.assertNotIn('      TMP: ${{ runner.temp }}\n', self.workflow)
        self.assertIn('      - name: Normalize Windows temp directory\n', self.workflow)
        self.assertIn('          "TEMP=$env:RUNNER_TEMP" >> $env:GITHUB_ENV\n', self.workflow)
        self.assertIn('          "TMP=$env:RUNNER_TEMP" >> $env:GITHUB_ENV\n', self.workflow)
        self.assertLess(
            self.workflow.index('      - name: Normalize Windows temp directory'),
            self.workflow.index('      - name: Verify viewer runtime dependencies'),
        )
        self.assertIn("version('flet') == '0.82.2'", self.workflow)
        self.assertIn("'NONCANONICAL_TEMP'", self.workflow)

    def test_viewer_frontend_has_no_direct_or_first_hop_db_dependency(self):
        for relative in VIEWER_FRONTEND:
            modules = imported_modules(REPO_ROOT / relative)
            self.assertEqual(sorted(m for m in modules if is_db_module(m)), [], relative)
            for module in sorted(m for m in modules if m.startswith("backend.")):
                target = REPO_ROOT / (module.replace(".", "/") + ".py")
                if target.is_file():
                    hop = imported_modules(target)
                    self.assertEqual(sorted(m for m in hop if is_db_module(m)), [], (relative, module))


if __name__ == "__main__":
    unittest.main()
