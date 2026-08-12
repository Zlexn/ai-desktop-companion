from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.repositories.personas import PersonaRepository
from app.repositories.sqlite import managed_connection
from app.services.persona_compiler import PersonaCompiler
from app.services.prompt_renderer import default_prompt_renderer


NOW = datetime(2026, 7, 21, tzinfo=UTC)


def _compiler() -> PersonaCompiler:
    renderer = default_prompt_renderer()
    return PersonaCompiler(
        template_text=renderer.load_template_text(),
        persona_max_characters=8_000,
    )


def _config(name: str = "林夕") -> dict[str, object]:
    renderer = default_prompt_renderer()
    config = renderer.load_persona_v1_config()
    config["identity"] = {**config["identity"], "name": name}
    return config


def test_repository_insert_versions_and_cas_activation(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        repository = PersonaRepository(connection)
        compiler = _compiler()
        with repository.write_transaction():
            first = repository.insert_artifact(
                compiler.compile(_config()),
                artifact_id="persona-1",
                created_at=NOW,
            )
            initial = repository.insert_initial_state(first.id, updated_at=NOW)
            second = repository.insert_artifact(
                compiler.compile(_config("林月")),
                artifact_id="persona-2",
                created_at=NOW + timedelta(seconds=1),
            )
            active = repository.cas_activate(
                second.id,
                expected_artifact_id=first.id,
                expected_generation=initial.activation_generation,
                updated_at=NOW + timedelta(seconds=1),
            )

        assert [item.version for item in repository.list_artifacts()] == [1, 2]
        assert active is not None
        assert active.artifact_id == second.id
        assert active.activation_generation == 1
        assert repository.cas_activate(
            first.id,
            expected_artifact_id=first.id,
            expected_generation=0,
            updated_at=NOW,
        ) is None


def test_repository_write_transaction_rolls_back_all_persona_writes(
    tmp_path: Path,
) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        repository = PersonaRepository(connection)
        with pytest.raises(RuntimeError, match="injected failure"):
            with repository.write_transaction():
                artifact = repository.insert_artifact(
                    _compiler().compile(_config()),
                    artifact_id="persona-1",
                    created_at=NOW,
                )
                repository.insert_initial_state(artifact.id, updated_at=NOW)
                repository.append_audit(
                    action="bootstrap",
                    artifact_id=artifact.id,
                    reason_code="initial_persona_bootstrap",
                    created_at=NOW,
                )
                raise RuntimeError("injected failure")

        assert repository.list_artifacts() == []
        assert repository.current_state() is None
        assert repository.latest_audit() is None


def test_repository_nested_transaction_uses_savepoint(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        repository = PersonaRepository(connection)
        with repository.write_transaction():
            first = repository.insert_artifact(
                _compiler().compile(_config()),
                artifact_id="persona-1",
                created_at=NOW,
            )
            with pytest.raises(RuntimeError):
                with repository.write_transaction():
                    repository.insert_artifact(
                        _compiler().compile(_config("林月")),
                        artifact_id="persona-2",
                        created_at=NOW,
                    )
                    raise RuntimeError("rollback savepoint")
            repository.insert_initial_state(first.id, updated_at=NOW)

        assert [item.id for item in repository.list_artifacts()] == ["persona-1"]
        assert repository.current_state().artifact_id == "persona-1"


def test_repository_redaction_preserves_hashes_and_metadata(tmp_path: Path) -> None:
    with managed_connection(f"sqlite:///{tmp_path / 'persona.db'}") as connection:
        repository = PersonaRepository(connection)
        compiler = _compiler()
        with repository.write_transaction():
            first = repository.insert_artifact(
                compiler.compile(_config()),
                artifact_id="persona-1",
                created_at=NOW,
            )
            second = repository.insert_artifact(
                compiler.compile(_config("林月")),
                artifact_id="persona-2",
                created_at=NOW,
            )
            repository.insert_initial_state(second.id, updated_at=NOW)
            redacted = repository.redact_payload(first.id, redacted_at=NOW)

        assert redacted.source_content is None
        assert redacted.rendered_system_prompt is None
        assert redacted.content_identity_hash == first.content_identity_hash
        assert redacted.behavior_fingerprint == first.behavior_fingerprint
        assert redacted.version == first.version
