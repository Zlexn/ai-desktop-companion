import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { MemoryWriteConsent } from '../api/types';
import { MemoryAutomationControls } from './MemoryAutomationControls';

const consent: MemoryWriteConsent = {
  scope_id: 'default',
  status: 'unknown',
  purpose: null,
  policy_version: null,
  retention_disclosure_version: null,
  allowed_memory_types_version: null,
  allowed_memory_types: [],
  generation: 0,
  granted_at: null,
  created_at: '2026-07-21T00:00:00Z',
  updated_at: '2026-07-21T00:00:00Z',
};

afterEach(cleanup);

describe('MemoryAutomationControls', () => {
  it('explains independent local writing and grants exact consent', async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <MemoryAutomationControls
        consent={consent}
        loading={false}
        latestJob={null}
        onUpdate={onUpdate}
      />,
    );

    expect(screen.getByText(/只授权写入本机长期记忆/)).toBeInTheDocument();
    expect(screen.getByText(/不会授权远程记忆抽取/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '允许本地自动写入' }));
    expect(onUpdate).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: '确认允许本地自动写入' }));
    expect(onUpdate).toHaveBeenCalledWith('grant');
  });

  it('shows revoke control and fixed background outcome labels', () => {
    render(
      <MemoryAutomationControls
        consent={{ ...consent, status: 'granted', generation: 2 }}
        loading={false}
        latestJob={{
          id: 'job-1',
          status: 'succeeded',
          outcome: 'completed_with_decisions',
          created_at: '2026-07-21T00:00:00Z',
          finished_at: '2026-07-21T00:00:01Z',
        }}
        onUpdate={vi.fn()}
      />,
    );

    expect(screen.getByRole('button', { name: '撤回本地自动写入' })).toBeInTheDocument();
    expect(screen.getByText('自动记忆：已完成')).toBeInTheDocument();
  });
});
