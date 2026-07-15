import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { EmotionAnalysisConsent } from '../api/types';
import { EmotionPanel } from './EmotionPanel';

const consent: EmotionAnalysisConsent = {
  scope_id: 'default-companion',
  status: 'unknown',
  disclosure_version: null,
  provider: null,
  deployment_provider: 'deepseek',
  deployment_enabled: true,
  updated_at: '2026-07-13T12:00:00Z',
};

const defaultProps = {
  state: null,
  events: [],
  loading: false,
  error: null,
  onSetEnabled: vi.fn(async () => undefined),
  onReset: vi.fn(async () => undefined),
  onRetry: vi.fn(async () => undefined),
  analysisConsent: consent,
  analysisAudits: [],
  analysisConsentLoading: false,
  analysisAuditLoading: false,
  onUpdateAnalysisConsent: vi.fn(async () => undefined),
  onRefreshAnalysisAudits: vi.fn(async () => undefined),
};

afterEach(cleanup);

describe('EmotionPanel analysis consent', () => {
  it('disables consent actions until consent metadata loads', () => {
    render(
      <EmotionPanel
        {...defaultProps}
        analysisConsent={null}
      />,
    );

    expect(screen.getByText('授权状态加载中……')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '授权远程分析' })).toBeDisabled();
  });

  it('discloses remote data, cost, and best-effort redaction before grant', async () => {
    const onUpdate = vi.fn(async () => undefined);
    render(<EmotionPanel {...defaultProps} onUpdateAnalysisConsent={onUpdate} />);

    expect(screen.getByText(/DeepSeek 会通过网络发送/)).toBeInTheDocument();
    expect(screen.getByText(/当前回合、最多 6 条近期消息和最多 3 条相关活跃记忆/)).toBeInTheDocument();
    expect(screen.getByText(/可能产生模型费用/)).toBeInTheDocument();
    expect(screen.getByText(/尽力隐藏明显凭据，但不是完整的隐私或 DLP 保证/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: '授权远程分析' }));
    expect(onUpdate).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: '确认授权并允许发送' }));
    expect(onUpdate).toHaveBeenCalledWith('grant');
  });

  it('supports decline revoke and regrant without changing local emotion switch', async () => {
    const onUpdate = vi.fn(async () => undefined);
    const { rerender } = render(<EmotionPanel {...defaultProps} onUpdateAnalysisConsent={onUpdate} />);

    await userEvent.click(screen.getByRole('button', { name: '暂不授权' }));
    expect(onUpdate).toHaveBeenCalledWith('decline');

    rerender(
      <EmotionPanel
        {...defaultProps}
        analysisConsent={{ ...consent, status: 'granted' }}
        onUpdateAnalysisConsent={onUpdate}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: '撤回远程分析授权' }));
    expect(onUpdate).toHaveBeenCalledWith('revoke');

    rerender(
      <EmotionPanel
        {...defaultProps}
        analysisConsent={{ ...consent, status: 'revoked' }}
        onUpdateAnalysisConsent={onUpdate}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: '重新授权远程分析' }));
    await userEvent.click(screen.getByRole('button', { name: '确认授权并允许发送' }));
    expect(onUpdate).toHaveBeenLastCalledWith('grant');
  });

  it('shows audit refresh progress and disables duplicate refresh', () => {
    render(
      <EmotionPanel
        {...defaultProps}
        analysisAuditLoading
      />,
    );

    expect(screen.getByRole('button', { name: '正在刷新分析记录……' })).toBeDisabled();
  });

  it('shows deployment-disabled state and safe audit categories', () => {
    render(
      <EmotionPanel
        {...defaultProps}
        analysisConsent={{ ...consent, status: 'granted', deployment_enabled: false }}
        analysisAudits={[{
          id: 'audit-1',
          job_id: 'job-1',
          outcome: 'invalid_output',
          source_session_id: 'session-1',
          source_user_message_id: 'user-1',
          source_assistant_message_id: 'assistant-1',
          schema_version: 'emotion_analysis_v1',
          provider: 'deepseek',
          model: 'deepseek-v4-flash',
          message_count: 2,
          memory_count: 0,
          input_characters: 30,
          redaction_count: 1,
          elapsed_ms: 12,
          reason_code: 'invalid_output',
          created_at: '2026-07-13T12:00:00Z',
        }]}
      />,
    );

    expect(screen.getByText(/部署配置尚未开启/)).toBeInTheDocument();
    expect(screen.getByText(/模型输出未通过严格校验/)).toBeInTheDocument();
    expect(screen.queryByText(/raw provider response/)).not.toBeInTheDocument();
  });
});
