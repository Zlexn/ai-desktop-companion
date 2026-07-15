from __future__ import annotations

import argparse
import os
import sqlite3
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app
from app.providers.base import LLMProvider

SKIPPED_EXIT_CODE = 2
_SYNTHETIC_FIXTURE = "虚构测试：最近考试压力较大，希望获得一些支持。"


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run an opt-in real DeepSeek Stage 4C smoke with synthetic data."
    )
    parser.add_argument("--database", type=Path)
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    return parser.parse_args(argv)


def _remove_database_files(database_path: Path) -> None:
    for path in (
        database_path,
        Path(f"{database_path}-wal"),
        Path(f"{database_path}-shm"),
    ):
        path.unlink(missing_ok=True)


def _analysis_tables_are_metadata_only(database_path: Path, key: str) -> bool:
    connection = sqlite3.connect(database_path)
    try:
        rows = {
            table: connection.execute(f"SELECT * FROM {table}").fetchall()
            for table in ("emotion_analysis_jobs", "emotion_analysis_audits")
        }
    finally:
        connection.close()
    serialized = repr(rows)
    return key not in serialized and _SYNTHETIC_FIXTURE not in serialized


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    emotion_provider_factory: Callable[[], LLMProvider] | None = None,
) -> int:
    args = _parse_args(argv)
    source_environment = os.environ if environ is None else environ
    key = source_environment.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        print("SKIPPED: DEEPSEEK_API_KEY is not set in this process environment")
        return SKIPPED_EXIT_CODE

    database_path = args.database or Path("test-results/stage4c-real-smoke.db")
    database_path = database_path.resolve()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    _remove_database_files(database_path)

    environment_updates = {
        "APP_ENV": "test",
        "DATABASE_URL": f"sqlite:///{database_path.as_posix()}",
        "LLM_PROVIDER": "fake",
        "LLM_MODEL": "stage4c-smoke-chat",
        "EMOTION_ANALYSIS_ENABLED": "true",
        "EMOTION_ANALYSIS_PROVIDER": "deepseek",
        "EMOTION_ANALYSIS_MODEL": args.model,
        "EMOTION_ANALYSIS_MAX_TOKENS": "384",
        "EMOTION_ANALYSIS_TIMEOUT_SECONDS": str(args.timeout_seconds),
        "EMOTION_ANALYSIS_MAX_RETRIES": "0",
        "DEEPSEEK_API_KEY": key,
    }
    original = {name: os.environ.get(name) for name in environment_updates}
    os.environ.update(environment_updates)
    get_settings.cache_clear()

    try:
        factory = emotion_provider_factory
        app = create_app(emotion_analysis_provider_factory=factory)
        with TestClient(app) as client:
            consent = client.put(
                "/api/emotion/analysis/consent",
                json={
                    "action": "grant",
                    "disclosure_version": "emotion-analysis-disclosure-v1",
                },
            )
            if consent.status_code != 200:
                print("BLOCKED: consent API did not succeed")
                return 1
            session_response = client.post(
                "/api/sessions",
                json={"title": "Stage 4C real smoke"},
            )
            if session_response.status_code not in {200, 201}:
                print("BLOCKED: session API did not succeed")
                return 1
            session_id = session_response.json()["id"]
            chat = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"content": _SYNTHETIC_FIXTURE},
            )
            if chat.status_code != 200:
                print("BLOCKED: chat API did not succeed")
                return 1

            deadline = time.monotonic() + args.timeout_seconds + 2.0
            audits: list[dict[str, object]] = []
            while time.monotonic() < deadline:
                audits = client.get("/api/emotion/analysis/audits").json()
                if audits:
                    break
                time.sleep(0.02)
            if not audits:
                print("BLOCKED: analysis did not reach a terminal audit")
                return 1
            outcome = str(audits[0]["outcome"])
            if outcome not in {"applied", "no_change"}:
                print(f"BLOCKED: audit_outcome={outcome}")
                return 1
            state = client.get("/api/emotion/state").json()
            if not all(0.0 <= float(value) <= 1.0 for value in state["vector"].values()):
                print("BLOCKED: emotion state escaped local bounds")
                return 1

        if not _analysis_tables_are_metadata_only(database_path, key):
            print("BLOCKED: analysis metadata tables contain forbidden raw data")
            return 1
        print(
            "PASS: Stage 4C real DeepSeek smoke "
            f"audit_outcome={outcome} bounded_state=true metadata_only=true"
        )
        return 0
    except Exception as exc:
        print(f"BLOCKED: {type(exc).__name__}")
        return 1
    finally:
        get_settings.cache_clear()
        for name, value in original.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        _remove_database_files(database_path)


if __name__ == "__main__":
    raise SystemExit(main())
