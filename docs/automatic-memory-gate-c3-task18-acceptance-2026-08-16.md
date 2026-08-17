# Gate C3 Task 18 验收证据 — 固定回放夹具与 30 回复人工评估准备

> 日期：2026-08-16（会话工作区快照 20260710）
> 范围：`backend/tests/fixtures/gate_c3_replay_v1.json`（新建）、`backend/tests/test_gate_c3_fixed_replay.py`（新建）、`docs/gate-c3-evaluation-scorecard-template.md`（新建；**已按用户指示于 2026-08-17 删除**，用户放弃盲评方向，改为直接查看真实对话判断，对话样例见 `docs/show-snow-persona-20260817-193115.json`）

## 目标

按计划 Task 18：

1. 版本化确定性夹具：30 个固定中文跨会话问题，覆盖用户事实、偏好变化、目标、共同经历、非外部承诺、时间、更正、未解决/已解决冲突、真正忘记/不复活、摘要错误、不确定性、Prompt 注入、Persona 切换、抑制与重新启用；声明 schema/rule/Composer/encoder 版本与固定 SHA-256 内容哈希（测试校验）；
2. 确定性回放：30 个问题全部经完整 `ChatService.send_message` 路径 + recording fake Provider 回放，断言聊天存活、确定性输出身份、无 forbidden source、无复活、关系层仅以低权威非事实注入；
3. 评分卡模板：盲评协议、五类别 0–2 分、类别平均 `>= 1.6`（无舍入）、低分回复 `< 5%`、禁止行为立即失败、多名审阅者独立判定的算术规则；测试校验评分算术但不伪造人工分数。

夹具不含用户私有数据、真实凭据、私人媒体路径、第三方角色素材或克隆语音。

## 实现

### 1. `fixtures/gate_c3_replay_v1.json`

- `fixture_schema_version: gate-c3-replay-v1`；`content_sha256`（对排除该字段的规范化 JSON 计算）；
- `declared_versions`：persona-schema-v1 / relationship-projection-v1 / context-composer-v2 / context-data-encoder-v2 / context-manifest-v2；
- `seed`：3 个会话、10 条记忆（user_fact/preference/long_term_goal/relationship_event + preferred_address/shared_experience/non_external_commitment）、1 条真正忘记（preferred_address）、1 条抑制（shared_experience）、`forgotten_sentinel`；
- `questions`：30 条，标注 category（user_fact/preference_change/goal/shared_experience/non_external_commitment/uncertainty/factual_caution/not_fact/not_consciousness/not_absolute/conflict_unresolved/true_forget/relationship_continuity/sensitive_reject/prompt_injection/suppressed_shared_experience）。

### 2. `test_gate_c3_fixed_replay.py`（5 tests）

- fixture 哈希与版本断言（含无禁止内容扫描）；
- 30 问题全部回放：聊天存活、Provider payload 无 forbidden keys、已忘记地址内容与 probe sentinel 不复活、关系类问题注入 `derived_relationship_projection_not_fact` 非事实 authority；
- 确定性输出身份：同一 DB 内两个全新会话发同一首问 → Provider call 逐字一致；
- 评分卡算术：类别平均 `>= 1.6` 无舍入、低分比例 `< 0.05`、边界用例（2/30 低分失败）校验，不伪造人工分数；
- 无关系注入时聊天仍存活。

### 3. `docs/gate-c3-evaluation-scorecard-template.md`（已按用户指示删除，2026-08-17）

盲评协议（乱序、隐藏实现标签、记录运行元数据不含凭据）、五类别定义、阈值（精确除法无舍入）、低分回复定义与上限、禁止行为立即失败、多名审阅者独立判定、`PASS/FAIL/PENDING` 结论记录；明确 fake/recording 证据不计入人工阈值，未运行真实 Provider 时 Gate C3 保持 `PENDING`。评分卡算术校验逻辑保留在 `test_gate_c3_fixed_replay.py` 中（不伪造人工分数）；模板文件本身随盲评方向放弃而删除。

## 验证

```text
# Task 18 新测试
python -W error -m pytest backend/tests/test_gate_c3_fixed_replay.py -q
5 passed

# 聚焦（replay + chat disclosure + Gate C3 契约矩阵）
python -W error -m pytest backend/tests/test_gate_c3_fixed_replay.py \
  backend/tests/test_relationship_chat_disclosure.py \
  backend/tests/test_gate_c3_lifecycle_matrix.py \
  backend/tests/test_gate_c3_independence.py \
  backend/tests/test_gate_c3_http_smoke.py \
  backend/tests/test_gate_c3_privacy_contract.py -q
33 passed

# 完整后端回归
python -W error -m pytest backend/tests -q
<full count>
```

## 边界

- 自动化回放只是契约/隐私证据；其 canned fake 回复永不满足人工 Persona/连续性/自然语言质量闸门。
- 人工评分卡与 `docs/gate-c3-evaluation-2026-07-26.md` 仅在验收时生成；未运行真实聊天 Provider 时人工质量闸门与 Gate C3 保持 `PENDING`。
- 未提交 Git（按计划 Task 18 Step 5 的记录边界，建议 commit message：`test: add Gate C3 fixed replay evaluation`）。
