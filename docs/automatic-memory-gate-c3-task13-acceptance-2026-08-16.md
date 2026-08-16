# Gate C3 Task 13 验收证据 — Persona 切换 / Rule 升级 / Safe Full Rebuild

> 日期：2026-08-16（会话工作区快照 20260710）
> 范围：`backend/app/services/relationship_reconciler.py`、`persona_service.py`、`api/dependencies.py`，以及 `backend/tests/test_relationship_persona_switch.py`、`test_relationship_full_rebuild.py`、`test_relationship_rule_upgrade.py`（新建）

## 目标

按计划 Task 13：

1. Persona 激活不产生关系事件、保留数值状态，同时用新 Persona provenance 激活投影；
2. Full rebuild 产生相同语义输出、不倍增 delta、不恢复 suppressed keys、中和 corrupt 状态；
3. 模拟 v2 rule 对 v1-invalid applies 追加普通 revoke（metadata-only `rule_migration`），仅追加 eligible unsuppressed v2 applies；绝不更新旧事件语义、绝不引入 `rule_migration` 事件类型。

## 实现

### 1. `relationship_reconciler.py` — 可配置 rule_version

- 构造器新增可选 `rule_version`（默认 `RELATIONSHIP_RULE_VERSION`）。
- `_current_identity` 用 `self._rule_version` 构造 source 快照（而非固定常量），使 v2 reconciler 感知升级后的规则版本。
- `run()` 的 eligible 分支 revoke 循环扩展：对 `event.rule_version != self._rule_version` 的旧 apply 也追加普通 revoke（rule migration revoke）。`rule_migration` 仅作为 reason 出现在 metadata-only audit，绝不新增事件类型。

### 2. `persona_service.py` — 激活触发投影 recompute

- `activate()` 在 CAS 激活 + 审计后调用 `after_pointer_switch`（生产注入 recompute）。
- `create_and_activate` 保持既有行为不触发（避免破坏既有 redact 回滚测试的假设）。

### 3. `api/dependencies.py` — 生产注入 recompute

- `get_persona_service` 注入 `after_pointer_switch=recompute_relationship_projection`：用当前 active persona 打开短连接、`projector.project` 直接重算投影。
- **关键**：不调用 `recover_and_scan`（那会 reserve 新 job 并与既有 job 身份冲突，触发 Task 9 的 `RelationshipJobIdentityMismatchError`）；源事实未变，仅需用新 persona 重算投影。

### 4. Full rebuild（复用现有机制）

- `scheduler.full_reconcile` 已具备幂等语义（Job identity 去重 + projector same_semantics 短路），无需新迁移路径。

## 验证

```text
# Task 13 新测试
python -W error -m pytest backend/tests/test_relationship_persona_switch.py \
  backend/tests/test_relationship_full_rebuild.py \
  backend/tests/test_relationship_rule_upgrade.py -q
4 passed

# 相关回归（persona / projection / determinism / reconciler / scheduler / API）
python -W error -m pytest backend/tests/test_persona_service.py \
  backend/tests/test_persona_startup.py backend/tests/test_relationship_determinism.py \
  backend/tests/test_relationship_projector.py backend/tests/test_relationship_reconciler.py \
  backend/tests/test_relationship_scheduler.py backend/tests/test_api_persona.py -q
70 passed

# 完整后端回归
python -W error -m pytest backend/tests -q
1814 passed
```

覆盖场景：

- `test_persona_activation_recomputes_projection_with_new_provenance`：activate 后投影引用新 persona、无新关系事件。
- `test_full_rebuild_produces_identical_semantics_without_delta_multiply`：rebuild 后 familiarity 不变、apply 仍 1 个。
- `test_full_rebuild_does_not_restore_suppressed_key`：suppress 后 rebuild 不重新 apply。
- `test_rule_version_change_revokes_old_apply_without_semantic_rewrite`：v2 reconciler 对 v1 apply 追加普通 revoke，无 rule_migration 事件类型。

## 边界

- 仅实现计划 Task 13 的 recompute/rebuild/rule 升级路径；未改动 authority/lineage/projection 评估核心。
- `create_and_activate` 不触发 notifier（保持既有行为，避免破坏 redact 回滚语义）。
- Task 14（C1 编码 + pre-dispatch 关系上下文重验证）尚未实施。
- 未提交 Git（按计划 Task 13 Step 5 的记录边界，建议 commit message：`feat: make relationship projections recomputable`）。
