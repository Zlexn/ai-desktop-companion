# 自动长期记忆与角色一致性增强 Gate C2 验收记录

> 日期：2026-07-25  
> 范围：Gate C2——受控会话摘要生成与注入、独立持久授权、撤回/失效、删除与重建、safe API 和独立 SummaryPanel。  
> 状态：**COMPLETED**；自动化验证全部通过，Task 15 修复复审 `APPROVED`，Gate C2 最终独立终审 `APPROVED`。本文件不把 Gate C3、Electron、Live2D、私人素材摄取或语音克隆写成已完成。

## 环境与工作树约束

- Windows 11，Python 3.12.6，FastAPI/SQLite/pytest；React/TypeScript/Vite/Vitest。
- 工作树在 Gate C2 前已存在 Gate A/B/C1 与历史未提交改动，并持续保持 dirty/unstaged。本轮未执行 stage、commit、push、reset、restore、clean 或 stash。
- 私人图片、视频、音频、声音参考及第三方角色素材未进入实现、测试、快照、验收证据或发行包。
- 自动验收使用 fake/recording Provider；未使用真实 API Key，也没有成功调用真实 Anthropic/DeepSeek 摘要服务。首次运行 privacy contract 时测试漏注入 chat Provider，因而以动态随机测试文本和明确无效的 `test-only` key 向 DeepSeek chat endpoint 发出过一次请求并收到 `401 Unauthorized`；不含用户数据、私人素材或真实凭据，不作为验收证据。测试随后改为注入 recording chat Provider并通过全套重跑。

## 实现结论

- 摘要 processing 与 injection 使用独立 consent 行、generation、policy fingerprint、dispatch fence、API 与 UI 控件；聊天、记忆抽取/写入、情感授权及环境配置均不能替代二者。
- 未授权、拒绝、撤回、stale policy 或 capability disabled 时，生成与注入 fail closed；远程未授权路径在 Provider 构造前停止。
- 生成只使用原子 completed chat turn；job 保存 sealed exact source manifest、logical identity/attempt epoch 与 barrier/authority/session-deletion/suppression 快照。
- durable scheduler 恢复兼容任务并 terminalize 不兼容任务；重复 source/epoch reservation 幂等。
- Provider I/O 不持有 SQLite write transaction；in-flight authority、barrier、source exclusion、session deletion 或 suppression 变化使结果丢弃且不提交摘要正文。
- exact active 摘要由 deterministic selector 按独立 injection authority 与 bounded relevance/字符预算选择；pre-chat disclosure fence 在 Provider send 前重新验证。任一失效时整组摘要清空并重组上下文。
- irreversible redaction 将 `summary_text` 物理置 NULL；source-set suppression 阻止自动复活；重建要求显式 one-time permit 和 generation CAS，只读取仍安全的完整轮次。
- true-forget 将相关 user/assistant echo 两侧都加入 exclusion、推进 barrier、清除受影响摘要、建立 suppression；重建不会重读已忘记内容。
- session deletion 与摘要 job/disclosure 竞态 fail closed；删除 source session 后聊天可无摘要继续，已删除 active chat session 不调用聊天 Provider。
- safe public APIs 不返回 source-set/logical identity/attempt epoch/policy fingerprint/rebuild permit/raw Provider output/Prompt/source IDs。
- SummaryPanel 独立于 Memory/Emotion/Persona，区分本地与远程语义，展示 exact disclosure fields，使用行内确认并安全呈现 active、stale-barrier redaction、redacted、quarantined、legacy 与 replacement 状态。

## 主张到自动化证据

| 主张 | 主要证据 |
|---|---|
| 独立 processing/injection 授权与 policy CAS | `test_summary_authorities.py`, `test_api_summaries.py`, `test_gate_c2_http_smoke.py` |
| 未授权/撤回零远程构造与发送 | `test_summary_job_service.py`, `test_gate_c2_http_smoke.py` |
| 原子完整轮次与 sealed exact sources | `test_chat_turn_repository.py`, `test_summary_source_snapshots.py`, `test_summary_job_repository.py` |
| durable recovery/dedup/incompatible terminalization | `test_summary_job_scheduler.py`, `test_gate_c2_http_smoke.py` |
| in-flight discard 与无事务 Provider I/O | `test_summary_dispatch_fences.py`, `test_summary_job_service.py`, `test_gate_c2_http_smoke.py` |
| deterministic selection/composition/budget | `test_summary_selection.py`, `test_context_data_encoder.py`, `test_context_composer.py` |
| pre-chat revalidation、zero-summary fallback、session deletion | `test_summary_chat_disclosure.py`, `test_summary_session_deletion.py`, `test_gate_c2_http_smoke.py` |
| suppression/redaction/rebuild/one-time permit | `test_summary_rebuild.py`, `test_api_summaries.py`, `test_gate_c2_http_smoke.py` |
| true-forget turn closure/physical NULL/safe rebuild | `test_summary_true_forget.py`, `test_gate_c2_http_smoke.py` |
| public API metadata-only 与 stale safe label | `test_api_summaries.py`, `test_gate_c2_privacy_contract.py` |
| runtime privacy values与 bounded review surface | `test_gate_c2_privacy_contract.py` |
| 独立安全 SummaryPanel | `frontend/src/components/SummaryPanel.test.tsx`, `frontend/src/api/client.test.ts`, `frontend/src/App.test.tsx` |

