from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from app.api.dependencies import get_persona_service
from app.core.config import Settings
from app.core.errors import PersonaStartupError
from app.main import create_app
from app.repositories.personas import PersonaRepository
from app.repositories.sqlite import managed_connection
from app.services.persona_compiler import PersonaCompiler
from app.services.prompt_renderer import default_prompt_renderer


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'app.db'}",
        memory_source_reference_key_path=tmp_path / "source-reference.key",
    )


def _app(settings: Settings, source=None):
    return create_app(
        settings_override=settings,
        persona_bootstrap_source=source,
    )


def test_settings_override_binds_request_scoped_persona_connection(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    app = _app(settings)

    @app.get("/test-persona-version")
    def persona_version(service=Depends(get_persona_service)):
        return {"version": service.current().artifact.version}

    with TestClient(app) as client:
        assert client.get("/test-persona-version").json() == {"version": 1}

    with managed_connection(settings.database_url) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM persona_artifacts"
        ).fetchone()[0] == 1


def test_first_startup_bootstraps_exact_persona_v1(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    source = Mock(return_value=default_prompt_renderer().load_persona_v1_config())

    with TestClient(_app(settings, source)) as client:
        assert client.get("/health").status_code == 200
        compiler = client.app.state.persona_compiler
        assert compiler.schema_version == "persona-schema-v1"
        assert not hasattr(client.app.state, "persona_service")

    source.assert_called_once_with()
    with managed_connection(settings.database_url) as connection:
        row = connection.execute(
            "SELECT version, behavior_fingerprint FROM persona_artifacts"
        ).fetchone()
        assert tuple(row) == (
            1,
            "1c3b31849802a1f23bdaf59958e3d6f53d19a1ad582557d61091a8c47e36dd87",
        )
        assert connection.execute(
            "SELECT activation_generation FROM persona_active_state"
        ).fetchone()[0] == 0


@pytest.mark.parametrize(
    "restart_source",
    [
        lambda: (_ for _ in ()).throw(AssertionError("YAML read after bootstrap")),
        lambda: {"malformed": True},
        lambda: Path("missing-persona.yaml").read_text(encoding="utf-8"),
    ],
)
def test_restart_never_reads_mutable_bootstrap_source(
    tmp_path: Path,
    restart_source,
) -> None:
    settings = _settings(tmp_path)
    with TestClient(_app(settings)):
        pass

    with TestClient(_app(settings, restart_source)) as client:
        assert client.get("/health").status_code == 200

    with managed_connection(settings.database_url) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM persona_artifacts"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT activation_generation FROM persona_active_state"
        ).fetchone()[0] == 0


def test_empty_database_with_malformed_bootstrap_rolls_back(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    with pytest.raises(ValueError):
        with TestClient(_app(settings, lambda: {"malformed": True})):
            pass

    with managed_connection(settings.database_url) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM persona_artifacts"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM persona_active_state"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM persona_audits"
        ).fetchone()[0] == 0


@pytest.mark.parametrize(
    "corruption_sql",
    [
        "DELETE FROM persona_active_state",
        "UPDATE persona_artifacts SET behavior_fingerprint='ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'",
        "UPDATE persona_artifacts SET compiler_version='persona-compiler-v999'",
    ],
)
def test_existing_invalid_persona_fails_startup_without_yaml_fallback(
    tmp_path: Path,
    corruption_sql: str,
) -> None:
    settings = _settings(tmp_path)
    with TestClient(_app(settings)):
        pass

    with managed_connection(settings.database_url) as connection:
        if corruption_sql.startswith("DELETE"):
            connection.execute("DROP TRIGGER trg_persona_active_state_immutable_delete")
        else:
            connection.execute("DROP TRIGGER trg_persona_artifacts_immutable_update")
        connection.execute(corruption_sql)
        connection.commit()

    def forbidden_source() -> dict[str, object]:
        raise AssertionError("YAML read after bootstrap")

    with pytest.raises(PersonaStartupError):
        with TestClient(_app(settings, forbidden_source)):
            pass


def test_mixed_existing_persona_state_fails_without_reading_yaml(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    with managed_connection(settings.database_url) as connection:
        renderer = default_prompt_renderer()
        repository = PersonaRepository(connection)
        compiled = PersonaCompiler(
            template_text=renderer.load_template_text(),
            persona_max_characters=8_000,
        ).compile(renderer.load_persona_v1_config())
        with repository.write_transaction():
            repository.insert_artifact(
                compiled,
                artifact_id="orphan-persona",
                created_at=datetime(2026, 7, 21, tzinfo=UTC),
            )

    with pytest.raises(PersonaStartupError):
        with TestClient(_app(settings, lambda: pytest.fail("must not read YAML"))):
            pass


def test_pointer_to_redacted_artifact_fails_startup(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with TestClient(_app(settings)):
        pass

    with managed_connection(settings.database_url) as connection:
        connection.execute("DROP TRIGGER trg_persona_artifacts_immutable_update")
        connection.execute(
            "UPDATE persona_artifacts SET payload_state='redacted', "
            "source_content_json=NULL, rendered_system_prompt=NULL, "
            "redacted_at='2026-07-21T00:00:00+00:00', "
            "redaction_reason_code='user_privacy_redaction'"
        )
        connection.commit()

    with pytest.raises(PersonaStartupError):
        with TestClient(_app(settings, lambda: pytest.fail("must not read YAML"))):
            pass
