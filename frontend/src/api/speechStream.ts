import type { ApiErrorEnvelope, SynthesizeSpeechOptions } from './types';

export type SpeechStreamEvent =
  | { type: 'start'; provider: string | null; model: string | null }
  | { type: 'segment'; index: number; audioBytes: Uint8Array; mediaType: 'audio/wav'; durationMs: number; sampleRate: number }
  | { type: 'done'; segmentCount: number }
  | { type: 'error'; message: string };

async function responseErrorMessage(response: Response): Promise<string> {
  let message = '请求失败，请稍后重试。';
  try {
    const body = (await response.json()) as ApiErrorEnvelope;
    message = body.error?.message || message;
  } catch {
    // Keep generic message.
  }
  return message;
}

function base64ToBytes(value: string): Uint8Array {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function parseEvent(line: string): SpeechStreamEvent {
  const raw = JSON.parse(line) as Record<string, unknown>;
  if (raw.type === 'start') {
    return {
      type: 'start',
      provider: typeof raw.provider === 'string' ? raw.provider : null,
      model: typeof raw.model === 'string' ? raw.model : null,
    };
  }
  if (raw.type === 'segment') {
    const index = Number(raw.index);
    const durationMs = Number(raw.duration_ms);
    const sampleRate = Number(raw.sample_rate);
    const audioBase64 = typeof raw.audio_base64 === 'string' ? raw.audio_base64 : '';
    if (!Number.isInteger(index) || index < 0 || !audioBase64 || raw.media_type !== 'audio/wav' || durationMs <= 0 || sampleRate <= 0) {
      throw new Error('语音流返回了无法播放的音频片段。');
    }
    return {
      type: 'segment',
      index,
      audioBytes: base64ToBytes(audioBase64),
      mediaType: 'audio/wav',
      durationMs,
      sampleRate,
    };
  }
  if (raw.type === 'done') {
    const segmentCount = Number(raw.segment_count);
    return { type: 'done', segmentCount: Number.isInteger(segmentCount) ? segmentCount : 0 };
  }
  if (raw.type === 'error') {
    return { type: 'error', message: typeof raw.message === 'string' ? raw.message : '语音合成失败，请稍后重试。' };
  }
  return { type: 'error', message: '语音流返回了未知事件。' };
}

async function* streamSpeechRequest(
  path: string,
  body: Record<string, unknown>,
  signal?: AbortSignal,
): AsyncGenerator<SpeechStreamEvent> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });

  if (!response.ok) {
    throw new Error(await responseErrorMessage(response));
  }
  if (!response.body) {
    throw new Error('当前浏览器不支持流式语音播放。');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let pending = '';
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      pending += decoder.decode(value, { stream: true });
      const lines = pending.split('\n');
      pending = lines.pop() ?? '';
      for (const line of lines) {
        if (line.trim()) yield parseEvent(line);
      }
    }
    pending += decoder.decode();
    if (pending.trim()) yield parseEvent(pending);
  } finally {
    reader.releaseLock();
  }
}

export async function* streamSpeech(
  text: string,
  options: SynthesizeSpeechOptions = {},
): AsyncGenerator<SpeechStreamEvent> {
  yield* streamSpeechRequest(
    '/api/audio/speech/stream',
    { text, voice_id: options.voiceId, speed: options.speed },
    options.signal,
  );
}

export async function* streamMessageSpeech(
  assistantMessageId: string,
  options: SynthesizeSpeechOptions = {},
): AsyncGenerator<SpeechStreamEvent> {
  yield* streamSpeechRequest(
    `/api/messages/${encodeURIComponent(assistantMessageId)}/speech/stream`,
    { voice_id: options.voiceId, speed: options.speed },
    options.signal,
  );
}
