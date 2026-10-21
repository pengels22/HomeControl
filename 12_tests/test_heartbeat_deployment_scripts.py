import json
import os
import shutil
import sqlite3
import subprocess
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / "11_scripts/heartbeat_deployment_preflight.sh"
BACKUP = ROOT / "11_scripts/heartbeat_backup.sh"


def write_config(path: Path, *, auth_mode="none", secret_path=None):
    data = {
        "role": "conflict",
        "bind_address": "127.0.0.1",
        "advertise_ip": "127.0.0.1",
        "port": 6004,
        "identity_interface": "eth0",
        "registry_db": str(path.parent / "registry.sqlite3"),
        "heartbeat_auth_mode": auth_mode,
    }
    if secret_path is not None:
        data["heartbeat_auth_secret_file"] = str(secret_path)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))
    return data


def run_script(args, env):
    merged = os.environ.copy()
    merged.update(env)
    return subprocess.run(
        args,
        cwd=ROOT,
        env=merged,
        text=True,
        capture_output=True,
        check=False,
    )


def test_preflight_baseline_accepts_legacy_unauthenticated_config(tmp_path):
    config = tmp_path / "config.json"
    write_config(config, auth_mode="none")

    result = run_script(
        [str(PREFLIGHT), "baseline", "conflict"],
        {
            "HC_HEARTBEAT_CONFIG": str(config),
            "HC_HEARTBEAT_DB": str(tmp_path / "missing.sqlite3"),
        },
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "legacy unauthenticated config detected" in result.stdout
    assert "not deployment-approved" in result.stdout


def test_preflight_strict_rejects_legacy_unauthenticated_config(tmp_path):
    config = tmp_path / "config.json"
    template = tmp_path / "template.json"
    write_config(config, auth_mode="none")
    write_config(template, auth_mode="none")

    result = run_script(
        [str(PREFLIGHT), "strict", "conflict"],
        {
            "HC_HEARTBEAT_CONFIG": str(config),
            "HC_HEARTBEAT_TEMPLATE": str(template),
            "HC_HEARTBEAT_DB": str(tmp_path / "missing.sqlite3"),
        },
    )

    assert result.returncode != 0
    assert "requires heartbeat_auth_mode=hmac-sha256" in result.stderr


def test_preflight_strict_accepts_matching_hmac_config_with_protected_secret(tmp_path):
    secret = tmp_path / "heartbeat-auth.secret"
    secret.write_text("test-secret")
    secret.chmod(0o600)
    config = tmp_path / "config.json"
    template = tmp_path / "template.json"
    write_config(config, auth_mode="hmac-sha256", secret_path=secret)
    shutil.copyfile(config, template)

    result = run_script(
        [str(PREFLIGHT), "strict", "conflict"],
        {
            "HC_HEARTBEAT_CONFIG": str(config),
            "HC_HEARTBEAT_TEMPLATE": str(template),
            "HC_HEARTBEAT_DB": str(tmp_path / "missing.sqlite3"),
        },
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "strict config matches template" in result.stdout


def test_preflight_strict_rejects_group_readable_secret(tmp_path):
    secret = tmp_path / "heartbeat-auth.secret"
    secret.write_text("test-secret")
    secret.chmod(0o640)
    config = tmp_path / "config.json"
    template = tmp_path / "template.json"
    write_config(config, auth_mode="hmac-sha256", secret_path=secret)
    shutil.copyfile(config, template)

    result = run_script(
        [str(PREFLIGHT), "strict", "conflict"],
        {
            "HC_HEARTBEAT_CONFIG": str(config),
            "HC_HEARTBEAT_TEMPLATE": str(template),
            "HC_HEARTBEAT_DB": str(tmp_path / "missing.sqlite3"),
        },
    )

    assert result.returncode != 0
    assert "must not be group/world readable" in result.stderr


def test_online_backup_is_consistent_while_database_writes_are_active(tmp_path):
    config = tmp_path / "config.json"
    write_config(config, auth_mode="none")
    db = tmp_path / "registry.sqlite3"
    conn = sqlite3.connect(db, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE heartbeat_events(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, details TEXT NOT NULL)")
    conn.commit()
    stop = threading.Event()

    def writer():
        i = 0
        while not stop.is_set():
            with conn:
                conn.execute("INSERT INTO heartbeat_events(ts, details) VALUES(?, ?)", (i, "active-write"))
            i += 1
            time.sleep(0.001)

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        time.sleep(0.02)
        backup_dir = tmp_path / "backup"
        result = run_script(
            [str(BACKUP), "conflict"],
            {
                "HC_ALLOW_NONROOT": "1",
                "HC_HEARTBEAT_CONFIG": str(config),
                "HC_HEARTBEAT_DB": str(db),
                "HC_HEARTBEAT_BACKUP_DIR": str(backup_dir),
            },
        )
    finally:
        stop.set()
        thread.join(timeout=2)
        conn.close()

    assert result.returncode == 0, result.stderr + result.stdout
    backup_db = backup_dir / "registry.sqlite3"
    assert backup_db.exists()
    assert not (backup_dir / "registry.sqlite3-wal").exists()
    restored = sqlite3.connect(backup_db)
    try:
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        count = restored.execute("SELECT COUNT(*) FROM heartbeat_events").fetchone()[0]
    finally:
        restored.close()
    assert count > 0


def test_heartbeat_backup_refuses_existing_destination(tmp_path):
    config = tmp_path / "config.json"
    write_config(config, auth_mode="none")
    backup_dir = tmp_path / "backup"
    backup_dir.mkdir()

    result = run_script(
        [str(BACKUP), "conflict"],
        {
            "HC_ALLOW_NONROOT": "1",
            "HC_HEARTBEAT_CONFIG": str(config),
            "HC_HEARTBEAT_DB": str(tmp_path / "missing.sqlite3"),
            "HC_HEARTBEAT_BACKUP_DIR": str(backup_dir),
        },
    )

    assert result.returncode != 0
    assert "backup destination already exists" in result.stderr


def test_heartbeat_backup_preserves_absent_release_marker(tmp_path):
    config = tmp_path / "config.json"
    write_config(config, auth_mode="none")
    marker = tmp_path / "homecontrol-release"
    backup_dir = tmp_path / "backup"

    result = run_script(
        [str(BACKUP), "conflict"],
        {
            "HC_ALLOW_NONROOT": "1",
            "HC_HEARTBEAT_CONFIG": str(config),
            "HC_HEARTBEAT_DB": str(tmp_path / "missing.sqlite3"),
            "HC_HEARTBEAT_BACKUP_DIR": str(backup_dir),
            "HC_HEARTBEAT_RELEASE_MARKER": str(marker),
        },
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert (backup_dir / "homecontrol-release.absent").exists()
    assert not (backup_dir / "homecontrol-release").exists()


def test_heartbeat_backup_detects_incomplete_application_backup_when_required(tmp_path):
    config = tmp_path / "config.json"
    write_config(config, auth_mode="none")
    backup_dir = tmp_path / "backup"

    result = run_script(
        [str(BACKUP), "conflict"],
        {
            "HC_ALLOW_NONROOT": "1",
            "HC_REQUIRE_APP_BACKUP": "1",
            "HC_HEARTBEAT_CONFIG": str(config),
            "HC_HEARTBEAT_DB": str(tmp_path / "missing.sqlite3"),
            "HC_HEARTBEAT_BACKUP_DIR": str(backup_dir),
        },
    )

    assert result.returncode != 0
    assert "incomplete heartbeat application backup" in result.stderr
