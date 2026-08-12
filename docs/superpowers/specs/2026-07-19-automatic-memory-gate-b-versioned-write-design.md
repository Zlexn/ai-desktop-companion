# 自动长期记忆与角色一致性增强：Gate B 版本化写入与删除安全设计

> 日期：2026-07-19  
> 状态：APPROVED——独立只读终审通过  
> 所属项目：本地虚拟角色交互系统  
> 前置条件：Gate A 已完成并验收；本设计不改变 Gate A 历史结论

## 1. 背景与本轮决策

Gate A 已建立互斥运行模式、本地 Governor、严格 extractor、独立远程披露授权、幂等后台 job、metadata-only audit 和 shadow 零 active-memory 写入闭环。Gate A 有意不保存 transient proposal 正文、canonical identity 或逐条 Evidence，因此历史 shadow job 不能被 Gate B 回放或“提升”为正式记忆。

Stage 3 的正式记忆仍以 `memories` 表为中心：手工记忆和用户确认候选可以成为 `active`，编辑为原地更新，现有 `DELETE /api/memories/{id}` 实际执行归档；冲突只追加 `conflict_detected` audit，双方仍可能同时保持 active。当前系统没有不可变版本元数据、Evidence、open conflict 状态机、自动写入授权、真实删除、deletion generation 或 tombstone。

本设计采用**兼容双层模型**：

1. 保留现有 `memories` 表、Stage 3 API 和 pending/dismissed 候选行为，作为当前可读投影和兼容入口；
2. 新增版本元数据、Evidence、冲突、删除屏障、自动写入授权和写入活动表；
3. 新的 `VersionedMemoryCommitService` 是自动 active 写入的唯一能力边界；
4. 不完全替换旧表，不把复杂状态硬塞进现有受 CHECK 约束的 `memories.status`，也不把 Gate B 数据塞入自由形态 `metadata_json`。

该路线比“只给旧行加 version 字段”更能隔离历史、删除和冲突语义，也比一次性替换旧表更适合已有本地数据和当前兼容要求。

## 2. Gate B 最小完整闭环

Gate B 只完成以下闭环：

1. 新增与远程抽取授权正交、默认拒绝、持久且可撤回的本地自动写入授权；
2. 在新 turn 上启用互斥 `auto_active`，沿用 Gate A 的 local/fake/remote extractor、Governor、scheduler 和聊天失败隔离；
3. 将 Governor 合格 proposal 以 `create | support | supersede | conflict | reject | no_change` 事务化处理；
4. 保存版本历史、来源 Evidence 和 metadata-only write activity；
5. open conflict 双方不得作为确定事实进入任何 memory context，并提供人工解决事务；
6. 区分归档与真实忘记，使用 generation、tombstone 和 CAS 阻止排队、在途、恢复及陈旧任务复活内容；
7. 为现有摘要增加来源删除屏障，但不注入摘要、不让摘要驱动记忆写入；
8. 在现有 MemoryPanel 增加最小授权、来源、历史、冲突、归档和忘记操作。

## 3. 明确排除

Gate B 不实现：

- 回放 Gate A 历史 shadow proposal；
- 自动解决 open conflict；
- 摘要注入、Context Composer 或摘要驱动的记忆抽取；
- Persona artifact、关系事件账本、关系投影或关系 UI；
- 改写 Stage 3 历史验收结论；
- Electron、Live2D、分层图片、私人素材导入或声音克隆；
- 真实第三方角色图片、视频或参考音频的读取、上传、测试、提交或打包；
- 用 hash、PROV 或本地 audit 宣称内容真实、获得法律意义上的同意或具备防篡改证明。

## 4. 核心安全不变量

1. `auto_active` 只是部署运行模式，不等于用户授权；没有当前有效的自动写入 grant，active mutation 必须为零。
2. 远程抽取 consent 只控制数据发送；自动写入 consent 只控制本地正式记忆提交，二者不能互相蕴含。
3. 每个 job 只能处理创建后新完成的 turn；模式切换不得扫描历史消息、历史 shadow job 或 pending/dismissed candidate。
4. Extractor、remote Provider、Gate A audit、context reader 和 UI 均不直接拥有自动 active 写能力。
5. Provider 调用不在 SQLite 写事务内；proposal 只在当前 worker 内存中存在，直到 commit 或丢弃。
6. 每个成功的内容变化都产生新版本元数据；历史版本不得被直接重新激活。
7. 用户真实忘记是唯一允许清除历史版本 payload 的例外。版本 lineage、hash、时间和 metadata-only activity 可保留，正文、subject、自由 metadata 和 embedding 必须清除。
8. open conflict 两侧不得进入文字聊天、情感分析或任何其他“确定事实”读取路径。
9. 自动 writer 必须携带 expected head、expected record generation、自动写入 consent generation 和 deletion snapshot；任一前置条件变化都不得静默覆盖或退化为 create。
10. tombstone 后，普通自动写入永远不能恢复该事实；恢复必须是未来独立设计的显式用户操作，Gate B 不提供自动 recreate。
11. `INSERT OR REPLACE` 和未分类的 `INSERT OR IGNORE` 禁止用于版本、current head、冲突、授权和 tombstone 状态转换。
12. 任何后台失败都不得回滚已持久化的 assistant reply，也不得把 proposal 正文写入普通日志或 job/audit。

## 5. 运行模式与授权

### 5.1 互斥模式

允许：

- `off`
- `candidate_confirmation`
- `shadow_auto`
- `auto_active`

默认仍为 `candidate_confirmation`。每个完成 turn 只执行一个分支：

```python
if mode == "off":
    pass
elif mode == "candidate_confirmation":
    create_pending_candidates()
elif mode == "shadow_auto":
    schedule_shadow_job()
elif mode == "auto_active":
    schedule_auto_active_job()
```

未知值继续 fail closed。Gate B 启用 `auto_active` 配置值，但不因环境变量自动授予写权限。

### 5.2 自动写入授权

新增单一用户范围的持久记录：

```text
scope_id = "default"
status = unknown | granted | declined | revoked
purpose = "write Governor-approved durable memories to local active storage"
policy_version = "memory-auto-write-policy-v1"
allowed_memory_types = 有序、严格枚举列表
retention_disclosure_version = "memory-auto-write-retention-v1"
generation = 单调递增整数
granted_at nullable
created_at
updated_at
```

