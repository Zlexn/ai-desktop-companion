import { useState } from 'react';
import type {
  SummaryAudit,
  SummaryAuthorityAction,
  SummaryAuthorityMutationRequest,
  SummaryCapabilities,
  SummaryInjectionConsent,
  SummaryItem,
  SummaryJob,
  SummaryJobMutationRequest,
  SummaryProcessingConsent,
  SummaryRebuildRequest,
  SummaryRedactRequest,
  SummaryStatus,
} from '../api/types';

interface SummaryPanelProps {
  capabilities: SummaryCapabilities | null;
  processingConsent: SummaryProcessingConsent | null;
  injectionConsent: SummaryInjectionConsent | null;
  status: SummaryStatus | null;
  summaries: SummaryItem[];
  jobs: SummaryJob[];
  audits: SummaryAudit[];
  loading: boolean;
  error: string | null;
  onRetryLoad: () => Promise<void>;
  onUpdateProcessing: (request: SummaryAuthorityMutationRequest) => Promise<void>;
  onUpdateInjection: (request: SummaryAuthorityMutationRequest) => Promise<void>;
  onRedact: (summaryId: string, request: SummaryRedactRequest) => Promise<void>;
  onRebuild: (summaryId: string, request: SummaryRebuildRequest) => Promise<void>;
  onRetryJob: (jobId: string, request: SummaryJobMutationRequest) => Promise<void>;
  onCancelJob: (jobId: string, request: SummaryJobMutationRequest) => Promise<void>;
}

type Confirmation =
  | { kind: 'processing'; action: SummaryAuthorityAction; label: string }
  | { kind: 'injection'; action: SummaryAuthorityAction; label: string }
  | { kind: 'redact'; summary: SummaryItem; label: string }
  | { kind: 'rebuild'; summary: SummaryItem; label: string }
  | { kind: 'retry'; job: SummaryJob; label: string }
  | { kind: 'cancel'; job: SummaryJob; label: string }
  | null;

const statusLabels: Record<string, string> = {
  unknown: '未决定',
  granted: '已允许',
  declined: '已拒绝',
  revoked: '已撤回',
  pending: '等待处理',
  running: '处理中',
  succeeded: '已完成',
  failed: '失败',
  cancelled: '已取消',
  skipped: '已跳过',
};

const reasonLabels: Record<string, string> = {
  provider_error: '概述服务失败，可在状态仍匹配时重试。',
  provider_unavailable: '概述服务未配置。',
  skipped_no_consent: '生成授权当前无效。',
  discarded_processing_authority_changed: '生成授权已变化。',
  discarded_provider_policy_changed: '生成配置已变化。',
  discarded_suppression_changed: '清除或重建状态已变化。',
  discarded_source_changed: '概述来源已变化。',
  discarded_source_excluded: '概述来源已被排除。',
  discarded_session_deleted: '来源会话已删除。',
  worker_error: '后台处理失败。',
};

function routeLabel(route: string): string {
  return route === 'remote' ? '远程 API' : '本地';
}

function consentState(status: string, valid: boolean): string {
  if (status === 'granted' && !valid) return '历史允许，当前配置下已失效';
  return statusLabels[status] ?? status;
}

function sourceRange(summary: SummaryItem): string {
  if (!summary.source_started_at || !summary.source_ended_at) return '来源时间不可用';
  return `${new Date(summary.source_started_at).toLocaleString()} 至 ${new Date(summary.source_ended_at).toLocaleString()}`;
}

function summaryState(summary: SummaryItem): string {
  if (summary.unavailable_label) return summary.unavailable_label;
  if (summary.payload_state === 'redacted') return '内容已清除';
  if (summary.payload_state === 'quarantined') return '内容不可用';
  if (summary.provenance_state !== 'exact') return '旧版来源，未经验证';
  if (summary.replaces_summary_id) return '重建替代版本';
  return '可用';
}

function jobMutation(job: SummaryJob): SummaryJobMutationRequest {
  const request: SummaryJobMutationRequest = {
    expected_status: job.status as SummaryJobMutationRequest['expected_status'],
  };
  if (job.job_kind === 'rebuild') {
    if (job.suppression_generation === null || job.suppression_generation === undefined) {
      throw new Error('重建任务缺少可安全操作的状态快照。');
    }
    if (!job.suppression_state) {
      throw new Error('重建任务缺少可安全操作的状态快照。');
    }
    request.expected_suppression_generation = job.suppression_generation;
    request.expected_suppression_state = job.suppression_state;
  }
  return request;
}

