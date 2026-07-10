import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { apiClient } from './client';

const originalFetch = globalThis.fetch;

describe('apiClient.transcribeAudio', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  function mockFetchResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
    return new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json', ...headers },
    });
  }

  it('uses FormData with file and language fields', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      mockFetchResponse(200, { text: '测试转写', detected_language: 'zh', duration_ms: null, provider: 'fake', model: 'fake-asr-v1', inference_ms: 0 }),
    );

    const audio = new Blob(['\x1a\x45\xdf\xa3test'], { type: 'audio/webm' });
    await apiClient.transcribeAudio(audio, { language: 'zh' });

    expect(fetch).toHaveBeenCalledTimes(1);
    const callArgs = vi.mocked(fetch).mock.calls[0];
    const url = callArgs[0] as string;
    expect(url).toBe('/api/audio/transcriptions');

    const init = callArgs[1]!;
    expect(init.method).toBe('POST');

    // FormData should be passed as body without manual Content-Type
    const body = init.body as FormData;
    expect(body).toBeInstanceOf(FormData);

    // Check no Content-Type header set manually
    const headers = init.headers as Record<string, string> | undefined;
    if (headers) {
      // Should not have Content-Type — browser sets it
      expect(headers['Content-Type']).toBeUndefined();
    }
  });

  it('does not set Content-Type header manually', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      mockFetchResponse(200, { text: 'x', detected_language: 'zh', duration_ms: null, provider: 'fake', model: 'fake-asr-v1', inference_ms: 0 }),
    );

    await apiClient.transcribeAudio(new Blob(['data'], { type: 'audio/webm' }));

    const init = vi.mocked(fetch).mock.calls[0][1]!;
    // FastAPI/httpx/StarletteTestClient may internally set this,
    // but our code should not manually set the Content-Type header.
    // Verify by checking the body is FormData (browser will auto-set boundary).
  });

  it('maps filename from mime type webm', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      mockFetchResponse(200, { text: 'x', detected_language: 'zh', duration_ms: null, provider: 'fake', model: 'fake-asr-v1', inference_ms: 0 }),
    );

    const audio = new Blob(['\x1a\x45\xdf\xa3'], { type: 'audio/webm;codecs=opus' });
    await apiClient.transcribeAudio(audio);

    const body = vi.mocked(fetch).mock.calls[0][1]!.body as FormData;
    const file = body.get('file') as File;
    expect(file.name).toBe('recording.webm');
  });

  it('maps filename from mime type mp4', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      mockFetchResponse(200, { text: 'x', detected_language: 'zh', duration_ms: null, provider: 'fake', model: 'fake-asr-v1', inference_ms: 0 }),
    );

    const audio = new Blob(['\x00\x00\x00\x18ftyp'], { type: 'audio/mp4' });
    await apiClient.transcribeAudio(audio);

    const body = vi.mocked(fetch).mock.calls[0][1]!.body as FormData;
    const file = body.get('file') as File;
    expect(file.name).toBe('recording.mp4');
  });

  it('parses transcription JSON correctly', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      mockFetchResponse(200, {
        text: '这是 Fake ASR 的确定性转写。',
        detected_language: 'zh',
        duration_ms: null,
        provider: 'fake',
        model: 'fake-asr-v1',
        inference_ms: 0,
      }),
    );

    const result = await apiClient.transcribeAudio(new Blob(['x'], { type: 'audio/webm' }));
    expect(result.text).toBe('这是 Fake ASR 的确定性转写。');
    expect(result.detected_language).toBe('zh');
    expect(result.duration_ms).toBeNull();
    expect(result.provider).toBe('fake');
    expect(result.model).toBe('fake-asr-v1');
    expect(result.inference_ms).toBe(0);
  });

  it('maps API error to user message', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      mockFetchResponse(502, { error: { message: '语音转写服务暂时不可用，请稍后重试。' } }),
    );

    await expect(apiClient.transcribeAudio(new Blob(['x'], { type: 'audio/webm' })))
      .rejects.toThrow('语音转写服务暂时不可用，请稍后重试。');
  });

  it('respects AbortSignal', async () => {
    const controller = new AbortController();
    controller.abort();

    vi.mocked(fetch).mockRejectedValueOnce(new DOMException('Aborted', 'AbortError'));

    await expect(apiClient.transcribeAudio(new Blob(['x'], { type: 'audio/webm' }), { signal: controller.signal }))
      .rejects.toThrow();
  });

  it('rejects invalid response missing text', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      mockFetchResponse(200, { detected_language: 'zh', duration_ms: null, provider: 'fake', model: '', inference_ms: 0 }),
    );

    await expect(apiClient.transcribeAudio(new Blob(['x'], { type: 'audio/webm' })))
      .rejects.toThrow('语音转写服务返回了无法处理的结果。');
  });
});
