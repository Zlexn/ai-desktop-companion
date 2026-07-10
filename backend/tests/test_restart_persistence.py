import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_health(base_url: str) -> None:
    deadline = time.monotonic() + 10
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base_url}/health", timeout=0.5, trust_env=False)
            if response.status_code == 200:
                return
        except Exception as exc:  # pragma: no cover - diagnostic only
            last_error = exc
        time.sleep(0.1)
    raise AssertionError(f"Backend did not become healthy: {last_error}")


def _start_backend(database_url: str, port: int) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--app-dir",
            "backend",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-access-log",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env={
            **dict(__import__("os").environ),
            "APP_ENV": "test",
            "DATABASE_URL": database_url,
            "LLM_PROVIDER": "fake",
            "LLM_MODEL": "test-model",
            "FAKE_PROVIDER_MODE": "ok",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _stop_backend(process: subprocess.Popen[str]) -> str:
    process.terminate()
    try:
        stdout, _ = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, _ = process.communicate(timeout=10)
    return stdout or ""


def test_sqlite_messages_persist_across_backend_process_restart(tmp_path: Path) -> None:
    database_path = tmp_path / "restart-persistence.db"
    database_url = f"sqlite:///{database_path}"
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"

    first_process = _start_backend(database_url, port)
    try:
        _wait_for_health(base_url)
        with httpx.Client(base_url=base_url, timeout=5.0, trust_env=False) as client:
            session = client.post("/api/sessions", json={"title": "重启验证"}).json()
            session_id = session["id"]
            first = client.post(f"/api/sessions/{session_id}/messages", json={"content": "第一轮"})
            second = client.post(f"/api/sessions/{session_id}/messages", json={"content": "第二轮"})
            assert first.status_code == 200
            assert second.status_code == 200
    finally:
        first_output = _stop_backend(first_process)

    second_process = _start_backend(database_url, port)
    try:
        _wait_for_health(base_url)
        with httpx.Client(base_url=base_url, timeout=5.0, trust_env=False) as client:
            messages_response = client.get(f"/api/sessions/{session_id}/messages")
            assert messages_response.status_code == 200
            messages = messages_response.json()
    finally:
        second_output = _stop_backend(second_process)

    assert [message["role"] for message in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[0]["content"] == "第一轮"
    assert messages[1]["content"].startswith("我听见了：第一轮")
    assert messages[2]["content"] == "第二轮"
    assert messages[3]["content"].startswith("我听见了：第二轮")
    assert database_path.exists()
    assert "Traceback" not in first_output
    assert "Traceback" not in second_output