function AuthorityControls({
  kind,
  consent,
  available,
  confirmation,
  setConfirmation,
}: {
  kind: 'processing' | 'injection';
  consent: SummaryProcessingConsent | SummaryInjectionConsent;
  available: boolean;
  confirmation: Confirmation;
  setConfirmation: (value: Confirmation) => void;
}) {
  const local = consent.route === 'local';
  const enableAction: SummaryAuthorityAction = local ? 'enable_local' : 'grant';
  const enableLabel = kind === 'processing'
    ? (local ? '启用本地生成' : '允许远程生成')
    : (local ? '启用本地注入' : '允许远程注入');
  const disableAction: SummaryAuthorityAction = local ? 'disable_local' : 'revoke';
  const disableLabel = local ? '关闭本地能力' : '撤回允许';
  const selected = confirmation?.kind === kind ? confirmation : null;

  if (selected) {
    return (
      <div className="summary-panel__confirmation">
        <strong>{selected.label}</strong>
        <button type="button" onClick={() => setConfirmation(null)}>取消</button>
      </div>
    );
  }

  return (
    <div className="summary-panel__actions">
      <button
        type="button"
        disabled={!available || (consent.status === 'granted' && consent.valid_for_current_policy)}
        onClick={() => setConfirmation({ kind, action: enableAction, label: `确认${enableLabel}` })}
      >
        {enableLabel}
      </button>
      {!local ? (
        <button
          type="button"
          disabled={!available || consent.status === 'declined'}
          onClick={() => setConfirmation({ kind, action: 'decline', label: '确认拒绝远程使用' })}
        >
          拒绝远程使用
        </button>
      ) : null}
      <button
        type="button"
        disabled={consent.status !== 'granted'}
        onClick={() => setConfirmation({ kind, action: disableAction, label: `确认${disableLabel}` })}
      >
        {disableLabel}
      </button>
    </div>
  );
}

