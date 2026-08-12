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

  it('uses exact Persona routes and safe mutation bodies', async () => {
    const current = {
      id: 'persona-1',
      version: 1,
      payload_state: 'active',
      config: null,
    };
    vi.mocked(fetch)
      .mockResolvedValueOnce(new Response(JSON.stringify(current), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([current]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(current), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(current), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ redacted: current, active: current }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ persona_artifacts: true }), { status: 200 }));

    await apiClient.getCurrentPersona();
    await apiClient.listPersonaArtifacts();
    const config = {
      identity: { name: '原创角色', species: '虚拟角色', role: '伙伴' },
      background: '背景',
      personality: { core_traits: ['温和'], values: ['准确'] },
      language_style: { tone: '克制', habits: ['简洁'] },
      relationship: { initial: '初识' },
      additional_prohibitions: [],
    };
    await apiClient.createPersonaArtifact({
      config,
      expected_artifact_id: 'persona-1',
      expected_generation: 2,
    });
    await apiClient.activatePersona({
      artifact_id: 'persona-2',
      expected_artifact_id: 'persona-1',
      expected_generation: 2,
    });
    await apiClient.redactPersonaArtifact('persona / old', {
      expected_artifact_id: 'persona-1',
      expected_generation: 2,
      confirmation: 'redact_persona_payload',
    });
    await apiClient.getPersonaCapabilities();

    expect(fetch).toHaveBeenNthCalledWith(1, '/api/persona/current', expect.any(Object));
    expect(fetch).toHaveBeenNthCalledWith(2, '/api/persona/artifacts', expect.any(Object));
    expect(fetch).toHaveBeenNthCalledWith(3, '/api/persona/artifacts', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ config, expected_artifact_id: 'persona-1', expected_generation: 2 }),
    }));
    expect(fetch).toHaveBeenNthCalledWith(4, '/api/persona/active', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ artifact_id: 'persona-2', expected_artifact_id: 'persona-1', expected_generation: 2 }),
    }));
    const redactCall = vi.mocked(fetch).mock.calls[4];
    expect(redactCall[0]).toBe('/api/persona/artifacts/persona%20%2F%20old/redact');
    expect(redactCall[1]).toEqual(expect.objectContaining({
      body: JSON.stringify({ expected_artifact_id: 'persona-1', expected_generation: 2, confirmation: 'redact_persona_payload' }),
    }));
    expect(JSON.stringify(vi.mocked(fetch).mock.calls)).not.toMatch(/compiled|full_hash|private_asset/);
  });

  it('uses exact summary routes, bounded query parameters, and CAS mutation bodies', async () => {
    const emptyPage = { items: [], next_cursor: null };
    vi.mocked(fetch)
      .mockResolvedValueOnce(new Response(JSON.stringify({ summary_processing: true }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'unknown' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'granted' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'unknown' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'granted' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ summary_counts: {}, job_counts: {} }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(emptyPage), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(emptyPage), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(emptyPage), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ outcome: 'redacted' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ outcome: 'rebuild_scheduled' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ outcome: 'retry_scheduled' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ outcome: 'cancelled' }), { status: 200 }));

    await apiClient.getSummaryCapabilities();
    await apiClient.getSummaryProcessingConsent();
    await apiClient.updateSummaryProcessingConsent({ action: 'grant', expected_generation: 2 });
    await apiClient.getSummaryInjectionConsent();
    await apiClient.updateSummaryInjectionConsent({ action: 'grant', expected_generation: 4 });
    await apiClient.getSummaryStatus();
    await apiClient.listSummaries({ sessionId: 'session / 1', limit: 100, cursor: 'cursor+one' });
    await apiClient.listSummaryJobs({ limit: 100, cursor: 'job+cursor' });
    await apiClient.listSummaryAudits({ limit: 100, cursor: 'audit+cursor' });
    await apiClient.redactSummary('summary / 1', {
      expected_suppression_generation: 3,
      confirmation: 'redact_summary_payload',
    });
    await apiClient.rebuildSummary('summary / 1', { expected_suppression_generation: 3 });
    await apiClient.retrySummaryJob('job / 1', {
      expected_status: 'failed',
      expected_suppression_generation: 5,
      expected_suppression_state: 'rebuild_in_progress',
    });
    await apiClient.cancelSummaryJob('job / 1', {
      expected_status: 'running',
      expected_suppression_generation: 5,
      expected_suppression_state: 'rebuild_in_progress',
    });

    expect(fetch).toHaveBeenNthCalledWith(1, '/api/summaries/capabilities', expect.any(Object));
    expect(fetch).toHaveBeenNthCalledWith(3, '/api/summaries/processing-consent', expect.objectContaining({
      method: 'PUT',
      body: JSON.stringify({ action: 'grant', expected_generation: 2 }),
    }));
    expect(fetch).toHaveBeenNthCalledWith(5, '/api/summaries/injection-consent', expect.objectContaining({
      method: 'PUT',
      body: JSON.stringify({ action: 'grant', expected_generation: 4 }),
    }));
    expect(String(vi.mocked(fetch).mock.calls[6][0])).toBe(
      '/api/summaries?limit=100&session_id=session+%2F+1&cursor=cursor%2Bone',
    );
    expect(String(vi.mocked(fetch).mock.calls[7][0])).toBe(
      '/api/summaries/jobs?limit=100&cursor=job%2Bcursor',
    );
    expect(String(vi.mocked(fetch).mock.calls[8][0])).toBe(
      '/api/summaries/audits?limit=100&cursor=audit%2Bcursor',
    );
    expect(fetch).toHaveBeenNthCalledWith(10, '/api/summaries/summary%20%2F%201/redact', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({
        expected_suppression_generation: 3,
        confirmation: 'redact_summary_payload',
      }),
    }));
    expect(fetch).toHaveBeenNthCalledWith(11, '/api/summaries/summary%20%2F%201/rebuild', expect.objectContaining({
      body: JSON.stringify({ expected_suppression_generation: 3 }),
    }));
    expect(fetch).toHaveBeenNthCalledWith(12, '/api/summaries/jobs/job%20%2F%201/retry', expect.objectContaining({
      body: JSON.stringify({
        expected_status: 'failed',
        expected_suppression_generation: 5,
        expected_suppression_state: 'rebuild_in_progress',
      }),
    }));
    expect(JSON.stringify(vi.mocked(fetch).mock.calls)).not.toMatch(
      /source_set_hash|policy_fingerprint|rebuild_permit_id|source_message_ids|source_turn_ids|prompt|raw_response/i,
    );
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

  it('calls Gate B consent, history, conflict, archive, forget, and undo routes', async () => {
    const emptyPage = { items: [], next_cursor: null };
    vi.mocked(fetch)
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'unknown' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: 'granted' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(emptyPage), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(emptyPage), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(emptyPage), { status: 200 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ scope: 'memory' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ action: 'retracted_support' }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ conflict: { id: 'c1' }, resolved_memory: null }), { status: 200 }));

    await apiClient.getMemoryWriteConsent();
    await apiClient.updateMemoryWriteConsent('grant');
    await apiClient.listMemoryVersions('m/1', 'cursor+one');
    await apiClient.listMemoryEvidence('m/1');
    await apiClient.listMemoryConflicts();
    await apiClient.archiveMemory('m/1');
    await apiClient.forgetMemory('m/1');
    await apiClient.undoLatestAutoMemory('m/1');
    await apiClient.resolveMemoryConflict('c/1', { kind: 'dismiss_both' });

    expect(fetch).toHaveBeenCalledWith('/api/memories/automation/write-consent', expect.objectContaining({ method: 'PUT' }));
    const consentBody = JSON.parse(String(vi.mocked(fetch).mock.calls[1][1]?.body));
    expect(consentBody.allowed_memory_types).toEqual(['user_fact', 'preference', 'long_term_goal', 'important_event', 'relationship_event', 'other']);
    expect(String(vi.mocked(fetch).mock.calls[2][0])).toContain('/api/memories/m%2F1/versions?');
    expect(String(vi.mocked(fetch).mock.calls[2][0])).toContain('cursor=cursor%2Bone');
    expect(fetch).toHaveBeenCalledWith('/api/memories/m%2F1/archive', expect.objectContaining({ method: 'POST' }));
    expect(fetch).toHaveBeenCalledWith('/api/memories/m%2F1/forget', expect.objectContaining({ method: 'POST' }));
    expect(fetch).toHaveBeenCalledWith('/api/memories/m%2F1/undo-latest-auto', expect.objectContaining({ method: 'POST' }));
    expect(fetch).toHaveBeenCalledWith('/api/memories/conflicts/c%2F1/resolve', expect.objectContaining({ method: 'POST' }));
    expect(JSON.stringify(vi.mocked(fetch).mock.calls)).not.toMatch(/hmac|reference_hash|canonical_key_hash|subject_key_hash/i);
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
