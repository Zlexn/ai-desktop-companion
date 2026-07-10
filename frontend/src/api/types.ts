export interface Session {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  session_id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
  metadata: Record<string, unknown>;
}

export interface ChatResponse {
  reply: string;
  metadata: {
    provider: string;
    model: string;
  };
}

export interface SpeechSynthesisResponse {
  blob: Blob;
  provider: string | null;
  model: string | null;
  durationMs: number | null;
  sampleRate: number | null;
}

export interface SynthesizeSpeechOptions {
  voiceId?: string;
  speed?: number;
  signal?: AbortSignal;
}

export interface ApiErrorEnvelope {
  error?: {
    code?: string;
    message?: string;
  };
}

export interface TranscriptionResult {
  text: string;
  detected_language: string | null;
  duration_ms: number | null;
  provider: string;
  model: string;
  inference_ms: number;
}

export interface TranscribeAudioOptions {
  language?: string;
  signal?: AbortSignal;
}

export type MemoryType = 'user_fact' | 'preference' | 'long_term_goal' | 'important_event' | 'relationship_event' | 'other';
export type MemoryStatus = 'active' | 'archived' | 'pending' | 'dismissed';

export interface MemoryRecord {
  id: string;
  content: string;
  memory_type: MemoryType;
  source: 'manual' | 'candidate';
  source_session_id: string | null;
  importance: number;
  confidence: number;
  status: MemoryStatus;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export interface CreateMemoryRequest {
  content: string;
  memory_type: MemoryType;
  source_session_id?: string | null;
  importance?: number;
  confidence?: number;
  metadata?: Record<string, unknown>;
}

export interface UpdateMemoryRequest {
  content?: string;
  memory_type?: MemoryType;
  importance?: number;
  confidence?: number;
  metadata?: Record<string, unknown>;
}

export interface MemoryMutationResponse {
  memory: MemoryRecord;
  conflicts: MemoryRecord[];
}

export type TranscriptionStreamEvent =
  | { type: 'start'; provider: string; model: string }
  | { type: 'partial'; index: number; text: string; isFinal: boolean; audioMs: number | null }
  | { type: 'final'; text: string; detectedLanguage: string | null; durationMs: number | null; provider: string; model: string; inferenceMs: number }
  | { type: 'done' }
  | { type: 'error'; message: string };
