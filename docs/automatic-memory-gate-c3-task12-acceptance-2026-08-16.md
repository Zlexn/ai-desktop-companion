# Gate C3 Task 12 验收证据 — True Forget 与 Preferred-Address Redaction 隐私原子化

> 日期：2026-08-16（会话工作区快照 20260710）
> 范围：`backend/app/services/relationship_privacy.py`（新建）、`relationship_dispatch.py`（新建）、`memory_forget_service.py`、`api/routes/memories.py`、`api/routes/sessions.py`、`api/dependencies.py`、`main.py`，以及 `backend/tests/test_relationship_true_forget.py`、`test_relationship_privacy_transactions.py`、`test_relationship_session_deletion.py`（新建）

## 目标

按计划 Task 12：让 true forget 与 preferred-address redaction 在**一个事务**内移除所有可读副本——

1. 捕获 eligible apply、append/ensure revoke、append suppress authority、物理清 NULL apply payload、清除源记忆/版本 payload、激活无地址投影、保留 metadata-only no-revival 行、全表面移除哨兵；
2. 每个操作后故障注入全回滚；
3. race：queued 隐私 mutation 在 chat disclosure 前优先；
4. session deletion 仅在源记忆独立失效时触发隐私，否则保留事件；
5. 冻结锁序 `SummaryProcessingFence → RelationshipDisclosureFence → SummaryDisclosureFence`。

## 实现

### 1. `relationship_privacy.py`（新建）

`RelationshipPrivacyPrimitive`——在 caller-owned Gate B 写事务内运行（要求 `in_transaction`，绝不打开嵌套独立连接）：

- `purge_preferred_address(source_memory_id, now)`：
  - 枚举 active preferred-address apply → `ledger.redact_preferred_address`（append revoke + one-use guard + 物理 `payload_json=NULL` + 删除 guard）；
  - `_append_suppression`：追加 `PRIVACY_REDACT` suppress authority（若已 suppress 则跳过），阻止 reapply/rebuild/rule-upgrade 复活；
  - 通过 `RelationshipProjector.project` 激活无地址投影（Persona-aware，从 active artifact 解析）；
  - fault checkpoint：`begin` / `redacted_apply` / `after_suppress` / `projection`。

### 2. `relationship_dispatch.py`（新建）

`RelationshipDisclosureFence(PriorityAsyncFence)`——复用 C2 的 `PriorityAsyncFence` 机制（queued mutation 优先、hold_dispatch 阻断）。

### 3. 集成

- `MemoryForgetService._forget_formal_memory`：在 `redact_versions` 前，**仅当该记忆存在 active preferred-address 关系**时调用 `purge_preferred_address`（普通记忆完全不受影响，既有 forget 测试零回归）。
- `api/routes/memories.py` forget 路由：按锁序 acquire `RelationshipDisclosureFence` **先于** `SummaryDisclosureFence`。
- `api/routes/sessions.py` delete 路由：锁序 `SummaryProcessing → Relationship → SummaryDisclosure`。
- `api/dependencies.py` / `main.py`：新增 `get_relationship_disclosure_fence` 与 `app.state.relationship_disclosure_fence`。

## 验证

```text
# Task 12 新测试
python -W error -m pytest backend/tests/test_relationship_true_forget.py \
  backend/tests/test_relationship_privacy_transactions.py \
  backend/tests/test_relationship_session_deletion.py -q
7 passed

# 相关隐私回归（forget/summary/session/API/conflict）
python -W error -m pytest backend/tests/test_memory_forget_service.py \
  backend/tests/test_summary_true_forget.py backend/tests/test_summary_session_deletion.py \
  backend/tests/test_api_memories.py backend/tests/test_api_sessions.py \
  backend/tests/test_relationship_conflict_lifecycle.py -q
84 passed

# 完整后端回归
python -W error -m pytest backend/tests -q
1809 passed
```

覆盖场景：

- `test_privacy_primitive_removes_address_from_apply_and_projection`：payload 物理 NULL、revoke、suppress、哨兵消失。
- `test_privacy_fault_rolls_back_all_writes`：after_suppress 故障 → payload 仍 active、无 revoke。
- `test_memory_forget_integration_purges_relationship_address`：真实 forget 服务端到端清除 + 投影无哨兵。
- `test_relationship_fence_*`：fence 结构、hold_dispatch 阻断、串行化、queued mutation 优先。
- `test_session_deletion_keeps_relationship_event...`：session 删除不失效记忆时事件保留。

## 边界

- 仅实现计划 Task 12 的隐私原子化；未改动 authority/lineage/projection 评估核心。
- `purge_preferred_address` 仅在存在 preferred-address 关系时触发，普通记忆 forget 路径不变。
- Task 13（Persona 切换 / rule 升级 / safe full rebuild）尚未实施。
- 未提交 Git（按计划 Task 12 Step 5 的记录边界，建议 commit message：`feat: integrate relationship true forget`）。