规则：

- 默认 lazy `unknown`，默认零 active 写入；
- grant/decline/revoke 每次 mutation 都递增 generation；
- grant 必须精确匹配 purpose、policy version、retention disclosure 和 memory type；
- Gate B 初始允许类型冻结为 `user_fact | preference | long_term_goal | important_event | relationship_event | other`；`commitment` 暂不加入现有枚举，避免在没有外部副作用边界和专用评测时扩大写入类型；
- grant 只允许写本机 SQLite，不允许远程发送；
- revoke 阻止未来提交，但不会隐式删除既有记忆；删除使用独立 forget 操作；
- grant 设置当前 generation 的 `granted_at`；每个 job 持久化 assistant message 的 `turn_completed_at`，dispatch 前及 commit transaction 内都要求 exact grant 的 `granted_at <= turn_completed_at`，否则 `skipped_turn_before_write_grant`，零 extractor/send/mutation；任何后续 grant 都不能追溯授权更早 turn；
- grant 之后不扫描或新建更早 turn 的 job；revoke 后即使 extractor 已返回，也只能写 metadata-only outcome。

`auto_active` 使用独立 `MemoryWriteDispatchFence`，write-consent mutation 和 worker 共享该 fence。PUT 请求进入时先登记 pending mutation，再取得 fence、递增 generation 并提交；worker 在任何 local/fake/remote extractor 前取得同一 fence并重新精确校验完整 write authority。存在 pending mutation 或 authority 不匹配时，零 extractor、零 remote send、零 active mutation。extractor 返回后、释放 fence 前再次校验 snapshot；commit transaction 内仍第三次复核。remote route 还需 Gate A remote-consent fence；唯一锁顺序冻结为 `write fence → remote fence`，mutation 只取得自己的 fence，禁止反向嵌套，以避免死锁。

### 5.3 双授权矩阵

| Extractor route | Remote consent | Write consent | 结果 |
|---|---:|---:|---|
| local/fake | 不需要 | granted | 可进入版本化 commit |
| local/fake | 任意 | 非 granted | `skipped_no_write_consent`，零 active mutation |
| remote | exact granted | granted | 可发送当前 turn，返回后再检查两种 generation，再 commit |
| remote | 非 exact | granted | 零发送，`skipped_no_consent` |
| remote | exact granted | 非 granted | 不发送；自动写入无授权时不为 active 模式进行额外远程披露 |
| remote in-flight revoke | 已发送 | 任一授权发生 mutation | 丢弃结果，零 active mutation |

最后一条采用更严格策略：`auto_active` 在写授权无效时不调用任何 extractor；它不是 shadow 观测模式。

## 6. 数据模型与兼容策略

### 6.1 `memories` 保持兼容投影

现有表保留，现有 `id` 作为稳定 `memory_id`。`pending` 和 `dismissed` 仍属于候选层，不建立 Gate B current head。现有 API 返回字段保持兼容；新增 V2 字段使用可选响应字段。

Gate B schema 生效后，所有改变正式 memory payload、状态、当前资格或来源分类的入口都必须通过统一 `VersionedMemoryMutationService`：manual create、PATCH、candidate confirm、legacy DELETE、显式 archive、forget、undo 和 conflict resolution 均在一个短事务内同步更新 V2 权威状态、版本和 legacy projection。API 不得再绕过该 service 直接修改 active/archived memory。只有迁移前 legacy 行允许暂时没有 state；迁移后新建或首次修改的 active/archived 行必须有 state/current version。Pending/dismissed 继续留在候选层，confirm 时原子建立 state、首版本和 projection。

迁移扩展 `MemorySource` 与 `memories.source` 约束以支持 `automatic`，不得把自动记录伪装为 manual/candidate。兼容的 manual create/confirm 没有 subject 时允许 `subject=NULL`，只提供 exact-hash 能力；非空 subject 对自动新记录强制。

新增 `memory_record_states`：

```text
memory_id PRIMARY KEY → memories.id
state: active | archived | conflicted | deleted
current_version_id nullable
head_version integer >= 0
record_generation integer >= 0
canonical_key_hash nullable
subject_key_hash nullable
canonicalization_version nullable
source_kind: legacy | manual | candidate | automatic | user_edit | user_revert
created_at
updated_at
```

该表是 Gate B 当前资格的权威。兼容投影规则：

- V2 `active` → legacy `memories.status=active`
- V2 `archived|deleted` → legacy `memories.status=archived`
- V2 `conflicted` → legacy行可保持 active，但所有 context query 必须 join `memory_record_states` 并排除；API 展示派生 V2 状态
- 没有 state row 的旧记录沿用 Stage 3 status；第一次 Gate B mutation 时进行受控 bootstrap

迁移不得把历史 `archived` 解释为 `deleted`，不得为旧记录伪造 source message 或 Evidence。

### 6.2 版本表

新增 `memory_versions`：

```text
id PRIMARY KEY
memory_id
version_number
parent_version_id nullable
operation: bootstrap | create | user_edit | auto_supersede | conflict_candidate |
           conflict_resolution | user_revert | archive | delete
memory_type
subject nullable
content nullable
content_hash
canonical_key_hash nullable
subject_key_hash nullable
canonicalization_version
confidence
importance
source_kind
source_session_id nullable FK → sessions.id ON DELETE SET NULL
source_session_reference_hash nullable
writer_policy_version
created_at
redacted_at nullable
UNIQUE(memory_id, id)
UNIQUE(memory_id, id, version_number)
UNIQUE(memory_id, version_number)
UNIQUE(parent_version_id)  # Gate B 线性 head；冲突候选使用独立 memory_id
```

数据库和 mutation service 必须共同保证 identity 一致性：`(memory_id,parent_version_id)` 复合 FK 指向同一 memory 的 version；`memory_record_states(memory_id,current_version_id,head_version)` 复合 FK 指向 `(memory_id,id,version_number)`；根版本只能为 `version_number=1,parent=NULL`，后续版本必须引用同一 memory 的前一连续版本。SQLite CHECK 不能表达的跨行约束使用 guarded insert/trigger，并以直接绕过 service 的反例测试验证。

