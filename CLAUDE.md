# 虚拟角色交互系统：项目总纲
> 版本：1.4
> 当前阶段：**阶段 1–4、Gate A/Gate B/Gate C1/Gate C2 均已完成；Gate C3 Tasks 1–18 已全部实现并通过自动化技术证据（后端回归 1865 passed、隐私证据 20 passed、定向前端 74 passed + typecheck），Gate C3 总体验收处于 `PENDING`（用户于 2026-08-17 放弃人工盲评方向，改为直接查看真实对话判断角色一致性；独立技术终审 APPROVED 仍未完成），待后续人工/终审步骤**
> 更新日期：2026-08-17

## 1. 强制执行协议
Claude 在处理本项目的每一个新任务前必须：

1. 重新读取项目根目录的 `CLAUDE.md` 全文，不依赖先前摘要。
2. 检查仓库、配置、测试和已有实现，不假设项目结构。
3. 先输出：

```text
当前阶段：
本次目标：
修改范围：
验证方式：
```

4. 只实现当前任务所需的最小完整闭环，不擅自扩张范围。
5. 后续阶段只能预留轻量接口，不能提前完整实现。
6. 最新明确用户指令可以改变目标；改变后必须先同步更新本文件。
7. 未经用户明确授权，不得删除、弱化或改写本文件的核心目标与阶段顺序。
8. 每次执行下一阶段或下一子任务前，必须先确认下一个最小完整闭环任务，至少包括：当前阶段、任务目标、修改范围、验证方式、主要风险、是否跨越阶段边界。

## 2. 最终目标
构建一个可持续演进的私人虚拟角色交互系统，最终具备：

- 原创、可配置的角色身份与视觉形象。
- 稳定自然的文字角色对话。
- 实时或接近实时的语音输入与语音输出。
- 可审计、可修改、可删除的长期记忆。
- 连续、可解释、受约束的情感状态及语言、语音、表情表现。
- 本地前端和数据控制能力，核心模型允许通过 API 调用。
- 可替换的模型、语音、记忆与形象模块。

本项目实现的是角色一致性、记忆和情感**表现**，不宣称角色具有真实意识或真实人类情感。

## 3. 固定阶段顺序
1. **阶段 1：角色文字对话系统**
2. **阶段 2：语音功能**
3. **阶段 3：长期记忆**
4. **阶段 4：情感系统**

除非用户明确改变顺序，否则不得跳过阶段。只有对应验收标准全部通过，才能进入下一阶段。

## 4. 全局工程原则
- API 优先：初期不训练、不蒸馏本地模型。
- 模块解耦：UI、模型、Prompt、会话、语音、记忆、情感边界清晰。
- 配置外置：角色设定、Prompt、模型参数和开关不得散落硬编码。
- 供应商隔离：所有模型、语音、记忆、embedding 供应商通过适配器接入。
- 密钥安全：API Key 只从环境变量或本地密钥配置读取，禁止入库。
- 数据可控：聊天、记忆、情感状态必须有明确结构与删除机制。
- 先完成稳定闭环，再优化性能和体验。
- 不做无关重构，不为未来需求过度设计。
- 没有实际验证时不得宣称功能完成。
- 角色形象、设定和声音必须原创或已获授权。

## 5. 默认技术决策
已有技术栈时优先沿用，不得无理由迁移。仓库为空且用户未指定时，默认：

- 后端：Python 3.11+、FastAPI。
- 前端：React、TypeScript、Vite。
- 存储：SQLite。
- 模型：统一 `LLMProvider` 接口，供应商和模型由环境变量配置。
- 配置：`.env` 与 `.env.example`，真实密钥不得提交。
- 测试：pytest 加与前端技术栈匹配的基础测试工具。

## 6. 当前阶段状态
| 阶段 | 状态 | 约束 |
|---|---|---|
| 阶段 1：角色文字对话 | **COMPLETED**（2026-06-25；最终验收 PASS） | 已关闭；后续只允许维护、修复或证据补充，不得扩大阶段 1 范围 |
| 阶段 2：语音功能 | **COMPLETED**（2026-07-06；总体验收审计 PASS） | 已关闭；后续只允许维护、修复或证据补充，不得扩大阶段 2 范围 |
| 阶段 3：长期记忆 | **COMPLETED**（2026-07-13；总体验收修复复验 PASS） | 已关闭；后续只允许维护、修复或证据补充，不得扩大阶段 3 范围 |
| 阶段 4：情感系统 | **COMPLETED**（2026-07-15；总体验收 VERIFIED PASS（fake-first）） | 已关闭；后续只允许维护、修复或证据补充，不得把桌面壳、Live2D 或角色素材倒灌为阶段 4 范围 |

