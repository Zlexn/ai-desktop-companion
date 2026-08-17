# Gate C3 验收记录（Task 19）— 状态：PENDING（等待人工评分卡与独立终审）

> 日期：2026-08-16（会话工作区快照 20260710）
> 计划：`docs/superpowers/plans/2026-07-26-automatic-memory-gate-c3-relationship-projection.md` Task 19
> 说明：本记录如实列出已完成的技术证据与仍未满足的验收条件。**Gate C3 目前不视为完成**；
> 人工质量评分卡（Step 3）与独立技术终审（Step 4）未完成，缺少任一即保持 `PENDING`。

## 1. 实施范围（已实现）

Tasks 1–18 全部实现并各自自检/验收：

- Tasks 1–2：契约、bounded 配置、domain types、显式 `canonical_subject_code` API 类型；
- Task 3：事务性 SQLite migration、显式 subject 约束、append-only/guarded redaction、authority/lineage epoch、projection CAS、migration rollback 不变量；
- Task 4：显式 `canonical_subject_code` 持久化到全部 Gate B memory-version 写入路径；
- Task 5：精确 current-head source snapshots、storage-type fail-closed、allowlisted rules；
- Task 6：append-only authority decisions、lineage closure、私有 inherited fingerprint、resolved-key re-enable；
- Task 7：事务绑定幂等 apply/revoke、one-use guard payload redaction；
- Task 8：稳定语义排序、familiarity fold、projection CAS、verified view、neutral fail-closed；
- Task 9：durable reconcile/scheduler/recovery + job attempt identity 修复（15/15）；
- Task 10：startup recovery + mutation notifier；
- Task 11：冲突血缘原子化 + authority 转移（16 tests）；
- Task 12：隐私原子化（revoke+suppress+payload NULL+无地址投影）+ 锁序 + forget 集成；
- Task 13：Persona 切换 / rule 升级 / safe full rebuild；
- Task 14：关系上下文编码与 pre-dispatch 重验证注入（ChatService 接线）；
- Task 15：safe local relationship APIs（`/api/relationship/*`）；
- Task 16：显式记忆分类 UI + 独立 RelationshipPanel（前端）；
- Task 17：完整生命周期/独立性/HTTP smoke/隐私契约矩阵；
- Task 18：固定回放夹具（30 问题）+ 评分卡模板 + 评分算术校验。

## 2. Claim-to-test 矩阵（代表性）

| 声明 | 证据 |
|---|---|
| 只有精确 eligible 当前版本贡献、无 stale/invalid 侧 | `test_gate_c3_lifecycle_matrix.py`（13 tests） |
| Evidence/支持零独立关系影响 | 同上 + `test_relationship_sources.py` |
| 冲突五种解决 + 血缘/抑制继承 | `test_relationship_conflict_lifecycle.py`（16）+ lifecycle matrix |
| suppression 跨 edits/rebuild/recovery/Persona/rule 存活至显式 re-enable | lifecycle matrix + `test_relationship_persona_switch.py` + `test_relationship_rule_upgrade.py` |
| true forget 清除地址 payload + 全表面缺席 | `test_relationship_true_forget.py` + `test_gate_c3_privacy_contract.py` |
| projection 历史只存 event IDs/codes/numbers 不存地址文本 | privacy contract + `test_relationship_projection_view.py` |
| 确定性投影/排序/familiarity 上限 | `test_relationship_determinism.py` + projector tests |
| Persona 切换不发明关系变化 | `test_relationship_persona_switch.py` + `test_gate_c3_independence.py` |
| 摘要/情感/消息/助手文本不 source 关系事实 | `test_gate_c3_independence.py`（6 tests） |
| 关系失败不阻断聊天 | `test_relationship_chat_disclosure.py` + `test_gate_c3_http_smoke.py` |
| C1 编码/manifest 隐私边界 | `test_relationship_chat_disclosure.py` + privacy contract + `test_context_composer.py` |
| 固定回放 30 问题 + 无复活 + 确定性输出身份 | `test_gate_c3_fixed_replay.py`（5 tests） |
| 无远程抽取/consent（仅本地） | `/api/relationship/capabilities` + `test_api_relationships.py` |
| forbidden public keys 不在 API/OpenAPI | `test_gate_c3_privacy_contract.py` + `test_api_relationships.py` |

## 3. 精确命令与结果（warning-strict）

