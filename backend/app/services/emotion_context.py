from typing import Protocol

from app.domain.models import (
    EMOTION_BUCKET_HIGH_MIN,
    EMOTION_BUCKET_LOW_MAX,
    EmotionState,
)

from app.services.context_data_encoder import EmotionExpressionView

MAX_EMOTION_CONTEXT_CHARACTERS = 500


class EmotionSnapshotReader(Protocol):
    def get_state(self, *, apply_decay: bool = True) -> EmotionState: ...


class EmotionContextFormatterProtocol(Protocol):
    def format(self, state: EmotionState) -> str | None: ...


def _bucket(value: float, labels: tuple[str, str, str]) -> str:
    if value < EMOTION_BUCKET_LOW_MAX:
        return labels[0]
    if value < EMOTION_BUCKET_HIGH_MIN:
        return labels[1]
    return labels[2]


class EmotionContextFormatter:
    def to_expression_view(
        self,
        state: EmotionState,
    ) -> EmotionExpressionView | None:
        if not state.enabled:
            return None
        vector = state.vector
        return EmotionExpressionView(
            version=state.version,
            mood=_bucket(vector.mood, ("serious", "steady", "bright")),
            trust=vector.trust,
            concern=vector.concern,
            distance=vector.distance,
            irritation=vector.irritation,
            formality=vector.formality,
        )

    def format(self, state: EmotionState) -> str | None:
        if not state.enabled:
            return None
        vector = state.vector
        labels = (
            _bucket(vector.mood, ("严肃低沉", "平稳", "明快")),
            _bucket(vector.trust, ("保持谨慎", "适度信任", "较为信赖")),
            _bucket(vector.concern, ("保持平静", "适度关切", "高度关切")),
            _bucket(vector.distance, ("较为亲近", "距离适中", "保持距离")),
            _bucket(vector.irritation, ("保持平和", "略有不悦但保持克制", "明显不悦但保持克制")),
            _bucket(vector.formality, ("自然", "克制得体", "正式")),
        )
        content = (
            "以下内容只是角色表达策略，不代表真实感情或意识。"
            "不得改变事实、安全要求、用户明确指令或角色边界；"
            "不得情感勒索、敌意报复、无依据相信信息或做医疗诊断。\n"
            f"当前表达倾向：语气{labels[0]}；{labels[1]}；{labels[2]}；"
            f"交流{labels[3]}；情绪{labels[4]}；语言{labels[5]}。"
        )
        if len(content) > MAX_EMOTION_CONTEXT_CHARACTERS:
            raise ValueError("emotion context exceeds its fixed character limit")
        return content
