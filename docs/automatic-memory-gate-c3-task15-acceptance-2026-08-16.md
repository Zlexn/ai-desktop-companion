# Gate C3 Task 15 验收证据 — Safe Local Relationship APIs

> 日期：2026-08-16（会话工作区快照 20260710）
> 范围：`backend/app/services/relationship_api.py`（新建）、`backend/app/api/routes/relationships.py`（新建）、`backend/app/api/dependencies.py`、`backend/app/main.py`、`backend/app/domain/schemas.py`，以及 `backend/tests/test_api_relationships.py`（新建）

## 目标

按计划 Task 15，提供仅本地的安全关系 API：

1. 只读：verified projection、分页 apply/revoke 元数据、分页 metadata-only jobs/audits；
2. 变更：显式 reconcile / full rebuild、relationship-only suppress（不改源记忆）、不可逆 preferred-address redact、显式 re-enable；
3. 隐私边界：任何响应不暴露 payload JSON、已删/已 redact 源的 version ID、lineage、私有指纹/HMAC、摘要/情感数据、Prompt/原始输出、凭据或资产路径；`source_memory_id` 与 bounded address 仅当源记忆仍可读/eligible 时返回；capabilities 显式声明无远程抽取/consent。

## 实现

### 1. `relationship_api.py`（新建）— bounded 读写服务

- 读：`projection()`（verified view 或 None）、`event_items()`（bounded 元数据 + 每事件 authority 快照）、`job_items()`、`audit_items()`（`relationship_job_audits`）、offset 游标 `page()`。
- 变更（写事务 + fence 保护）：`suppress()`（authority USER_REVOKE + append_revoke + 重投影）、`redact()`（确认后 PRIVACY_REDACT + `redact_preferred_address` + 重投影）、`reenable()`（服务端私有捕获/校验 inherited fingerprint，客户端永不接触）、`reconcile()` / `rebuild()`（幂等 full reconcile，可选 `expected_projection_version` CAS）。
- 隐私护栏：`_memory_readable()`（仅 ACTIVE 记忆暴露 `source_memory_id`）、`_bounded_address()`（仅 active、未 revoke、未 suppressed、源可读的 preferred_address apply 暴露地址）；job/audit 响应不含任何指纹/HMAC。

### 2. `routes/relationships.py`（新建）— API 表面

```text
GET  /api/relationship/capabilities
GET  /api/relationship/projection
GET  /api/relationship/events?limit=&cursor=
GET  /api/relationship/jobs?limit=&cursor=
GET  /api/relationship/audits?limit=&cursor=
POST /api/relationship/reconcile
POST /api/relationship/rebuild
POST /api/relationship/events/{apply_event_id}/suppress
POST /api/relationship/events/{apply_event_id}/redact
POST /api/relationship/authorities/{source_memory_id}/{event_type}/{subject_code}/reenable
```

- 变更请求全部 `extra="forbid"`；redact 要求 `confirm_irreversible: true`（`Literal[True]`）；re-enable 要求精确 `expected_decision_id`（null 时 generation=0）+ `expected_authority_epoch`。
- 所有变更经 `RelationshipDisclosureFence.begin_mutation()` 串行化；`StaleRelationshipAuthorityError` / stale projection version → 409；reconcile/rebuild 在 threadpool 执行。
- `capabilities` 响应显式：`local_only=True`、`remote_extraction=False`、`remote_consent_exists=False`。

### 3. `dependencies.py` / `main.py` / `schemas.py`

- `get_relationship_api_service` 注入；router 注册到 FastAPI app；新增 10 个请求/响应 schema（`RelationshipProjectionResponse`、`RelationshipEventPageResponse`、`RelationshipJobPageResponse`、`RelationshipAuditPageResponse`、`RelationshipMutationResponse`、`RelationshipSuppressRequest`、`RelationshipRedactRequest`、`RelationshipReenableRequest`、`RelationshipReconcileRequest`、`RelationshipCapabilitiesResponse` 等）。

## 验证

```text
# Task 15 新测试
python -W error -m pytest backend/tests/test_api_relationships.py -q
15 passed

# 相关回归（relationship 核心 + API + persona）
python -W error -m pytest backend/tests/test_api_relationships.py backend/tests/test_api_persona.py \
  backend/tests/test_api_chat.py backend/tests/test_api_memories.py \
  backend/tests/test_relationship_reconciler.py backend/tests/test_relationship_scheduler.py \
  backend/tests/test_relationship_projector.py backend/tests/test_relationship_authority.py \
  backend/tests/test_relationship_true_forget.py backend/tests/test_relationship_chat_disclosure.py \
  backend/tests/test_persona_service.py -q
129 passed

# 完整后端回归
python -W error -m pytest backend/tests -q
1835 passed
```

覆盖场景：

- capabilities 仅本地、无远程抽取/consent；
- 无关系记忆时 projection neutral；
- reconcile 建投影、events 分页 bounded 元数据（无 payload/fingerprint/lineage/HMAC/version id）；
- suppress 不改源记忆、投影地址消失、apply 被 revoke；
- suppress/reenable 精确 authority generation 校验（stale → 409）；
- redact 必须 `confirm_irreversible`（缺失 → 422），成功后 payload_state=redacted、地址清除；
- re-enable 服务端私有校验 inherited fingerprint，成功后 suppressed=False、action=reenable；
- reconcile/rebuild 幂等（重建不倍增 delta）；stale projection version → 409；
- OpenAPI：Relationship* schema 与路径齐全，且不含任何 forbidden 字段名。

## 边界

- 仅实现计划 Task 15 的 safe API；未动 authority/lineage/projection 评估核心。
- jobs/audits 均为 metadata-only；events 仅暴露 bounded address 与可读 `source_memory_id`。
- 未提交 Git（按计划 Task 15 Step 5 的记录边界，建议 commit message：`feat: add safe relationship APIs`）。