普通版本只插入不更新。真实忘记时先追加 `operation=delete` 的无正文 head version，再允许且要求将该 memory 的所有版本 `subject/content` 置空并设置 `redacted_at`；这是隐私删除例外，不改变 parent、hash、operation、版本号和时间。`state=deleted` 时，`current_version_id/head_version` 必须指向该 identity 最后一个 `operation=delete` version；该 version 的 parent 指向删除前 head，`subject/content` 始终为空，保留的 canonical/subject hash 仅用于 lineage/tombstone，不能由 API 反推或展示 payload。guarded insert/trigger 必须拒绝 deleted state 指向非-delete head。

旧 active/archived 记录在首次读取历史或首次 mutation 时可以原子 bootstrap：`source_kind=legacy`，不创建 Evidence，不声称存在未知来源消息。

### 6.3 Evidence

新增 `memory_evidence`：

```text
evidence_id PRIMARY KEY
memory_id
memory_version_id
source_session_id nullable
source_message_id nullable
source_session_reference_hash
source_message_reference_hash
source_available
source_deleted_at nullable
relation: supports | contradicts | corrects
observed_at
extractor_kind: local | fake | remote | manual | candidate
extractor_provider nullable
extractor_model nullable
confidence
created_at
UNIQUE(memory_version_id, source_message_id, relation)
FOREIGN KEY(memory_id, memory_version_id) → memory_versions(memory_id, id)
```

Evidence 只引用既有本地 message，不复制 message content、source quote、prompt、raw response 或隐藏推理。创建时 source message 必须存在且 role/session 匹配；保存版本化、不可逆的 session/message reference hash，以便源删除后仍有 metadata-only provenance identity。正常状态 `source_available=true`；session 删除事务将 message/session FK 置空、保留 hash/relation并写 `source_deleted_at`，API 展示不可用。Evidence 撤销使用独立 `memory_evidence_retractions(evidence_id UNIQUE, reason_code, created_at)`，不删除原 Evidence。

Reference hash 冻结为 `memory-source-reference-v1`：使用本地应用首次初始化时生成并安全保存的随机 reference salt 做 HMAC-SHA-256（不是裸 hash），分别对 typed material `session:<id>`、`message:<id>` 计算；数据库只存 digest，不存 salt 或原 ID 副本。所有 version、Evidence、job 和 session scoped forget 使用同一版本/salt。Session scoped forget 可接受已删除 session 的原 scope ID，在请求内计算 digest 后匹配 provenance；不要求 session 行仍存在，响应和审计不返回 digest。Salt 丢失时 fail closed，禁止声称可完成已删除 session 的 scoped forget。

`relation` 永远表示 source message 相对于 `memory_version_id` 所指版本的关系：`create` 为新版本写 supports；`support` 为 current head 写 supports；`supersede` 为旧 head 写 corrects、为新版本写 supports；`conflict` 为每个被反驳 eligible head 写 contradicts、为新 conflicted candidate 写 supports；`reject/no_change` 不新增 Evidence。同一 message 可在同一事务中产生指向不同版本的多条 Evidence。

### 6.4 冲突

新增 `memory_conflicts`：

```text
conflict_id PRIMARY KEY
left_memory_id
right_memory_id
status: open | resolved
resolution_kind nullable:
  choose_left | choose_right | replace_both | both_contextual | dismiss_both |
  forget_left | forget_right | forget_both
resolved_memory_id nullable
created_at
resolved_at nullable
CHECK(left_memory_id < right_memory_id)
```

实现使用 partial unique index 保证每对记录最多一个 open conflict，并以 trigger/guarded insert 保证任一 `memory_id` 最多作为一个 open conflict 的任一 endpoint；resolved 历史允许保留多次，但普通自动 writer 不重新激活历史版本。目标已参与 open conflict 时，自动 writer 返回 `blocked_open_conflict`，零 version、Evidence 和 state mutation。Forget 作为隐私操作可关闭该 identity 的唯一 open pair；保留侧只有在不再 conflicted 时恢复 eligibility。

### 6.5 写入活动

新增 metadata-only `memory_write_activities`：

```text
op_id PRIMARY KEY
job_id
proposal_index
proposal_fingerprint
turn_id
memory_id nullable
previous_version_id nullable
result_version_id nullable
conflict_id nullable
decision
outcome
expected_head_version nullable
observed_record_generation nullable
write_consent_generation
remote_consent_generation nullable
remote_authority_fingerprint nullable
governor_version
commit_policy_version
canonicalization_version
extractor_kind
provider_identifier nullable
model_identifier nullable
created_at
finished_at
UNIQUE(job_id, proposal_fingerprint, commit_policy_version)
```

这是 proposal 级记录，`job_id` 不得单列 UNIQUE。`proposal_index` 只用于展示当前输出顺序，不用于跨恢复身份。Governor 接受 proposal 后，对 source message IDs、memory type、normalized subject/content 及所有会影响语义/目标选择的已验证字段做确定性序列化：

```text
proposal_fingerprint = SHA-256(deterministic_validated_proposal_material)
op_id = SHA-256(job_id + proposal_fingerprint + commit_policy_version)
```

activity 只保存 fingerprint，不保存 material 或正文。每个进入 commit policy 的 proposal 恰有一条 activity，包括 reject、no_change、stale 和 consent/deletion 拒绝。local/fake 的 remote consent 字段必须为空。禁止正文、subject、proposal、source quote、prompt、raw response、exception text、Authorization 和 secret-bearing identifier。

### 6.6 删除 generation 与 tombstone

新增：

```text
memory_deletion_generations(
  scope: all | memory_type | session,
  scope_id,
  generation,
  updated_at,
  PRIMARY KEY(scope, scope_id)
)

memory_tombstones(
  tombstone_id PRIMARY KEY,
  source_memory_id,
  memory_type,
  canonical_key_hash nullable,
  subject_key_hash nullable,
  canonicalization_version,
  delete_generation,
  reason_code,
  created_at,
  expires_at nullable
)
```

`all` 使用固定 `scope_id="*"`。每个 auto-active job reserve 时捕获：

- global generation；
- 当前 session generation；
- 所有 Gate B 允许 memory type 的 generation；
- write-consent generation。

具体 memory tombstone 在 proposal canonicalization 后检查。scope 优先级为 `all > memory_type/session > memory tombstone`，任一匹配都拒绝。

### 6.7 Canonicalization

冻结：

