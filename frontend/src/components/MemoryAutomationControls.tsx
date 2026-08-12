import { useState } from 'react';
import type { MemoryJobSummary, MemoryWriteConsent, MemoryWriteConsentAction } from '../api/types';

interface MemoryAutomationControlsProps {
  consent: MemoryWriteConsent | null;
  loading: boolean;
  latestJob: MemoryJobSummary | null;
  onUpdate: (action: MemoryWriteConsentAction) => Promise<void>;
}

const JOB_LABELS: Record<string, string> = {
  completed_with_decisions: '自动记忆：已完成',
  provider_error: '自动记忆：服务失败',
  invalid_output: '自动记忆：结果无效',
  skipped_no_write_consent: '自动记忆：因未授权跳过',
  skipped_write_consent_changed: '自动记忆：因授权变化跳过',
  skipped_turn_before_write_grant: '自动记忆：授权前回合已跳过',
  cancelled_session_deleted: '自动记忆：会话删除后取消',
  cancelled: '自动记忆：已取消',
  failed: '自动记忆：失败',
};

export function MemoryAutomationControls({
  consent,
  loading,
  latestJob,
  onUpdate,
}: MemoryAutomationControlsProps) {
  const [confirmingGrant, setConfirmingGrant] = useState(false);
  const granted = consent?.status === 'granted';
  const status = consent?.status ?? 'unknown';
  const jobLabel = latestJob?.outcome
    ? JOB_LABELS[latestJob.outcome] ?? `自动记忆：${latestJob.outcome}`
    : latestJob?.status === 'pending' || latestJob?.status === 'running'
      ? '自动记忆：同步中'
      : null;

  return (
    <section className="memory-automation" aria-label="自动记忆设置">
      <h3>本地自动写入</h3>
      <p className="memory-panel__hint">
        只授权写入本机长期记忆；不会授权远程记忆抽取，也不会改变远程发送设置。
        内容保存在本地，可随时撤回授权，并可单独归档或真正忘记。
      </p>
      <p className="memory-automation__status">
        当前状态：<strong>{granted ? '已允许' : status === 'revoked' ? '已撤回' : status === 'declined' ? '已拒绝' : '未选择'}</strong>
        {consent ? ` · 授权代次 ${consent.generation}` : ''}
      </p>
      <div className="memory-panel__actions">
        {granted ? (
          <button type="button" disabled={loading} onClick={() => void onUpdate('revoke')}>
            撤回本地自动写入
          </button>
        ) : confirmingGrant ? (
          <>
            <button type="button" disabled={loading} onClick={() => {
              setConfirmingGrant(false);
              void onUpdate('grant');
            }}>
              确认允许本地自动写入
            </button>
            <button type="button" onClick={() => setConfirmingGrant(false)}>取消授权</button>
          </>
        ) : (
          <>
            <button type="button" disabled={loading} onClick={() => setConfirmingGrant(true)}>
              允许本地自动写入
            </button>
            <button type="button" disabled={loading} onClick={() => void onUpdate('decline')}>
              暂不允许
            </button>
          </>
        )}
      </div>
      {jobLabel ? <p className="memory-automation__job" aria-live="polite">{jobLabel}</p> : null}
    </section>
  );
}
