export interface PersonaConfig {
  identity: { name: string; species: string; role: string };
  background: string;
  personality: { core_traits: string[]; values: string[] };
  language_style: { tone: string; habits: string[] };
  relationship: { initial: string };
  additional_prohibitions: string[];
}

export interface PersonaArtifact {
  id: string;
  version: number;
  payload_state: 'active' | 'redacted';
  schema_version: string;
  ruleset_version: string;
  template_version: string;
  compiler_version: string;
  config: PersonaConfig | null;
  created_at: string;
  redacted_at: string | null;
  active: boolean;
  activation_generation: number;
  fingerprint_prefix: string | null;
  outcome: string | null;
}

export interface PersonaCreateRequest {
  config: PersonaConfig;
  expected_artifact_id: string;
  expected_generation: number;
}

export interface PersonaActivateRequest {
  artifact_id: string;
  expected_artifact_id: string;
  expected_generation: number;
}

export interface PersonaRedactRequest {
  expected_artifact_id: string;
  expected_generation: number;
  replacement_artifact_id?: string | null;
  replacement_config?: PersonaConfig | null;
  confirmation: 'redact_persona_payload';
}

export interface PersonaRedactResponse {
  redacted: PersonaArtifact;
  active: PersonaArtifact;
}

export interface PersonaCapabilities {
  persona_artifacts: boolean;
  context_composer: boolean;
  summary_processing: boolean;
  summary_injection: boolean;
  relationship_projection: boolean;
  remote_summary: string;
}

export type SummaryAuthorityStatus = 'unknown' | 'granted' | 'declined' | 'revoked';
export type SummaryAuthorityAction = 'grant' | 'decline' | 'revoke' | 'enable_local' | 'disable_local';
export type SummaryPayloadState = 'active' | 'redacted' | 'quarantined';
export type SummarySuppressionState = 'suppressed' | 'rebuild_authorized' | 'rebuild_in_progress' | 'rebuild_completed';
export type SummaryJobStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'skipped';

export interface SummaryCapabilities {
  summary_processing: boolean;
  summary_injection: boolean;
  processing_route: 'local' | 'remote';
  processing_provider: string;
  processing_model: string;
  injection_route: 'local' | 'remote';
  injection_provider: string;
  injection_model: string;
  remote_summary: string;
}

interface SummaryConsentBase {
  scope_id: string;
  status: SummaryAuthorityStatus;
  route: 'local' | 'remote';
  disclosure_version: string;
  purpose: string;
  provider: string;
  model: string;
  disclosed_fields: string[];
  generation: number;
  valid_for_current_policy: boolean;
  reason_code: string | null;
  updated_at: string;
}

export interface SummaryProcessingConsent extends SummaryConsentBase {}

export interface SummaryInjectionConsent extends SummaryConsentBase {
  max_fragment_count: number;
  max_fragment_characters: number;
  max_total_characters: number;
}

export interface SummaryStatus {
  summary_counts: Record<string, number>;
  job_counts: Record<string, number>;
}

export interface SummaryItem {
  id: string;
  session_id: string;
  summary_text: string | null;
  source_kind: string;
  payload_state: SummaryPayloadState;
  provenance_state: string;
  source_message_count: number;
  source_turn_count: number;
  source_started_at: string | null;
  source_ended_at: string | null;
  replaces_summary_id: string | null;
  suppression_generation: number;
  suppression_state: SummarySuppressionState | null;
  unavailable_label: string | null;
  created_at: string;
  updated_at: string;
}

