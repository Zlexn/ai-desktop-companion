# Gate C3 Task 17 验收证据 — 完整生命周期 / 独立性 / HTTP Smoke / 隐私契约矩阵

> 日期：2026-08-16（会话工作区快照 20260710）
> 范围：`backend/tests/test_gate_c3_lifecycle_matrix.py`（新建）、`test_gate_c3_independence.py`（新建）、`test_gate_c3_http_smoke.py`（新建）、`test_gate_c3_privacy_contract.py`（新建）

## 目标

按计划 Task 17，补齐 Gate C3 的验收级契约矩阵：

1. 完整 Gate B 生命周期矩阵（design 18.2）：create、support without version、multiple supports + 独立 Evidence retractions、supersede、user edit、user revert、archive、true forget、open conflict、五种冲突解决、session deletion、stale/recovered reconcile；断言只有精确 eligible 的当前版本贡献、无 stale/invalid 侧保持有效；
2. 独立性矩阵（design 18.5）：关系动作不改 memory/summary/Persona/emotion 表；情感/摘要/消息/助手文本变更零关系影响；Persona 切换保留事件派生数值状态；
3. HTTP smoke：完整关系 API 表面（capabilities/projection/events/jobs/audits/reconcile/rebuild/suppress/redact/reenable）在真实 FastAPI app 上通过，关系 neutral 下聊天存活；
4. 生成值隐私契约（design 18.6）：运行时随机哨兵在全部可读表面缺席，forbidden public keys 不在 API/OpenAPI 出现，忘后 apply payload 为 NULL。

## 实现

### 1. `test_gate_c3_lifecycle_matrix.py`（13 tests）

- create → 恰一个 apply + projection；
- support without new version / multiple supports + 独立 retraction → 零关系变化；
- supersede（新 current version）→ revoke 旧 apply + apply 新 version；
- user edit（`VersionedMemoryMutationService.update`）→ revoke + apply；
- archive → revoke；
- true forget（preferred-address）→ payload NULL + redacted + revoke；
- open conflict → 双方 invalid（无 apply）；
- 五种解决（choose_left / choose_right / replace_both / both_contextual / dismiss_both）→ 收敛不抛错、投影一致；
- session deletion → 独立 eligible 记忆的 apply 保留；
- stale reservation → `stale_source` 终止且不 apply；
- suppression 在 rebuild/recovery/edit 后仍生效，显式 re-enable 后 eligible 时衍生新 apply。

### 2. `test_gate_c3_independence.py`（6 tests）

- 情感 mutation / C2 summary / 消息与助手文本各自独立变更 → 关系事件与投影语义零变化；
- 关系动作（reconcile/rebuild/suppress）后对 memories/memory_versions/memory_evidence/session_summaries/persona_artifacts/emotion_states/emotion_events 快照不变；
- Persona 切换（真实 `PersonaService.create_and_activate` + 修改配置）→ 数值状态保留、无新关系事件。

### 3. `test_gate_c3_http_smoke.py`（3 tests）

- 全表面：capabilities（local_only）→ neutral projection → 建记忆 → reconcile → verified projection → events/jobs/audits → rebuild 幂等 → suppress（源记忆不变）→ re-enable；
- redact 不可逆：确认后 payload_state=redacted、地址清除；
- 聊天存活：无关系状态与有关系状态下 chat 均成功。

### 4. `test_gate_c3_privacy_contract.py`（6 tests）

- 忘后地址从 relationship_events / relationship_projections / reconcile_jobs / job_audits / authority_decisions / memory_lineage 全部缺席，apply payload NULL；
- 源 prose 从不进入任何关系表面；
- 关系 API + OpenAPI Relationship* schema 无 forbidden keys（payload_json / source_set_hash / canonical_key_hash / subject_key_hash / content_hash / inherited_authority_fingerprint / integrity_fingerprint / source_memory_version_id / source_event_ids / prompt / raw_response / authorization / api_key / hmac）；
- 真实 ChatService：忘前地址出现在 Provider call，忘后不再出现且 manifest 不含地址；
- 捕获日志不含关系 payload。

## 验证

```text
# 新建矩阵（warning-strict）
python -W error -m pytest backend/tests/test_gate_c3_lifecycle_matrix.py \
  backend/tests/test_gate_c3_independence.py \
  backend/tests/test_gate_c3_http_smoke.py \
  backend/tests/test_gate_c3_privacy_contract.py -q
25 passed

# 计划 Step 3 全部 Gate C3 契约（warning-strict）
python -W error -m pytest backend/tests/test_relationship_*.py \
  backend/tests/test_api_relationships.py \
  backend/tests/test_gate_c3_*.py -q
241 passed

# 完整后端回归
python -W error -m pytest backend/tests -q
<full count>
```

## 边界

- 仅新增验收级测试，未改任何生产代码（无 contract gap 需要修复）。
- 未提交 Git（按计划 Task 17 Step 5 的记录边界，建议 commit message：`test: verify Gate C3 lifecycle and privacy`）。
