import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type {
  SummaryAudit,
  SummaryCapabilities,
  SummaryInjectionConsent,
  SummaryItem,
  SummaryJob,
  SummaryProcessingConsent,
  SummaryStatus,
} from '../api/types';
import { SummaryPanel } from './SummaryPanel';

const capabilities: SummaryCapabilities = {
  summary_processing: true,
  summary_injection: true,
  processing_route: 'remote',
  processing_provider: 'deepseek',
  processing_model: 'summary-model',
  injection_route: 'remote',
  injection_provider: 'deepseek',
  injection_model: 'chat-model',
  remote_summary: 'remote_summary_available_requires_consent',
};

const processing: SummaryProcessingConsent = {
  scope_id: 'default',
  status: 'unknown',
  route: 'remote',
  disclosure_version: 'summary-processing-disclosure-v1',
  purpose: '生成低可信会话概述',
  provider: 'deepseek',
  model: 'summary-model',
  disclosed_fields: ['完整对话轮次文本'],
  generation: 2,
  valid_for_current_policy: false,
  reason_code: 'not_granted_for_current_policy',
  updated_at: '2026-07-25T00:00:00Z',
};

const injection: SummaryInjectionConsent = {
  scope_id: 'default',
  status: 'unknown',
  route: 'remote',
  disclosure_version: 'summary-injection-disclosure-v1',
  purpose: '向聊天模型提供低可信会话概述',
  provider: 'deepseek',
  model: 'chat-model',
  disclosed_fields: ['会话概述文本'],
  generation: 4,
  max_fragment_count: 2,
  max_fragment_characters: 1000,
  max_total_characters: 1600,
  valid_for_current_policy: false,
  reason_code: 'not_granted_for_current_policy',
  updated_at: '2026-07-25T00:00:00Z',
};

const activeSummary: SummaryItem = {
  id: 'summary-active',
  session_id: 'session-1',
  summary_text: '用户正在准备一次旅行。',
  source_kind: 'generated',
  payload_state: 'active',
  provenance_state: 'exact',
  source_message_count: 4,
  source_turn_count: 2,
  source_started_at: '2026-07-24T00:00:00Z',
  source_ended_at: '2026-07-24T00:05:00Z',
  replaces_summary_id: null,
  suppression_generation: 0,
  suppression_state: null,
  unavailable_label: null,
  created_at: '2026-07-24T00:06:00Z',
  updated_at: '2026-07-24T00:06:00Z',
};

const redactedSummary: SummaryItem = {
  ...activeSummary,
  id: 'summary-redacted',
  summary_text: null,
  payload_state: 'redacted',
  suppression_generation: 3,
  suppression_state: 'suppressed',
  unavailable_label: '内容已清除',
};

const rebuildJob: SummaryJob = {
  id: 'job-1',
  session_id: 'session-1',
  job_kind: 'rebuild',
  status: 'failed',
  source_summary_id: 'summary-redacted',
  source_message_count: 4,
  source_turn_count: 2,
  route: 'remote',
  provider: 'deepseek',
  model: 'summary-model',
  summarizer_schema_version: 'summary-schema-v1',
  job_schema_version: 'summary-job-v1',
  attempt_count: 1,
  reason_code: 'provider_error',
  error_category: 'provider',
  retryable: true,
  cancellable: true,
  suppression_generation: 5,
  suppression_state: 'rebuild_in_progress',
  created_at: '2026-07-25T00:00:00Z',
  started_at: '2026-07-25T00:00:01Z',
  finished_at: '2026-07-25T00:00:02Z',
};

const status: SummaryStatus = {
  summary_counts: { active: 1, redacted: 1 },
  job_counts: { failed: 1 },
};

const audits: SummaryAudit[] = [];

function props() {
  return {
    capabilities,
    processingConsent: processing,
    injectionConsent: injection,
    status,
    summaries: [activeSummary, redactedSummary],
    jobs: [rebuildJob],
    audits,
    loading: false,
    error: null,
    onRetryLoad: vi.fn(async () => undefined),
    onUpdateProcessing: vi.fn(async () => undefined),
    onUpdateInjection: vi.fn(async () => undefined),
    onRedact: vi.fn(async () => undefined),
    onRebuild: vi.fn(async () => undefined),
    onRetryJob: vi.fn(async () => undefined),
    onCancelJob: vi.fn(async () => undefined),
  };
}

afterEach(cleanup);

