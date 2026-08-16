# Gate C3 Task 11 验收证据 — 冲突血缘原子化与 Authority 转移

> 日期：2026-08-15（会话工作区快照 20260710）
> 范围：`backend/app/services/memory_conflict_resolution.py`、`backend/app/api/dependencies.py`，以及 `backend/tests/test_relationship_conflict_lifecycle.py`（新建）

## 目标

按计划 Task 11：将冲突解析的 lineage 记录与关系 authority 转移原子化——

1. 每个 resolved identity 在 resolve 事务内插入 `(resolved, left)` 与 `(resolved, right)` lineage（含 conflict_id + resolution_kind），关闭冲突前完成；
2. choose_left/right 复制 selected 精确版本 code；replacement 验证显式 code；
3. 提交后调度双方 + resolved ID；dismiss_both 不创建 lineage/identity、仅调度旧双方；
4. resolved-key authority 通过 lineage closure 继承父方 suppress/reenable；分歧保守 suppress；显式 re-enable 需精确 inherited fingerprint；
5. lineage 故障注入回滚全部写入。

## 实现

### 1. `memory_conflict_resolution.py`

- 构造器新增可选 `relationship_notifier`（默认 `NoOpRelationshipChangeNotifier`），保持既有测试/调用方兼容。
- `resolve()` 在 `conflict_closed` 之后、`audit` 之前，为 `resolved_memory_id` 调用 `RelationshipLedgerRepository.append_conflict_lineage`（插入双方 lineage），并新增 `lineage` 检查点（fault injection）。
- 事务提交后（`with self._versioned.write_transaction()` 退出），调用 `_notify_relationship_change((left, right, resolved?))`：dismiss_both 只通知旧双方，其余场景通知双方 + resolved ID。notifier 异常在边界捕获，绝不影响已提交的 resolve。
- 新增 `lineage` checkpoint 加入现有 fault 参数化测试。

### 2. `dependencies.py`

- `get_memory_conflict_resolution_service` 注入 `get_relationship_change_notifier`（复用 Task 10 的 notifier 依赖）。

### 3. Authority 转移

- `RelationshipAuthorityService._evaluate` 已支持 lineage closure 继承（Task 6 实现）：`inherited_suppressed` 聚合 closure 内所有 suppress；own re-enable 需精确匹配 inherited fingerprint 才能解除；分歧（任一方 suppress）→ suppressed。Task 11 通过正确写入 lineage 使该机制生效，无需修改 authority 服务本身。

## 验证

```text
# 新增冲突生命周期测试
python -W error -m pytest backend/tests/test_relationship_conflict_lifecycle.py -q
13 passed

# 冲突 + relationship 回归
python -W error -m pytest backend/tests/test_memory_conflict_resolution.py \
  backend/tests/test_relationship_authority.py backend/tests/test_relationship_lineage.py \
  backend/tests/test_relationship_reconciler.py backend/tests/test_relationship_scheduler.py \
  backend/tests/test_relationship_startup.py backend/tests/test_relationship_mutation_hooks.py -q
45 passed

# 完整后端回归
python -W error -m pytest backend/tests -q
1802 passed（Tasks 9–11 + 独立审阅修复后最终计数；含 both_contextual/传递 suppression/rollback 不通知补充测试）
```

覆盖的关键场景：

- `test_resolve_inserts_lineage_for_both_sides_before_scheduling`：lineage 两行正确（resolved→left/right、conflict_id、resolution_kind）；notifier 收到双方 + resolved。
- `test_resolved_identity_inherits_parent_suppression`：父方 suppress → resolved identity 继承 suppressed。
- `test_parent_disagreement_resolves_to_suppression`：一方 suppress + 一方 re-enable → 分歧保守 suppressed。
- `test_dismiss_both_creates_no_lineage_and_schedules_old_sides`：dismiss 无 lineage/identity，仅调度旧双方。
- `test_resolution_fault_rolls_back_lineage[6 checkpoints]`：resolved_identity/left_archived/right_archived/conflict_closed/lineage/audit 任一故障 → lineage 与冲突状态全部回滚。
- `test_choose_left_copies_selected_exact_subject_code`：choose_left 复制 conflict 实际 left 方的精确 code。
- `test_uncoded_replacement_has_no_relationship_subject`：无 code 的 replacement → resolved identity 无 canonical_subject_code。
- `test_resolved_key_explicit_reenable_overrides_inherited_suppression`：显式 re-enable（带精确 inherited fingerprint）解除继承 suppression。

## 边界

- 仅实现计划 Task 11 的 lineage 原子化 + authority 转移接线；未改动 authority 评估核心逻辑（Task 6 已实现）、projection、Composer。
- `dismiss_both` 语义符合设计 §6.4：不创建 identity，旧 applies 保持 revoked/ineligible。
- lineage 永不通过文本推断（仅由 conflict_id 显式记录）。
- Task 12（true forget / preferred-address redaction 隐私原子化）尚未实施。
- 未提交 Git（按计划 Task 11 Step 5 的记录边界，建议 commit message：`feat: preserve relationship authority through conflicts`）。
