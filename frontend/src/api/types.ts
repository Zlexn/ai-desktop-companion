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
  assistant_message_id: string;
}

export type ExpressionDelivery = 'neutral' | 'warm' | 'reassuring' | 'reserved' | 'firm';
export type ExpressionIntensity = 'low' | 'medium';

export interface MessageExpressionResponse {
  assistant_message_id: string;
  schema_version: 1;
  delivery: ExpressionDelivery;
  intensity: ExpressionIntensity;
  rate: number;
  source: 'persisted_plan' | 'default';
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

export interface EmotionVector {
  mood: number;
  trust: number;
  concern: number;
  distance: number;
  irritation: number;
  formality: number;
}

export interface EmotionState {
  scope_id: string;
  enabled: boolean;
  vector: EmotionVector;
  version: number;
  updated_at: string;
}

export interface EmotionEvent {
  id: string;
  event_type: 'transition' | 'decay' | 'settings' | 'reset';
  before: EmotionVector;
  after: EmotionVector;
  applied_delta: EmotionVector;
  reason_codes: string[];
  source_session_id: string | null;
  source_user_message_id: string | null;
  source_assistant_message_id: string | null;
  engine: string;
  rule_version: string;
  created_at: string;
}

export type EmotionAnalysisConsentStatus = 'unknown' | 'granted' | 'declined' | 'revoked';
export type EmotionAnalysisConsentAction = 'grant' | 'decline' | 'revoke';

export interface EmotionAnalysisConsent {
  scope_id: string;
  status: EmotionAnalysisConsentStatus;
  disclosure_version: string | null;
  provider: string | null;
  deployment_provider: string;
  deployment_enabled: boolean;
  updated_at: string;
}

export interface EmotionAnalysisAudit {
  id: string;
  job_id: string;
  outcome: 'applied' | 'no_change' | 'skipped' | 'invalid_output' | 'provider_error' | 'revoked' | 'failed';
  source_session_id: string;
  source_user_message_id: string;
  source_assistant_message_id: string;
  schema_version: string;
  provider: string;
  model: string;
  message_count: number;
  memory_count: number;
  input_characters: number;
  redaction_count: number;
  elapsed_ms: number;
  reason_code: string;
  created_at: string;
}

export type TranscriptionStreamEvent =
  | { type: 'start'; provider: string; model: string }
  | { type: 'partial'; index: number; text: string; isFinal: boolean; audioMs: number | null }
  | { type: 'final'; text: string; detectedLanguage: string | null; durationMs: number | null; provider: string; model: string; inferenceMs: number }
  | { type: 'done' }
  | { type: 'error'; message: string };