```text
canonicalization_version = "memory-canonicalization-v1"
normalized = Unicode NFKC → 删除 Cf → 合并空白 → ASCII lower
canonical_key_hash = SHA-256(memory_type + ":" + normalized_subject + ":" + normalized_content)
subject_key_hash = SHA-256(memory_type + ":" + normalized_subject)
```

Extractor 提供的 `canonical_key_hint` 永远不可信且不参与计算。

Tombstone 匹配：

1. exact canonical hash 命中：拒绝；
2. 同 memory type 且 subject hash 命中：保守拒绝；
3. V2 新记录必须有本地 Governor 验证后的非空 subject；
4. 旧记录若没有可信 subject，只能保证 exact hash 防复活；UI 在单条忘记时必须说明：如需覆盖同会话、同类型或全部可能改写，使用相应 scoped forget；不得伪称 legacy paraphrase 已得到完整语义屏障。

Tombstone 默认永不过期。Gate B 不提供普通清除 tombstone API；“彻底清理审计元数据”属于本机维护模式的后续独立设计，以免破坏防复活。

## 7. 自动 commit 决策

### 7.1 两层 Governor

Gate A Governor 继续负责：

- turn preflight；
- 敏感内容、删除意图和“不要记住”过滤；
- strict type/subject/content/source/confidence；
- proposal/字符预算；
- 当前 response 内 canonical 去重。

新增本地 `MemoryCommitPolicy` 负责 repository-aware 决策。remote extractor 不能直接选择最终 decision。

自动 `create | support | supersede | conflict` 必须以当前 user-role message 作为 primary Evidence，并由纯本地规则得到 `explicit_user_assertion` 或对应 decision 的更强结论。Assistant message 只能作为补充，不能单独证明用户事实。Extractor 的 source IDs、reason、confidence 和 canonical hint 都不构成 grounding；本地规则无法从用户原文确认 proposal 所表达的事实、偏好、更正或矛盾时，以 `unverified_user_claim` 拒绝。

### 7.2 决策规则

按 proposal 原顺序处理：

- `reject`：Gate A Governor 拒绝、授权失效、删除屏障、非法来源或不允许类型；
- `support`：存在同 canonical hash 的唯一 eligible current record；只追加 supports Evidence，不新建版本；
- `ambiguous_exact_target`：exact canonical hash 命中两条或以上 eligible current record，或冻结的确定性规则无法选出唯一 target；不得任选、不得 create、不得自动建立 semantic conflict，只写 metadata-only activity，零 version/Evidence/active mutation；
- `create`：无 exact、无保守语义冲突、无 tombstone；新建 memory projection、version、Evidence 和 activity；
- `supersede`：仅当本地规则在用户原文中确认明确更正/时间变化，并且存在唯一可 supersede current head；旧 current 归档结束，新版本成为同一 memory identity 的新 head；
- `conflict`：仅当保守语义规则得到唯一 eligible conflicting target 且该 target 不参与 open conflict 时，创建独立 `conflicted` candidate memory/version、contradicts Evidence 和 open conflict；两侧都失去确定事实资格；
- `ambiguous_conflict_target`：语义矛盾目标超过一个或无法由冻结规则唯一确定；只写 metadata-only activity，零 version、Evidence、conflict 和 active mutation；
- `no_change`：同一 source/evidence 幂等重复或已经应用的 op。

`eligible current record` 精确定义为：已建立 V2 state、`state=active`、current version 完整、未 deleted，且不作为任何 open conflict endpoint。legacy active 在参与自动决策前必须受控 bootstrap；无法安全 bootstrap 或 exact target 不唯一时 fail closed。

同一 job 的 proposal 按原顺序逐条提交，每条 proposal 使用独立短事务；已提交 proposal 不因后续 proposal 的数据库失败而回滚，job audit 记录各 decision/outcome 聚合。业务上的 `conflict` 是成功记录的安全结果，不是事务异常。这样避免一个 later proposal 使 earlier 已安全决策全部丢失，也允许每次 CAS 针对最新 head 重评。

### 7.3 Supersede 限制

- 必须基于当前 user message 的明确更正或时间变化句式；assistant 自己生成的文本不能触发；
- target 有 open conflict 时不得 supersede，必须先解决 conflict；
- expected head 或 generation 变化时返回 `stale_head`，不使用旧 proposal 自动重评重试；
- 历史 archived 版本不能直接 active；恢复旧内容要创建 `user_revert` 新版本。

## 8. 原子事务与并发

单次 commit：

1. Provider 已结束，当前 proposal 位于 worker 内存；
2. 开始独立短写事务；
3. 读取并精确校验 write consent generation/status/purpose/policy/retention disclosure/allowed types；remote proposal 还必须校验随 batch 传入的 remote authority snapshot：status、generation、purpose、provider、disclosure version 和有序 fields；
4. 读取 global/session/type generations 并与 reserve snapshot 比较；
5. 检查 exact/subject tombstone；
6. 读取 current head、record generation、open conflict 和 Evidence；
7. 运行纯本地 commit policy；
8. 插入 version/Evidence/conflict/activity；
9. 以 expected state/head/generation 做条件更新；零行必须回滚当前 proposal 事务并分类；
10. commit 当前 proposal 后释放连接；proposal transaction 在读取 head 或运行 policy 前先按 `(job_id, proposal_fingerprint, frozen_commit_policy_version)` 查询 activity；命中直接 `duplicate_op`。唯一冲突必须回滚当前 proposal 的全部业务写，再读取既有 activity 分类；
11. 所有 proposal 处理完毕后，以独立短事务原子完成 job terminal outcome 与聚合 audit；若进程在 proposal commit 后、job terminalization 前崩溃，恢复时重新抽取并计算 proposal fingerprint，只有相同 fingerprint 的 activity 返回 `no_change/duplicate_op`，proposal 变序、增加、删除或内容变化不得误命中，也不得重复已提交 active mutation。

允许使用 `BEGIN IMMEDIATE` 和 guarded `UPDATE ... RETURNING`。`SQLITE_BUSY`、`SQLITE_BUSY_SNAPSHOT` 或零行条件更新不能拿旧语义决定直接重试；若配置允许有限数据库重试，必须从新事务重新读取并重新运行本地 policy，且不得重新调用 remote Provider。Gate B 默认数据库语义重试次数在实施计划中冻结为小的有限值。