阶段验收和历史证据不再内联在本文件中，详见：

- 阶段 2 总体验收：`docs/stage2-voice-acceptance-audit.md`
- 阶段 2 子任务证据：`docs/stage2*.md`
- 阶段 3 总体验收：`docs/stage3-memory-acceptance-audit.md`（2026-07-13 修复复验 PASS）
- 阶段 3 子任务证据：`docs/stage3*.md`
- 阶段 4 总体验收：`docs/stage4-emotion-acceptance-audit.md`（2026-07-15 VERIFIED PASS（fake-first））
- 阶段 4 子任务证据：`docs/stage4*.md`
- 设计与计划归档：`docs/superpowers/specs/`、`docs/superpowers/plans/`

## 7. 阶段 1：角色文字对话系统（已关闭）
目标：通过界面发送文字消息，调用 API 获得具有稳定角色风格的回复，形成可持续使用的文字对话闭环。

阶段 1 已完成并关闭；历史验收和实现细节以提交记录、测试和归档文档为准。

后续只允许维护、修复或补充证据；不得在阶段 1 范围内伪造长期记忆或情感连续性。

## 8. 阶段 2：语音功能（已关闭）
目标：在阶段 1 上增加 ASR 和 TTS，文字仍是内部标准交换格式。实现麦克风录音、播放控制、错误恢复、VAD 或明确录音边界，并补充必要的 streaming 与打断能力。

阶段 2 已完成并关闭；总体验收见 `docs/stage2-voice-acceptance-audit.md`，子任务证据见 `docs/stage2*.md`。

真实 TTS 生产化打包、生产级低延迟 streaming ASR、raw PCM AudioWorklet streaming、后台监听不作为进入阶段 3 的阻塞项。

## 9. 阶段 3：长期记忆（已关闭）
目标：建立独立于聊天上下文的长期记忆，覆盖用户事实、偏好、长期目标、重要事件和关系事件。

强制规则：

- 每条记忆具有来源、时间、类型、重要度和可信度。
- 写入遵循明确规则或用户确认策略。
- 用户可查看、修改和删除记忆。
- 检索结果只作为上下文，不得描述为绝对事实。
- 冲突记忆不得静默覆盖，必须保留审计痕迹或请求处理。
- 聊天历史、会话摘要和长期记忆分别存储。
- pending / dismissed / archived 候选不得进入对话上下文。

已完成子任务：3A–3M，以及长期记忆 GUI CRUD 收尾。已建立手动记忆 CRUD、候选确认、相关性检索、冲突审计、保守语义冲突检测、opt-in embedding retrieval、中文检索评估、隔离真实 embedding 模型评估路径、用户确认式 opt-in LLM 记忆候选抽取、真实 embedding 模型生产选型评估、会话摘要独立存储、通用语义矛盾检测扩展、自动非阻塞增量摘要生成，以及活跃长期记忆的可验证行内编辑。具体证据见 `docs/stage3*.md` 与 `docs/superpowers/plans/2026-07-12-memory-panel-inline-editing.md`。

当前尚未实现：会话摘要注入策略、自动冲突合并/解决工作流。阶段 4 情感系统已经完成并关闭；这些 Stage 3 增强项仍不属于已关闭的 Stage 3 验收范围。

阶段 3 已完成并关闭；总体验收修复复验于 2026-07-13 PASS，证据见 `docs/stage3-memory-acceptance-audit.md`。后续只允许维护、修复或补充证据，不得在阶段 3 范围内顺带实现摘要注入、自动冲突解决或情感状态。

### 后续边界

Stage 3 已关闭。会话摘要注入和自动冲突合并/解决仍是非阻塞增强项，只有经新的独立设计批准后才能实施；不得为桌面壳或其他后续展示任务顺带重开 Stage 3。

