# Gate C3 Task 10 验收证据 — Startup Recovery 与 Mutation Notifier 接线

> 日期：2026-08-15（会话工作区快照 20260710）
> 范围：`backend/app/main.py`、`backend/app/api/dependencies.py`、`backend/app/services/relationship_hooks.py`（新建）、`relationship_reconciler.py`、`relationship_scheduler.py`、`versioned_memory_mutation.py`、`versioned_memory_commit.py`，以及 `backend/tests/test_relationship_startup.py`、`test_relationship_mutation_hooks.py`（新建）

## 目标

按计划 Task 10：为本地关系 reconcile 调度接线完整生命周期——

1. `create_app` 构建一个本地 scheduler，startup 时恢复已有 job、执行确定性收敛扫描、建立初始投影、不暴露远程能力、干净关闭；
2. 手动 create/update/archive/confirm 与自动 create/supersede/conflict-recording 在各自 Gate B 事务提交后调度受影响 memory ID；
3. notifier 失败不阻断 mutation，最终收敛由 startup 扫描保证（幂等、不重复效果）。

## 实现

### 1. `relationship_hooks.py`（新建）

```python
class RelationshipChangeNotifier(Protocol):
    def schedule(self, memory_ids: tuple[str, ...]) -> None: ...

class NoOpRelationshipChangeNotifier:  # 默认，保持既有单元构造器兼容
class RelationshipChangeNotifierImpl:  # database_url + persona_id，schedule 时用短连接
```

- `NoOpRelationshipChangeNotifier` 是默认实现，任何未注入 notifier 的既有构造路径行为不变。
- `RelationshipChangeNotifierImpl` 每个 `schedule` 调用打开 `managed_connection` 短连接，不捕获长期连接/大对象。

### 2. Mutation 侧接线

- `VersionedMemoryMutationService`（手动路径）：构造器新增可选 `relationship_notifier`；`create_manual` / `update` / `confirm_candidate` / `archive` 在各自事务提交后调用 `_notify_relationship_change_for_memory(memory_id)`。notifier 异常在边界捕获，绝不影响已提交的 Gate B mutation。
- `VersionedMemoryCommitService`（自动路径）：构造器新增可选 `relationship_notifier`；`commit_one` 成功返回后通知 `memory_id`；当结果含 `conflict_id` 时查询 `memory_conflicts` 并同时入队 left/right 两个身份（计划要求 "Automatic conflict recording must enqueue both newly conflicted identities"）。

### 3. Startup 收敛

- `RelationshipReconciler.startup_scan_memory_ids()`：确定性扫描集合 = 所有已分类 current head ∪ 所有未被 revoke 的 effective apply source ∪ 所有 lineage contributor/resolved identity，去重排序。
- `RelationshipScheduler.recover_and_scan(now)`：组合 `recover()`（恢复/终止旧 job）+ 对扫描集合 `schedule`（幂等 reservation）+ `run_pending`。
- `RelationshipScheduler.schedule` 对无法 reserve 的 memory（已删除/未分类/conflicted head）容错跳过，不阻塞扫描。
- `RelationshipReconciler.close()` / `RelationshipScheduler.close()`：lifespan shutdown 时释放长期连接，避免 Windows 文件锁。

### 4. `main.py` / `dependencies.py`

- `create_app` lifespan 在 Persona bootstrap 之后构建 scheduler：先用 managed_connection 执行 `recover_and_scan`（startup 收敛），再暴露 `app.state.relationship_scheduler`（含短生命周期裸连接）与 `app.state.relationship_change_notifier`（短连接实现）。
- 任何 relationship 初始化异常都被捕获并降级为 `scheduler=None` + `NoOpRelationshipChangeNotifier`，绝不影响应用启动或聊天。
- `dependencies.py` 新增 `get_relationship_change_notifier`（从 `app.state` 读取，默认 NoOp），注入 `get_versioned_memory_mutation_service`；`main.py` 的自动写入路径构造 `VersionedMemoryCommitService` 时同样注入。
- 未暴露任何远程能力（无 `relationship_remote_capability`、无 remote provider）。

## 验证

```text
# Task 10 新测试
python -W error -m pytest backend/tests/test_relationship_startup.py \
  backend/tests/test_relationship_mutation_hooks.py -q
11 passed

# 计划 RED 组合（startup + hooks + memory_job_service + mutation/commit 回归 + persona startup）
37 passed（含 reconciler/scheduler/recovery）

# 完整后端回归
python -W error -m pytest backend/tests -q
1802 passed（Tasks 9–11 + 独立审阅修复后最终计数）

# 前端类型检查（后端改动不影响前端契约）
npm run typecheck  →  exit 0
```

覆盖的关键场景：

- `test_startup_builds_one_scheduler_and_establishes_projection`：启动构建 scheduler、无源时保持干净 schema。
- `test_startup_with_eligible_source_establishes_current_projection`：预置 apply 后重启，投影与 apply 各恰一次。
- `test_startup_recovery_reserves_missing_jobs_without_duplicate_effects`：notifier 失败（job 缺失）→ 重启后 startup 扫描收敛恰一次，无重复 apply/无多余 revoke。
- `test_startup_no_remote_capability_exposed`：无远程能力暴露。
- `test_startup_clean_shutdown_does_not_error`：lifespan 退出干净（修复了长期连接导致的 Windows 文件锁：smoke 测试回归通过）。
- mutation hooks：create/update/archive/confirm 提交后调度；notifier 失败被捕获且 mutation 成功；默认构造器无 notifier 兼容。

## 边界

- 仅实现计划 Task 10 的本地生命周期接线；未改动 authority/lineage/projection/Composer/Gate B 写入逻辑。
- shadow（evidence-only）路径不写关系事件，未注入 notifier（计划允许零语义变化）。
- Task 11（冲突血缘 + 保守 authority 转移原子化）尚未实施。
- 未提交 Git（按计划 Task 10 Step 5 的记录边界，建议 commit message：`feat: wire relationship reconciliation lifecycle`）。
