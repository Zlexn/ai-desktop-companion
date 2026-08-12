# 自动长期记忆与角色一致性增强 Gate C1 验收记录

> 日期：2026-07-22  
> 范围：Gate C1——不可变 Persona artifact、确定性 Context Composer、reply/job Persona provenance、C2 前远程摘要 fence、最小 PersonaPanel。  
> 状态：**COMPLETED**；自动化验证全部通过，独立终审 `APPROVED`。本文件不会把 C2 摘要处理/注入或 C3 关系投影写成已完成。

## 环境与仓库约束

- Windows 11，Python 3.12.6，FastAPI/SQLite/pytest；React/TypeScript/Vite/Vitest。
- 工作树在 Gate C1 前已存在大量未提交改动。本轮未执行 stage、commit、push、reset、restore、clean 或 stash。
- 私人图片、视频、音频和声音参考材料未进入实现、测试、快照或验收证据。
- 未调用真实远程摘要、远程记忆提取或远程情感分析作为验收证据。

## 实现结论

- Persona 以 append-only artifact 和 CAS active pointer 持久化；完整性验证失败时启动和聊天均 fail closed，不回退到每轮读取 YAML。
- 当前用户输入在持久化前执行独立 8000 字符硬限；Composer 只在末尾附加一次当前消息。
- 动态记忆/情感通过版本化 canonical JSON 不可信数据边界编码；摘要与关系层在 C1 保持空。
- Composer 与 Anthropic/DeepSeek/Fake adapters 共享精确 payload normalization，并在 Adapter 发网前验证 `ChatDispatchBudget`。
- assistant message 保存 metadata-only `context_manifest`；Provider 同名 metadata 不能覆盖。manifest 不含 Persona Prompt、完整 hash、记忆/情感文本、删除内容或完整 payload。
- 同一 composition 的 Persona artifact ID 同步写入 assistant manifest 与新自动记忆 job；旧 job 的 NULL provenance 保持兼容且不伪造回填。
- `SESSION_SUMMARY_PROVIDER=llm` 在 C2 专用授权机制前使用 no-op scheduler；不调用显式或默认 summary factory，不构造远程 Provider、不调度远程摘要、不发送字节。其它 consent 不能替代该缺失授权。
- PersonaPanel 只使用安全 API 字段，支持 current/list/create/activate/redact/capabilities，变更操作有明确确认；redacted history 固定显示“内容已清除”。

## 契约与证据矩阵

| 主张 | 主要自动化证据 |
|---|---|
| Persona schema/CAS/append-only/redaction/integrity | `test_persona_migration.py`, `test_persona_repository.py`, `test_persona_service.py`, `test_persona_startup.py` |
| Canonical compiler 与冻结 bootstrap hash | `test_persona_compiler.py`, `test_prompt_renderer.py` |
| Safe Persona API/capabilities | `test_api_persona.py` |
| Current-message exclusion、eligible memory provenance | `test_context_builder.py` |
| Untrusted canonical data envelope | `test_context_data_encoder.py` |
| Deterministic ordering/trimming/protected overflow | `test_context_composer.py` |
| Adapter normalized count/dispatch budget | `test_provider_payload_normalization.py`, `test_chat_service.py` |
| Reply manifest namespace、Provider metadata allowlist 与无内容泄漏 | `test_chat_service.py`, `test_gate_c1_privacy_contract.py` |
| HTTP bootstrap/no-change/CAS/reactivate/redact/restart/over-limit | `test_gate_c1_http_smoke.py` |
| HTTP in-flight Persona switch 下 exact reply/job provenance | `test_gate_c1_http_smoke.py`, `test_chat_service.py`, `test_memory_job_scheduler.py`, `test_memory_automation_repository.py` |
| Open-conflict/archived memory exclusion、对抗数据编码、residual protected-only dispatch | `test_gate_c1_http_smoke.py`, `test_context_data_encoder.py`, `test_context_composer.py` |
| Bounded review surface、日志、完整 fingerprints/compiled Prompt/raw Provider/API/HMAC/deleted payload/private path | `test_gate_c1_privacy_contract.py` |
| Remote summary zero construction/send | `test_api_persona.py`, `test_provider_factory.py`, `test_gate_c1_http_smoke.py` |
| Minimal safe PersonaPanel | `frontend/src/components/PersonaPanel.test.tsx`, `frontend/src/api/client.test.ts`, `frontend/src/App.test.tsx` |

