import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { MemoryEvidencePage, MemoryVersionPage } from '../api/types';
import { MemoryHistoryDetails } from './MemoryHistoryDetails';

const versions: MemoryVersionPage = {
  items: [{
    id: 'version-2',
    memory_id: 'memory-1',
    version_number: 2,
    parent_version_id: 'version-1',
    operation: 'user_edit',
    memory_type: 'preference',
    subject: '饮品偏好',
    content: '用户喜欢红茶',
    confidence: 1,
    importance: 3,
    source_kind: 'user_edit',
    source_session_id: null,
    created_at: '2026-07-21T00:00:00Z',
    redacted_at: null,
    canonical_subject_code: null,
  }],
  next_cursor: 'version-next',
};

const evidence: MemoryEvidencePage = {
  items: [{
    id: 'evidence-1',
    memory_id: 'memory-1',
    memory_version_id: 'version-2',
    source_session_id: 'session-1',
    source_message_id: 'message-1',
    source_available: true,
    relation: 'supports',
    observed_at: '2026-07-21T00:00:00Z',
    extractor_kind: 'local',
    extractor_provider: null,
    extractor_model: 'memory-local-rules-v1',
    confidence: 0.9,
    created_at: '2026-07-21T00:00:00Z',
  }],
  next_cursor: null,
};

afterEach(cleanup);

describe('MemoryHistoryDetails', () => {
  it('loads history and evidence only after expansion', async () => {
    const loadVersions = vi.fn().mockResolvedValue(versions);
    const loadEvidence = vi.fn().mockResolvedValue(evidence);
    const user = userEvent.setup();
    render(
      <MemoryHistoryDetails
        memoryId="memory-1"
        loadVersions={loadVersions}
        loadEvidence={loadEvidence}
      />,
    );

    expect(loadVersions).not.toHaveBeenCalled();
    expect(loadEvidence).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: '查看版本和证据' }));
    expect(await screen.findByText('用户喜欢红茶')).toBeInTheDocument();
    expect(await screen.findByText(/支持 · 本地规则/)).toBeInTheDocument();
    expect(screen.getByText(/会话 session-1 · 消息 message-1/)).toBeInTheDocument();
  });

  it('never renders redacted payload and supports version pagination', async () => {
    const loadVersions = vi.fn()
      .mockResolvedValueOnce({
        items: [{ ...versions.items[0], content: null, subject: null, redacted_at: '2026-07-21T00:01:00Z' }],
        next_cursor: 'next',
      })
      .mockResolvedValueOnce({ items: [], next_cursor: null });
    const user = userEvent.setup();
    render(
      <MemoryHistoryDetails
        memoryId="memory-1"
        loadVersions={loadVersions}
        loadEvidence={vi.fn().mockResolvedValue({ items: [], next_cursor: null })}
      />,
    );

    await user.click(screen.getByRole('button', { name: '查看版本和证据' }));
    expect(await screen.findByText('内容已忘记')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '加载更多版本' }));
    expect(loadVersions).toHaveBeenLastCalledWith('memory-1', 'next');
  });
});
