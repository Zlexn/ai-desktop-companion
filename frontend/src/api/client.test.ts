import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { apiClient } from './client';

const originalFetch = globalThis.fetch;

describe('apiClient', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it('lists sessions', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify([{ id: 's1', title: '会话' }]), { status: 200 }));

    await expect(apiClient.listSessions()).resolves.toEqual([{ id: 's1', title: '会话' }]);
  });

  it('surfaces API error messages', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ error: { message: '模型服务响应超时，请稍后重试。' } }), { status: 504 }),
    );

    await expect(apiClient.sendMessage('s1', '你好')).rejects.toThrow('模型服务响应超时，请稍后重试。');
  });

  it('gets and validates a message-bound expression with the provided signal', async () => {
    const signal = new AbortController().signal;
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({
        assistant_message_id: 'assistant / 1',
        schema_version: 1,
        delivery: 'warm',
        intensity: 'medium',
        rate: 1.04,
        source: 'persisted_plan',
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );

    await expect(
      apiClient.getMessageExpression('assistant / 1', { signal }),
    ).resolves.toMatchObject({
      assistant_message_id: 'assistant / 1',
      source: 'persisted_plan',
    });
    expect(fetch).toHaveBeenCalledWith(
      '/api/messages/assistant%20%2F%201/expression',
      expect.objectContaining({ signal }),
    );
  });

  it('rejects malformed expression JSON at the network boundary', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({
        assistant_message_id: 'assistant-1',
        schema_version: 1,
        delivery: 'unknown',
        intensity: 'low',
        rate: 1,
        source: 'default',
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );

    await expect(apiClient.getMessageExpression('assistant-1')).rejects.toThrow(
      '表达服务返回了无法处理的结果。',
    );
  });

  it('synthesizes speech as binary audio with metadata headers', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(new Uint8Array([82, 73, 70, 70]), {
        status: 200,
        headers: {
          'Content-Type': 'audio/wav',
          'X-TTS-Provider': 'fake',
          'X-TTS-Model': 'fake-tone-v1',
          'X-Audio-Duration-Ms': '240',
          'X-Audio-Sample-Rate': '16000',
        },
      }),
    );

    const result = await apiClient.synthesizeSpeech('你好', { voiceId: 'fake-default', speed: 1.0 });

    expect(result.blob.type).toBe('audio/wav');
    expect(result.provider).toBe('fake');
    expect(result.model).toBe('fake-tone-v1');
    expect(result.durationMs).toBe(240);
    expect(result.sampleRate).toBe(16000);
    expect(fetch).toHaveBeenCalledWith('/api/audio/speech', expect.objectContaining({ method: 'POST' }));
  });

  it('synthesizes persisted assistant speech without client text or expression options', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      new Response(new Uint8Array([82, 73, 70, 70]), {
        status: 200,
        headers: { 'Content-Type': 'audio/wav', 'X-TTS-Provider': 'fake' },
      }),
    );
    const controller = new AbortController();

    const result = await apiClient.synthesizeMessageSpeech('assistant/42', {
      voiceId: 'fake-default',
      speed: 1.04,
      signal: controller.signal,
    });

    expect(result.blob.type).toBe('audio/wav');
    expect(result.provider).toBe('fake');
    expect(fetch).toHaveBeenCalledWith(
      '/api/messages/assistant%2F42/speech',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ voice_id: 'fake-default', speed: 1.04 }),
        signal: controller.signal,
      }),
    );
    const [, init] = vi.mocked(fetch).mock.calls[0];
    expect(String(init?.body)).not.toContain('text');
    expect(String(init?.body)).not.toContain('delivery');
    expect(String(init?.body)).not.toContain('signal');
  });

  it('omits undefined message speech options and maps API errors', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(new Response(new Uint8Array([82, 73, 70, 70]), { status: 200, headers: { 'Content-Type': 'audio/wav' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ error: { message: '消息语音不可用。' } }), { status: 502 }));

    await apiClient.synthesizeMessageSpeech('a1');
    await expect(apiClient.synthesizeMessageSpeech('a1')).rejects.toThrow('消息语音不可用。');

    expect(vi.mocked(fetch).mock.calls[0][1]?.body).toBe('{}');
  });

  it('rejects unsupported speech content types', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response('not audio', { status: 200, headers: { 'Content-Type': 'text/plain' } }));

    await expect(apiClient.synthesizeSpeech('你好')).rejects.toThrow('语音合成服务返回了无法播放的音频。');
  });

  it('creates a memory', async () => {
    const created = {
      memory: {
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
      },
      conflicts: [],
    };
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify(created), { status: 201 }));

    await expect(apiClient.createMemory({ content: '用户偏好中文回复。', memory_type: 'preference' })).resolves.toEqual(created);
    expect(fetch).toHaveBeenCalledWith('/api/memories', expect.objectContaining({ method: 'POST' }));
  });

  it('lists and deletes memories', async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    await expect(apiClient.listMemories()).resolves.toEqual([]);
    await expect(apiClient.deleteMemory('m1')).resolves.toBeUndefined();
    expect(fetch).toHaveBeenCalledWith('/api/memories', expect.objectContaining({ headers: expect.any(Object) }));
    expect(fetch).toHaveBeenCalledWith('/api/memories/m1', expect.objectContaining({ method: 'DELETE' }));
  });

  it('lists pending memory candidates', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }));

    await expect(apiClient.listMemories('pending')).resolves.toEqual([]);

    expect(fetch).toHaveBeenCalledWith('/api/memories?status_filter=pending', expect.objectContaining({ headers: expect.any(Object) }));
  });

  it('confirms and dismisses memory candidates', async () => {
    const confirmed = {
      memory: {
        id: 'm1',
        content: '用户喜欢红茶。',
        memory_type: 'preference',
        source: 'candidate',
        source_session_id: 's1',
        importance: 3,
        confidence: 0.7,
        status: 'active',
        created_at: '2026-07-06T00:00:00Z',
        updated_at: '2026-07-06T00:00:01Z',
        metadata: { confirmed_at: '2026-07-06T00:00:01Z' },
      },
      conflicts: [],
    };
    const dismissed = {
      id: 'm2',
      content: '用户不喜欢咖啡。',
      memory_type: 'preference',
      source: 'candidate',
      source_session_id: 's1',
      importance: 3,
      confidence: 0.7,
      status: 'dismissed',
      created_at: '2026-07-06T00:00:00Z',
      updated_at: '2026-07-06T00:00:01Z',
      metadata: { dismissed_at: '2026-07-06T00:00:01Z' },
    };
    vi.mocked(fetch)
      .mockResolvedValueOnce(new Response(JSON.stringify(confirmed), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(dismissed), { status: 200 }));

    await expect(apiClient.confirmMemoryCandidate('m1')).resolves.toEqual(confirmed);
    await expect(apiClient.dismissMemoryCandidate('m2')).resolves.toEqual(dismissed);

    expect(fetch).toHaveBeenCalledWith('/api/memories/m1/confirm', expect.objectContaining({ method: 'POST' }));
    expect(fetch).toHaveBeenCalledWith('/api/memories/m2/dismiss', expect.objectContaining({ method: 'POST' }));
  });
});
