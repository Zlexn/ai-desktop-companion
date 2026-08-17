import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type {
  RelationshipAudit,
  RelationshipCapabilities,
  RelationshipEvent,
  RelationshipJob,
  RelationshipProjection,
} from '../api/types';
import { RelationshipPanel } from './RelationshipPanel';

const capabilities: RelationshipCapabilities = {
  local_only: true,
  remote_extraction: false,
  remote_consent_exists: false,
  projection: true,
};

const projection: RelationshipProjection = {
  available: true,
  projection_id: 'projection-1',
  projection_version: 4,
  familiarity_bucket: 'familiar',
  preferred_address: '小雪',
  relationship_summary_code: 'familiar',
  persona_artifact_id: 'persona-1',
  projection_rule_version: 'relationship-projection-v1',
  contributing_event_count: 2,
};

const neutralProjection: RelationshipProjection = {
  available: false,
  projection_id: null,
  projection_version: null,
  familiarity_bucket: null,
  preferred_address: null,
  relationship_summary_code: null,
  persona_artifact_id: null,
  projection_rule_version: null,
  contributing_event_count: null,
};

const applyEvent: RelationshipEvent = {
  id: 'apply-1',
  event_kind: 'apply',
  event_type: 'preferred_address',
  subject_code: 'preferred_address',
  payload_state: 'active',
  address: '小雪',
  source_memory_id: 'memory-1',
  revokes_event_id: null,
  rule_version: 'relationship-projection-v1',
  persona_artifact_id: 'persona-1',
  observed_at: '2026-08-16T00:00:00Z',
  created_at: '2026-08-16T00:00:00Z',
  authority: {
    decision_id: 'decision-1',
    generation: 2,
    authority_epoch: 1,
    suppressed: false,
  },
};

const suppressedApplyEvent: RelationshipEvent = {
  ...applyEvent,
  id: 'apply-2',
  address: null,
  authority: {
    decision_id: 'decision-2',
    generation: 3,
    authority_epoch: 2,
    suppressed: true,
  },
};

const redactedApplyEvent: RelationshipEvent = {
  ...applyEvent,
  id: 'apply-3',
  payload_state: 'redacted',
  address: null,
};

const revokeEvent: RelationshipEvent = {
  id: 'revoke-1',
  event_kind: 'revoke',
  event_type: 'preferred_address',
  subject_code: 'preferred_address',
  payload_state: 'active',
  address: null,
  source_memory_id: 'memory-1',
  revokes_event_id: 'apply-1',
  rule_version: 'relationship-projection-v1',
  persona_artifact_id: 'persona-1',
  observed_at: '2026-08-16T00:01:00Z',
  created_at: '2026-08-16T00:01:00Z',
  authority: {
    decision_id: 'decision-1',
    generation: 2,
    authority_epoch: 1,
    suppressed: true,
  },
};

const job: RelationshipJob = {
  id: 'job-1',
  status: 'succeeded',
  outcome: 'applied',
  source_memory_id: 'memory-1',
  captured_event_type: 'preferred_address',
  captured_subject_code: 'preferred_address',
  captured_record_head_version: 1,
  captured_record_generation: 0,
  captured_authority_generation: 2,
  captured_authority_epoch: 1,
  attempt_count: 1,
  reason_code: 'eligible_apply',
  error_category: null,
  relationship_rule_version: 'relationship-projection-v1',
  persona_artifact_id: 'persona-1',
  created_at: '2026-08-16T00:00:00Z',
  started_at: '2026-08-16T00:00:01Z',
  finished_at: '2026-08-16T00:00:02Z',
};

const audit: RelationshipAudit = {
  id: 'audit-1',
  job_id: 'job-1',
  outcome: 'applied',
  reason_code: 'eligible_apply',
  attempt_count: 1,
  created_at: '2026-08-16T00:00:00Z',
};

function props() {
  return {
    capabilities,
    projection,
    events: [applyEvent, suppressedApplyEvent, redactedApplyEvent, revokeEvent],
    jobs: [job],
    audits: [audit],
    loading: false,
    error: null,
    onRetryLoad: vi.fn(),
    onReconcile: vi.fn(),
    onRebuild: vi.fn(),
    onSuppress: vi.fn(),
    onRedact: vi.fn(),
    onReenable: vi.fn(),
  };
}

afterEach(() => {
  cleanup();
});

