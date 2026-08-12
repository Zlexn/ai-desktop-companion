import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { MemoryConflict } from '../api/types';
import { MemoryConflictPanel } from './MemoryConflictPanel';

const conflict: MemoryConflict = {
  id: 'conflict-1',
  left_memory_id: 'left-1',
  right_memory_id: 'right-1',
  status: 'open',
  resolution_kind: null,
  resolved_memory_id: null,
  created_at: '2026-07-21T00:00:00Z',
  resolved_at: null,
};

afterEach(cleanup);

describe('MemoryConflictPanel', () => {
  it('offers all five explicit user resolution kinds', async () => {
    const onResolve = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<MemoryConflictPanel conflicts={[conflict]} loading={false} onResolve={onResolve} />);

    expect(screen.getByRole('button', { name: '采用左侧记忆' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '采用右侧记忆' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '替换双方' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '保留语境区别' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '双方都不保留' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '采用左侧记忆' }));
    expect(onResolve).toHaveBeenCalledWith('conflict-1', { kind: 'choose_left' });
  });

  it('requires replacement payload and exposes context fields by label', async () => {
    const onResolve = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<MemoryConflictPanel conflicts={[conflict]} loading={false} onResolve={onResolve} />);

    await user.click(screen.getByRole('button', { name: '保留语境区别' }));
    await user.type(screen.getByLabelText('解决后的主题'), '工作时的饮品偏好');
    await user.type(screen.getByLabelText('解决后的内容'), '用户在工作时喜欢红茶');
    await user.click(screen.getByRole('button', { name: '提交语境化解决' }));

    expect(onResolve).toHaveBeenCalledWith('conflict-1', expect.objectContaining({
      kind: 'both_contextual',
      subject: '工作时的饮品偏好',
      content: '用户在工作时喜欢红茶',
      memory_type: 'preference',
    }));
  });
});