```text
python -W error -m pytest backend/tests -q
1865 passed（Task 18 基线 1865，含全部 Gate C3 契约）

python -W error -m pytest backend/tests/test_gate_c3_privacy_contract.py \
  backend/tests/test_relationship_true_forget.py \
  backend/tests/test_relationship_privacy_transactions.py \
  backend/tests/test_relationship_chat_disclosure.py \
  backend/tests/test_gate_c3_fixed_replay.py -q
20 passed

python -m compileall -q backend/app      # OK
git diff --check                          # exit 0（无空白错误；LF→CRLF 为既有 advisory）
npm --prefix frontend run typecheck       # PASS
npm --prefix frontend test -- src/api/client.test.ts src/components/MemoryPanel.test.tsx src/components/RelationshipPanel.test.tsx src/App.test.tsx
74 passed（覆盖全部改动前端文件）

# 受限项（沙箱环境限制，非代码缺陷）：
npm --prefix frontend test（全量）与 npm --prefix frontend run build
→ vite 配置加载阶段 node 子进程 piped stdio 被文件沙箱拦截（spawn EPERM）；用户已拒绝提权审批。
```

## 4. 生成值隐私证据

- 运行时随机哨兵（地址/来源 prose/API key 模式/HMAC/私有指纹/资产路径）经
  `test_gate_c3_privacy_contract.py` 验证：忘后地址从 relationship_events /
  relationship_projections / reconcile_jobs / job_audits / authority_decisions /
  memory_lineage / 捕获日志 / Provider call / manifest 全部缺席；apply payload
  物理 NULL；`forgotten_sentinel` 不回放复活。
- Git 审阅面：`git ls-files` 仅 `.env.example`（模板）；工作树 `git status --short` 干净；
  代码/文档面扫描到的 `sk-*`、`ghp_*`、RSA key 等模式全部为既有测试的负例夹具
  （断言会被净化/拒绝），无真实密钥/令牌/HMAC/私有资产路径入库。

## 5. True-forget 证明

`test_relationship_true_forget.py` + `test_gate_c3_privacy_contract.py`：同一 Gate B
写事务内 revoke + suppress + payload 物理清 NULL + 激活无地址投影；全部可读表面断言哨兵缺席。

## 6. 人工评估分数 — **PENDING**

- 已提供：`docs/gate-c3-evaluation-scorecard-template.md`（盲评协议、五类别 0–2 分、
  阈值 `>= 1.6` 无舍入、低分 `< 5%`、多名审阅者独立判定、`PASS/FAIL/PENDING`）。
- `test_gate_c3_fixed_replay.py` 校验评分算术但不伪造人工分数。
- **未完成**：真实 30 回复盲评（需人类评审者对真实配置聊天 Provider 的回复打分；
  fake/recording 证据不计入人工阈值）。未满足 → Gate C3 保持 `PENDING`。

## 7. 独立技术终审 — **PENDING**

- 需向独立评审者提供：已批准设计、本计划、完整当前 diff、上述命令/结果、隐私证据、
  人工评分卡；仅显式 `APPROVED` 且无未解决 high/critical 发现才能关闭 C3。
- 本会话未执行独立终审 → Gate C3 保持 `PENDING`。

## 8. 已知限制

- 全量前端测试与 `npm run build` 因沙箱 `spawn EPERM` 未在本会话运行（用户拒绝提权）；
  已用覆盖全部改动文件的定向测试 + typecheck 替代。
- 未刻意运行真实聊天 Provider（避免把 fake 回复当作人工质量证据）；人工闸门因此保持 PENDING。

## 9. 树状态与提交声明

- `git status --short` 干净；最近提交：`8ad352c test: add Gate C3 fixed replay evaluation`。
- 未对本记录做 Git 变更（本记录为工作区新文件，待人工/终审步骤完成后一并归档提交）。

## 10. 结论

Gate C3 **PENDING**：全部自动化技术证据通过（后端 1865 passed、隐私证据 20 passed、
compileall/diff-check/typecheck/定向前端 74 passed），但 Step 3（人工评分卡）与
Step 4（独立终审）未完成。按计划要求，缺少人工评分或独立终审任一即不得标记完成。
准确 blocker：**① 真实 30 回复盲评评分卡缺失；② 独立技术终审 APPROVED 缺失；
③ 沙箱阻止全量前端测试/build 运行（用户已拒绝提权）**。
