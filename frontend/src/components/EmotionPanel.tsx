import { useState } from 'react';
import type { EmotionAnalysisAudit, EmotionAnalysisConsent, EmotionAnalysisConsentAction, EmotionEvent, EmotionState, EmotionVector } from '../api/types';

const DIMENSIONS: Array<{ key: keyof EmotionVector; label: string; low: string; high: string }> = [
  { key: 'mood', label: '心境', low: '严肃低沉', high: '明快' },
  { key: 'trust', label: '信任倾向', low: '谨慎', high: '信赖' },
  { key: 'concern', label: '关切程度', low: '平静', high: '高度关切' },
  { key: 'distance', label: '交流距离', low: '亲近', high: '疏离' },
  { key: 'irritation', label: '不悦程度', low: '平和', high: '明显不悦' },
  { key: 'formality', label: '正式程度', low: '自然', high: '正式' },
];

const REASONS: Record<string, string> = {
  neutral_turn: '普通交流',
  user_respectful_support: '收到尊重或感谢',
  user_explicit_apology: '收到明确道歉',
  user_clear_boundary: '用户明确了交流边界',
  user_repeated_hostility: '检测到明确敌意表达',
  user_distress_signal: '检测到明确求助或不适信号',
  settings_enabled: '已开启情感表达状态',
  settings_disabled: '已关闭情感表达状态',
  manual_reset: '用户手动重置',
  time_decay: '随时间自然回归基线',
};

const PROVIDER_LABELS: Record<string, string> = {
  anthropic: 'Anthropic',
  deepseek: 'DeepSeek',
};

const AUDIT_OUTCOMES: Record<EmotionAnalysisAudit['outcome'], string> = {
  applied: '已应用受本地约束的分析建议',
  no_change: '分析建议不改变状态',
  skipped: '分析已安全跳过',
  invalid_output: '模型输出未通过严格校验',
  provider_error: '远程模型调用失败',
  revoked: '发送前已撤回授权',
  failed: '分析任务失败',
};

function level(value: number): string {
  if (value < 0.34) return '低';
  if (value < 0.67) return '中';
  return '高';
}

interface EmotionPanelProps {
  state: EmotionState | null;
  events: EmotionEvent[];
  loading: boolean;
  error: string | null;
  onSetEnabled: (enabled: boolean) => Promise<void>;
  onReset: () => Promise<void>;
  onRetry: () => Promise<void>;
  analysisConsent: EmotionAnalysisConsent | null;
  analysisAudits: EmotionAnalysisAudit[];
  analysisConsentLoading: boolean;
  analysisAuditLoading: boolean;
  onUpdateAnalysisConsent: (action: EmotionAnalysisConsentAction) => Promise<void>;
  onRefreshAnalysisAudits: () => Promise<void>;
}

export function EmotionPanel({
  state,
  events,
  loading,
  error,
  onSetEnabled,
  onReset,
  onRetry,
  analysisConsent,
  analysisAudits,
  analysisConsentLoading,
  analysisAuditLoading,
  onUpdateAnalysisConsent,
  onRefreshAnalysisAudits,
}: EmotionPanelProps) {
  const [confirmation, setConfirmation] = useState<'reset' | 'grant' | null>(null);
  const consentActionsDisabled = analysisConsentLoading || analysisConsent === null;

  return (
    <section className="emotion-panel" aria-label="情感表达状态">
      <h2>情感表达状态</h2>
      <p>这些数值只是可审计的角色表达策略，不代表真实感情或意识。</p>
      {error ? <p role="alert">{error}</p> : null}
      {error && !state ? <button type="button" disabled={loading} onClick={() => void onRetry()}>重新加载状态</button> : null}
      {loading ? <p>状态加载中……</p> : null}
      {state ? (
        <>
          <label>
            <input
              type="checkbox"
              checked={state.enabled}
              disabled={loading}
              onChange={(event) => void onSetEnabled(event.currentTarget.checked)}
            />
            启用情感表达状态
          </label>
          <p>版本 {state.version} · 更新于 {new Date(state.updated_at).toLocaleString()}</p>
          <ul>
            {DIMENSIONS.map((dimension) => {
              const value = state.vector[dimension.key];
              return (
                <li key={dimension.key}>
                  <strong>{dimension.label}</strong>：{value.toFixed(2)}（{level(value)}；{dimension.low} → {dimension.high}）
                </li>
              );
            })}
          </ul>
          {confirmation === 'reset' ? (
            <div>
              <button type="button" disabled={loading} onClick={() => { setConfirmation(null); void onReset(); }}>确认重置</button>
              <button type="button" onClick={() => setConfirmation(null)}>取消</button>
            </div>
          ) : (
            <button type="button" disabled={loading} onClick={() => setConfirmation('reset')}>重置状态</button>
          )}
        </>
      ) : null}
      <h3>LLM 辅助情感分析</h3>
      <p>
        授权后，{analysisConsent ? (PROVIDER_LABELS[analysisConsent.deployment_provider] ?? analysisConsent.deployment_provider) : '所选模型'} 会通过网络发送当前回合、最多 6 条近期消息和最多 3 条相关活跃记忆。
        这可能产生模型费用。系统会尽力隐藏明显凭据，但不是完整的隐私或 DLP 保证。
      </p>
      {analysisConsent && !analysisConsent.deployment_enabled ? <p>部署配置尚未开启，因此即使已授权也不会发起分析。</p> : null}
      {analysisConsent ? <p>当前授权状态：{analysisConsent.status}</p> : <p>授权状态加载中……</p>}
      {analysisConsent?.status === 'granted' ? (
        <button type="button" disabled={consentActionsDisabled} onClick={() => void onUpdateAnalysisConsent('revoke')}>撤回远程分析授权</button>
      ) : confirmation === 'grant' ? (
        <div>
          <button
            type="button"
            disabled={consentActionsDisabled}
            onClick={() => {
              setConfirmation(null);
              void onUpdateAnalysisConsent('grant');
            }}
          >
            确认授权并允许发送
          </button>
          <button type="button" onClick={() => setConfirmation(null)}>取消</button>
        </div>
      ) : (
        <div>
          <button type="button" disabled={consentActionsDisabled} onClick={() => setConfirmation('grant')}>
            {analysisConsent?.status === 'revoked' || analysisConsent?.status === 'declined' ? '重新授权远程分析' : '授权远程分析'}
          </button>
          {analysisConsent?.status === 'unknown' ? (
            <button type="button" disabled={consentActionsDisabled} onClick={() => void onUpdateAnalysisConsent('decline')}>暂不授权</button>
          ) : null}
        </div>
      )}
      <h4>最近远程分析结果</h4>
      <button type="button" disabled={analysisAuditLoading} onClick={() => void onRefreshAnalysisAudits()}>
        {analysisAuditLoading ? '正在刷新分析记录……' : '刷新分析记录'}
      </button>
      {analysisAudits.length === 0 ? <p>暂无远程分析记录。</p> : (
        <ul>
          {analysisAudits.map((audit) => (
            <li key={audit.id}>
              {AUDIT_OUTCOMES[audit.outcome]} · {audit.provider}/{audit.model} · {new Date(audit.created_at).toLocaleString()}
            </li>
          ))}
        </ul>
      )}
      <h3>最近变化原因</h3>
      {events.length === 0 ? <p>暂无状态变化记录。</p> : (
        <ul>
          {events.map((event) => (
            <li key={event.id}>
              {event.reason_codes.map((reason) => REASONS[reason] ?? reason).join('、')} · {new Date(event.created_at).toLocaleString()}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