describe('SummaryPanel', () => {
  it('keeps processing and injection decisions independent with exact confirmation', async () => {
    const value = props();
    render(<SummaryPanel {...value} />);
    await userEvent.click(screen.getByText('会话概述'));

    await userEvent.click(screen.getByRole('button', { name: '允许远程生成' }));
    expect(value.onUpdateProcessing).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: '确认允许远程生成' }));

    expect(value.onUpdateProcessing).toHaveBeenCalledWith({
      action: 'grant',
      expected_generation: 2,
    });
    expect(value.onUpdateInjection).not.toHaveBeenCalled();
  });

  it('never renders private identities, redacted payload, or unavailable source text', async () => {
    const value = props();
    render(<SummaryPanel {...value} />);
    await userEvent.click(screen.getByText('会话概述'));

    expect(screen.getByText('低可信会话概述')).toBeInTheDocument();
    for (const field of injection.disclosed_fields) {
      expect(document.body.textContent).toContain(field);
    }
    expect(screen.getAllByText('内容已清除').length).toBeGreaterThan(0);
    expect(screen.queryByText('DELETED_SUMMARY_SENTINEL')).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(
      /source_set_hash|policy_fingerprint|rebuild_permit_id|source_message_ids|source_turn_ids/i,
    );
    expect(screen.getAllByText(/2 个完整轮次/).length).toBeGreaterThan(0);
  });

  it('renders stale-barrier redactions as unavailable without exposing payload', async () => {
    const value = props();
    value.summaries = [{
      ...activeSummary,
      id: 'summary-stale',
      summary_text: null,
      payload_state: 'redacted',
      unavailable_label: '状态已过期',
    }];
    render(<SummaryPanel {...value} />);
    await userEvent.click(screen.getByText('会话概述'));

    expect(screen.getAllByText('状态已过期').length).toBeGreaterThan(0);
    expect(screen.queryByText('STALE_SUMMARY_SENTINEL')).not.toBeInTheDocument();
  });

  it('renders quarantined, legacy, and replacement states without unavailable payloads', async () => {
    const value = props();
    value.summaries = [
      {
        ...activeSummary,
        id: 'summary-quarantined',
        summary_text: null,
        payload_state: 'quarantined',
        unavailable_label: '内容不可用',
      },
      {
        ...activeSummary,
        id: 'summary-legacy',
        summary_text: 'LEGACY_SUMMARY_SENTINEL',
        provenance_state: 'legacy_unverified',
      },
      {
        ...activeSummary,
        id: 'summary-replacement',
        summary_text: '安全重建版本',
        replaces_summary_id: 'summary-redacted',
      },
    ];
    render(<SummaryPanel {...value} />);
    await userEvent.click(screen.getByText('会话概述'));

    expect(screen.getAllByText('内容不可用').length).toBeGreaterThan(0);
    expect(screen.getAllByText('旧版来源，未经验证').length).toBeGreaterThan(0);
    expect(screen.getByText('重建替代版本')).toBeInTheDocument();
    expect(screen.getByText('安全重建版本')).toBeInTheDocument();
    expect(screen.queryByText('LEGACY_SUMMARY_SENTINEL')).not.toBeInTheDocument();
  });

  it('uses suppression snapshots for rebuild retry and cancel confirmations', async () => {
    const value = props();
    render(<SummaryPanel {...value} />);
    await userEvent.click(screen.getByText('会话概述'));

    await userEvent.click(screen.getByRole('button', { name: '重建已清除概述' }));
    expect(value.onRebuild).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: '确认重建概述' }));
    expect(value.onRebuild).toHaveBeenCalledWith('summary-redacted', {
      expected_suppression_generation: 3,
    });

    await userEvent.click(screen.getByRole('button', { name: '重试任务' }));
    await userEvent.click(screen.getByRole('button', { name: '确认重试任务' }));
    expect(value.onRetryJob).toHaveBeenCalledWith('job-1', {
      expected_status: 'failed',
      expected_suppression_generation: 5,
      expected_suppression_state: 'rebuild_in_progress',
    });

    await userEvent.click(screen.getByRole('button', { name: '取消任务' }));
    await userEvent.click(screen.getByRole('button', { name: '确认取消任务' }));
    expect(value.onCancelJob).toHaveBeenCalledWith('job-1', {
      expected_status: 'failed',
      expected_suppression_generation: 5,
      expected_suppression_state: 'rebuild_in_progress',
    });
  });

  it('uses local enable wording without claiming remote disclosure', async () => {
    const value = props();
    value.capabilities = {
      ...capabilities,
      processing_route: 'local',
      processing_provider: 'fake',
      processing_model: 'fake-session-summary-v1',
      injection_route: 'local',
      injection_provider: 'fake',
      injection_model: 'fake-model',
      remote_summary: 'local_summary_available',
    };
    value.processingConsent = { ...processing, route: 'local', provider: 'fake' };
    value.injectionConsent = { ...injection, route: 'local', provider: 'fake' };
    render(<SummaryPanel {...value} />);
    await userEvent.click(screen.getByText('会话概述'));

    expect(screen.getByRole('button', { name: '启用本地生成' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '启用本地注入' })).toBeInTheDocument();
    expect(screen.queryByText(/允许远程/)).not.toBeInTheDocument();
  });
});
