# Gate C3 Task 9 遗留修复验收 — Reconcile Job 快照身份

> 日期：2026-08-15（会话工作区快照 20260710）
> 范围：`backend/app/repositories/relationship_migration.py`、`backend/app/repositories/relationship_ledger.py`、`backend/tests/test_relationship_migration.py`

## 背景

Gate C3 Task 9（durable local reconcile jobs and recovery）的 `RelationshipReconciler` / `RelationshipScheduler` 实现已存在，但 `backend/tests/test_relationship_reconciler.py::test_archive_after_apply_reconciles_revoke` 失败：

```
ValueError: existing relationship job identity has different semantics
```

## 根因

`relationship_reconcile_jobs` 的 attempt identity 唯一索引

```sql
idx_relationship_job_attempt_identity (scope_id, source_memory_version_id,
    relationship_rule_version, captured_authority_generation,
    captured_authority_epoch, captured_inherited_authority_fingerprint)
```

不包含捕获的源快照字段（`captured_record_head_version` / `captured_record_generation` / `captured_record_state`）。因此当源记忆被 archive（`record_generation` 递增、`record_state` 变为 archived，而 `current_version_id` 不变）时，重新 `reserve` 命中旧 job 的唯一索引，`INSERT ... ON CONFLICT DO NOTHING` 不产生新行，语义复查发现捕获的 generation/state 与当前源不一致，直接抛 `ValueError`，导致旧的 apply 永远无法被 revoke。

这与设计文档 §9「captured record head/state/generation 属于 job 元数据」以及计划 Task 9 Step 1 要求覆盖 **archive/delete/redaction** 场景不符。重复/重试/恢复不得倍增效果，但源状态变化（archive/delete/redaction）必须能触发新的 reconcile job 以撤销旧的 apply。

## 修复

1. **唯一索引升级**（`relationship_migration.py`）：`idx_relationship_job_attempt_identity` 加入 `captured_record_head_version`、`captured_record_generation`、`captured_record_state`，使 attempt identity 绑定完整的捕获源快照。
2. **旧库迁移**（`relationship_migration.py::_replace_job_attempt_identity_index`）：检测已存在的 legacy 索引（不含 `captured_record_generation`），DROP 后按新定义重建；在 `migrate_gate_c3` 的 schema 执行后调用。
3. **reserve 匹配同步**（`relationship_ledger.py::reserve_job`）：reserve 后的 SELECT 匹配条件与新索引保持一致，确保按完整快照身份去重/复用，而不是只按版本+authority 去重。

## 验证

```text
# Task 9 全部测试
python -W error -m pytest backend/tests/test_relationship_reconciler.py \
  backend/tests/test_relationship_scheduler.py backend/tests/test_relationship_recovery.py -q
15 passed

# 全部 relationship 测试（含 migration/schema/projector/ledger/authority/lineage…）
15 个文件 → 153 passed

# 完整后端回归
python -W error -m pytest backend/tests -q
1802 passed
```

> 注：1802 为 Tasks 9–11 全部实现 + 独立审阅修复后的最终计数（Task 9 修复单独验证时为 1770 passed）。

新增迁移升级测试 `test_migration_upgrades_legacy_job_attempt_identity_index`（`backend/tests/test_relationship_migration.py`）验证 legacy 索引被正确重建为含快照字段的新定义。

## 边界

- 本次仅修复 Task 9 范围内的 job 快照身份缺陷；未改动 authority、lineage、projection、Composer、Gate B 写入路径。
- 未提交 Git（按计划 Task 9 Step 5 的记录边界，建议 commit message：`feat: fix relationship reconcile job snapshot identity`）。
- Task 9 剩余能力（attempt 耗尽、stale/incompatible recovery、事务回滚等）已在既有测试中覆盖并通过。