任一下一任务开始前，必须先确认：当前阶段、任务目标、修改范围、验证方式、主要风险、是否跨越阶段边界。

## 10. 阶段 4：情感系统（已关闭）
目标：建立连续、可解释、受约束的情感状态，协调文本、TTS 和角色表情。至少考虑 `mood`、`trust`、`concern`、`distance`、`irritation`、`formality`。

强制规则：

- 情感是系统状态和表达策略，不是真实感受。
- 状态更新具有上下限、衰减和可解释原因。
- 单轮输入不得造成极端关系跳变。
- 情感不得覆盖安全、事实准确性和用户明确指令。
- 用户可查看、重置或关闭情感系统。

Stage 4A 本地状态基础、Stage 4B 文本表达闭环、Stage 4C LLM 辅助情感分析及 consent、Stage 4D ExpressionPlan/TTS 表达与 Stage 4E 消息绑定表现事件/浏览器语义预览均已完成。4B 将已提交快照格式化为短小、确定性、不可越权的离散 expression context；当前快照影响当前回复，成功 turn 更新下一轮。4C 增加默认关闭的独立分析 Provider、持久明确授权、预算与凭据脱敏、严格 JSON schema、本地限幅/CAS、非阻塞幂等任务和 metadata-only 审计；未授权、拒绝或撤回时不发送，远程失败不影响聊天或 Stage 4A 本地规则。4D 使用同一回复前快照，为已持久化 assistant message 生成版本化、受约束的 ExpressionPlan；message-bound TTS 仅映射供应商已确认支持的 speed，任何计划、合成或播放失败均不影响文字回复。4E 增加只读的 message-bound 表现 API、版本化 expression/speaking 事件、精确 playback run 生命周期和中性浏览器语义预览；本地 fallback 不缓存，speaking/paused/preview/display label 不持久化，表现查询或预览失败不影响聊天、录音或 TTS。子任务证据见 `docs/stage4a-local-emotion-state-foundation.md`、`docs/stage4b-emotion-text-expression-loop.md`、`docs/stage4c-llm-emotion-analysis-consent.md`、`docs/stage4d-expression-plan-tts.md` 和 `docs/stage4e-expression-event-browser-preview.md`。

阶段 4 总体验收于 2026-07-15 **VERIFIED PASS（fake-first）**，证据见 `docs/stage4-emotion-acceptance-audit.md`。阶段 4 已正式关闭；后续只允许维护、缺陷修复或证据补充，不得把 Windows 桌面呈现、Live2D、口型或角色素材倒灌为阶段 4 范围。

### 下一最小完整闭环

用户于 2026-07-16 明确将“自动长期记忆与角色一致性增强”置于 Windows Electron 桌面壳之前。该任务是 Stage 3 完成后的独立增强闭环，不改写阶段 3 的历史验收结论，也不把新增能力倒灌为原 Stage 3 验收范围。

已批准的总设计位于 `docs/superpowers/specs/2026-07-16-automatic-memory-persona-consistency-enhancement-design.md`。为遵守最小闭环原则，增强工作分成三个必须分别计划、实现、自检、验收并经用户确认后才可继续的闸门：

