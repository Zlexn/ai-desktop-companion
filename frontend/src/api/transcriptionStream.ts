import type { ApiErrorEnvelope, TranscribeAudioOptions, TranscriptionResult, TranscriptionStreamEvent } from './types';

async function responseErrorMessage(response: Response): Promise<string> {
  let message = '请求失败，请稍后重试。';
  try {
    const body = (await response.json()) as ApiErrorEnvelope;
    message = body.error?.message || message;
  } catch {
    // Keep generic message for non-JSON errors.
  }
  return message;
}

function filenameForChunk(chunk: Blob, index: number): string {
  const normalized = chunk.type.split(';')[0].trim().toLowerCase();
  if (normalized === 'audio/webm') return `chunk-${index}.webm`;
  if (normalized === 'audio/mp4') return `chunk-${index}.mp4`;
  if (normalized === 'audio/wav' || normalized === 'audio/x-wav') return `chunk-${index}.wav`;
  return `chunk-${index}.bin`;
}

function parseEvent(line: string): TranscriptionStreamEvent {
  const payload = JSON.parse(line) as Record<string, unknown>;
  const type = payload.type;
  if (type === 'start') {
    const provider = String(payload.provider ?? '');
    const model = String(payload.model ?? '');
    if (!provider || !model) throw new Error('语音流返回了无法处理的转写片段。');
    return { type: 'start', provider, model };
  }
  if (type === 'partial') {
    const index = Number(payload.index);
    const text = String(payload.text ?? '').trim();
    const audioMs = payload.audio_ms === null || payload.audio_ms === undefined ? null : Number(payload.audio_ms);
    if (!Number.isInteger(index) || index < 0 || !text || (audioMs !== null && (!Number.isFinite(audioMs) || audioMs < 0))) {
      throw new Error('语音流返回了无法处理的转写片段。');
    }
    return { type: 'partial', index, text, isFinal: payload.is_final === true, audioMs };
  }
  if (type === 'final') {
    const text = String(payload.text ?? '').trim();
    const provider = String(payload.provider ?? '');
    const model = String(payload.model ?? '');
    const inferenceMs = Number(payload.inference_ms);
    const durationMs = payload.duration_ms === null || payload.duration_ms === undefined ? null : Number(payload.duration_ms);
    const detectedLanguage = payload.detected_language === null || payload.detected_language === undefined ? null : String(payload.detected_language);
    if (!text || !provider || !model || !Number.isInteger(inferenceMs) || inferenceMs < 0 || (durationMs !== null && (!Number.isFinite(durationMs) || durationMs < 0))) {
      throw new Error('语音流返回了无法处理的转写片段。');
    }
    return { type: 'final', text, detectedLanguage, durationMs, provider, model, inferenceMs };
  }
  if (type === 'done') return { type: 'done' };
  if (type === 'error') return { type: 'error', message: String(payload.message || '语音转写失败，请重新录制或手动输入。') };
  throw new Error('语音流返回了无法处理的转写片段。');
}

export async function* streamTranscription(
  chunks: Blob[],
  options: TranscribeAudioOptions = {},
): AsyncGenerator<TranscriptionStreamEvent> {
  const formData = new FormData();
  chunks.forEach((chunk, index) => {
    formData.append('chunks', chunk, filenameForChunk(chunk, index));
  });
  formData.append('language', options.language ?? 'zh');

  const response = await fetch('/api/audio/transcriptions/stream', {
    method: 'POST',
    body: formData,
    signal: options.signal,
  });

  if (!response.ok) {
    throw new Error(await responseErrorMessage(response));
  }
  const contentType = response.headers.get('content-type') ?? '';
  if (contentType.toLowerCase().startsWith('application/json')) {
    const body = (await response.json()) as TranscriptionResult;
    if (!body.text || !body.provider || !body.model) {
      throw new Error('语音流返回了无法处理的转写片段。');
    }
    yield { type: 'start', provider: body.provider, model: body.model };
    yield {
      type: 'final',
      text: body.text,
      detectedLanguage: body.detected_language,
      durationMs: body.duration_ms,
      provider: body.provider,
      model: body.model,
      inferenceMs: body.inference_ms,
    };
    yield { type: 'done' };
    return;
  }

  if (!response.body) {
    throw new Error('浏览器不支持流式语音转写。');
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
        const event = line.trim();
        if (event) yield parseEvent(event);
      }
    }
    pending += decoder.decode();
    if (pending.trim()) yield parseEvent(pending.trim());
  } finally {
    reader.releaseLock();
  }
}