export interface SummaryJob {
  id: string;
  session_id: string;
  job_kind: 'incremental' | 'rebuild';
  status: SummaryJobStatus;
  source_summary_id?: string | null;
  source_message_count: number;
  source_turn_count: number;
  route: 'fake' | 'remote';
  provider: string | null;
  model: string | null;
  summarizer_schema_version: string;
  job_schema_version: string;
  attempt_count: number;
  reason_code: string | null;
  error_category: string | null;
  retryable: boolean;
  cancellable: boolean;
  suppression_generation?: number | null;
  suppression_state?: SummarySuppressionState | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface SummaryAudit {
  id: string;
  kind: string;
  status: string;
  outcome: string | null;
  session_id: string | null;
  job_id: string | null;
  summary_id: string | null;
  generation: number | null;
  source_message_count: number | null;
  source_turn_count: number | null;
  route: string | null;
  provider: string | null;
  model: string | null;
  reason_code: string | null;
  error_category: string | null;
  created_at: string;
}

export type SummaryPage = KeysetPage<SummaryItem>;
export type SummaryJobPage = KeysetPage<SummaryJob>;
export type SummaryAuditPage = KeysetPage<SummaryAudit>;

export interface SummaryAuthorityMutationRequest {
  action: SummaryAuthorityAction;
  expected_generation: number;
}

export interface SummaryRedactRequest {
  expected_suppression_generation: number;
  confirmation: 'redact_summary_payload';
}

export interface SummaryRebuildRequest {
  expected_suppression_generation: number;
}

export interface SummaryJobMutationRequest {
  expected_status: Exclude<SummaryJobStatus, 'succeeded'>;
  expected_suppression_generation?: number;
  expected_suppression_state?: SummarySuppressionState;
}

export interface SummaryMutationResponse {
  outcome: string;
  summary_id: string | null;
  job_id: string | null;
  status: string | null;
  suppression_generation: number | null;
  suppression_state: SummarySuppressionState | null;
}

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
export type MemorySource = 'manual' | 'candidate' | 'automatic';
export type MemoryV2State = 'active' | 'archived' | 'conflicted' | 'deleted';
export type MemoryV2SourceKind = 'legacy' | 'manual' | 'candidate' | 'automatic' | 'user_edit' | 'user_revert';
export type RelationshipSubjectCode = 'preferred_address' | 'shared_experience' | 'non_external_commitment';

export interface MemoryRecord {
  id: string;
  content: string;
  memory_type: MemoryType;
  source: MemorySource;
  source_session_id: string | null;
  importance: number;
  confidence: number;
  status: MemoryStatus;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
  v2_state: MemoryV2State | null;
  v2_source_kind: MemoryV2SourceKind | null;
  version_count: number;
  evidence_count: number;
  has_open_conflict: boolean;
  can_undo_latest_auto: boolean;
  canonical_subject_code: RelationshipSubjectCode | null;
}

export interface CreateMemoryRequest {
  content: string;
  memory_type: MemoryType;
  source_session_id?: string | null;
  importance?: number;
  confidence?: number;
  metadata?: Record<string, unknown>;
  canonical_subject_code?: RelationshipSubjectCode | null;
}

export interface UpdateMemoryRequest {
  content?: string;
  memory_type?: MemoryType;
  importance?: number;
  confidence?: number;
  metadata?: Record<string, unknown>;
  canonical_subject_code?: RelationshipSubjectCode | null;
}

export interface ConfirmMemoryCandidateRequest {
  canonical_subject_code?: RelationshipSubjectCode | null;
}

export interface MemoryMutationResponse {
  memory: MemoryRecord;
  conflicts: MemoryRecord[];
}

export type MemoryWriteConsentStatus = 'unknown' | 'granted' | 'declined' | 'revoked';
export type MemoryWriteConsentAction = 'grant' | 'decline' | 'revoke';

export interface MemoryWriteConsent {
  scope_id: string;
  status: MemoryWriteConsentStatus;
  purpose: string | null;
  policy_version: string | null;
  retention_disclosure_version: string | null;
  allowed_memory_types_version: string | null;
  allowed_memory_types: MemoryType[];
  generation: number;
  granted_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface MemoryVersion {
  id: string;
  memory_id: string;
  version_number: number;
  parent_version_id: string | null;
  operation: 'bootstrap' | 'create' | 'user_edit' | 'auto_supersede' | 'conflict_candidate' | 'conflict_resolution' | 'user_revert' | 'archive' | 'delete';
  memory_type: MemoryType;
  subject: string | null;
  content: string | null;
  confidence: number;
  importance: number;
  source_kind: 'legacy' | 'manual' | 'candidate' | 'automatic' | 'user_edit' | 'user_revert';
  source_session_id: string | null;
  created_at: string;
  redacted_at: string | null;
  canonical_subject_code: RelationshipSubjectCode | null;
}

export interface MemoryEvidence {
  id: string;
  memory_id: string;
  memory_version_id: string;
  source_session_id: string | null;
  source_message_id: string | null;
  source_available: boolean;
  relation: 'supports' | 'contradicts' | 'corrects';
  observed_at: string;
  extractor_kind: 'local' | 'fake' | 'remote' | 'manual' | 'candidate';
  extractor_provider: string | null;
  extractor_model: string | null;
  confidence: number;
  created_at: string;
}

export interface KeysetPage<T> {
  items: T[];
  next_cursor: string | null;
}

export type MemoryVersionPage = KeysetPage<MemoryVersion>;
export type MemoryEvidencePage = KeysetPage<MemoryEvidence>;

export type MemoryConflictResolutionKind = 'choose_left' | 'choose_right' | 'replace_both' | 'both_contextual' | 'dismiss_both';

export interface MemoryConflict {
  id: string;
  left_memory_id: string;
  right_memory_id: string;
  status: 'open' | 'resolved';
  resolution_kind: MemoryConflictResolutionKind | 'forget_left' | 'forget_right' | 'forget_both' | null;
  resolved_memory_id: string | null;
  created_at: string;
  resolved_at: string | null;
}

export type MemoryConflictPage = KeysetPage<MemoryConflict>;

export type MemoryConflictResolutionRequest =
  | { kind: 'choose_left' | 'choose_right' | 'dismiss_both' }
  | {
      kind: 'replace_both' | 'both_contextual';
      content: string;
      memory_type: MemoryType;
      subject: string;
      importance: number;
      confidence: number;
      canonical_subject_code?: RelationshipSubjectCode | null;
    };

export interface MemoryConflictResolutionResponse {
  conflict: MemoryConflict;
  resolved_memory: MemoryRecord | null;
}

export interface MemoryForgetResponse {
  scope: 'memory' | 'session' | 'memory_type' | 'all';
  scope_id: string | null;
  forgotten_memory_ids: string[];
  forgotten_candidate_ids: string[];
  deletion_generation: number;
  summary_barrier_generation: number;
}

export interface MemoryUndoResponse {
  memory_id: string;
  action: 'forgotten_create' | 'reverted_supersede' | 'retracted_support';
  memory: MemoryRecord | null;
}

export interface MemoryJobSummary {
  id: string;
  turn_id?: string;
  schema_version?: string;
  session_id?: string | null;
  user_message_id?: string | null;
  assistant_message_id?: string | null;
  mode?: string;
  extractor_route?: string;
  status: 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled';
  attempt_count?: number;
  outcome: string | null;
  error_category?: string | null;
  governor_version?: string;
  consent_generation?: number | null;
  created_at: string;
  started_at?: string | null;
  finished_at: string | null;
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