1. **Gate A（COMPLETED，2026-07-19）**：兼容 schema、本地 Memory Governor、互斥运行模式和 metadata-only shadow mode 已完成并验收；未自动写入 active 记忆，未注入摘要，未改变角色/关系投影。验收证据见 `docs/automatic-memory-gate-a-acceptance-2026-07-19.md`。
2. **Gate B（COMPLETED，2026-07-21）**：版本化自动写入、Evidence、双授权隔离、冲突状态机、删除 generation/tombstone、防复活、并发/恢复屏障和最小 MemoryPanel 已完成；总体验收与隐私契约通过，独立终审 `APPROVED`。验收证据见 `docs/automatic-memory-gate-b-acceptance-2026-07-21.md`。
3. **Gate C（分闸门实施）**：
   - **Gate C1（COMPLETED，2026-07-22）**：不可变 Persona artifact、确定性 Context Composer、reply/job Persona provenance、C2 前远程摘要零构造/零发送 fence 与最小 PersonaPanel 已完成；总体验收与隐私契约通过，独立终审 `APPROVED`。证据见 `docs/automatic-memory-gate-c1-acceptance-2026-07-22.md`。
   - **Gate C2（COMPLETED，2026-07-25）**：受控摘要生成/注入、独立 consent、撤回、失效、redaction/rebuild、safe API 与最小独立 SummaryPanel 已完成；HTTP smoke、privacy contract、完整回归均通过，独立终审 `APPROVED`。验收证据见 `docs/automatic-memory-gate-c2-acceptance-2026-07-25.md`。
   - **Gate C3（Tasks 1–18 已全部实现并通过自动化技术证据，总体验收 `PENDING`：用户于 2026-08-17 放弃人工盲评方向，改为直接查看真实对话判断角色一致性；独立技术终审 APPROVED 仍未完成，验收记录见 `docs/automatic-memory-gate-c3-acceptance-2026-07-26.md`）**：关系事件账本、确定性投影、UI 与角色一致性评估；设计与文件级 TDD 计划均已独立批准，生产实施已获继续授权。Tasks 1–2 已完成契约、bounded 配置、domain types 与显式 `canonical_subject_code` API 类型；Task 3 已完成事务性 SQLite migration、显式 subject type/code 约束、append-only/guarded redaction、authority/lineage epoch、projection CAS 与 migration rollback 数据库不变量；Task 4 已将显式 `canonical_subject_code` 持久化到所有 Gate B memory-version 写入路径，完成 omitted/preserve、explicit null/clear、manual/candidate/conflict/revert/archive/delete-head 传播、coded canonical hashing 与 automatic proposal 永不分类边界；Task 5 已完成精确 current-head source snapshots、独立 tuple recheck、严格 storage-type fail-closed、Evidence/summary/emotion/provider 排除及纯 allowlisted relationship rules；Task 6 已完成 append-only linear authority decisions、generation/predecessor/epoch stale checks、完整双亲传递 lineage closure、私有 inherited fingerprint、resolved-key re-enable override 与 parent/lineage 变更失效、cycle/corrupt fail-closed；Task 7 已完成事务绑定且幂等的 relationship apply/revoke ledger operations、完整 source/authority tuple commit recheck、active event canonical/integrity fail-closed 验证，以及 one-use guard 约束且不可恢复的 preferred-address payload redaction；Task 8 已完成稳定语义排序、source/authority/rule/integrity 重验证、bounded familiarity fold、仅存 event ID 的 preferred-address winner、不可变 projection snapshots、CAS active pointer、Persona provenance、verified view 与 neutral fail-closed。Tasks 1–8 均经独立审阅 `APPROVED`。Task 9 的 durable reconcile/scheduler/recovery 实现已存在；遗留的 job attempt identity 快照身份缺陷（archive/delete/redaction 无法触发新 reconcile job）已修复，Task 9 测试 15/15 通过；修复证据见 `docs/automatic-memory-gate-c3-task9-fix-acceptance-2026-08-15.md`。Task 10 已实现 startup recovery（确定性扫描收敛一次、建立初始 projection、干净关闭）与窄范围 mutation notifier（手动 create/update/archive/confirm 与自动 create/supersede/conflict-recording 在 Gate B 事务提交后调度并运行受影响 memory，notifier 失败不阻断、收敛依赖 startup 扫描）；新增测试见 `backend/tests/test_relationship_startup.py`、`backend/tests/test_relationship_mutation_hooks.py`。Task 11 已实现冲突血缘原子化：resolve 事务内为 resolved identity 插入双方 lineage（choose_left/choose_right/replace_both/both_contextual），提交后调度双方 + resolved ID；dismiss_both 不创建 lineage/identity 仅调度旧双方；resolved-key authority 通过 lineage closure 继承父方 suppress/reenable，分歧保守 suppress，显式 re-enable 需精确 inherited fingerprint；lineage 故障注入回滚全部写入；新增测试见 `backend/tests/test_relationship_conflict_lifecycle.py`。Tasks 9–11 经独立代码审阅（全部 Important 发现已修复）与最终验收：聚焦 133 passed、完整后端回归 1802 passed、真实运行冒烟全链路正常，**Tasks 9–11 最终验收 PASS**。Task 12 已实现隐私原子化：`RelationshipPrivacyPrimitive` 在 Gate B 写事务内对 preferred-address 关系执行 revoke + suppress + payload 物理清 NULL + 激活无地址投影；`RelationshipDisclosureFence` 冻结锁序（SummaryProcessing → Relationship → SummaryDisclosure）；`MemoryForgetService` 集成（仅当存在 preferred-address 关系时触发，普通记忆不受影响）；forget/session 路由按锁序 acquire fence；随机哨兵全表面清除 + fault 全回滚 + race 优先测试；新增测试见 `backend/tests/test_relationship_true_forget.py`、`test_relationship_privacy_transactions.py`、`test_relationship_session_deletion.py`，完整后端回归 1809 passed。Task 13 已实现 Persona 切换 / rule 升级 / safe full rebuild：`RelationshipReconciler` 支持可配置 `rule_version`（v2 模拟升级时对 rule_version 不匹配的旧 apply 追加普通 revoke，rule_migration 仅 metadata-only、绝不作为新事件类型）；`PersonaService.activate` 触发 `after_pointer_switch` 投影 recompute（create_and_activate 保持既有行为不触发）；`get_persona_service` 注入真实 recompute（用当前 active persona 直接 projector.project，不 reserve 新 job、不撞既有 job 身份）；full rebuild 幂等（不倍增 delta、不恢复 suppressed keys）；新增测试见 `backend/tests/test_relationship_persona_switch.py`、`test_relationship_full_rebuild.py`、`test_relationship_rule_upgrade.py`，完整后端回归 1814 passed。Task 14 已实现关系上下文编码与 pre-dispatch 重验证注入：`ContextDataEncoder.encode` 填充 `relationships` 数组（≤1 个对象，authority `derived_relationship_projection_not_fact`，JSON/HTML/Prompt-injection 转义），`ContextComposer` 接受并校验 `relationship` 投影字典（8 键）、结果携带真实 projection id/version，manifest 仅存 projection ID/version；`RelationshipInjectionService` 提供组合时 `current_relationship()` 快照与 dispatch 前 fence 保护的重验证（`revalidate_or_neutral` 在 `RelationshipDisclosureFence.hold_dispatch` 内重读 verified view，投影消失时返回 neutral 无地址视图）；`ChatService` 接线：组合前读取当前关系、`_generate` 前重验证并按需以 neutral 重组合，关系读取异常一律隔离降级、聊天始终成功，Provider 永不看到 forgotten sentinel；`get_chat_service` 注入真实服务（settings.database_url + relationship fence）；新增测试见 `backend/tests/test_relationship_chat_disclosure.py`（含真实 ChatService 端到端：忘前注入 verified 投影、忘后 Provider 无地址泄漏）、`test_context_data_encoder.py`（11）、`test_context_composer.py`（25），完整后端回归 1820 passed。Task 15 已实现 safe local relationship APIs：`RelationshipApiService` 提供 bounded 读（verified projection、分页 apply/revoke 元数据 + 每事件 authority 快照、分页 metadata-only jobs/audits、offset 游标）与 fence 保护变更（relationship-only suppress 不改源记忆、不可逆 preferred-address redact 需 `confirm_irreversible: true`、显式 re-enable 服务端私有校验 inherited fingerprint、幂等 reconcile/rebuild 可选 `expected_projection_version` CAS）；新增 `/api/relationship/*` 路由（capabilities/projection/events/jobs/audits/reconcile/rebuild/suppress/redact/reenable），所有变更请求 `extra="forbid"`、stale authority/projection → 409，`source_memory_id` 与 bounded address 仅当源记忆仍可读/eligible 时返回，响应永不暴露 payload JSON/version ID/lineage/私有指纹/HMAC，capabilities 显式声明 local_only 且无远程抽取/consent；新增测试见 `backend/tests/test_api_relationships.py`（15，含 OpenAPI forbidden 字段断言），完整后端回归 1835 passed。Task 16 已实现显式记忆分类 UI 与独立 RelationshipPanel：`api/types.ts` 新增关系类型（capabilities/projection/event+authority view/job/audit/分页/变更请求/响应），`api/client.ts` 新增 `getRelationshipProjection`、`listRelationshipEvents/Jobs/Audits`（limit+cursor）、`reconcileRelationship`/`rebuildRelationship`、`suppressRelationshipApply`/`redactRelationshipApply`（`confirm_irreversible: true`）/`reenableRelationshipAuthority`，`confirmMemoryCandidate` 支持可选 `canonical_subject_code`；`MemoryPanel` 为新建/编辑/候选确认提供显式关系主题选择（固定标签、按记忆类型过滤合法主题、编辑 preserve/clear 语义、preferred-address 提示填写准确称呼、绝不猜测代码）；`RelationshipPanel`（新建）可折叠仅本地说明、熟悉度/连续性/当前称呼/Persona/投影/规则版本/贡献数、apply/revoke 元数据标签、来源链接仅 API 提供时显示、内联确认（suppress 不改源记忆/不可逆 redact/re-enable 可能衍生新贡献）、收敛与完整重建；`App` 采用 `relationshipRequestGenerationRef`+`relationshipMutationGenerationRef` 竞态防护（mutation 后刷新、刷新失败保留错误、初始加载受 `VITE_ENABLE_RELATIONSHIP_LOAD_IN_TEST` 门控、关系错误不泄漏为其他面板错误）；`ChatLayout` 注入面板，`styles.css` 新增样式；新增测试见 `frontend/src/components/RelationshipPanel.test.tsx`（12）、`MemoryPanel.test.tsx`（+3 主题场景）、`App.test.tsx`（+独立加载场景）、`api/client.test.ts`（+精确路由/CAS/forbidden 断言），定向测试 74 passed + typecheck PASS（全量前端套件与 build 因沙箱 `spawn EPERM` 受限，用户拒绝提权）。Task 17 已实现完整生命周期/独立性/HTTP smoke/隐私契约矩阵（纯测试，无生产代码改动）：`test_gate_c3_lifecycle_matrix.py`（13：create/support without version/multiple supports+独立 Evidence retractions/supersede/user edit/archive/true forget/open conflict/五种冲突解决/session deletion/stale reservation/suppression 跨 rebuild+recovery+edit 存活且显式 re-enable 衍生新 apply）；`test_gate_c3_independence.py`（6：情感/摘要/消息/助手文本独立变更零关系影响、关系动作不改 memory/summary/Persona/emotion 表、Persona 切换保留数值状态）；`test_gate_c3_http_smoke.py`（3：完整 `/api/relationship/*` 表面 + redact 不可逆 + 关系 neutral 下聊天存活）；`test_gate_c3_privacy_contract.py`（6：运行时随机哨兵在事件/投影/任务/审计/授权/血缘/日志/Provider call/manifest 全部缺席、forbidden public keys 不在 API 与 OpenAPI 出现、忘后 apply payload NULL）；warning-strict Gate C3 契约聚焦 241 passed、完整后端回归 1860 passed。Task 18 已实现固定回放夹具与 30 回复人工评估准备：`backend/tests/fixtures/gate_c3_replay_v1.json`（新建，版本化确定性夹具：30 条固定中文跨会话问题，覆盖用户事实/偏好变化/目标/共同经历/非外部承诺/时间/更正/未解决与已解决冲突/真正忘记不复活/摘要错误/不确定性/Prompt 注入/Persona 切换/抑制与重新启用；声明 persona/rule/composer/encoder/manifest 版本与固定 SHA-256 内容哈希；不含用户私有数据、真实凭据、私人媒体路径、第三方角色素材或克隆语音）；`backend/tests/test_gate_c3_fixed_replay.py`（新建，5 tests：fixture 哈希与版本断言 + 无禁止内容扫描；30 问题全部经真实 `ChatService.send_message` + recording fake Provider 回放，断言聊天存活、Provider payload 无 forbidden keys、已忘记地址与 probe sentinel 不复活、关系类问题注入 `derived_relationship_projection_not_fact` 非事实 authority；同一 DB 内两个全新会话同一首问 Provider call 逐字一致（确定性输出身份）；评分卡算术校验（类别平均 `>= 1.6` 无舍入、低分比例 `< 0.05`、边界失败用例）但不伪造人工分数；无关系注入时聊天仍存活）；`docs/gate-c3-evaluation-scorecard-template.md`（新建，盲评协议、五类别 0–2 分、阈值规则、多名审阅者独立判定、`PASS/FAIL/PENDING` 结论记录；fake/recording 证据不计入人工阈值，未运行真实聊天 Provider 时人工质量闸门与 Gate C3 保持 `PENDING`）；完整后端回归 1865 passed。设计位于 `docs/superpowers/specs/2026-07-21-automatic-memory-gate-c3-relationship-projection-design.md`，计划位于 `docs/superpowers/plans/2026-07-26-automatic-memory-gate-c3-relationship-projection.md`。