describe('RelationshipPanel', () => {
  it('shows a collapsible local-only explanation without remote or consent wording', () => {
    render(<RelationshipPanel {...props()} />);

    expect(screen.getByText('关系投影')).toBeInTheDocument();
    expect(screen.getByText(/仅本地模式 · 无远程抽取 · 无远程授权/)).toBeInTheDocument();
    expect(screen.queryByText(/允许远程|已授权远程|consent/i)).not.toBeInTheDocument();
  });

  it('renders the current projection with fixed labels and bounded values', () => {
    render(<RelationshipPanel {...props()} />);

    expect(screen.getByText(/熟悉度：熟悉 · 连续性：稳定/)).toBeInTheDocument();
    expect(screen.getByText(/当前称呼：小雪/)).toBeInTheDocument();
    expect(screen.getByText(/Persona persona-1 · 投影版本 4 · 规则版本 relationship-projection-v1 · 贡献事件 2 个/)).toBeInTheDocument();
  });

  it('renders neutral projection when unavailable', () => {
    render(<RelationshipPanel {...props()} projection={neutralProjection} events={[]} jobs={[]} audits={[]} />);

    expect(screen.getByText('当前没有已验证的关系投影。')).toBeInTheDocument();
    expect(screen.queryByText(/当前称呼：/)).not.toBeInTheDocument();
  });

  it('paginates apply/revoke metadata labels and hides unavailable values', () => {
    render(<RelationshipPanel {...props()} />);

    expect(screen.getAllByText(/贡献 · 偏好的称呼/)).toHaveLength(3);
    expect(screen.getByText(/撤销 · 偏好的称呼/)).toBeInTheDocument();
    expect(screen.getByText('内容已清除')).toBeInTheDocument();
    // Only the active apply exposes the bounded address.
    expect(screen.getAllByText('称呼：小雪')).toHaveLength(1);
  });

  it('links to the source memory only when the API supplies one', () => {
    const withoutSource: RelationshipEvent = { ...applyEvent, source_memory_id: null };
    render(<RelationshipPanel {...props()} events={[withoutSource]} />);

    expect(screen.queryByText(/来源记忆：/)).not.toBeInTheDocument();
  });

  it('shows reconcile/rebuild actions and invokes them', async () => {
    const onReconcile = vi.fn().mockResolvedValue(undefined);
    const onRebuild = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<RelationshipPanel {...props()} onReconcile={onReconcile} onRebuild={onRebuild} />);

    await user.click(screen.getByRole('button', { name: '重新收敛' }));
    expect(onReconcile).toHaveBeenCalledWith({});

    await user.click(screen.getByRole('button', { name: '完整重建' }));
    expect(onRebuild).toHaveBeenCalledWith({});
  });

  it('suppress requires an inline confirmation explaining the source memory is unchanged', async () => {
    const onSuppress = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<RelationshipPanel {...props()} events={[applyEvent]} onSuppress={onSuppress} />);

    await user.click(screen.getByRole('button', { name: '仅撤销关系贡献' }));
    expect(onSuppress).not.toHaveBeenCalled();
    expect(screen.getByText(/仅撤销关系贡献不会修改或删除来源记忆/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '确认仅撤销关系贡献' }));
    expect(onSuppress).toHaveBeenCalledWith('apply-1', {
      expected_decision_id: 'decision-1',
      expected_decision_generation: 2,
      expected_authority_epoch: 1,
    });
  });

  it('redaction requires an inline irreversible confirmation and sends confirm_irreversible', async () => {
    const onRedact = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<RelationshipPanel {...props()} events={[applyEvent]} onRedact={onRedact} />);

    await user.click(screen.getByRole('button', { name: '永久清除该称呼' }));
    expect(onRedact).not.toHaveBeenCalled();
    expect(screen.getByText(/永久清除后不可恢复/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '确认永久清除该称呼' }));
    expect(onRedact).toHaveBeenCalledWith('apply-1', {
      expected_decision_id: 'decision-1',
      expected_decision_generation: 2,
      expected_authority_epoch: 1,
      confirm_irreversible: true,
    });
  });

  it('re-enable explains it may derive a new apply and sends the authority expectation', async () => {
    const onReenable = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<RelationshipPanel {...props()} events={[suppressedApplyEvent]} onReenable={onReenable} />);

    await user.click(screen.getByRole('button', { name: '重新允许该关系主题' }));
    expect(onReenable).not.toHaveBeenCalled();
    expect(screen.getByText(/重新允许后，若来源记忆仍符合规则/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '确认重新允许该关系主题' }));
    expect(onReenable).toHaveBeenCalledWith('memory-1', 'preferred_address', 'preferred_address', {
      expected_decision_id: 'decision-2',
      expected_decision_generation: 3,
      expected_authority_epoch: 2,
    });
  });

  it('never renders redacted/deleted or unavailable values', () => {
    render(<RelationshipPanel {...props()} events={[redactedApplyEvent, revokeEvent]} />);

    // Redacted apply: no address, no suppress/redact actions.
    expect(screen.queryByText('称呼：小雪')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '仅撤销关系贡献' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '永久清除该称呼' })).not.toBeInTheDocument();
  });

  it('renders jobs and audits as metadata-only', () => {
    render(<RelationshipPanel {...props()} />);

    expect(screen.getByText('已完成')).toBeInTheDocument();
    expect(screen.getByText(/偏好的称呼 · 尝试 1 次/)).toBeInTheDocument();
    expect(screen.getByText(/最近 1 条元数据审计/)).toBeInTheDocument();
    expect(screen.queryByText(/payload|fingerprint|hmac|lineage/i)).not.toBeInTheDocument();
  });

  it('shows the error and a retry action without leaking other panels', () => {
    render(<RelationshipPanel {...props()} error="关系投影加载失败" projection={null} events={[]} jobs={[]} audits={[]} />);

    expect(screen.getByRole('alert')).toHaveTextContent('关系投影加载失败');
    expect(screen.getByRole('button', { name: '重新加载关系投影' })).toBeInTheDocument();
  });
});