## 9. 冲突解决

只允许用户/API 显式解决：

- `choose_left` / `choose_right`：读取被选侧 payload，创建第三个 resolved memory identity 及 `conflict_resolution` 根版本；原 left/right identities 都归档；`resolved_memory_id` 指向新 identity。新版本复制被选侧的当前 payload 和受控字段；不伪造聊天 Evidence，保留被选侧既有 Evidence 的 provenance 只通过 resolution activity 引用 left/right 和 selected version ID；它不继承旧 open-conflict membership；
- `replace_both`：请求必须提供新 content/type/subject，创建新 current memory；归档双方；
- `both_contextual`：请求必须提供明确区分时间或语境的新 content/type/subject，创建新 current memory；归档双方；
- `dismiss_both`：归档双方，不产生 current memory；
- `forget_left | forget_right`：忘记侧进入 deleted；保留侧若未 archived/deleted 且不再参与其他 open conflict，则恢复 active，`resolved_memory_id` 指向保留侧，不复制正文、不创建 resolution version；
- `forget_both`：双方均在同一 forget scope 中 deleted，`resolved_memory_id=NULL`。

除 `dismiss_both/forget_both` 外，`resolved_memory_id` 必须指向解决后唯一 eligible current memory。五种用户 resolve 中，`choose_left/right`、`replace_both` 和 `both_contextual` 都创建新的 resolved identity（后两者使用请求 payload，前者使用被选侧 payload）；原 conflict sides 均归档。解决事务必须校验 conflict 仍 open、两侧 head 未变化、write payload 通过同一敏感信息和结构校验。解决操作不需要自动写入 consent，因为它是用户显式操作，但必须写本地 activity/audit。对 conflicted record 执行普通 archive 返回 `409 conflict_requires_resolution`，不得以 archive 隐式关闭冲突。

## 10. 归档、真实忘记与撤销

### 10.1 API 兼容

- 现有 `DELETE /api/memories/{id}` 保持 Stage 3 的归档语义，标记为 legacy archive，避免静默改变既有客户端；
- 新增 `POST /api/memories/{id}/archive`，作为明确归档入口；
- 新增 `POST /api/memories/{id}/forget`，执行真实忘记；
- 新增 `POST /api/memories/forget`，执行 `session | memory_type | all` scoped forget。

前端把“归档”和“忘记”分开，忘记必须二次确认并说明它不会删除原始聊天消息。

### 10.2 True forget 事务

1. 校验当前 head；
2. 在清空任何 payload 前，读取兼容 projection 和全部未 redacted 历史版本；对每个不同 `(memory_type, canonical_key_hash, subject_key_hash, canonicalization_version)` 建立 tombstone，缺少可信 subject 的版本只建立 exact tombstone；任一插入失败则整个 forget 回滚；
3. 基于删除前 current head 追加 `operation=delete` 的新 version：parent 指向旧 head、version_number 连续递增、subject/content 为空，保留允许的 lineage/hash/canonical metadata；条件更新 `current_version_id/head_version` 指向 delete version 并递增 record/scope generation；
4. 将 projection 置为 V2 deleted、legacy archived；
5. 清空 `memories.content`，将 metadata 缩减为固定删除标识，移除候选 `source_quote` 等自由正文；
6. 清空该 memory 所有 version 的 `subject/content` 并标记 `redacted_at`；
7. 删除 embedding；
8. 以 `forget_left/right/both` 关闭涉及该 memory 的 open conflict；保留侧只有在不再参与其他 open conflict 时恢复 eligibility；
9. 查找 `memory_audit_events.memory_id` 或 `related_memory_ids_json` 引用该 memory 的历史事件，保留 ID、事件类型、operation、关联 ID 和时间，但将自由 `metadata_json` 原子替换为 `{"payload_redacted":true,"reason_code":"memory_true_forget"}`；不得保留原字符串、数组或嵌套值；
10. 写 metadata-only delete activity；
11. 递增摘要来源屏障并写入受影响 source-message exclusion。

任一 payload、tombstone、audit metadata、embedding、conflict 或 barrier 操作失败都回滚当前 forget。Scoped forget 对覆盖的每个 identity 执行同样规则。

Session scoped forget 的目标集合冻结为：任何未 redacted version 的 `source_session_id` 或 `source_session_reference_hash` 匹配该 scope，或存在同样匹配且未撤回 Evidence 的 memory identity，均整条 true forget；不能因另一个 session 仍有 supports Evidence 而保留相同 payload。目标集合必须在递增 session generation 的同一事务快照中确定。源 session 已删除时仍允许传入原 scope ID，本地计算 reference digest 后匹配，不要求 session row 存在。

Scoped forget 还必须覆盖候选层：session 覆盖 `source_session_id` 匹配的 pending/dismissed，memory_type 覆盖匹配类型，all 覆盖全部 pending/dismissed。命中候选在同一事务内不可恢复地 redaction：清空正文和 metadata 中的 source quote/reason/其他自由 payload，删除 embedding，并写固定删除标识；需要 tombstone 时只能在清空前本地计算，原文不得进入 activity/audit/log。后续 confirm/dismiss 对已 forget candidate 返回 `410 candidate_forgotten`，禁止 active 转换。

单条 memory forget 不删除源聊天消息；session scoped forget 也不删除会话本身。

现有 `DELETE /api/sessions/{session_id}` 必须改由 `SessionDeletionCoordinator` 执行，不得直接调用 legacy delete。Coordinator 在一个短写事务内锁定 session、递增 session deletion generation、将 pending/running auto-active job 原子终态化为 `CANCELLED/cancelled_session_deleted` 并各写唯一 metadata-only terminal audit、把 version/Evidence/job source 降级为 HMAC-only unavailable reference，再删除 messages/session。

为支持保留 job/audit，迁移必须数据保留地重建 `memory_jobs`：`session_id/user_message_id/assistant_message_id` 改为 nullable `ON DELETE SET NULL`，并新增不可逆 `session_reference_hash/user_message_reference_hash/assistant_message_reference_hash`；job audit 的 `job_id` 继续引用保留的 job，不 cascade。`memory_versions.source_session_id` 必须为 nullable `ON DELETE SET NULL`，Evidence FK 同样 `ON DELETE SET NULL`（或等价删除前 trigger），不得 cascade。

