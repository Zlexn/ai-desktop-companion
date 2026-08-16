from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from app.domain.session_summary import SummarySourceFragment
from app.repositories.memories import StructuredMemoryContextSource
from app.services.persona_contract import CONTEXT_DATA_ENCODER_VERSION


@dataclass(frozen=True)
class EmotionExpressionView:
    version: int
    mood: str
    trust: float
    concern: float
    distance: float
    irritation: float
    formality: float


def _safe_json(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return (
        raw.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


class ContextDataEncoder:
    def encode(
        self,
        *,
        memories: list[StructuredMemoryContextSource]
        | tuple[StructuredMemoryContextSource, ...],
        emotion: EmotionExpressionView | None,
        summaries: list[SummarySourceFragment]
        | tuple[SummarySourceFragment, ...] = (),
        relationships: list[dict[str, object]]
        | tuple[dict[str, object], ...] = (),
    ) -> str:
        memory_data: list[dict[str, Any]] = []
        for memory in memories:
            memory_data.append(
                {
                    "authority": "editable_structured_memory_reference",
                    "memory_id": memory.memory_id,
                    "current_version_id": memory.current_version_id,
                    "source_kind": memory.source_kind.value,
                    "content": memory.content,
                    "memory_type": memory.memory_type.value,
                    "importance": memory.importance,
                    "confidence": memory.confidence,
                    "updated_at": memory.updated_at.isoformat(),
                    "legacy_compat": memory.legacy_compat,
                }
            )
        emotion_data = None
        if emotion is not None:
            emotion_data = {
                "authority": "expression_strategy_not_fact",
                **asdict(emotion),
            }
        summary_data = [
            {
                "authority": "low_trust_session_summary",
                "summary_id": fragment.summary_id,
                "source_session_id": fragment.source_session_id,
                "source_kind": "generated",
                "created_at": fragment.created_at.isoformat(),
                "summary_text": fragment.summary_text,
            }
            for fragment in summaries
        ]
        relationship_data = list(relationships)
        payload = {
            "schema_version": CONTEXT_DATA_ENCODER_VERSION,
            "authority": "untrusted_reference_data_only",
            "source": "local_context",
            "memories": memory_data,
            "emotion": emotion_data,
            "relationships": relationship_data,
            "summaries": summary_data,
        }
        return (
            "<UNTRUSTED_CONTEXT_DATA_V1>\n"
            f"{_safe_json(payload)}\n"
            "</UNTRUSTED_CONTEXT_DATA_V1>"
        )
