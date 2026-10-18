import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "10_scripts" / "homecontrol_system_test.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("homecontrol_system_test_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_fixture(tmp_path, *extra):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--fixture", "--report-dir", str(tmp_path), "--lock-file", str(tmp_path / ".lock"), *extra],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_fixture_generates_all_reports_and_keeps_safety_incomplete(tmp_path):
    result = run_fixture(tmp_path)
    assert result.returncode == 2
    summary = json.loads(result.stdout)
    assert summary["overall"] == "INCOMPLETE"
    report_dir = Path(summary["report_dir"])
    assert report_dir.parent == tmp_path
    assert report_dir.name.startswith("hc-system-")
    for name in ("report.html", "report.json", "report.txt", "detailed-results.json", "test-manifest.json", "sanitized-diagnostics.json"):
        assert (report_dir / name).is_file()
    report = json.loads((report_dir / "report.json").read_text())
    assert report["safety"]["physical_output_writes"] is False
    assert any(item["name"] == "isolated production-shaped driver suite" and item["status"] == "PASS" for item in report["results"])
    assert len(report["communications_matrix"]) == 4
    assert any(item["subsystem"] == "HCM stress" and item["status"] == "PASS" for item in report["results"])
    assert report["abort_conditions"] == []
    assert "222222" not in (report_dir / "report.json").read_text()


def test_fixture_injected_failure_is_nonzero_and_reported(tmp_path):
    result = run_fixture(tmp_path, "--inject-failure")
    assert result.returncode == 2
    summary = json.loads(result.stdout)
    report = json.loads((Path(summary["report_dir"]) / "report.json").read_text())
    assert report["overall"] == "FAIL"
    assert any(item["status"] == "FAIL" and item["name"] == "deliberate fixture failure" for item in report["results"])


def test_run_lock_rejects_second_run(tmp_path):
    runner = load_runner()
    with runner.run_lock(tmp_path / "lock"):
        with pytest.raises(RuntimeError, match="already running"):
            with runner.run_lock(tmp_path / "lock"):
                pass


def test_overall_status_does_not_count_skip_as_pass():
    runner = load_runner()
    result = runner.Result("x", "y", runner.SKIP, "d", "e", "a", 0)
    assert runner.overall_status([result]) == "INCOMPLETE"


def test_isolated_supervision_failure_aborts_workload_and_returns_nonzero(tmp_path):
    result = run_fixture(tmp_path, "--inject-supervision-failure")
    assert result.returncode == 2
    summary = json.loads(result.stdout)
    report = json.loads((Path(summary["report_dir"]) / "report.json").read_text())
    assert report["overall"] == "FAIL"
    assert "isolated Conflict ACK freshness failure" in report["abort_conditions"]
    assert any(item["subsystem"] == "HCM stress" and item["status"] == "FAIL" for item in report["results"])


def test_full_skip_remote_blocks_scenarios_before_any_workload(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--full", "--skip-remote", "--stress-duration", "1", "--timeout", "61", "--report-dir", str(tmp_path), "--lock-file", str(tmp_path / ".lock")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    summary = json.loads(result.stdout)
    report = json.loads((Path(summary["report_dir"]) / "report.json").read_text())
    assert any(item["name"] == "independent output inhibition gate" and item["status"] == "BLOCKED" for item in report["results"]) is False
    assert any(item["name"] == "bounded isolated read-only workload" and item["status"] == "BLOCKED" for item in report["results"])
