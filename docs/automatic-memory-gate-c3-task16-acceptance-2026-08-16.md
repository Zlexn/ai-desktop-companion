# Gate C3 Task 16 验收证据 — 显式记忆分类 UI 与独立 RelationshipPanel

> 日期：2026-08-16（会话工作区快照 20260710）
> 范围：`frontend/src/components/RelationshipPanel.tsx`（新建）、`RelationshipPanel.test.tsx`（新建）、`api/types.ts`、`api/client.ts`、`components/MemoryPanel.tsx`、`MemoryPanel.test.tsx`、`App.tsx`、`App.test.tsx`、`components/ChatLayout.tsx`、`styles.css`

## 目标

按计划 Task 16：

1. MemoryPanel 为手动新建/编辑与候选确认提供可选的关系主题选择（固定标签、编辑保留/清除语义、preferred-address 内容必须是准确称呼、绝不猜测代码）；
2. 独立 RelationshipPanel：可折叠本地说明、熟悉度/连续性/当前称呼、Persona/投影/规则版本与贡献数、分页 apply/revoke 元数据标签、API 提供来源链接才显示、收敛/重建、内联确认（suppress 不改源记忆 / 不可逆 redact / 显式 re-enable 说明）、redacted/删除/不可用值永不渲染、无文件/URL/资产输入、无摘要/情感/Provider/授权措辞；
3. 竞态：stale load 不覆盖后发 mutation、mutation 错误在刷新失败后保留、关系错误不泄漏为其他面板错误。

## 实现

### 1. `api/types.ts` — 关系类型

新增 `RelationshipCapabilities`（`local_only` / `remote_extraction` / `remote_consent_exists` / `projection`）、`RelationshipProjection`、`RelationshipAuthorityView`、`RelationshipEvent`（含 bounded `address` 与可空 `source_memory_id`）、`RelationshipJob`、`RelationshipAudit`、分页类型、`RelationshipSuppressRequest` / `RelationshipRedactRequest`（`confirm_irreversible: true`）/ `RelationshipReenableRequest` / `RelationshipReconcileRequest`、`RelationshipMutationResponse`。

### 2. `api/client.ts` — 关系 API

`getRelationshipCapabilities`、`getRelationshipProjection`、`listRelationshipEvents/Jobs/Audits`（limit+cursor）、`reconcileRelationship` / `rebuildRelationship`、`suppressRelationshipApply` / `redactRelationshipApply` / `reenableRelationshipAuthority`（全部 POST + CAS body）。`confirmMemoryCandidate` 支持可选 `canonical_subject_code`。

### 3. `MemoryPanel.tsx` — 显式关系主题选择

- 新建/编辑/候选确认各一个 `MemorySubjectSelect`（固定标签：不指定 / 偏好的称呼 / 共同经历 / 不对外承诺），按记忆类型过滤合法主题（`relationship_event` 全量，`preference`/`user_fact` 仅 `preferred_address`），绝不自动猜测代码；
- 编辑时初始化为现有主题，`不指定（保留现有）` 保持省略、`清除关系主题` 显式发送 null（preserve/clear 语义）；
- 选择 `preferred_address` 时提示“必须填写希望使用的准确称呼”。

### 4. `RelationshipPanel.tsx`（新建）

- 可折叠 `<details>`：仅本地说明、能力行（无远程抽取/授权）；
- 当前投影：熟悉度（固定标签）、连续性“稳定”、当前称呼、Persona/投影/规则版本、贡献事件数；不可用时中性说明；
- 事件列表：apply/revoke 固定标签、bounded 称呼（仅 active apply）、来源链接仅在 API 提供时显示、redacted 显示“内容已清除”；
- 内联确认：仅撤销关系贡献（说明不改源记忆）、永久清除该称呼（不可逆）、重新允许该关系主题（说明可能衍生新贡献）；
- 收敛/完整重建按钮；任务与审计元数据。

### 5. `App.tsx` / `ChatLayout.tsx` / `styles.css`

- `relationshipRequestGenerationRef` + `relationshipMutationGenerationRef`（镜像 SummaryPanel 竞态模式）；`loadRelationshipState` / `runRelationshipMutation`（mutation 后刷新、刷新失败保留错误）；
- 初始加载受 `VITE_ENABLE_RELATIONSHIP_LOAD_IN_TEST` 门控；候选确认成功后若关系面板已启用则刷新关系状态；
- ChatLayout 注入 RelationshipPanel；新增 `relationship-panel*` 样式。

## 验证

```text
# Task 16 相关测试（覆盖全部改动文件）
npm --prefix frontend test -- src/api/client.test.ts src/components/MemoryPanel.test.tsx src/components/RelationshipPanel.test.tsx src/App.test.tsx
74 passed

# 类型检查
npm --prefix frontend run typecheck
PASS
```

覆盖场景（RelationshipPanel.test.tsx 12 个）：

- 可折叠本地说明、无允许远程/consent 措辞；
- 熟悉度/连续性/当前称呼、Persona/投影/规则版本与贡献数；
- neutral 投影渲染；
- apply/revoke 元数据标签、bounded 地址仅 active apply、redacted 不渲染地址；
- 来源链接仅在 API 提供时显示；
- 收敛/重建按钮与调用；
- suppress 内联确认（不改源记忆）；
- redact 内联确认（`confirm_irreversible: true`）；
- re-enable 说明与 authority expectation；
- redacted/删除/不可用值永不渲染；
- jobs/audits 仅元数据（无 payload/fingerprint/hmac/lineage）；
- 错误显示与重试，不泄漏其他面板。

MemoryPanel.test.tsx 新增：候选确认可携带显式主题、关系事件记忆带主题创建、编辑清除主题（`canonical_subject_code: null`）。App.test.tsx 新增：`VITE_ENABLE_RELATIONSHIP_LOAD_IN_TEST=1` 时独立加载 RelationshipPanel。client.test.ts 新增：精确关系路由、bounded 查询参数、CAS body、无 forbidden 键。

## 边界

- 仅实现计划 Task 16 的显式分类 UI 与独立面板；未动 authority/lineage/projection 后端核心。
- 竞态防护沿用既有 generation ref 模式；无模态框（内联确认足够）。
- **受限项**：完整前端套件（`npm --prefix frontend test` 全量）与 `npm run build` 因沙箱 `spawn EPERM`（node 子进程 piped stdio 被文件沙箱拦截，vite 配置加载阶段）无法在本会话运行；用户已拒绝对该命令的提权审批。已通过覆盖全部改动文件的定向测试 74 passed + typecheck PASS 验证。
- 未提交 Git（按计划 Task 16 Step 5 的记录边界，建议 commit message：`feat: add local relationship panel`）。