删除事务先为所有匹配的 version/Evidence/job 确认或补齐 HMAC reference，再将直接 source session/message IDs 置空，完成 terminalization/audit 后才能删除源行；不得保留原 ID，任一步失败整体回滚。删除后 HMAC digest 是唯一 session/message provenance identity。迟到 worker 受 terminal job 不可变和 session generation 双重阻断，无副作用退出，不写 activity/version/Evidence。聊天会话删除不会隐式 forget 派生长期记忆，后者必须显式调用 session scoped forget。

### 10.3 撤销最近自动变化

- 自动 create：执行 true forget，防止相同自动事实再次出现；
- 自动 supersede：创建 `user_revert` 新版本，其 payload 复制前一历史版本，parent 指向当前 head；为被撤销的自动版本 canonical key 创建 tombstone；
- support：为最近自动 Evidence 追加 retraction，不删除 Evidence；
- conflict：用户使用冲突解决 API，不提供隐式 undo。

撤销是显式用户操作，不要求 auto-write consent，但必须做 CAS 并记录 metadata-only activity。

## 11. 摘要来源屏障

Gate B 继续禁止摘要注入和摘要驱动写入。为防 Gate C 未来从已删除来源恢复内容：

- 新增单例 `memory_summary_barrier(generation)`；
- 每次 true forget（任意 scope）递增 generation；
- session scoped forget 在同一事务快照中把该 session 的全部 message IDs 写入 exclusions，不限于 Evidence 已列出的 IDs；memory_type/all 命中 identity 只有 session provenance 而缺可靠 message ID 时，保守地把对应 source session 的全部 messages 写入 exclusions；exclusion 集写入和 barrier 递增同一事务提交；
- `session_summaries` 增加 `observed_memory_summary_barrier`，旧行兼容默认 0；
- 新增 `memory_summary_source_exclusions(source_message_id PRIMARY KEY, reason_code, created_at)`，只保存 ID 和原因码；
- summary job 在读取任何 message payload、构造 batch 或调用 Provider 前，必须在同一只读快照读取 barrier 与全部 exclusions，先过滤命中的 source IDs；被排除正文不得进入 Provider input、sanitizer、中间 payload、日志或异常；过滤后为空或低于阈值时 metadata-only `skipped_source_exclusion`；
- summary job 随后冻结有序 source message IDs 和捕获的 barrier；Provider 返回后不得改用较新 generation；
- summary commit 必须同时满足当前 barrier 等于捕获值、冻结 source set 与 exclusions 无交集，否则丢弃 summary payload；
- 旧 summary 的 coverage 命中 exclusion 或 observed generation 过期时，Gate B reader/API 只返回 metadata 和 `stale=true`，不得返回 summary 正文；
- Gate B 当前不向 chat 或 auto-memory 使用 summary，也不重建受影响 summary；Gate C 只能在明确排除被忘记来源后重建和设计注入。

该策略故意保守：一次记忆忘记可使全部旧摘要对未来注入失效，并阻止排队或新 summary 从已排除来源重新携带被忘事实，优先隐私而不是复用率。

## 12. Job、scheduler 与恢复

- `memory_jobs` 允许 `auto_active`，但 Gate A `shadow_auto` 行为和 audit 继续保持 metadata-only；
- auto-active 使用新的冻结 schema/workflow version，实施计划确定名称；
- reserve 时 `memory_jobs` 持久化且不可更新：`reserved_mode`、`workflow_version`、`extractor_route`、`governor_version`、`commit_policy_version`、`canonicalization_version`、allowed-memory-types set version，以及 write/remote consent 与 deletion snapshots；
- recovery、SQLite retry 和 fingerprint/op_id 只使用这些冻结值；当前 mode/workflow/route 与 reserve 不精确匹配时，Extractor 前以 `skipped_mode_changed`（或 shutdown cancellation）终结，零调用、零 active mutation，禁止静默换 route/policy；
- 同一新 turn 每种有效 workflow 只保留一个 job，ChatService 只创建当前模式对应 job；
- 不提供历史 turn 批量回放或 shadow→active replay API；
- reserve 同步持久化 generation snapshot；worker 后台执行；
- startup 只恢复既有 pending/running auto-active jobs，并重新执行授权/deletion/CAS 检查；
- revoke/forget 必须使旧任务在 commit 时安全跳过；
- terminal audit 保存固定 outcome 和计数，不保存 proposal；
- job 意外失败仍使用固定 `failed` 类别，不保存异常文本。

Job terminal outcome 与 proposal decision 分离：完整处理 proposal 序列后，job 为 `SUCCEEDED/completed_with_decisions`，具体结果由固定 `decision_counts` 和 `outcome_counts` 聚合；整 job 在 proposal 阶段前被跳过、失败或取消时才使用 `skipped_* | invalid_output | provider_error | failed | cancelled`。新增 proposal activity outcome 至少包括：

```text
committed_create
committed_support
committed_supersede
conflict_recorded
no_change
rejected_governor_policy
duplicate_op
skipped_no_write_consent
skipped_write_consent_changed
skipped_no_consent
skipped_consent_changed
skipped_deletion_barrier
skipped_tombstone
blocked_open_conflict
ambiguous_exact_target
ambiguous_conflict_target
unverified_user_claim
skipped_turn_before_write_grant
skipped_mode_changed
cancelled_session_deleted
stale_head
invalid_output
provider_error
failed
cancelled
```

## 13. API

新增或扩展：

```http
GET /api/memories/automation/write-consent
PUT /api/memories/automation/write-consent
GET /api/memories/{memory_id}/versions
GET /api/memories/{memory_id}/evidence
GET /api/memories/conflicts?status=open&limit=20
POST /api/memories/conflicts/{conflict_id}/resolve
POST /api/memories/{memory_id}/archive
POST /api/memories/{memory_id}/forget
POST /api/memories/forget
POST /api/memories/{memory_id}/undo-latest-auto
```

要求：

