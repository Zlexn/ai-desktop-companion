import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiClient } from '../api/client';
import { useExpressionPreviewController } from './useExpressionPreviewController';

vi.mock('../api/client', () => ({
  apiClient: { getMessageExpression: vi.fn() },
}));

const persisted = {
  assistant_message_id: 'a',
  schema_version: 1 as const,
  delivery: 'warm' as const,
  intensity: 'medium' as const,
  rate: 1.04,
  source: 'persisted_plan' as const,
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe('useExpressionPreviewController', () => {
  it('does not cache local fallback and retries the same message', async () => {
    vi.mocked(apiClient.getMessageExpression)
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(persisted);
    const { result } = renderHook(() =>
      useExpressionPreviewController('session-1'),
    );

    act(() => result.current.selectAssistantMessage('session-1', 'a'));
    await waitFor(() =>
      expect(result.current.state.expression?.delivery).toBe('neutral'),
    );
    act(() => result.current.selectAssistantMessage('session-1', 'a'));
    await waitFor(() =>
      expect(result.current.state.expression?.delivery).toBe('warm'),
    );

    expect(apiClient.getMessageExpression).toHaveBeenCalledTimes(2);
  });

  it('caches successful API default values', async () => {
    vi.mocked(apiClient.getMessageExpression).mockResolvedValueOnce({
      ...persisted,
      delivery: 'neutral',
      intensity: 'low',
      rate: 1,
      source: 'default',
    });
    const { result } = renderHook(() =>
      useExpressionPreviewController('session-1'),
    );

    act(() => result.current.selectAssistantMessage('session-1', 'a'));
    await waitFor(() =>
      expect(result.current.state.expression?.source).toBe('default'),
    );
    act(() => result.current.selectAssistantMessage('session-1', 'a'));

    expect(apiClient.getMessageExpression).toHaveBeenCalledTimes(1);
  });

  it('ignores a late response after selecting another message', async () => {
    let resolveOld!: (value: typeof persisted) => void;
    vi.mocked(apiClient.getMessageExpression)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }))
      .mockResolvedValueOnce({ ...persisted, assistant_message_id: 'b', delivery: 'firm' });
    const { result } = renderHook(() =>
      useExpressionPreviewController('session-1'),
    );

    act(() => result.current.selectAssistantMessage('session-1', 'a'));
    act(() => result.current.selectAssistantMessage('session-1', 'b'));
    await waitFor(() =>
      expect(result.current.state.expression?.assistantMessageId).toBe('b'),
    );
    resolveOld(persisted);
    await act(async () => { await Promise.resolve(); });

    expect(result.current.state.expression?.assistantMessageId).toBe('b');
  });

  it('activates a run synchronously without duplicating an equal in-flight request', () => {
    vi.mocked(apiClient.getMessageExpression).mockImplementation(
      () => new Promise(() => undefined),
    );
    const { result } = renderHook(() =>
      useExpressionPreviewController('session-1'),
    );

    act(() => result.current.selectAssistantMessage('session-1', 'a'));
    let accepted = false;
    act(() => {
      accepted = result.current.onRunActivated({
        assistantMessageId: 'a',
        playbackRunId: 1,
      });
    });

    expect(accepted).toBe(true);
    expect(result.current.state.activeRun).toEqual({
      assistantMessageId: 'a',
      playbackRunId: 1,
    });
    expect(apiClient.getMessageExpression).toHaveBeenCalledTimes(1);
  });

  it('force reload bypasses a successful cached expression', async () => {
    vi.mocked(apiClient.getMessageExpression)
      .mockResolvedValueOnce(persisted)
      .mockResolvedValueOnce({ ...persisted, delivery: 'firm' });
    const { result } = renderHook(() => useExpressionPreviewController('session-1'));

    act(() => result.current.selectAssistantMessage('session-1', 'a'));
    await waitFor(() => expect(result.current.state.expression?.delivery).toBe('warm'));
    act(() => result.current.selectAssistantMessage('session-1', 'a', { forceReload: true }));
    await waitFor(() => expect(result.current.state.expression?.delivery).toBe('firm'));

    expect(apiClient.getMessageExpression).toHaveBeenCalledTimes(2);
  });

  it('retries an uncached local fallback when a playback run activates', async () => {
    vi.mocked(apiClient.getMessageExpression)
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(persisted);
    const { result } = renderHook(() => useExpressionPreviewController('session-1'));

    act(() => result.current.selectAssistantMessage('session-1', 'a'));
    await waitFor(() => expect(result.current.state.expression?.delivery).toBe('neutral'));
    act(() => {
      result.current.onRunActivated({ assistantMessageId: 'a', playbackRunId: 1 });
    });
    await waitFor(() => expect(result.current.state.expression?.delivery).toBe('warm'));

    expect(apiClient.getMessageExpression).toHaveBeenCalledTimes(2);
  });

  it('keeps a newer run active when stale lifecycle callbacks arrive', async () => {
    vi.mocked(apiClient.getMessageExpression).mockResolvedValue(persisted);
    const { result } = renderHook(() => useExpressionPreviewController('session-1'));

    act(() => result.current.onRunActivated({ assistantMessageId: 'a', playbackRunId: 1 }));
    await waitFor(() => expect(result.current.state.expression).not.toBeNull());
    act(() => result.current.onRunActivated({ assistantMessageId: 'a', playbackRunId: 2 }));
    act(() => {
      result.current.onSpeakingEvent({ type: 'speaking', assistantMessageId: 'a', playbackRunId: 1, phase: 'started' });
      result.current.onRunDeactivated({ assistantMessageId: 'a', playbackRunId: 1 });
    });

    expect(result.current.state.activeRun).toEqual({ assistantMessageId: 'a', playbackRunId: 2 });
    expect(result.current.state.phase).toBe('ready');
  });

  it('clear invalidates a late response and leaves the controller idle', async () => {
    let resolveOld!: (value: typeof persisted) => void;
    vi.mocked(apiClient.getMessageExpression).mockImplementationOnce(
      () => new Promise((resolve) => { resolveOld = resolve; }),
    );
    const { result } = renderHook(() => useExpressionPreviewController('session-1'));

    act(() => result.current.selectAssistantMessage('session-1', 'a'));
    act(() => result.current.clear());
    resolveOld(persisted);
    await act(async () => { await Promise.resolve(); });

    expect(result.current.state).toEqual({
      phase: 'idle',
      selectedAssistantMessageId: null,
      expression: null,
      activeRun: null,
    });
  });

  it('drops only cache entries for the deleted session', async () => {
    vi.mocked(apiClient.getMessageExpression)
      .mockResolvedValueOnce(persisted)
      .mockResolvedValueOnce({ ...persisted, assistant_message_id: 'b' })
      .mockResolvedValueOnce(persisted);
    const { result, rerender } = renderHook(
      ({ sessionId }) => useExpressionPreviewController(sessionId),
      { initialProps: { sessionId: 'session-1' as string | null } },
    );
    act(() => result.current.selectAssistantMessage('session-1', 'a'));
    await waitFor(() => expect(result.current.state.expression).not.toBeNull());
    rerender({ sessionId: 'session-2' });
    act(() => result.current.selectAssistantMessage('session-2', 'b'));
    await waitFor(() =>
      expect(result.current.state.expression?.assistantMessageId).toBe('b'),
    );

    act(() => result.current.dropSession('session-2'));
    rerender({ sessionId: 'session-1' });
    act(() => result.current.selectAssistantMessage('session-1', 'a'));

    expect(apiClient.getMessageExpression).toHaveBeenCalledTimes(2);
  });
});
