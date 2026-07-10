import { afterEach, describe, expect, it, vi } from 'vitest';
import { streamTranscription } from './transcriptionStream';

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

describe('streamTranscription', () => {
  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it('posts audio chunks and parses NDJSON events split across network chunks', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response(streamFromChunks([
      '{"type":"start","provider":"fake","model":"fake-asr-v1"}\n{"type":"par',
      'tial","index":0,"text":"语音","is_final":false,"audio_ms":1000}\n',
      '{"type":"final","text":"语音转写文本","detected_language":"zh","duration_ms":null,"provider":"fake","model":"fake-asr-v1","inference_ms":0}\n',
      '{"type":"done"}\n',
    ]), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));

    const chunks = [new Blob(['one'], { type: 'audio/webm' }), new Blob(['two'], { type: 'audio/webm' })];
    const events = await collect(streamTranscription(chunks, { language: 'zh' }));

    expect(globalThis.fetch).toHaveBeenCalledWith('/api/audio/transcriptions/stream', expect.objectContaining({ method: 'POST' }));
    const body = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][1]?.body;
    expect(body).toBeInstanceOf(FormData);
    expect(Array.from((body as FormData).getAll('chunks'))).toHaveLength(2);
    expect((body as FormData).get('language')).toBe('zh');
    expect(events).toEqual([
      { type: 'start', provider: 'fake', model: 'fake-asr-v1' },
      { type: 'partial', index: 0, text: '语音', isFinal: false, audioMs: 1000 },
      { type: 'final', text: '语音转写文本', detectedLanguage: 'zh', durationMs: null, provider: 'fake', model: 'fake-asr-v1', inferenceMs: 0 },
      { type: 'done' },
    ]);
  });

  it('throws a user-facing error for malformed partial events', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response(streamFromChunks([
      '{"type":"partial","index":-1,"text":"","is_final":false,"audio_ms":1000}\n',
    ]), { status: 200 }));

    await expect(collect(streamTranscription([new Blob(['one'], { type: 'audio/webm' })]))).rejects.toThrow('语音流返回了无法处理的转写片段。');
  });

  it('uses the normal error envelope for HTTP failures', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { message: '流式转写不可用。' } }), {
      status: 502,
      headers: { 'Content-Type': 'application/json' },
    }));

    await expect(collect(streamTranscription([new Blob(['one'], { type: 'audio/webm' })]))).rejects.toThrow('流式转写不可用。');
  });
});