- 静态 routes 必须在 `/{memory_id}` 动态 route 前注册；
- versions、Evidence 和 conflicts 使用 keyset pagination：请求 `limit=20`（1–100）与 nullable opaque cursor，响应 `{items, next_cursor}`；
- versions 稳定键为 `(version_number DESC,id DESC)`，Evidence 为 `(observed_at DESC,evidence_id DESC)`，conflicts 为 `(created_at DESC,conflict_id DESC)`；cursor 必须绑定 memory/status filter，filter 不匹配返回 400；redacted 项继续参与排序；
- history/evidence 只返回本地可见内容和来源 ID，不返回 Provider raw response；deleted history 返回 redacted payload；
- conflict resolution 使用严格 discriminated schema；
- scoped forget 使用严格 `scope`，`memory_type/session` 要求对应 `scope_id`，`all` 禁止 scope_id；
- write consent API 不修改 remote consent、mode 或既有 memory；
- remote consent API 不修改 write consent；
- API key、Authorization、prompt、raw response、hidden reasoning 不出现在 schema。

## 14. 最小前端

在现有 MemoryPanel 内增加：

- 自动写入授权状态、明确用途/本地存储/撤回说明和 grant/revoke 控件；
- source badge：manual/candidate/automatic/user edit/legacy；
- V2 state、版本数量、Evidence 数量和 open-conflict 提示；
- history/evidence 按需展开；
- 明确分开的“归档”与“忘记”按钮；
- open conflict 列表和五种用户选择的解决操作；forget resolution 由 forget 事务自动使用，不作为普通冲突表单选项；
- 最近自动 create/support/supersede 的撤销入口；
- 后台状态：同步中、完成、失败、隐私跳过、冲突待处理。

不得增加 Persona、关系成长、摘要注入或桌面角色界面。无障碍、键盘操作和现有测试约定保持。

## 15. 配置与冻结版本

| 项目 | Gate B 值 |
|---|---|
| 默认 mode | `candidate_confirmation` |
| 新 mode | `auto_active`，必须另有 write grant |
| auto-write policy | `memory-auto-write-policy-v1` |
| retention disclosure | `memory-auto-write-retention-v1` |
| canonicalization | `memory-canonicalization-v1` |
| commit policy | `memory-commit-policy-v1` |
| remote disclosure | 继续 `memory-extraction-disclosure-v1` |
| Gate A Governor | 继续 `memory-governor-rules-v1`，若规则变化必须新版本 |
| tombstone expiry | 默认永不过期 |
| summary use | 禁止注入、禁止驱动写入 |
| Provider retries | 保持 Gate A 远程 extractor `0` |

proposal/字符预算沿用 Gate A 默认和合法范围；新增数据库语义重试、history/conflict list 默认值和 fixture hash 在文件级实施计划中冻结。真实密钥继续只来自后端环境变量。

## 16. 迁移与回滚

迁移必须**数据保留、前向兼容并在单个 schema 初始化事务中完成**。允许为放宽既有 SQLite `CHECK` 约束执行事务化表重建。这仍是兼容迁移，不是丢弃数据；任一步失败回滚全部 schema/data 变化。

任何父表重建前，实施计划必须查询并冻结完整入站 FK 依赖图；发现未声明依赖时迁移 fail closed。所有依赖子表与父表在同一事务内按明确顺序重建：保留旧父/子数据 → 创建并复制新父表 → 创建并复制指向新父表的新子表 → 校验 → 删除旧子/父表 → 重建索引/trigger。至少覆盖 `memories → memory_embeddings`、`memory_jobs → memory_job_audits` 及全部 Gate B 新增引用。迁移结束前执行 `PRAGMA foreign_key_check` 并逐表断言行数、关键字段、唯一键和 FK 保真；禁止关闭 `foreign_keys` 绕过。具体要求：

1. 保留现有 sessions/messages/memories/candidates/audits/summaries/Gate A jobs；对 `memories.source`、`memory_jobs.mode/outcome/FK nullability` 和 `memory_job_audits.outcome/job FK` 的冻结 CHECK/FK 使用上述单事务重建扩展合法枚举并支持 session 删除后保留 job/audit；
2. 创建 Gate B 新表、索引和必要 summary column；
3. 不批量 bootstrap pending/dismissed；
4. 不把 archived 改成 deleted；
5. 不伪造 source message、subject 或 Evidence；
6. migration failure 阻止应用在部分 schema 上运行；
7. 关闭 `auto_active` 可回退到 `shadow_auto`、`candidate_confirmation` 或 `off`；
8. 回退不删除新表，现有 eligible memory 仍可读、编辑、归档和忘记；
9. 旧客户端的 DELETE 仍执行 archive。

## 17. 测试与验收

### 17.1 固定 fixtures

实施计划必须提供版本化 fixture 文件，并冻结内容 hash 或可断言 schema version，至少覆盖：

- exact support；
- safe create；
- explicit correction supersede；
- ambiguous contradiction conflict；
- sensitive reject；
- explicit no-memory/delete intent reject；
- tombstone exact hit；
- subject-key conservative hit；
- user edit vs delayed job；
- forget vs queued/in-flight/recovered job；
- write revoke pending/before extraction、during extraction、before commit：write fence 保证前两者零额外 extractor/发送，所有情况零 active mutation；
- remote consent 与 write consent 正交矩阵。

### 17.2 单元/仓储测试

- data-preserving forward migration，包括 `memories.source`、`memory_jobs.mode/outcome/source-FK nullability`、`memory_job_audits.outcome/job retention FK` 的事务化重建，历史行计数/字段逐项保真、reference hash 初始化、`PRAGMA foreign_key_check` 为空及失败全回滚；
- version linearity、unique head、同 identity 复合 FK/guarded insert、CAS 和 zero-row 分类；
- Evidence 幂等和 retraction；
- open conflict partial uniqueness、endpoint 单一 open membership、五种人工 resolve、三种 forget resolution，以及重复 endpoint guarded-insert 反例；
- true forget payload redaction、delete head shape、全部历史 canonical tombstone、候选层不可恢复 redaction、legacy audit metadata 缩减、embedding 删除和 generation；
- legacy archived 不变成 deleted；
- pending/dismissed 不自动升级；
- canonicalization 固定向量；
- summary barrier 单调性、session 全 message exclusion、仅有 session provenance 时的保守 exclusion、发送前过滤、捕获 generation CAS、queued/in-flight summary fault injection；
- session deletion coordinator：Evidence/version/job 的稳定 HMAC reference 保留，删除后所有直接 session/message ID 为 NULL、auto-active job/audit 安全终态、源删除后 scoped forget 和 worker 无副作用退出；
- metadata-only activity 的 forbidden columns/fields。

