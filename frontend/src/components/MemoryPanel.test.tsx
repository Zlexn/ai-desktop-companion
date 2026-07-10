import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { MemoryRecord } from '../api/types';
import { MemoryPanel } from './MemoryPanel';

const memory: MemoryRecord = {
  id: 'm1',
  content: '用户偏好中文回复。',
  memory_type: 'preference',
  source: 'manual',
  source_session_id: null,
  importance: 3,
  confidence: 1,
  status: 'active',
  created_at: '2026-07-06T00:00:00Z',
  updated_at: '2026-07-06T00:00:00Z',
  metadata: {},
};

const candidate: MemoryRecord = {
  id: 'c1',
  content: '用户喜欢红茶。',
  memory_type: 'preference',
  source: 'candidate',
  source_session_id: 's1',
  importance: 3,
  confidence: 0.7,
  status: 'pending',
  created_at: '2026-07-06T00:00:00Z',
  updated_at: '2026-07-06T00:00:00Z',
  metadata: { candidate_reason: 'explicit_like_statement' },
};

afterEach(() => {
  cleanup();
});

describe('MemoryPanel', () => {
  it('renders boundary helper and empty state', () => {
    render(<MemoryPanel memories={[]} candidates={[]} loading={false} error={null} conflicts={[]} onCreate={vi.fn()} onUpdate={vi.fn()} onDelete={vi.fn()} onConfirmCandidate={vi.fn()} onDismissCandidate={vi.fn()} />);

    expect(screen.getByText('长期记忆')).toBeInTheDocument();
    expect(screen.getByText(/聊天记录不会自动变成长期记忆/)).toBeInTheDocument();
    expect(screen.getByText('暂无长期记忆。')).toBeInTheDocument();
  });

  it('submits a new memory', async () => {
    const onCreate = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<MemoryPanel memories={[]} candidates={[]} loading={false} error={null} conflicts={[]} onCreate={onCreate} onUpdate={vi.fn()} onDelete={vi.fn()} onConfirmCandidate={vi.fn()} onDismissCandidate={vi.fn()} />);

    await user.type(screen.getByLabelText('记忆内容'), '用户偏好中文回复。');
    await user.selectOptions(screen.getByLabelText('记忆类型'), 'preference');
    await user.click(screen.getByRole('button', { name: '保存记忆' }));

    expect(onCreate).toHaveBeenCalledWith({
      content: '用户偏好中文回复。',
      memory_type: 'preference',
      importance: 3,
      confidence: 1,
    });
  });

  it('renders memories, conflict details, and delete action', async () => {
    const onDelete = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<MemoryPanel memories={[memory]} candidates={[]} loading={false} error={null} conflicts={[memory]} onCreate={vi.fn()} onUpdate={vi.fn()} onDelete={onDelete} onConfirmCandidate={vi.fn()} onDismissCandidate={vi.fn()} />);

    expect(screen.getAllByText('用户偏好中文回复。')).toHaveLength(2);
    expect(screen.getByText(/发现相似记忆/)).toBeInTheDocument();
    const conflictRegion = screen.getByRole('region', { name: '冲突记忆明细' });
    expect(conflictRegion).toBeInTheDocument();
    expect(within(conflictRegion).getByText(/preference · importance 3 · confidence 1.00/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '删除记忆' }));
    expect(onDelete).toHaveBeenCalledWith('m1');
  });

  it('renders pending candidates and candidate actions', async () => {
    const onConfirmCandidate = vi.fn().mockResolvedValue(undefined);
    const onDismissCandidate = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <MemoryPanel
        memories={[memory]}
        candidates={[candidate]}
        loading={false}
        error={null}
        conflicts={[]}
        onCreate={vi.fn()}
        onUpdate={vi.fn()}
        onDelete={vi.fn()}
        onConfirmCandidate={onConfirmCandidate}
        onDismissCandidate={onDismissCandidate}
      />,
    );

    expect(screen.getByText('待确认记忆')).toBeInTheDocument();
    expect(screen.getByText(/确认前不会用于对话/)).toBeInTheDocument();
    expect(screen.getByText('用户喜欢红茶。')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '保存为长期记忆' }));
    expect(onConfirmCandidate).toHaveBeenCalledWith('c1');

    await user.click(screen.getByRole('button', { name: '忽略' }));
    expect(onDismissCandidate).toHaveBeenCalledWith('c1');
  });
});
