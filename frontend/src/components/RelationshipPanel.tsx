import { useState } from 'react';
import type {
  RelationshipAudit,
  RelationshipCapabilities,
  RelationshipEvent,
  RelationshipJob,
  RelationshipProjection,
  RelationshipReconcileRequest,
  RelationshipRedactRequest,
  RelationshipReenableRequest,
  RelationshipSuppressRequest,
} from '../api/types';

interface RelationshipPanelProps {
  capabilities: RelationshipCapabilities | null;
  projection: RelationshipProjection | null;
  events: RelationshipEvent[];
  jobs: RelationshipJob[];
  audits: RelationshipAudit[];
  loading: boolean;
  error: string | null;
  onRetryLoad: () => Promise<void>;
  onReconcile: (request: RelationshipReconcileRequest) => Promise<void>;
  onRebuild: (request: RelationshipReconcileRequest) => Promise<void>;
  onSuppress: (applyEventId: string, request: RelationshipSuppressRequest) => Promise<void>;
  onRedact: (applyEventId: string, request: RelationshipRedactRequest) => Promise<void>;
  onReenable: (
    sourceMemoryId: string,
    eventType: string,
    subjectCode: string,
    request: RelationshipReenableRequest,
  ) => Promise<void>;
}

type Confirmation =
  | { kind: 'suppress'; event: RelationshipEvent; label: string }
  | { kind: 'redact'; event: RelationshipEvent; label: string }
  | { kind: 'reenable'; event: RelationshipEvent; label: string }
  | null;

const familiarityLabels: Record<string, string> = {
  reserved: '保留',
  steady: '稳定',
  familiar: '熟悉',
  close: '亲近',
};

const summaryLabels: Record<string, string> = {
  reserved: '保留',
  steady: '稳定',
  familiar: '熟悉',
  close: '亲近',
};

const eventKindLabels: Record<string, string> = {
  apply: '贡献',
  revoke: '撤销',
};

const subjectLabels: Record<string, string> = {
  preferred_address: '偏好的称呼',
  shared_experience: '共同经历',
  non_external_commitment: '不对外承诺',
};

const jobStatusLabels: Record<string, string> = {
  pending: '等待处理',
  running: '处理中',
  succeeded: '已完成',
  failed: '失败',
  cancelled: '已取消',
  skipped: '已跳过',
};

function authorityRequest(event: RelationshipEvent): RelationshipSuppressRequest {
  return {
    expected_decision_id: event.authority.decision_id,
    expected_decision_generation: event.authority.generation,
    expected_authority_epoch: event.authority.authority_epoch,
  };
}

function reenableRequest(event: RelationshipEvent): RelationshipReenableRequest {
  return {
    expected_decision_id: event.authority.decision_id,
    expected_decision_generation: event.authority.generation,
    expected_authority_epoch: event.authority.authority_epoch,
  };
}