## 实际验证命令与结果

1. Gate C1 warning-strict 聚焦套件：

```text
python -W error -m pytest backend/tests/test_persona_migration.py backend/tests/test_persona_compiler.py backend/tests/test_persona_repository.py backend/tests/test_persona_service.py backend/tests/test_api_persona.py backend/tests/test_context_data_encoder.py backend/tests/test_context_composer.py backend/tests/test_provider_payload_normalization.py backend/tests/test_chat_service.py backend/tests/test_memory_job_scheduler.py backend/tests/test_memory_automation_repository.py backend/tests/test_gate_c1_http_smoke.py backend/tests/test_gate_c1_privacy_contract.py -q
190 passed in 14.69s
```

2. Gate A/B 与阶段受影响回归：

```text
python -W error -m pytest backend/tests/test_gate_b_http_smoke.py backend/tests/test_gate_b_privacy_contract.py backend/tests/test_memory_forget_service.py backend/tests/test_session_deletion_coordinator.py backend/tests/test_memory_conflict_resolution.py backend/tests/test_emotion_context.py backend/tests/test_emotion_analysis_service.py backend/tests/test_expression_plan_service.py backend/tests/test_api_chat.py -q
118 passed in 13.87s
```

3. 后端全量：

```text
python -W error -m pytest backend/tests -q
1316 passed in 89.81s
```

4. Python 编译：

```text
python -m compileall -q backend/app
exit 0
```

5. 前端全量、类型和构建：

```text
npm --prefix frontend test
31 files passed; 250 tests passed in 21.17s
npm --prefix frontend run typecheck
exit 0
npm --prefix frontend run build
Vite 8.0.16: 49 modules transformed; build succeeded in 142ms
```

6. whitespace 检查：

```text
git diff --check
exit 0
```

Windows 工作副本输出 LF→CRLF advisory；没有 whitespace error，且未执行任何 Git 修改操作。

## 隐私与删除结论

- Persona public API 只返回 bounded config、版本字段与 12 字符 fingerprint prefix；不返回完整 hash 或编译 Prompt。
- Persona irreversible redaction 后，SQLite 的 `source_content_json` 与 `rendered_system_prompt` 均为 NULL；public list/detail 不返回 sentinel。
- Provider metadata 使用固定 allowlist；测试 Provider 返回的 `raw_response`、`api_key` 和未知 metadata 均不进入 SQLite 或 public API。
- 隐私契约从实际运行时 Persona 行读取完整 `content_identity_hash`、`behavior_fingerprint` 和 active compiled Prompt，并与实际生成的 HMAC key/digest、Provider raw output、API-key sentinel、deleted Persona payload、private-asset path 一起检查 public API、captured logs、frontend fixture 及 bounded tracked + untracked review surface。
- context manifest 只保存 ID、版本、selected counts、固定 reason counts 和预算数值。
- API keys 仍只来自后端环境；本次未向前端、SQLite、日志或验收记录写入真实 key。
- HMAC source-reference key 仍位于 SQLite/Git 之外，本次未改变 Gate B 的 privacy contract。

## 明确未完成与边界

- C2 的摘要 processing consent、in-flight revocation/discard、摘要 rebuild/invalidation 和摘要注入尚未实现。
- C3 的 relationship event ledger、projection、UI 和集成角色一致性评估尚未实现。
- Electron、Live2D、私人素材摄取和语音克隆不属于 Gate C1。
- 未执行提交或发布。

## 独立审阅

独立 Agent 在先前终审中返回 `CHANGES_REQUIRED`，指出 HTTP smoke 覆盖和 privacy contract 的日志/review-surface 证据不足。修复后，Agent 重新读取当前规格、计划、实现、测试、完整脏工作树 diff 与最新验证证据，最终明确返回：

```text
APPROVED
```

无未解决的 high/critical privacy、correctness、concurrency、stage-boundary 或 acceptance-integrity 阻塞项。
