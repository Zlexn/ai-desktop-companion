# Gate C3 Task 14 验收证据 — 关系上下文编码与 Pre-dispatch 重验证注入

> 日期：2026-08-16（会话工作区快照 20260710）
> 范围：`backend/app/services/context_data_encoder.py`、`context_composer.py`、`chat_service.py`、`relationship_injection.py`（新建）、`api/dependencies.py`，以及 `backend/tests/test_context_data_encoder.py`、`test_context_composer.py`、`test_relationship_chat_disclosure.py`、`test_chat_service.py`、`test_api_chat.py`

## 目标

按计划 Task 14：

1. 把 verified relationship projection 编码进 C1 上下文（`relationships` 数组 ≤1 个对象），跨 fake/Anthropic/DeepSeek 做 JSON/HTML/Prompt-injection 转义；
2. 组合（composition）与 Provider I/O 之间发生 suppress/redaction/forget 时，pre-dispatch 重验证并重组合为 neutral/无关系上下文，聊天始终成功，Provider 永不看到 forgotten sentinel；
3. Manifest 只存 projection ID/version；关系层绝不改变 Persona/system rules。

## 实现

### 1. `context_data_encoder.py` — 编码关系投影

- `encode(..., relationships=())` 填充 `"relationships"` 数组（原为硬编码 `[]`）。
- `_safe_json` 对 `< > & \u2028 \u2029` 转义，跨 fake/Anthropic/DeepSeek payload normalization 生效。

### 2. `context_composer.py` — 接收并校验投影

- `ContextCompositionRequest.relationship: dict[str, object] | None`（默认 None）。
- `_validate_request` 校验 8 个键（authority / projection_id / projection_version / familiarity_bucket / preferred_address / relationship_summary_code / persona_artifact_id / projection_rule_version），缺失即拒绝。
- 结果携带真实 `relationship_projection_id` / `relationship_projection_version`；`_build_messages` 只在非 None 时把 `[request.relationship]` 交给 encoder。
- 版本常量保持 C2 的 `context-composer-v2` / `context-data-encoder-v2` / `context-manifest-v2`（C3 常量已定义但按计划延后到 Gate C 最终验收再统一 bump，避免破坏既有 v2 断言）。

### 3. `relationship_injection.py`（新建）— 组合快照 + fence 保护重验证

- `RelationshipInjectionService(database_url, fence)`：
  - `current_relationship()`：组合时读取当前 verified view（无 fence，best-effort 快照）；
  - `revalidate_or_neutral(relationship, now=None)`：在 `RelationshipDisclosureFence.hold_dispatch()` 内重读 `RelationshipProjector.current_view()`；投影消失（suppressed/redacted/corrupt）时返回 neutral 无地址视图（`projection_id="neutral"`，`preferred_address=None`），否则返回当前 verified 视图。

### 4. `chat_service.py` — 接线

- 构造器新增 `relationship_injection: RelationshipInjectionService | None = None`（默认 None，旧调用方不受影响）。
- `send_message`：组合前 `current_relationship()` 取快照（异常隔离降级为 None）；`_generate` 前 `revalidate_or_neutral` 重验证，变化时以 neutral/当前视图重组合；关系读取异常一律捕获、降级为无关系上下文，聊天始终成功。
- 重组合通过局部 `_build_composition(current_sources, current_relationship)` 统一构造，summary revalidation 沿用原内层 context。

### 5. `api/dependencies.py` — 生产注入

- 新增 `get_relationship_injection_service`（`settings.database_url` + `get_relationship_disclosure_fence`）。
- `get_chat_service` 注入 `relationship_injection`。

## 验证

```text
# Task 14 组合测试
python -W error -m pytest backend/tests/test_context_data_encoder.py \
  backend/tests/test_context_composer.py \
  backend/tests/test_relationship_chat_disclosure.py \
  backend/tests/test_chat_service.py backend/tests/test_api_chat.py -q
111 passed

# 完整后端回归
python -W error -m pytest backend/tests -q
1820 passed
```

覆盖场景：

- `test_encoder_accepts_single_relationship_projection` / `test_encoder_escapes_relationship_preferred_address`：≤1 对象、8 键、`<>&` 转义。
- `test_injection_service_neutralizes_relationship_when_revalidation_fails`：投影消失 → neutral 无地址。
- `test_injection_service_keeps_valid_relationship`：真实 reconcile 投影通过重验证保留。
- `test_chat_sends_verified_relationship_and_neutral_after_forget`（真实 ChatService 端到端）：忘前 Provider 收到 verified 投影（含地址哨兵），`MemoryForgetService.forget_memory` 后重发消息 Provider 无地址泄漏、聊天成功。
- 既有 `test_chat_service.py` / `test_api_chat.py` 回归全绿（默认 `relationship_injection=None` 路径无行为变化）。

## 边界

- 仅实现计划 Task 14 的编码与 pre-dispatch 重验证；未动 authority/lineage/projection 评估核心。
- C3 上下文版本常量（`CONTEXT_COMPOSER_VERSION_C3` 等）保持定义未启用，统一在 Gate C 最终验收 bump。
- 组合时快照读取不持有 fence（best-effort），权威检查在 dispatch 前 fence 内完成。
- 未提交 Git（按计划 Task 14 Step 5 的记录边界，建议 commit message：`feat: inject verified relationship projections`）。
