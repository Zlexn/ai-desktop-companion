from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.core.errors import (
    PersonaIntegrityError,
    PersonaVersionConflictError,
    ValidationAppError,
)
from app.repositories.personas import PersonaRepository
from app.repositories.sqlite import managed_connection
from app.services.persona_compiler import PersonaCompiler
from app.services.persona_service import PersonaService
from app.services.prompt_renderer import default_prompt_renderer


NOW = datetime(2026, 7, 21, tzinfo=UTC)


def _config(name: str = "雪乃") -> dict[str, object]:
    config = default_prompt_renderer().load_persona_v1_config()
    config["identity"] = {**config["identity"], "name": name}
    return config


def _service(
    connection,
    *,
    ids: list[str] | None = None,
    after_pointer_switch=None,
) -> PersonaService:
    renderer = default_prompt_renderer()
    id_values = iter(ids or [f"persona-{index}" for index in range(1, 20)])
    return PersonaService(
        PersonaRepository(connection),
        compiler=PersonaCompiler(
            template_text=renderer.load_template_text(),
            persona_max_characters=8_000,
        ),
        bootstrap_config=_config(),
        now=lambda: NOW,
        new_id=lambda: next(id_values),
        after_pointer_switch=after_pointer_switch,
    )


def test_bootstrap_is_atomic_and_idempotent(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        service = _service(connection)
        first = service.bootstrap()
        second = service.bootstrap()

        assert first.outcome == "bootstrap"
        assert first.artifact.version == 1
        assert first.active.activation_generation == 0
        assert second.outcome == "no_change"
        assert second.artifact == first.artifact
        assert service.list_artifacts() == [first.artifact]


def test_create_freezes_complete_behavior_and_no_change(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        service = _service(connection)
        first = service.bootstrap()
        no_change = service.create_and_activate(
            _config(),
            expected_artifact_id=first.artifact.id,
            expected_generation=first.active.activation_generation,
        )

        assert no_change.outcome == "no_change"
        assert service.list_artifacts() == [first.artifact]
        assert service.latest_audit()["action"] == "no_change"


def test_historical_equivalent_content_creates_new_version(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        service = _service(connection)
        first = service.bootstrap()
        second = service.create_and_activate(
            _config("林月"),
            first.artifact.id,
            first.active.activation_generation,
        )
        third = service.create_and_activate(
            _config(),
            second.artifact.id,
            second.active.activation_generation,
        )

        assert third.outcome == "created"
        assert third.artifact.version == 3
        assert third.artifact.id not in {first.artifact.id, second.artifact.id}
        assert (
            third.artifact.behavior_fingerprint
            == first.artifact.behavior_fingerprint
        )
        assert (
            third.active.activation_generation
            == second.active.activation_generation + 1
        )
        assert service.latest_audit()["action"] == "created"


def test_create_and_activate_rejects_stale_pointer(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        service = _service(connection)
        first = service.bootstrap()

        with pytest.raises(PersonaVersionConflictError):
            service.create_and_activate(
                _config("林月"),
                expected_artifact_id="stale",
                expected_generation=first.active.activation_generation,
            )

        assert service.list_artifacts() == [first.artifact]
        assert service.latest_audit()["action"] == "activation_conflict"


def test_activate_historical_artifact_and_no_change(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        service = _service(connection)
        first = service.bootstrap()
        second = service.create_and_activate(
            _config("林月"),
            first.artifact.id,
            first.active.activation_generation,
        )
        activated = service.activate(
            first.artifact.id,
            second.artifact.id,
            second.active.activation_generation,
        )
        no_change = service.activate(
            first.artifact.id,
            activated.artifact.id,
            activated.active.activation_generation,
        )

        assert activated.outcome == "activated"
        assert activated.active.artifact_id == first.artifact.id
        assert no_change.outcome == "no_change"


def test_current_rejects_integrity_mismatch(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        service = _service(connection)
        first = service.bootstrap()
        connection.execute("DROP TRIGGER trg_persona_artifacts_immutable_update")
        connection.execute(
            "UPDATE persona_artifacts SET behavior_fingerprint=? WHERE id=?",
            ("f" * 64, first.artifact.id),
        )
        connection.commit()

        with pytest.raises(PersonaIntegrityError):
            service.current()

        assert service.latest_audit()["action"] == "integrity_rejected"


def test_redact_noncurrent_requires_no_replacement(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        service = _service(connection)
        first = service.bootstrap()
        second = service.create_and_activate(
            _config("林月"),
            first.artifact.id,
            first.active.activation_generation,
        )
        result = service.redact(
            first.artifact.id,
            expected_artifact_id=second.artifact.id,
            expected_generation=second.active.activation_generation,
            replacement_artifact_id=None,
            replacement_config=None,
            confirmation="redact_persona_payload",
        )

        assert result.redacted.source_content is None
        assert result.active == second.active


def test_redact_current_switches_pointer_before_payload_clear(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        service = _service(connection)
        first = service.bootstrap()
        second = service.create_and_activate(
            _config("林月"),
            first.artifact.id,
            first.active.activation_generation,
        )
        result = service.redact(
            second.artifact.id,
            expected_artifact_id=second.artifact.id,
            expected_generation=second.active.activation_generation,
            replacement_artifact_id=first.artifact.id,
            replacement_config=None,
            confirmation="redact_persona_payload",
        )

        assert result.redacted.source_content is None
        assert result.active.artifact_id == first.artifact.id


def test_redact_current_can_create_replacement_config(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        service = _service(connection)
        first = service.bootstrap()
        result = service.redact(
            first.artifact.id,
            expected_artifact_id=first.artifact.id,
            expected_generation=first.active.activation_generation,
            replacement_artifact_id=None,
            replacement_config=_config("林月"),
            confirmation="redact_persona_payload",
        )

        assert result.active.artifact_id != first.artifact.id
        assert [item.version for item in service.list_artifacts()] == [1, 2]
        assert service.current().artifact.source_content["identity"]["name"] == "林月"


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "replacement_artifact_id": None,
            "replacement_config": None,
            "confirmation": "wrong",
        },
        {
            "replacement_artifact_id": "persona-1",
            "replacement_config": _config("林月"),
            "confirmation": "redact_persona_payload",
        },
        {
            "replacement_artifact_id": None,
            "replacement_config": None,
            "confirmation": "redact_persona_payload",
        },
        {
            "replacement_artifact_id": "persona-1",
            "replacement_config": None,
            "confirmation": "redact_persona_payload",
        },
    ],
)
def test_redact_current_rejects_invalid_replacement_cases(
    tmp_path: Path,
    kwargs: dict[str, object],
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        service = _service(connection)
        first = service.bootstrap()
        with pytest.raises(ValidationAppError):
            service.redact(
                first.artifact.id,
                expected_artifact_id=first.artifact.id,
                expected_generation=first.active.activation_generation,
                **kwargs,
            )


def test_redact_noncurrent_rejects_unrelated_replacement(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        service = _service(connection)
        first = service.bootstrap()
        second = service.create_and_activate(
            _config("林月"),
            first.artifact.id,
            first.active.activation_generation,
        )

        with pytest.raises(ValidationAppError):
            service.redact(
                first.artifact.id,
                expected_artifact_id=second.artifact.id,
                expected_generation=second.active.activation_generation,
                replacement_artifact_id=None,
                replacement_config=_config("林星"),
                confirmation="redact_persona_payload",
            )


def test_redaction_rolls_back_pointer_switch_on_injected_failure(
    tmp_path: Path,
) -> None:
    def fail_after_switch() -> None:
        raise RuntimeError("injected after pointer switch")

    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        service = _service(connection, after_pointer_switch=fail_after_switch)
        first = service.bootstrap()
        second = service.create_and_activate(
            _config("林月"),
            first.artifact.id,
            first.active.activation_generation,
        )

        with pytest.raises(RuntimeError, match="injected after pointer switch"):
            service.redact(
                second.artifact.id,
                expected_artifact_id=second.artifact.id,
                expected_generation=second.active.activation_generation,
                replacement_artifact_id=first.artifact.id,
                replacement_config=None,
                confirmation="redact_persona_payload",
            )

        current = service.current()
        assert current.artifact.id == second.artifact.id
        assert current.artifact.source_content is not None


def test_redact_noncurrent_rejects_integrity_invalid_current(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        service = _service(connection)
        first = service.bootstrap()
        second = service.create_and_activate(
            _config("林月"),
            first.artifact.id,
            first.active.activation_generation,
        )
        connection.execute("DROP TRIGGER trg_persona_artifacts_immutable_update")
        connection.execute(
            "UPDATE persona_artifacts SET behavior_fingerprint=? WHERE id=?",
            ("f" * 64, second.artifact.id),
        )
        connection.commit()

        with pytest.raises(PersonaIntegrityError):
            service.redact(
                first.artifact.id,
                expected_artifact_id=second.artifact.id,
                expected_generation=second.active.activation_generation,
                replacement_artifact_id=None,
                replacement_config=None,
                confirmation="redact_persona_payload",
            )

        assert PersonaRepository(connection).artifact(first.artifact.id).source_content is not None


def test_redact_rejects_integrity_invalid_target(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        service = _service(connection)
        first = service.bootstrap()
        second = service.create_and_activate(
            _config("林月"),
            first.artifact.id,
            first.active.activation_generation,
        )
        connection.execute("DROP TRIGGER trg_persona_artifacts_immutable_update")
        connection.execute(
            "UPDATE persona_artifacts SET behavior_fingerprint=? WHERE id=?",
            ("f" * 64, first.artifact.id),
        )
        connection.commit()

        with pytest.raises(PersonaIntegrityError):
            service.redact(
                first.artifact.id,
                expected_artifact_id=second.artifact.id,
                expected_generation=second.active.activation_generation,
                replacement_artifact_id=None,
                replacement_config=None,
                confirmation="redact_persona_payload",
            )


def test_redact_rejects_integrity_invalid_replacement(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        service = _service(connection)
        first = service.bootstrap()
        second = service.create_and_activate(
            _config("林月"),
            first.artifact.id,
            first.active.activation_generation,
        )
        connection.execute("DROP TRIGGER trg_persona_artifacts_immutable_update")
        connection.execute(
            "UPDATE persona_artifacts SET behavior_fingerprint=? WHERE id=?",
            ("f" * 64, first.artifact.id),
        )
        connection.commit()

        with pytest.raises(PersonaIntegrityError):
            service.redact(
                second.artifact.id,
                expected_artifact_id=second.artifact.id,
                expected_generation=second.active.activation_generation,
                replacement_artifact_id=first.artifact.id,
                replacement_config=None,
                confirmation="redact_persona_payload",
            )