export function RelationshipPanel(props: RelationshipPanelProps) {
  const {
    capabilities,
    projection,
    events,
    jobs,
    audits,
    loading,
    error,
    onRetryLoad,
    onReconcile,
    onRebuild,
    onSuppress,
    onRedact,
    onReenable,
  } = props;
  const [confirmation, setConfirmation] = useState<Confirmation>(null);
  const [reconcileBusy, setReconcileBusy] = useState(false);
  const [rebuildBusy, setRebuildBusy] = useState(false);

  async function confirm() {
    const selected = confirmation;
    if (!selected) return;
    setConfirmation(null);
    if (selected.kind === 'suppress') {
      await onSuppress(selected.event.id, authorityRequest(selected.event));
    } else if (selected.kind === 'redact') {
      await onRedact(selected.event.id, {
        ...authorityRequest(selected.event),
        confirm_irreversible: true,
      });
    } else if (selected.kind === 'reenable' && selected.event.source_memory_id) {
      await onReenable(
        selected.event.source_memory_id,
        selected.event.event_type,
        selected.event.subject_code,
        reenableRequest(selected.event),
      );
    }
  }

  async function runReconcile() {
    setReconcileBusy(true);
    try {
      await onReconcile({});
    } finally {
      setReconcileBusy(false);
    }
  }

  async function runRebuild() {
    setRebuildBusy(true);
    try {
      await onRebuild({});
    } finally {
      setRebuildBusy(false);
    }
  }

  const confirmationButton = confirmation ? (
    <button type="button" onClick={() => void confirm()}>{confirmation.label}</button>
  ) : null;

  return (
    <section className="relationship-panel" aria-label="关系投影">
      <details>
        <summary>关系投影</summary>
        <div className="relationship-panel__content">
          <h3>本地关系投影（非事实）</h3>
          <p className="relationship-panel__hint">
            关系投影是本地推导、可撤回的角色关系上下文，仅用于一致性表现，不代表真实关系事实。这里不连接远程抽取、不收集或发送任何数据。
          </p>
          {capabilities ? (
            <p className="relationship-panel__hint">
              仅本地模式 · 无远程抽取 · 无远程授权。
            </p>
          ) : null}
          {error ? <p className="relationship-panel__error" role="alert">{error}</p> : null}
          {error ? <button type="button" onClick={() => void onRetryLoad()}>重新加载关系投影</button> : null}
          {loading ? <p>关系投影加载中……</p> : null}

          {projection ? (
            <section>
              <h4>当前投影</h4>
              {projection.available ? (
                <>
                  <p>
                    熟悉度：{projection.familiarity_bucket ? familiarityLabels[projection.familiarity_bucket] ?? projection.familiarity_bucket : '不可用'} · 连续性：稳定
                  </p>
                  <p>
                    当前称呼：{projection.preferred_address ?? '（未设定）'}
                  </p>
                  <p>
                    Persona {projection.persona_artifact_id ?? '不可用'} · 投影版本 {projection.projection_version ?? '不可用'} · 规则版本 {projection.projection_rule_version ?? '不可用'} · 贡献事件 {projection.contributing_event_count ?? 0} 个
                  </p>
                </>
              ) : (
                <p>当前没有已验证的关系投影。</p>
              )}
              <div className="relationship-panel__actions">
                <button type="button" disabled={reconcileBusy} onClick={() => void runReconcile()}>
                  {reconcileBusy ? '正在收敛……' : '重新收敛'}
                </button>
                <button type="button" disabled={rebuildBusy} onClick={() => void runRebuild()}>
                  {rebuildBusy ? '正在重建……' : '完整重建'}
                </button>
              </div>
            </section>
          ) : null}

          <section>
            <h4>关系事件</h4>
            {events.length === 0 ? <p>暂无关系事件。</p> : (
              <ul className="relationship-panel__list">
                {events.map((event) => (
                  <li key={event.id}>
                    <strong>
                      {eventKindLabels[event.event_kind] ?? event.event_kind} · {subjectLabels[event.event_type] ?? event.event_type}
                    </strong>
                    <p>
                      {event.payload_state === 'redacted' ? '内容已清除' : (
                        event.event_kind === 'apply' && event.event_type === 'preferred_address'
                          ? `称呼：${event.address ?? '（不可用）'}`
                          : '元数据'
                      )}
                    </p>
                    <p>规则 {event.rule_version} · Persona {event.persona_artifact_id}</p>
                    {event.source_memory_id ? (
                      <p>来源记忆：{event.source_memory_id}</p>
                    ) : null}
                    <div className="relationship-panel__actions">
                      {event.event_kind === 'apply' && event.payload_state === 'active' ? (
                        <button
                          type="button"
                          onClick={() => setConfirmation({ kind: 'suppress', event, label: '确认仅撤销关系贡献' })}
                        >
                          仅撤销关系贡献
                        </button>
                      ) : null}
                      {event.event_kind === 'apply' && event.event_type === 'preferred_address' && event.payload_state === 'active' ? (
                        <button
                          type="button"
                          onClick={() => setConfirmation({ kind: 'redact', event, label: '确认永久清除该称呼' })}
                        >
                          永久清除该称呼
                        </button>
                      ) : null}
                      {event.authority.suppressed ? (
                        <button
                          type="button"
                          onClick={() => setConfirmation({ kind: 'reenable', event, label: '确认重新允许该关系主题' })}
                        >
                          重新允许该关系主题
                        </button>
                      ) : null}
                    </div>
                    {confirmation?.kind === 'suppress' && confirmation.event.id === event.id ? (
                      <p className="relationship-panel__confirmation">
                        仅撤销关系贡献不会修改或删除来源记忆；来源记忆仍在长期记忆面板中管理。
                      </p>
                    ) : null}
                    {confirmation?.kind === 'redact' && confirmation.event.id === event.id ? (
                      <p className="relationship-panel__confirmation">
                        永久清除后不可恢复，且该称呼不会再被使用。
                      </p>
                    ) : null}
                    {confirmation?.kind === 'reenable' && confirmation.event.id === event.id ? (
                      <p className="relationship-panel__confirmation">
                        重新允许后，若来源记忆仍符合规则，收敛可能为同一关系主题生成新的贡献。
                      </p>
                    ) : null}
                    {confirmation && confirmation.event.id === event.id ? (
                      <>
                        {confirmationButton}
                        <button type="button" onClick={() => setConfirmation(null)}>取消</button>
                      </>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <h4>收敛任务</h4>
            {jobs.length === 0 ? <p>暂无收敛任务。</p> : (
              <ul className="relationship-panel__list">
                {jobs.map((job) => (
                  <li key={job.id}>
                    <strong>{jobStatusLabels[job.status] ?? job.status}</strong>
                    <p>{subjectLabels[job.captured_subject_code] ?? job.captured_subject_code} · 尝试 {job.attempt_count} 次</p>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <h4>审计</h4>
            <p>最近 {audits.length} 条元数据审计；不包含来源文本、提示词或模型输出。</p>
          </section>
        </div>
      </details>
    </section>
  );
}
