import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "11_scripts" / "homecontrol_system_test.py"


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


def test_overall_status_allows_explicit_live_stress_guard_as_expected_skip():
    runner = load_runner()
    result = runner.Result("Live stress/resources", "production workload guard", runner.BLOCKED, "d", "e", "not executed", 0)
    assert runner.overall_status([result]) == "PASS_WITH_EXPECTED_SKIPS"


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


def test_live_matrix_checks_registered_module_to_hcm_listener(monkeypatch):
    runner = load_runner()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"modules":[{"hostname":"lab1","ip_address":"192.168.20.36","online":true}]}'

    def fake_urlopen(request, timeout):
        assert request.full_url == "http://192.168.20.27:8080/api/v1/modules"
        assert request.headers["Authorization"] == "Bearer test-token"
        assert timeout == 5
        return Response()

    class Socket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_connect(address, timeout):
        assert address == ("192.168.20.27", 6501)
        assert timeout == 3
        return Socket()

    monkeypatch.setenv("HC_SYSTEM_TEST_HCM_URL", "http://192.168.20.27:8080")
    monkeypatch.setenv("HC_SYSTEM_TEST_HCM_TOKEN", "test-token")
    monkeypatch.setattr(runner.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(runner.socket, "create_connection", fake_connect)
    coord = runner.Coordinator(deadline=runner.time.monotonic() + 10, run_id="matrix", report_dir=Path("/tmp"))

    runner.run_live_communications(coord, skip_remote=False)

    assert coord.results[-1].status == runner.PASS
    assert coord.communication_matrix == [{
        "source": "lab1",
        "destination": "hcm",
        "protocol": "tls-tcp",
        "port": 6501,
        "expected": True,
        "registered": True,
        "online": True,
        "address": "192.168.20.27",
        "coverage": "live_registry",
        "authentication": "not_probed",
        "note": "module initiates authenticated control session to HCM",
        "actual": "PASS",
        "latency_ms": None,
        "error": None,
    }]