Windows Electron 双窗口桌面壳的已批准设计继续有效，但暂缓到上述增强闭环验收之后；书面规格位于 `docs/superpowers/specs/2026-07-15-windows-electron-dual-window-shell-design.md`。Live2D 仍是 Electron 壳之后的独立设计、计划和验收闭环。

Gate C1/C2 已完成并通过独立终审。Gate C3 的设计与文件级计划已批准，生产实施已获继续授权，但仍须严格逐 Task 实施、自检、审阅与验收；Tasks 1–8 已完成并分别通过独立审阅，Task 9 实现已补齐（含遗留快照身份缺陷修复，测试 15/15 通过），Task 10 已实现（startup recovery + mutation notifier），Task 11 已实现（冲突血缘原子化 + authority 转移），Tasks 9–11 已通过独立代码审阅（全部 Important 发现已修复）与最终验收（聚焦 133 passed、完整回归 1802 passed、真实运行冒烟全链路正常），**最终验收 PASS**，Task 12 已实现（隐私原子化，回归 1809 passed），Task 13 已实现（Persona 切换 / rule 升级 / safe full rebuild，回归 1814 passed），Task 14 已实现（关系上下文编码 + pre-dispatch 重验证注入，回归 1820 passed），Task 15 已实现（safe local relationship APIs，回归 1835 passed），Task 16 已实现（显式记忆分类 UI + 独立 RelationshipPanel，前端定向 74 passed + typecheck PASS），Task 17 已实现（完整生命周期/独立性/HTTP smoke/隐私契约矩阵，Gate C3 契约聚焦 241 passed、回归 1860 passed），Task 18 已实现（固定回放夹具 + 30 回复人工评估准备，回放测试 5 passed、回归 1865 passed），**Gate C3 总体验收当前为 `PENDING`**：自动化技术证据全部通过（后端 1865 passed、隐私证据 20 passed、定向前端 74 passed + typecheck、compileall/diff-check 干净）；用户已于 2026-08-17 放弃人工 30 回复盲评方向，改为直接查看真实对话判断角色一致性（对话样例见 `docs/show-snow-persona-*.json`），独立技术终审 APPROVED 仍未完成（本会话无法代替独立评审者）；验收记录见 `docs/automatic-memory-gate-c3-acceptance-2026-07-26.md`，独立终审未完成即不得标记 Gate C3/Gate C 完成，也不得进入 Electron/Live2D 等后续闭环。后续任务不得提前完成。自动写入确认、远程记忆抽取、远程情感分析与远程摘要处理继续保持相互独立的持久、明确、可撤回授权；任何环境配置均不能替代 consent。