export function SummaryPanel(props: SummaryPanelProps) {
  const {
    capabilities,
    processingConsent,
    injectionConsent,
    status,
    summaries,
    jobs,
    audits,
    loading,
    error,
    onRetryLoad,
    onUpdateProcessing,
    onUpdateInjection,
    onRedact,
    onRebuild,
    onRetryJob,
    onCancelJob,
  } = props;
  const [confirmation, setConfirmation] = useState<Confirmation>(null);

  async function confirm() {
    const selected = confirmation;
    if (!selected) return;
    setConfirmation(null);
    if (selected.kind === 'processing' && processingConsent) {
      await onUpdateProcessing({
        action: selected.action,
        expected_generation: processingConsent.generation,
      });
    } else if (selected.kind === 'injection' && injectionConsent) {
      await onUpdateInjection({
        action: selected.action,
        expected_generation: injectionConsent.generation,
      });
    } else if (selected.kind === 'redact') {
      await onRedact(selected.summary.id, {
        expected_suppression_generation: selected.summary.suppression_generation,
        confirmation: 'redact_summary_payload',
      });
    } else if (selected.kind === 'rebuild') {
      await onRebuild(selected.summary.id, {
        expected_suppression_generation: selected.summary.suppression_generation,
      });
    } else if (selected.kind === 'retry') {
      await onRetryJob(selected.job.id, jobMutation(selected.job));
    } else if (selected.kind === 'cancel') {
      await onCancelJob(selected.job.id, jobMutation(selected.job));
    }
  }

  const confirmationButton = confirmation ? (
    <button type="button" onClick={() => void confirm()}>{confirmation.label}</button>
  ) : null;

  return (
    <section className="summary-panel" aria-label="会话概述">
      <details>
        <summary>会话概述</summary>
        <div className="summary-panel__content">
          <h3>低可信会话概述</h3>
          <p className="summary-panel__hint">
            概述只作为低可信上下文，不会覆盖角色设定、正式记忆或情感状态。这里只显示数量与时间范围，不显示来源消息正文。
          </p>
          {error ? <p className="summary-panel__error" role="alert">{error}</p> : null}
          {error ? <button type="button" onClick={() => void onRetryLoad()}>重新加载会话概述</button> : null}
          {loading ? <p>会话概述加载中……</p> : null}

          {capabilities ? (
            <section>
              <h4>能力与路径</h4>
              <p>
                生成：{capabilities.summary_processing ? '可用' : '未启用'} · {routeLabel(capabilities.processing_route)} · {capabilities.processing_provider} / {capabilities.processing_model}
              </p>
              <p>
                注入：{capabilities.summary_injection ? '可用' : '未启用'} · {routeLabel(capabilities.injection_route)} · {capabilities.injection_provider} / {capabilities.injection_model}
              </p>
            </section>
          ) : null}

          {processingConsent && capabilities ? (
            <section>
              <h4>概述生成授权</h4>
              <p>{consentState(processingConsent.status, processingConsent.valid_for_current_policy)}</p>
              <p>用途：{processingConsent.purpose}</p>
              <p>将使用：{processingConsent.disclosed_fields.join('、')}</p>
              <AuthorityControls
                kind="processing"
                consent={processingConsent}
                available={capabilities.summary_processing}
                confirmation={confirmation}
                setConfirmation={setConfirmation}
              />
              {confirmation?.kind === 'processing' ? confirmationButton : null}
            </section>
          ) : null}

          {injectionConsent && capabilities ? (
            <section>
              <h4>概述注入授权</h4>
              <p>{consentState(injectionConsent.status, injectionConsent.valid_for_current_policy)}</p>
              <p>用途：{injectionConsent.purpose}</p>
              <p>将使用：{injectionConsent.disclosed_fields.join('、')}</p>
              <p>
                上限：{injectionConsent.max_fragment_count} 条，每条 {injectionConsent.max_fragment_characters} 字符，总计 {injectionConsent.max_total_characters} 字符
              </p>
              <AuthorityControls
                kind="injection"
                consent={injectionConsent}
                available={capabilities.summary_injection}
                confirmation={confirmation}
                setConfirmation={setConfirmation}
              />
              {confirmation?.kind === 'injection' ? confirmationButton : null}
            </section>
          ) : null}

          {status ? (
            <section>
              <h4>状态</h4>
              <p>概述 {Object.values(status.summary_counts).reduce((sum, value) => sum + value, 0)} 条 · 任务 {Object.values(status.job_counts).reduce((sum, value) => sum + value, 0)} 个</p>
            </section>
          ) : null}

          <section>
            <h4>概述记录</h4>
            {summaries.length === 0 ? <p>暂无会话概述。</p> : (
              <ul className="summary-panel__list">
                {summaries.map((summary) => (
                  <li key={summary.id}>
                    <strong>{summaryState(summary)}</strong>
                    {summary.payload_state === 'active' && summary.provenance_state === 'exact' ? (
                      <p>{summary.summary_text}</p>
                    ) : (
                      <p>{summary.unavailable_label ?? summaryState(summary)}</p>
                    )}
                    <p>{summary.source_turn_count} 个完整轮次 · {summary.source_message_count} 条消息</p>
                    <p>{sourceRange(summary)}</p>
                    <div className="summary-panel__actions">
                      {summary.payload_state === 'active' ? (
                        <button type="button" onClick={() => setConfirmation({ kind: 'redact', summary, label: '确认永久清除概述内容' })}>永久清除概述内容</button>
                      ) : null}
                      {summary.payload_state === 'redacted' && summary.suppression_state === 'suppressed' ? (
                        <button type="button" onClick={() => setConfirmation({ kind: 'rebuild', summary, label: '确认重建概述' })}>重建已清除概述</button>
                      ) : null}
                    </div>
                    {confirmation?.kind === 'redact' && confirmation.summary.id === summary.id ? confirmationButton : null}
                    {confirmation?.kind === 'rebuild' && confirmation.summary.id === summary.id ? confirmationButton : null}
                    {(confirmation?.kind === 'redact' || confirmation?.kind === 'rebuild') && confirmation.summary.id === summary.id ? (
                      <button type="button" onClick={() => setConfirmation(null)}>取消</button>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <h4>最近任务</h4>
            {jobs.length === 0 ? <p>暂无摘要任务。</p> : (
              <ul className="summary-panel__list">
                {jobs.map((job) => (
                  <li key={job.id}>
                    <strong>{job.job_kind === 'rebuild' ? '重建' : '增量生成'} · {statusLabels[job.status] ?? job.status}</strong>
                    <p>{job.source_turn_count} 个完整轮次 · 尝试 {job.attempt_count} 次</p>
                    {job.reason_code ? <p>{reasonLabels[job.reason_code] ?? '任务未完成，请刷新状态后再决定。'}</p> : null}
                    <div className="summary-panel__actions">
                      {job.retryable ? <button type="button" onClick={() => setConfirmation({ kind: 'retry', job, label: '确认重试任务' })}>重试任务</button> : null}
                      {job.cancellable ? <button type="button" onClick={() => setConfirmation({ kind: 'cancel', job, label: '确认取消任务' })}>取消任务</button> : null}
                    </div>
                    {confirmation?.kind === 'retry' && confirmation.job.id === job.id ? confirmationButton : null}
                    {confirmation?.kind === 'cancel' && confirmation.job.id === job.id ? confirmationButton : null}
                    {(confirmation?.kind === 'retry' || confirmation?.kind === 'cancel') && confirmation.job.id === job.id ? (
                      <button type="button" onClick={() => setConfirmation(null)}>取消</button>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <h4>安全审计</h4>
            <p>最近 {audits.length} 条元数据审计；不包含来源文本、提示词或模型原始输出。</p>
          </section>
        </div>
      </details>
    </section>
  );
}