## 实际验证命令与结果

### Gate C2 warning-strict 聚焦套件

计划中的命令列出了不存在的 `backend/tests/test_summary_invalidation.py`，首次运行因此退出 4、未执行测试。实际 invalidation 覆盖位于 `test_summary_rebuild.py`、`test_summary_true_forget.py` 与 `test_summary_session_deletion.py`。删除不存在路径后重跑：

```text
python -W error -m pytest backend/tests/test_session_summary_contract.py backend/tests/test_summary_c2_migration.py backend/tests/test_chat_turn_repository.py backend/tests/test_summary_authorities.py backend/tests/test_summary_dispatch_fences.py backend/tests/test_summary_source_snapshots.py backend/tests/test_summary_job_repository.py backend/tests/test_summary_job_scheduler.py backend/tests/test_summary_job_service.py backend/tests/test_summary_rebuild.py backend/tests/test_summary_true_forget.py backend/tests/test_summary_session_deletion.py backend/tests/test_summary_selection.py backend/tests/test_summary_chat_disclosure.py backend/tests/test_api_summaries.py backend/tests/test_gate_c2_http_smoke.py backend/tests/test_gate_c2_privacy_contract.py backend/tests/test_context_data_encoder.py backend/tests/test_context_composer.py backend/tests/test_chat_service.py -q
297 passed in 21.73s
```

### Gate A/B/C1 与阶段受影响回归

```text
python -W error -m pytest backend/tests/test_gate_b_http_smoke.py backend/tests/test_gate_b_privacy_contract.py backend/tests/test_gate_c1_http_smoke.py backend/tests/test_gate_c1_privacy_contract.py backend/tests/test_memory_forget_service.py backend/tests/test_session_deletion_coordinator.py backend/tests/test_memory_conflict_resolution.py backend/tests/test_emotion_context.py backend/tests/test_emotion_analysis_service.py backend/tests/test_expression_plan_service.py backend/tests/test_api_chat.py backend/tests/test_api_persona.py -q
146 passed in 14.92s
```

### 后端全量

```text
python -W error -m pytest backend/tests -q
1593 passed in 91.44s
```

### 前端全量、类型与构建

```text
npm --prefix frontend test
32 test files passed; 258 tests passed in 15.20s
npm --prefix frontend run typecheck
exit 0
npm --prefix frontend run build
Vite 8.0.16: 50 modules transformed; build succeeded in 158ms
```

Task 15 修复后聚焦前端：

```text
npm --prefix frontend test -- src/api/client.test.ts src/components/SummaryPanel.test.tsx src/App.test.tsx
3 test files passed; 51 tests passed
```

### 编译与 whitespace

```text
python -m compileall -q backend/app
exit 0
git diff --check
exit 0
```

`git diff --check` 仅输出 Windows 工作副本既有 LF→CRLF advisory，没有 whitespace error，也没有执行 Git 修改操作。

## 隐私与删除证据

- `test_gate_c2_privacy_contract.py` 每次动态生成 source text、deleted summary payload、Provider raw output、API-key sentinel、HMAC key/digest、source-set/policy fingerprints、rebuild permit 与 private-asset path。
- 所有动态值均检查不出现在 public summary API JSON、captured logs、SummaryPanel fixture 或 bounded tracked + untracked review surface。
- SQLite 直接断言 irreversible redaction 后 `(summary_text, payload_state) == (NULL, 'redacted')`。
- private irreversible fingerprints/permit 只允许存在于其专用 consent/job/suppression 列中；public audit unions 和 frontend contract 不暴露这些字段。
- `summary_authority_audits`、`summary_job_audits`、`summary_suppression_audits`、`summary_payload_audits` 的 schema 与实际行均不包含 source/summary text、Prompt 或 raw response。
- HMAC key 保持在 SQLite/Git 外；真实凭据与私人素材未参与验收。

## 已知边界与诚实限制

- 真实远程 Provider 未作为本次自动验收证据调用；远程契约由 recording adapters、factory/send counters、fingerprints 与 dispatch fences 验证。真实供应商可用性、网络延迟、配额和输出质量仍未验证。
- HTTP smoke 对 queue-priority fence 的底层顺序由专用 async 单测覆盖；HTTP 层验证 revoke-before-dispatch、in-flight discard、redaction-before-next-send 和 source deletion fallback。没有把单个 TestClient 跨线程调度时序当作生产并发证明。
- C3 relationship event ledger/projection/UI 尚未实施；summary text 仍不得作为关系、Memory Governor、Persona 或 emotion 的事实来源。
- Electron、Live2D、私人素材摄取、语音克隆与发行打包仍未实施或授权。
- 未执行提交、推送或任何 Git 清理。

## 独立审阅

Task 15 的独立 reviewer 曾返回 `CHANGES_REQUIRED`，指出 injection disclosure fields、stale public state 和 state-rendering tests 不足；修复并复验后明确返回：

```text
APPROVED
```

Gate C2 完整 diff、设计/计划、HTTP smoke、privacy contract 与上述新鲜验证证据经独立 reviewer 读取并复跑 acceptance contracts（`11 passed in 5.28s`），最终明确返回：

```text
APPROVED
```

无未解决 high/critical privacy、correctness、concurrency、stage-boundary 或 acceptance-integrity 阻塞项。
