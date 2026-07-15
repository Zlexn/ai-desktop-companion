# Stage 4C LLM-Assisted Emotion Analysis and Consent Design

> 日期：2026-07-13  
> 状态：设计已批准  
> 默认分析 Provider：DeepSeek  
> 频率：每个成功回合最多一次  
> Consent：持续到主动撤回

## 目标

在不改变 4A 本地规则 fallback 和 4B 文本表达时序的前提下，增加可明确授权、可撤回、幂等、预算受限、凭据脱敏和严格 JSON 验证的远程 LLM 情感分析。远程模型仅提出 delta；本地 policy 是唯一约束和状态写入边界。

## 三重门控

仅当 emotion state enabled、部署配置 `EMOTION_ANALYSIS_ENABLED=true`、持久 consent=granted 时调用。三个状态互不推导。unknown/declined/revoked 零调用。

## 数据流

assistant 成功持久化后：本地规则立即更新；独立后台 analysis job 按 `(assistant_message_id, schema_version)` 幂等排队；执行前重新检查 consent；构建脱敏/预算输入；调用独立 DeepSeek；严格解析；本地限幅；CAS 写 `llm_assisted` event；写不含原文的 audit。任何失败不阻塞 ChatResponse，不撤销本地规则。

## Consent

状态 unknown/granted/declined/revoked，保存 disclosure/policy version、provider 和时间。grant 二次确认；decline 不重复打扰；revoke 阻止未发送 queued job；reset 不改变 consent；可重新授权。

## 输入最小化

当前 turn 必含；最近最多 6 条；最多 3 条 query-relevant active memory。禁止 pending/dismissed/archived、summary、metadata、embedding、audit、原始音频。先 best-effort credential sanitizer，再单条和总字符预算。输入置于 `untrusted_data` JSON；system 明确数据指令不可执行、不得诊断/判真/下关系结论、不得泄露凭据，只输出 JSON。

## 严格输出

固定 `emotion_analysis_v1`：should_apply、allowlisted signals、六维完整 finite proposed_delta、输入中 allowlisted source IDs、allowlisted reason codes。拒绝 code fence、自然语言、额外字段、缺字段、bool 数值、NaN/Infinity、伪造 ID、自由 explanation。should_apply=false 要求零 delta。

## 本地合并

LLM 是 proposal generator；最终始终通过 EmotionPolicy 每维 cap 与 `[0,1]` clamp。本地明确边界规则不能被反转；冲突建议保守向零合并。成功事件 engine=`llm_assisted`、版本=`emotion-policy-v1+emotion-analysis-v1`。

## 配置

独立 DeepSeek provider/model/token/timeout/retry（默认 retry 0）与消息/memory 数量和字符预算。使用 `create_named_provider`，不在业务层调用 SDK。Settings.redacted 不泄露 key。

## 持久化

- consent table；
- analysis jobs unique assistant+schema；
- analysis audit：类别、IDs、provider/model、counts、redaction count、elapsed、reason；无 prompt/raw response/正文/key。

## API/UI

GET/PUT consent（仅 grant/decline/revoke）、GET audit。EmotionPanel 独立展示 provider、数据范围、脱敏限制、费用/网络、二次确认、拒绝、撤回、重新授权和安全分类 audit。本地 emotion enabled 与远程 consent 分开。

## 完成标准

未授权零调用；授权后每成功 turn 最多一次；撤回阻止 queued/future；只发送预算内且脱敏的数据；非法 JSON 全失败关闭；LLM delta 本地限幅；失败不影响聊天/规则；audit 无原文；完整 backend/frontend/E2E/runtime 和 review 通过；无 ExpressionPlan/TTS/桌面资源。
