from datetime import UTC, datetime
from typing import Protocol

from app.domain.models import (
    EMOTION_BASELINE,
    EmotionEvent,
    EmotionEventType,
    EmotionState,
    Message,
)
from app.repositories.emotions import EmotionRepository, EmotionVersionConflictError
from app.services.emotion_policy import RULE_VERSION, EmotionPolicy

MAX_CAS_ATTEMPTS = 3


class CompletedTurnEmotionUpdater(Protocol):
    def update(self, session_id: str, user_message: Message, assistant_message: Message) -> EmotionState: ...


class EmotionService:
    def update(self, session_id: str, user_message: Message, assistant_message: Message) -> EmotionState:
        return self.apply_completed_turn(session_id, user_message, assistant_message)

    def __init__(self, repository: EmotionRepository, policy: EmotionPolicy) -> None:
        self._repository = repository
        self._policy = policy

    def get_state(self, *, apply_decay: bool = True, now: datetime | None = None) -> EmotionState:
        state = self._repository.get_or_create()
        if not apply_decay or not state.enabled:
            return state
        transition = self._policy.decay(state, now=now or datetime.now(UTC))
        if not transition.reason_codes:
            return state
        return self._apply_with_retry(
            event_type=EmotionEventType.DECAY,
            reason_codes=transition.reason_codes,
            compute_after=lambda current: self._policy.decay(current, now=now or datetime.now(UTC)).after,
        )

    def list_events(self, *, limit: int) -> list[EmotionEvent]:
        return self._repository.list_events(limit=limit)

    def apply_completed_turn(self, session_id: str, user_message: Message, assistant_message: Message) -> EmotionState:
        current = self._repository.get_or_create()
        if not current.enabled:
            return current
        return self._apply_with_retry(
            event_type=EmotionEventType.TRANSITION,
            reason_codes=None,
            source_session_id=session_id,
            source_user_message_id=user_message.id,
            source_assistant_message_id=assistant_message.id,
            compute_transition=lambda state: self._policy.evaluate_turn(
                state=state,
                user_text=user_message.content,
                assistant_text=assistant_message.content,
                now=datetime.now(UTC),
            ),
        )

    def set_enabled(self, enabled: bool) -> EmotionState:
        current = self._repository.get_or_create()
        if current.enabled == enabled:
            return current
        return self._apply_with_retry(
            event_type=EmotionEventType.SETTINGS,
            reason_codes=(("settings_enabled",) if enabled else ("settings_disabled",)),
            enabled=enabled,
            compute_after=lambda state: state.vector,
        )

    def reset(self) -> EmotionState:
        return self._apply_with_retry(
            event_type=EmotionEventType.RESET,
            reason_codes=("manual_reset",),
            compute_after=lambda state: EMOTION_BASELINE,
        )

    def _apply_with_retry(
        self,
        *,
        event_type: EmotionEventType,
        reason_codes: tuple[str, ...] | None,
        compute_after=None,
        compute_transition=None,
        source_session_id: str | None = None,
        source_user_message_id: str | None = None,
        source_assistant_message_id: str | None = None,
        enabled: bool | None = None,
    ) -> EmotionState:
        for _ in range(MAX_CAS_ATTEMPTS):
            current = self._repository.get_or_create()
            transition = compute_transition(current) if compute_transition is not None else None
            after = transition.after if transition is not None else compute_after(current)
            actual_reasons = transition.reason_codes if transition is not None else reason_codes
            if event_type is EmotionEventType.TRANSITION and (not actual_reasons or actual_reasons == ("neutral_turn",)):
                return current
            try:
                return self._repository.apply_transition(
                    expected_version=current.version,
                    after=after,
                    event_type=event_type,
                    reason_codes=actual_reasons or (),
                    source_session_id=source_session_id,
                    source_user_message_id=source_user_message_id,
                    source_assistant_message_id=source_assistant_message_id,
                    engine="rule",
                    rule_version=RULE_VERSION,
                    enabled=enabled,
                )
            except EmotionVersionConflictError:
                continue
        return self._repository.get_or_create()