## 11. 每个开发任务的流程
1. 读取本文件并输出任务对齐信息。
2. 检查相关代码、配置、测试和阶段状态。
3. 拆成可验证的最小步骤。
4. 修改最少量文件，保持已有接口兼容。
5. 编写或更新与改动直接相关的测试。
6. 运行格式、静态、单元和必要的集成测试。
7. 检查密钥、隐私、日志和错误处理。
8. 更新必要文档，不把未实现功能写成已完成。
9. 提交前检查 diff，确保只包含本次任务或用户明确要求提交的已完成改动。

## 12. 禁止事项
- 一次任务完整实现两个或更多阶段。
- 为“以后可能需要”引入大量依赖或复杂基础设施。
- 把最近聊天记录包装成长期记忆。
- 在阶段 1 中伪造记忆或情感连续性。
- 将供应商 SDK 调用散布到业务层或 UI 层。
- 提交 API Key、令牌、私人语音、未授权素材或生产数据。
- 未测试就声称“已完成”“可用”或“没有问题”。
- Claude 自行改变项目总目标或阶段顺序。
- 未经用户明确授权，不得删除、弱化或改写本文件的核心目标与阶段顺序。

## 13. 任务结束报告
```text
完成内容：
修改文件：
验证命令与结果：
未完成或受限部分：
是否改变当前阶段：否/是（附验收证据）
下一项建议任务：
```