### 17.3 服务与并发测试

- `auto_active` 无 write grant：零 extractor、零 active mutation；
- local/fake + write grant：create/support/supersede/conflict 结果正确；
- remote + write grant 但无 remote consent：零发送；
- remote exact consent 但无 write grant：零发送；
- 任一 consent generation 变化：在途结果丢弃；
- legacy 多条 exact active 记录：`ambiguous_exact_target`；多条 semantic conflicting targets：`ambiguous_conflict_target`；两者均零 version/Evidence/conflict/active mutation；
- assistant 自生事实但 extractor 伪指 user source：`unverified_user_claim`，零 Evidence/version/active mutation；
- grant/revoke/grant 边界：`turn_completed_at < granted_at` 的既有 job 为 `skipped_turn_before_write_grant`，零 extractor/send/mutation；
- startup recovery 使用冻结 workflow 输入；mode/route/policy 变化时零 extractor、零 commit；proposal 变序/增删/内容变化时 fingerprint 只命中相同 proposal；
- remote response 后、SQLite commit 前 remote consent mutation：零 active mutation；
- stale head、用户编辑、forget、scope generation 竞争：旧 job 零覆盖、零复活；
- `SQLITE_BUSY`/snapshot retry 从新状态重评，不重复 Provider send；
- startup recovery 保留幂等和屏障；
- open conflict 双方在 Chat Context 和 emotion-analysis memory input 中均为零；
- shadow mode 继续零 active mutation；candidate mode 继续只产生 pending。

### 17.4 API/前端测试

- write consent 与 remote consent 互不修改；
- history/evidence/conflict keyset pagination：每类至少建立 101 条并遍历全部页面，断言无遗漏、无重复、filter-bound cursor 和稳定顺序；
- legacy DELETE archive、new forget true delete；
- conflict resolve/undo CAS；
- MemoryPanel 授权、状态、历史、冲突、归档/忘记确认；
- deleted payload 不在 API、DOM、日志或快照中出现。

### 17.5 完整验收

1. Gate B focused backend tests，warnings-as-errors；
2. 完整 backend 回归；
3. frontend Vitest、TypeScript 和 production build；
4. real FastAPI HTTP smoke，使用 fake/local，不调用真实云 extractor；
5. SQLite 前后检查：版本/Evidence/冲突/tombstone/activity 原子一致；
6. 并发 fault injection：revoke、forget、user edit、restart recovery；
7. privacy scan：无 secret、prompt、raw response、deleted payload 泄露；
8. Gate A shadow acceptance 核心矩阵重跑；
9. 独立代码审查没有未解决 high/critical；
10. `git diff --check`；
11. 记录未验证范围，不把 fake/local 结果写成真实云证据。

## 18. 通过条件

Gate B 只有在以下条件全部满足时完成：

- 没有 exact write grant 时，`auto_active` 零 extractor、零 active mutation；
- remote consent 不能替代 write consent，write consent 不能替代 remote consent；
- create/support/supersede/conflict 均有原子版本/Evidence/activity 证据；
- open conflict 双方不进入任何确定事实上下文；
- true forget 清除本地 memory/version 可读 payload 和 embedding，保留最小 tombstone；
- queued、in-flight、retry、startup recovery job 在删除或撤回后零复活；
- 用户编辑不会被陈旧后台任务覆盖；
- Gate A shadow metadata-only 与 active-zero-mutation 契约不回归；
- Stage 1–4 完整回归和受影响前端验证通过；
- 独立审查无未解决高严重度问题；
- 验收记录忠实区分已验证、未运行和范围外内容。

任何失败都使 Gate B 保持未完成，不进入 Gate C。

## 19. 研究依据与适用限制

以下一手资料用于支持设计原则，不替代项目自己的业务不变量：

- W3C PROV-O：https://www.w3.org/TR/prov-o/  
  支持把版本、生成活动和 revision/provenance 分开表达；不规定 SQLite schema、权限、真实性或 consent。
- W3C PROV-DM：https://www.w3.org/TR/prov-dm/  
  支持 entity/activity/agent 与 derivation 的概念分离；不构成完整 event-store 实现。
- SQLite Isolation：https://www.sqlite.org/isolation.html  
  支持单 writer、WAL snapshot 和 `SQLITE_BUSY_SNAPSHOT` 下从新快照重评；单 writer 不消除业务 stale-write 风险。
- SQLite Transactions：https://www.sqlite.org/lang_transaction.html  
  支持短事务和 `BEGIN IMMEDIATE`；不自动提供版本链或业务 conflict。
- SQLite ON CONFLICT：https://www.sqlite.org/lang_conflict.html  
  `REPLACE` 可删除冲突行，`IGNORE` 可静默跳过，因此不适合版本历史和受审计状态转换。
- SQLite RETURNING：https://www.sqlite.org/lang_returning.html  
  支持 guarded mutation 返回实际修改行；零行原因仍须由领域层分类。
- Apache Cassandra Tombstones：https://cassandra.apache.org/doc/latest/cassandra/managing/operating/compaction/tombstones.html  
  仅用于说明删除标记过早消失可能让延迟旧写复现的通用风险；Cassandra 的复制/compaction 机制不能当作 SQLite 行为。
- RFC 9110 If-Match：https://www.rfc-editor.org/rfc/rfc9110.html#section-13.1.1  
  仅类比“前置条件失败则不执行”；具体本地实现是 SQLite 条件事务和领域结果。
- NIST SP 800-53 Rev. 5 AC-6：https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-53r5.pdf  
  支持最小权限和 writer 能力隔离；不是特定司法辖区的 consent 法律结论。
- RFC 6973：https://www.rfc-editor.org/rfc/rfc6973.html  
  支持目的限定、数据最小化和控制；不替代本地法律审查。

## 20. 后续顺序

Gate B 规格经独立复核并形成批准的文件级实施计划后，才可开始 TDD 实施。Gate B 验收后仍需获得继续授权，才能设计 Gate C。Gate C 完成后才回到已批准的 Windows Electron 双窗口桌面壳；第一版形象继续使用用户选择的分层图片状态机，用户私人形象和声音素材继续只留在本机忽略目录，不进入 Git、测试或发行包。
