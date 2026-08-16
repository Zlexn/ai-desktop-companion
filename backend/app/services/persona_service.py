from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.core.errors import (
    NotFoundError,
    PersonaIntegrityError,
    PersonaStartupError,
    PersonaVersionConflictError,
    ValidationAppError,
)
from app.domain.persona import PersonaActiveState, PersonaArtifact, PersonaPayloadState
from app.repositories.personas import PersonaRepository
from app.services.persona_compiler import PersonaCompiler


@dataclass(frozen=True)
class PersonaActivationResult:
    artifact: PersonaArtifact
    active: PersonaActiveState
    outcome: str


PersonaMutationResult = PersonaActivationResult


@dataclass(frozen=True)
class PersonaRedactionResult:
    redacted: PersonaArtifact
    active: PersonaActiveState


class PersonaService:
    def __init__(
        self,
        repository: PersonaRepository,
        *,
        compiler: PersonaCompiler,
        bootstrap_config: Mapping[str, object] | Callable[[], Mapping[str, object]],
        now: Callable[[], datetime] | None = None,
        new_id: Callable[[], str] | None = None,
        after_pointer_switch: Callable[[], None] | None = None,
    ) -> None:
        self._repository = repository
        self._compiler = compiler
        self._bootstrap_config = bootstrap_config
        self._now = now or (lambda: datetime.now(UTC))
        self._new_id = new_id or (lambda: str(uuid4()))
        self._after_pointer_switch = after_pointer_switch

    @contextmanager
    def _write_transaction(self) -> Iterator[None]:
        try:
            with self._repository.write_transaction():
                yield
        except PersonaVersionConflictError:
            self._record_rejected_audit(
                action="activation_conflict",
                reason_code="stale_active_state",
            )
            raise
        except PersonaIntegrityError:
            self._record_rejected_audit(
                action="integrity_rejected",
                reason_code="integrity_verification_failed",
            )
            raise

    def _record_rejected_audit(self, *, action: str, reason_code: str) -> None:
        state = self._repository.current_state()
        artifact_id = state.artifact_id if state is not None else "unknown"
        try:
            with self._repository.write_transaction():
                self._repository.append_audit(
                    action=action,
                    artifact_id=artifact_id,
                    reason_code=reason_code,
                    created_at=self._now(),
                )
        except (RuntimeError, sqlite3.IntegrityError):
            return

    def bootstrap(self) -> PersonaActivationResult:
        config = (
            self._bootstrap_config()
            if callable(self._bootstrap_config)
            else self._bootstrap_config
        )
        with self._write_transaction():
            current = self._repository.current_state()
            artifacts = self._repository.list_artifacts()
            if current is not None or artifacts:
                if current is None:
                    raise PersonaIntegrityError()
                artifact = self._require_verified_artifact(current.artifact_id)
                return PersonaActivationResult(artifact, current, "no_change")
            now = self._now()
            artifact = self._repository.insert_artifact(
                self._compiler.compile(config),
                artifact_id=self._new_id(),
                created_at=now,
            )
            active = self._repository.insert_initial_state(
                artifact.id,
                updated_at=now,
            )
            self._repository.append_audit(
                action="bootstrap",
                artifact_id=artifact.id,
                reason_code="initial_persona_bootstrap",
                created_at=now,
            )
            return PersonaActivationResult(artifact, active, "bootstrap")

    def verify_existing_startup_state(self, state) -> PersonaActivationResult:
        if state.artifact_count <= 0 or state.active_state is None:
            raise PersonaStartupError()
        try:
            artifact = self._require_verified_artifact(
                state.active_state.artifact_id
            )
        except (NotFoundError, PersonaIntegrityError) as exc:
            raise PersonaStartupError() from exc
        return PersonaActivationResult(artifact, state.active_state, "current")

    def current(self) -> PersonaActivationResult:
        state = self._repository.current_state()
        if state is None:
            raise PersonaIntegrityError()
        try:
            artifact = self._require_verified_artifact(state.artifact_id)
        except PersonaIntegrityError:
            self._record_rejected_audit(
                action="integrity_rejected",
                reason_code="integrity_verification_failed",
            )
            raise
        return PersonaActivationResult(artifact, state, "current")

    def list_artifacts(self) -> list[PersonaArtifact]:
        artifacts = self._repository.list_artifacts()
        return [
            artifact
            if artifact.payload_state is PersonaPayloadState.REDACTED
            else self._require_verified_artifact(artifact.id)
            for artifact in artifacts
        ]

    def artifact(self, artifact_id: str) -> PersonaArtifact:
        artifact = self._repository.artifact(artifact_id)
        if artifact is None:
            raise NotFoundError()
        if artifact.payload_state is PersonaPayloadState.REDACTED:
            return artifact
        return self._require_verified_artifact(artifact_id)

    def latest_audit(self) -> sqlite3.Row | None:
        return self._repository.latest_audit()

    def create_and_activate(
        self,
        config: Mapping[str, object],
        expected_artifact_id: str,
        expected_generation: int,
    ) -> PersonaMutationResult:
        compiled = self._compiler.compile(config)
        with self._write_transaction():
            current = self._require_expected_state(
                expected_artifact_id,
                expected_generation,
            )
            current_artifact = self._require_verified_artifact(current.artifact_id)
            now = self._now()
            if current_artifact.behavior_fingerprint == compiled.behavior_fingerprint:
                self._repository.append_audit(
                    action="no_change",
                    artifact_id=current_artifact.id,
                    reason_code="behavior_unchanged",
                    created_at=now,
                )
                return PersonaActivationResult(
                    current_artifact,
                    current,
                    "no_change",
                )
            artifact = self._repository.insert_artifact(
                compiled,
                artifact_id=self._new_id(),
                created_at=now,
            )
            active = self._cas_activate(
                artifact.id,
                expected_artifact_id=expected_artifact_id,
                expected_generation=expected_generation,
                updated_at=now,
            )
            self._repository.append_audit(
                action="created",
                artifact_id=artifact.id,
                reason_code="user_created_persona",
                created_at=now,
            )
            return PersonaActivationResult(artifact, active, "created")

    def activate(
        self,
        artifact_id: str,
        expected_artifact_id: str,
        expected_generation: int,
    ) -> PersonaActivationResult:
        with self._write_transaction():
            state = self._require_expected_state(
                expected_artifact_id,
                expected_generation,
            )
            artifact = self._require_verified_artifact(artifact_id)
            if artifact.id == state.artifact_id:
                return PersonaActivationResult(artifact, state, "no_change")
            now = self._now()
            active = self._cas_activate(
                artifact.id,
                expected_artifact_id=expected_artifact_id,
                expected_generation=expected_generation,
                updated_at=now,
            )
            self._repository.append_audit(
                action="activated",
                artifact_id=artifact.id,
                reason_code="user_activated_persona",
                created_at=now,
            )
            if self._after_pointer_switch is not None:
                self._after_pointer_switch()
            return PersonaActivationResult(artifact, active, "activated")

    def redact(
        self,
        artifact_id: str,
        *,
        expected_artifact_id: str,
        expected_generation: int,
        replacement_artifact_id: str | None,
        replacement_config: Mapping[str, object] | None,
        confirmation: str,
    ) -> PersonaRedactionResult:
        if confirmation != "redact_persona_payload":
            raise ValidationAppError("需要确认永久清除角色配置内容。")
        if replacement_artifact_id is not None and replacement_config is not None:
            raise ValidationAppError("只能提供一种替代角色配置。")

        compiled_replacement = (
            self._compiler.compile(replacement_config)
            if replacement_config is not None
            else None
        )
        with self._write_transaction():
            current = self._require_expected_state(
                expected_artifact_id,
                expected_generation,
            )
            self._require_verified_artifact(current.artifact_id)
            target = self._require_verified_artifact(artifact_id)
            target_is_current = target.id == current.artifact_id
            has_replacement = (
                replacement_artifact_id is not None or compiled_replacement is not None
            )
            if target_is_current != has_replacement:
                raise ValidationAppError("替代角色配置与清除目标不匹配。")
            now = self._now()
            active = current
            if target_is_current:
                if replacement_artifact_id == target.id:
                    raise ValidationAppError("不能使用待清除的角色配置作为替代。")
                if replacement_artifact_id is not None:
                    replacement = self._require_verified_artifact(
                        replacement_artifact_id
                    )
                else:
                    assert compiled_replacement is not None
                    replacement = self._repository.insert_artifact(
                        compiled_replacement,
                        artifact_id=self._new_id(),
                        created_at=now,
                    )
                active = self._cas_activate(
                    replacement.id,
                    expected_artifact_id=expected_artifact_id,
                    expected_generation=expected_generation,
                    updated_at=now,
                )
                if self._after_pointer_switch is not None:
                    self._after_pointer_switch()
            try:
                redacted = self._repository.redact_payload(
                    target.id,
                    redacted_at=now,
                )
            except sqlite3.IntegrityError as exc:
                raise ValidationAppError("无法清除当前或最后可用的角色配置。") from exc
            self._repository.append_audit(
                action="payload_redacted",
                artifact_id=target.id,
                reason_code="user_privacy_redaction",
                created_at=now,
            )
            return PersonaRedactionResult(redacted, active)

    def _require_expected_state(
        self,
        expected_artifact_id: str,
        expected_generation: int,
    ) -> PersonaActiveState:
        state = self._repository.current_state()
        if (
            state is None
            or state.artifact_id != expected_artifact_id
            or state.activation_generation != expected_generation
        ):
            raise PersonaVersionConflictError()
        return state

    def _cas_activate(
        self,
        artifact_id: str,
        *,
        expected_artifact_id: str,
        expected_generation: int,
        updated_at: datetime,
    ) -> PersonaActiveState:
        state = self._repository.cas_activate(
            artifact_id,
            expected_artifact_id=expected_artifact_id,
            expected_generation=expected_generation,
            updated_at=updated_at,
        )
        if state is None:
            raise PersonaVersionConflictError()
        return state

    def _require_verified_artifact(self, artifact_id: str) -> PersonaArtifact:
        artifact = self._repository.artifact(artifact_id)
        if artifact is None:
            raise NotFoundError()
        if (
            artifact.payload_state is PersonaPayloadState.REDACTED
            or artifact.source_content is None
            or artifact.rendered_system_prompt is None
        ):
            raise PersonaIntegrityError()
        try:
            self._compiler.verify(
                source_content=artifact.source_content,
                rendered_system_prompt=artifact.rendered_system_prompt,
                content_identity_hash=artifact.content_identity_hash,
                behavior_fingerprint=artifact.behavior_fingerprint,
                schema_version=artifact.schema_version,
                ruleset_version=artifact.ruleset_version,
                template_version=artifact.template_version,
                compiler_version=artifact.compiler_version,
            )
        except ValueError as exc:
            raise PersonaIntegrityError() from exc
        return artifact
