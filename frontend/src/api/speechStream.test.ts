import { afterEach, describe, expect, it, vi } from 'vitest';
import { streamMessageSpeech, streamSpeech } from './speechStream';

const originalFetch = globalThis.fetch;

function streamFromChunks(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

async function collect<T>(iterable: AsyncIterable<T>): Promise<T[]> {
  const items: T[] = [];
  for await (const item of iterable) items.push(item);
  return items;
}

describe('streamSpeech', () => {
  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it('parses NDJSON events split across network chunks', async () => {
    const wavBase64 = btoa(String.fromCharCode(82, 73, 70, 70, 0, 0, 0, 0, 87, 65, 86, 69));
    globalThis.fetch = vi.fn().mockResolvedValue(new Response(streamFromChunks([
      '{"type":"start","provider":"fake","model":"fake-tone-v1"}\n{"type":"seg',
      `ment","index":0,"audio_base64":"${wavBase64}","media_type":"audio/wav","duration_ms":100,"sample_rate":16000}\n`,
      '{"type":"done","segment_count":1}\n',
    ]), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));

    const events = await collect(streamSpeech('hello'));

    expect(events[0]).toEqual({ type: 'start', provider: 'fake', model: 'fake-tone-v1' });
    expect(events[1]).toMatchObject({ type: 'segment', index: 0, mediaType: 'audio/wav', durationMs: 100, sampleRate: 16000 });
    expect(Array.from(events[1].type === 'segment' ? events[1].audioBytes : [])).toEqual([82, 73, 70, 70, 0, 0, 0, 0, 87, 65, 86, 69]);
    expect(events[2]).toEqual({ type: 'done', segmentCount: 1 });
  });

  it('streams persisted assistant speech with encoded ID and narrow body', async () => {
    const controller = new AbortController();
    globalThis.fetch = vi.fn().mockResolvedValue(new Response(streamFromChunks([
      '{"type":"done","segment_count":0}\n',
    ]), { status: 200 }));

    await collect(streamMessageSpeech('assistant/42', {
      voiceId: 'fake-default',
      speed: 1.04,
      signal: controller.signal,
    }));

    expect(fetch).toHaveBeenCalledWith(
      '/api/messages/assistant%2F42/speech/stream',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ voice_id: 'fake-default', speed: 1.04 }),
        signal: controller.signal,
      }),
    );
    const [, init] = vi.mocked(fetch).mock.calls[0];
    expect(String(init?.body)).not.toContain('text');
    expect(String(init?.body)).not.toContain('signal');
  });

  it('maps message stream HTTP errors and omits undefined options', async () => {
    globalThis.fetch = vi.fn()
      .mockResolvedValueOnce(new Response(streamFromChunks(['{"type":"done","segment_count":0}\n']), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ error: { message: '消息流不可用。' } }), { status: 404 }));

    await collect(streamMessageSpeech('a1'));
    await expect(collect(streamMessageSpeech('a1'))).rejects.toThrow('消息流不可用。');

    expect(vi.mocked(fetch).mock.calls[0][1]?.body).toBe('{}');
  });

  it('throws a user-facing error for malformed segment events', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response(streamFromChunks([
      '{"type":"segment","index":0,"audio_base64":"","media_type":"audio/wav","duration_ms":0,"sample_rate":0}\n',
    ]), { status: 200 }));

    await expect(collect(streamSpeech('hello'))).rejects.toThrow('语音流返回了无法播放的音频片段。');
  });

  it('uses the normal error envelope for HTTP failures', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { message: '流式语音不可用。' } }), {
      status: 502,
      headers: { 'Content-Type': 'application/json' },
    }));

    await expect(collect(streamSpeech('hello'))).rejects.toThrow('流式语音不可用。');
  });
});
