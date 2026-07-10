import { streamSpeech } from './speechStream';
import { streamTranscription } from './transcriptionStream';
import type { ApiErrorEnvelope, ChatResponse, CreateMemoryRequest, MemoryMutationResponse, MemoryRecord, MemoryStatus, Message, Session, SpeechSynthesisResponse, SynthesizeSpeechOptions, TranscribeAudioOptions, TranscriptionResult, UpdateMemoryRequest } from './types';

async function requestJson<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  });

  if (!response.ok) {
    throw new Error(await responseErrorMessage(response));
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

async function responseErrorMessage(response: Response): Promise<string> {
  let message = '请求失败，请稍后重试。';
  try {
    const body = (await response.json()) as ApiErrorEnvelope;
    message = body.error?.message || message;
  } catch {
    // Keep the generic message when the server does not return JSON.
  }
  return message;
}

function numericHeader(headers: Headers, name: string): number | null {
  const value = headers.get(name);
  if (!value) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

async function requestSpeech(text: string, options: SynthesizeSpeechOptions = {}): Promise<SpeechSynthesisResponse> {
  const response = await fetch('/api/audio/speech', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, voice_id: options.voiceId, speed: options.speed }),
    signal: options.signal,
  });

  if (!response.ok) {
    throw new Error(await responseErrorMessage(response));
  }

  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.toLowerCase().startsWith('audio/wav')) {
    throw new Error('语音合成服务返回了无法播放的音频。');
  }

  return {
    blob: await response.blob(),
    provider: response.headers.get('x-tts-provider'),
    model: response.headers.get('x-tts-model'),
    durationMs: numericHeader(response.headers, 'x-audio-duration-ms'),
    sampleRate: numericHeader(response.headers, 'x-audio-sample-rate'),
  };
}

function mapMimeToFilename(mimeType: string): string {
  const normalized = mimeType.split(';')[0].trim().toLowerCase();
  if (normalized === 'audio/webm') return 'recording.webm';
  if (normalized === 'audio/mp4') return 'recording.mp4';
  if (normalized === 'audio/wav' || normalized === 'audio/x-wav') return 'recording.wav';
  return 'recording.bin';
}

export const apiClient = {
  listSessions(): Promise<Session[]> {
    return requestJson<Session[]>('/api/sessions');
  },

  createSession(title?: string): Promise<Session> {
    return requestJson<Session>('/api/sessions', {
      method: 'POST',
      body: JSON.stringify({ title }),
    });
  },

  deleteSession(sessionId: string): Promise<void> {
    return requestJson<void>(`/api/sessions/${sessionId}`, { method: 'DELETE' });
  },

  listMessages(sessionId: string): Promise<Message[]> {
    return requestJson<Message[]>(`/api/sessions/${sessionId}/messages`);
  },

  sendMessage(sessionId: string, content: string): Promise<ChatResponse> {
    return requestJson<ChatResponse>(`/api/sessions/${sessionId}/messages`, {
      method: 'POST',
      body: JSON.stringify({ content }),
    });
  },

  listMemories(status: MemoryStatus = 'active'): Promise<MemoryRecord[]> {
    const suffix = status === 'active' ? '' : `?status_filter=${encodeURIComponent(status)}`;
    return requestJson<MemoryRecord[]>(`/api/memories${suffix}`);
  },

  createMemory(request: CreateMemoryRequest): Promise<MemoryMutationResponse> {
    return requestJson<MemoryMutationResponse>('/api/memories', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  updateMemory(memoryId: string, request: UpdateMemoryRequest): Promise<MemoryMutationResponse> {
    return requestJson<MemoryMutationResponse>(`/api/memories/${memoryId}`, {
      method: 'PATCH',
      body: JSON.stringify(request),
    });
  },

  confirmMemoryCandidate(memoryId: string): Promise<MemoryMutationResponse> {
    return requestJson<MemoryMutationResponse>(`/api/memories/${memoryId}/confirm`, { method: 'POST' });
  },

  dismissMemoryCandidate(memoryId: string): Promise<MemoryRecord> {
    return requestJson<MemoryRecord>(`/api/memories/${memoryId}/dismiss`, { method: 'POST' });
  },

  deleteMemory(memoryId: string): Promise<void> {
    return requestJson<void>(`/api/memories/${memoryId}`, { method: 'DELETE' });
  },

  synthesizeSpeech(text: string, options?: SynthesizeSpeechOptions): Promise<SpeechSynthesisResponse> {
    return requestSpeech(text, options);
  },

  streamSpeech,

  streamTranscription,

  async transcribeAudio(audio: Blob, options?: TranscribeAudioOptions): Promise<TranscriptionResult> {
    const formData = new FormData();
    const filename = mapMimeToFilename(audio.type);
    formData.append('file', audio, filename);
    formData.append('language', options?.language ?? 'zh');

    const response = await fetch('/api/audio/transcriptions', {
      method: 'POST',
      body: formData,
      signal: options?.signal,
    });

    if (!response.ok) {
      throw new Error(await responseErrorMessage(response));
    }

    const body = (await response.json()) as TranscriptionResult;
    if (!body.text || !body.provider) {
      throw new Error('语音转写服务返回了无法处理的结果。');
    }

    return body;
  },
};
