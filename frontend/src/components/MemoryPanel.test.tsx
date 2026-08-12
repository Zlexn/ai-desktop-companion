import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { MemoryRecord } from '../api/types';
import { MemoryPanel, numberDraftFromInput } from './MemoryPanel';

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
  v2_state: 'active',
  v2_source_kind: 'manual',
  version_count: 1,
  evidence_count: 0,
  has_open_conflict: false,
  can_undo_latest_auto: false,
  canonical_subject_code: null,
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
  v2_state: null,
  v2_source_kind: null,
  version_count: 0,
  evidence_count: 0,
  has_open_conflict: false,
  can_undo_latest_auto: false,
  canonical_subject_code: null,
};

afterEach(() => {
  cleanup();
});

describe('MemoryPanel', () => {
  it('represents an empty numeric input as an empty draft', () => {
    const input = document.createElement('input');
    input.type = 'number';
    input.value = '';

    expect(numberDraftFromInput(input)).toBe('');
  });

  it('renders boundary helper and empty state', () => {
    render(<MemoryPanel memories={[]} candidates={[]} loading={false} error={null} conflicts={[]} onCreate={vi.fn()} onUpdate={vi.fn()} onDelete={vi.fn()} onConfirmCandidate={vi.fn()} onDismissCandidate={vi.fn()} />);

    expect(screen.getByText('长期记忆')).toBeInTheDocument();
    expect(screen.getByText(/自动写入仅在你单独授权本地写入且规则允许时发生/)).toBeInTheDocument();
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
    await user.click(screen.getByRole('button', { name: '归档记忆' }));
    expect(onDelete).toHaveBeenCalledWith('m1');
  });

  it('edits only active memories and cancels without updating', async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <MemoryPanel
        memories={[memory]}
        candidates={[candidate]}
        loading={false}
        error={null}
        conflicts={[]}
        onCreate={vi.fn()}
        onUpdate={onUpdate}
        onDelete={vi.fn()}
        onConfirmCandidate={vi.fn()}
        onDismissCandidate={vi.fn()}
      />,
    );

    expect(screen.getAllByRole('button', { name: '编辑记忆' })).toHaveLength(1);
    await user.click(screen.getByRole('button', { name: '编辑记忆' }));

    expect(screen.getByLabelText('编辑记忆内容')).toHaveValue(memory.content);
    expect(screen.getByLabelText('编辑记忆类型')).toHaveValue(memory.memory_type);
    expect(screen.getByLabelText('编辑重要度')).toHaveValue(memory.importance);
    expect(screen.getByLabelText('编辑可信度')).toHaveValue(memory.confidence);

    await user.click(screen.getByRole('button', { name: '取消编辑' }));

    expect(onUpdate).not.toHaveBeenCalled();
    expect(screen.queryByLabelText('编辑记忆内容')).not.toBeInTheDocument();
    expect(screen.getByText(memory.content)).toBeInTheDocument();
  });

  it('saves trimmed typed values and exits editing after success', async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <MemoryPanel
        memories={[memory]}
        candidates={[]}
        loading={false}
        error={null}
        conflicts={[]}
        onCreate={vi.fn()}
        onUpdate={onUpdate}
        onDelete={vi.fn()}
        onConfirmCandidate={vi.fn()}
        onDismissCandidate={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: '编辑记忆' }));
    const contentInput = screen.getByLabelText('编辑记忆内容');
    await user.clear(contentInput);
    await user.type(contentInput, '  更新后的记忆  ');
    await user.selectOptions(screen.getByLabelText('编辑记忆类型'), 'user_fact');
    const importanceInput = screen.getByLabelText('编辑重要度');
    await user.clear(importanceInput);
    await user.type(importanceInput, '5');
    const confidenceInput = screen.getByLabelText('编辑可信度');
    await user.clear(confidenceInput);
    await user.type(confidenceInput, '0.8');
    await user.click(screen.getByRole('button', { name: '保存修改' }));

    expect(onUpdate).toHaveBeenCalledWith('m1', {
      content: '更新后的记忆',
      memory_type: 'user_fact',
      importance: 5,
      confidence: 0.8,
    });
    expect(screen.queryByLabelText('编辑记忆内容')).not.toBeInTheDocument();
  });

  it('keeps the editor open and shows the shared error when update fails', async () => {
    const onUpdate = vi.fn().mockRejectedValue(new Error('更新失败'));
    const user = userEvent.setup();
    render(
      <MemoryPanel
        memories={[memory]}
        candidates={[]}
        loading={false}
        error="更新失败"
        conflicts={[]}
        onCreate={vi.fn()}
        onUpdate={onUpdate}
        onDelete={vi.fn()}
        onConfirmCandidate={vi.fn()}
        onDismissCandidate={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: '编辑记忆' }));
    await user.click(screen.getByRole('button', { name: '保存修改' }));

    expect(await screen.findByLabelText('编辑记忆内容')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('更新失败');
  });

  it('disables saving a blank edit', async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <MemoryPanel
        memories={[memory]}
        candidates={[]}
        loading={false}
        error={null}
        conflicts={[]}
        onCreate={vi.fn()}
        onUpdate={onUpdate}
        onDelete={vi.fn()}
        onConfirmCandidate={vi.fn()}
        onDismissCandidate={vi.fn()}
      />,
    );

    await user.click(screen.getByRole('button', { name: '编辑记忆' }));
    const contentInput = screen.getByLabelText('编辑记忆内容');
    await user.clear(contentInput);
    await user.type(contentInput, '   ');

    expect(screen.getByRole('button', { name: '保存修改' })).toBeDisabled();
    expect(onUpdate).not.toHaveBeenCalled();
  });

  it('keeps empty numeric drafts controlled without warning and saves after recovery', async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const user = userEvent.setup();
    try {
      render(
        <MemoryPanel
          memories={[memory]}
          candidates={[]}
          loading={false}
          error={null}
          conflicts={[]}
          onCreate={vi.fn()}
          onUpdate={onUpdate}
          onDelete={vi.fn()}
          onConfirmCandidate={vi.fn()}
          onDismissCandidate={vi.fn()}
        />,
      );

      await user.click(screen.getByRole('button', { name: '编辑记忆' }));
      const importanceInput = screen.getByLabelText('编辑重要度');
      const confidenceInput = screen.getByLabelText('编辑可信度');

      fireEvent.change(importanceInput, { target: { value: '', valueAsNumber: Number.NaN } });
      expect(importanceInput).toHaveValue(null);
      expect(screen.getByRole('button', { name: '保存修改' })).toBeDisabled();

      await user.type(importanceInput, '5');
      await user.clear(confidenceInput);
      expect(confidenceInput).toHaveValue(null);
      expect(screen.getByRole('button', { name: '保存修改' })).toBeDisabled();

      await user.type(confidenceInput, '0.8');
      await user.click(screen.getByRole('button', { name: '保存修改' }));

      expect(onUpdate).toHaveBeenCalledWith('m1', {
        content: memory.content,
        memory_type: memory.memory_type,
        importance: 5,
        confidence: 0.8,
      });
      expect(consoleError.mock.calls.flat().join(' ')).not.toContain('Received NaN for the `value` attribute');
    } finally {
      consoleError.mockRestore();
    }
  });

  it('separates archive and confirmed true forget and uses authoritative V2 indicators', async () => {
    const automatic: MemoryRecord = {
      ...memory,
      id: 'auto-1',
      source: 'manual',
      v2_state: 'active',
      v2_source_kind: 'automatic',
      version_count: 3,
      evidence_count: 2,
      has_open_conflict: true,
      can_undo_latest_auto: true,
    };
    const onArchive = vi.fn().mockResolvedValue(undefined);
    const onForget = vi.fn().mockResolvedValue(undefined);
    const onUndo = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <MemoryPanel
        memories={[automatic]}
        candidates={[]}
        loading={false}
        error={null}
        conflicts={[]}
        onCreate={vi.fn()}
        onUpdate={vi.fn()}
        onDelete={vi.fn()}
        onArchive={onArchive}
        onForget={onForget}
        onUndoLatestAuto={onUndo}
        onConfirmCandidate={vi.fn()}
        onDismissCandidate={vi.fn()}
      />,
    );

    expect(screen.getByText('自动写入')).toBeInTheDocument();
    expect(screen.getByText('V2 当前有效')).toBeInTheDocument();
    expect(screen.getByText('3 个版本')).toBeInTheDocument();
    expect(screen.getByText('2 条证据')).toBeInTheDocument();
    expect(screen.getByText('存在待解决冲突')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '归档记忆' }));
    expect(onArchive).toHaveBeenCalledWith('auto-1');
    expect(onForget).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: '真正忘记' }));
    expect(screen.getByText(/不会删除原始聊天消息/)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '确认真正忘记' }));
    expect(onForget).toHaveBeenCalledWith('auto-1');

    await user.click(screen.getByRole('button', { name: '撤销最近自动变化' }));
    expect(onUndo).toHaveBeenCalledWith('auto-1');
  });

  it('hides automatic undo after a later user edit', () => {
    const edited: MemoryRecord = {
      ...memory,
      id: 'edited-auto-create',
      source: 'automatic',
      v2_source_kind: 'user_edit',
      version_count: 2,
      evidence_count: 1,
      can_undo_latest_auto: false,
    };
    render(
      <MemoryPanel
        memories={[edited]}
        candidates={[]}
        loading={false}
        error={null}
        conflicts={[]}
        onCreate={vi.fn()}
        onUpdate={vi.fn()}
        onDelete={vi.fn()}
        onUndoLatestAuto={vi.fn()}
        onConfirmCandidate={vi.fn()}
        onDismissCandidate={vi.fn()}
      />,
    );

    expect(screen.getByText('用户编辑')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '撤销最近自动变化' })).not.toBeInTheDocument();
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
