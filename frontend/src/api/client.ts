import { parseMessageExpressionResponse } from '../expression/events';
import { streamMessageSpeech, streamSpeech } from './speechStream';
import { streamTranscription } from './transcriptionStream';
import type { ApiErrorEnvelope, ChatResponse, CreateMemoryRequest, EmotionAnalysisAudit, EmotionAnalysisConsent, EmotionAnalysisConsentAction, EmotionEvent, EmotionState, MemoryConflictPage, MemoryConflictResolutionRequest, MemoryConflictResolutionResponse, MemoryEvidencePage, MemoryForgetResponse, MemoryJobSummary, MemoryMutationResponse, MemoryRecord, MemoryStatus, MemoryUndoResponse, MemoryVersionPage, MemoryWriteConsent, MemoryWriteConsentAction, Message, MessageExpressionResponse, PersonaActivateRequest, PersonaArtifact, PersonaCapabilities, PersonaCreateRequest, PersonaRedactRequest, PersonaRedactResponse, RelationshipAuditPage, RelationshipCapabilities, RelationshipEventPage, RelationshipJobPage, RelationshipMutationResponse, RelationshipProjection, RelationshipReconcileRequest, RelationshipRedactRequest, RelationshipReenableRequest, RelationshipSubjectCode, RelationshipSuppressRequest, Session, SpeechSynthesisResponse, SummaryAuditPage, SummaryAuthorityMutationRequest, SummaryCapabilities, SummaryInjectionConsent, SummaryJobMutationRequest, SummaryJobPage, SummaryMutationResponse, SummaryPage, SummaryProcessingConsent, SummaryRebuildRequest, SummaryRedactRequest, SummaryStatus, SynthesizeSpeechOptions, TranscribeAudioOptions, TranscriptionResult, UpdateMemoryRequest } from './types';

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

async function requestSpeech(
  path: string,
  body: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<SpeechSynthesisResponse> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
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
  getCurrentPersona(): Promise<PersonaArtifact> {
    return requestJson<PersonaArtifact>('/api/persona/current');
  },

  listPersonaArtifacts(): Promise<PersonaArtifact[]> {
    return requestJson<PersonaArtifact[]>('/api/persona/artifacts');
  },

  createPersonaArtifact(request: PersonaCreateRequest): Promise<PersonaArtifact> {
    return requestJson<PersonaArtifact>('/api/persona/artifacts', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  activatePersona(request: PersonaActivateRequest): Promise<PersonaArtifact> {
    return requestJson<PersonaArtifact>('/api/persona/active', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  redactPersonaArtifact(
    artifactId: string,
    request: PersonaRedactRequest,
  ): Promise<PersonaRedactResponse> {
    return requestJson<PersonaRedactResponse>(
      `/api/persona/artifacts/${encodeURIComponent(artifactId)}/redact`,
      { method: 'POST', body: JSON.stringify(request) },
    );
  },

  getPersonaCapabilities(): Promise<PersonaCapabilities> {
    return requestJson<PersonaCapabilities>('/api/persona/capabilities');
  },

  getSummaryCapabilities(): Promise<SummaryCapabilities> {
    return requestJson<SummaryCapabilities>('/api/summaries/capabilities');
  },

  getSummaryProcessingConsent(): Promise<SummaryProcessingConsent> {
    return requestJson<SummaryProcessingConsent>('/api/summaries/processing-consent');
  },

  updateSummaryProcessingConsent(
    request: SummaryAuthorityMutationRequest,
  ): Promise<SummaryProcessingConsent> {
    return requestJson<SummaryProcessingConsent>('/api/summaries/processing-consent', {
      method: 'PUT',
      body: JSON.stringify(request),
    });
  },

  getSummaryInjectionConsent(): Promise<SummaryInjectionConsent> {
    return requestJson<SummaryInjectionConsent>('/api/summaries/injection-consent');
  },

  updateSummaryInjectionConsent(
    request: SummaryAuthorityMutationRequest,
  ): Promise<SummaryInjectionConsent> {
    return requestJson<SummaryInjectionConsent>('/api/summaries/injection-consent', {
      method: 'PUT',
      body: JSON.stringify(request),
    });
  },

  getSummaryStatus(): Promise<SummaryStatus> {
    return requestJson<SummaryStatus>('/api/summaries/status');
  },

  listSummaries(
    options: { sessionId?: string | null; limit?: number; cursor?: string | null } = {},
  ): Promise<SummaryPage> {
    const params = new URLSearchParams({ limit: String(options.limit ?? 20) });
    if (options.sessionId) params.set('session_id', options.sessionId);
    if (options.cursor) params.set('cursor', options.cursor);
    return requestJson<SummaryPage>(`/api/summaries?${params}`);
  },

  listSummaryJobs(
    options: { limit?: number; cursor?: string | null } = {},
  ): Promise<SummaryJobPage> {
    const params = new URLSearchParams({ limit: String(options.limit ?? 20) });
    if (options.cursor) params.set('cursor', options.cursor);
    return requestJson<SummaryJobPage>(`/api/summaries/jobs?${params}`);
  },

  listSummaryAudits(
    options: { limit?: number; cursor?: string | null } = {},
  ): Promise<SummaryAuditPage> {
    const params = new URLSearchParams({ limit: String(options.limit ?? 20) });
    if (options.cursor) params.set('cursor', options.cursor);
    return requestJson<SummaryAuditPage>(`/api/summaries/audits?${params}`);
  },

  redactSummary(
    summaryId: string,
    request: SummaryRedactRequest,
  ): Promise<SummaryMutationResponse> {
    return requestJson<SummaryMutationResponse>(
      `/api/summaries/${encodeURIComponent(summaryId)}/redact`,
      { method: 'POST', body: JSON.stringify(request) },
    );
  },

  rebuildSummary(
    summaryId: string,
    request: SummaryRebuildRequest,
  ): Promise<SummaryMutationResponse> {
    return requestJson<SummaryMutationResponse>(
      `/api/summaries/${encodeURIComponent(summaryId)}/rebuild`,
      { method: 'POST', body: JSON.stringify(request) },
    );
  },

  retrySummaryJob(
    jobId: string,
    request: SummaryJobMutationRequest,
  ): Promise<SummaryMutationResponse> {
    return requestJson<SummaryMutationResponse>(
      `/api/summaries/jobs/${encodeURIComponent(jobId)}/retry`,
      { method: 'POST', body: JSON.stringify(request) },
    );
  },

  cancelSummaryJob(
    jobId: string,
    request: SummaryJobMutationRequest,
  ): Promise<SummaryMutationResponse> {
    return requestJson<SummaryMutationResponse>(
      `/api/summaries/jobs/${encodeURIComponent(jobId)}/cancel`,
      { method: 'POST', body: JSON.stringify(request) },
    );
  },

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

  getMessageExpression(
    assistantMessageId: string,
    options: { signal?: AbortSignal } = {},
  ): Promise<MessageExpressionResponse> {
    return requestJson<unknown>(
      `/api/messages/${encodeURIComponent(assistantMessageId)}/expression`,
      { signal: options.signal },
    ).then(parseMessageExpressionResponse);
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

  confirmMemoryCandidate(
    memoryId: string,
    subjectCode?: RelationshipSubjectCode | null,
  ): Promise<MemoryMutationResponse> {
    return requestJson<MemoryMutationResponse>(`/api/memories/${memoryId}/confirm`, {
      method: 'POST',
      body: JSON.stringify({ canonical_subject_code: subjectCode ?? null }),
    });
  },

  dismissMemoryCandidate(memoryId: string): Promise<MemoryRecord> {
    return requestJson<MemoryRecord>(`/api/memories/${memoryId}/dismiss`, { method: 'POST' });
  },

  deleteMemory(memoryId: string): Promise<void> {
    return requestJson<void>(`/api/memories/${memoryId}`, { method: 'DELETE' });
  },

  archiveMemory(memoryId: string): Promise<void> {
    return requestJson<void>(`/api/memories/${encodeURIComponent(memoryId)}/archive`, { method: 'POST' });
  },

  forgetMemory(memoryId: string): Promise<MemoryForgetResponse> {
    return requestJson<MemoryForgetResponse>(`/api/memories/${encodeURIComponent(memoryId)}/forget`, { method: 'POST' });
  },

  undoLatestAutoMemory(memoryId: string): Promise<MemoryUndoResponse> {
    return requestJson<MemoryUndoResponse>(`/api/memories/${encodeURIComponent(memoryId)}/undo-latest-auto`, { method: 'POST' });
  },

  getMemoryWriteConsent(): Promise<MemoryWriteConsent> {
    return requestJson<MemoryWriteConsent>('/api/memories/automation/write-consent');
  },

  updateMemoryWriteConsent(action: MemoryWriteConsentAction): Promise<MemoryWriteConsent> {
    return requestJson<MemoryWriteConsent>('/api/memories/automation/write-consent', {
      method: 'PUT',
      body: JSON.stringify({
        action,
        policy_version: 'memory-auto-write-policy-v1',
        retention_disclosure_version: 'memory-auto-write-retention-v1',
        allowed_memory_types_version: 'memory-auto-write-types-v1',
        allowed_memory_types: ['user_fact', 'preference', 'long_term_goal', 'important_event', 'relationship_event', 'other'],
      }),
    });
  },

  listMemoryVersions(memoryId: string, cursor?: string | null, limit = 20): Promise<MemoryVersionPage> {
    const params = new URLSearchParams({ limit: String(limit) });
    if (cursor) params.set('cursor', cursor);
    return requestJson<MemoryVersionPage>(`/api/memories/${encodeURIComponent(memoryId)}/versions?${params}`);
  },

  listMemoryEvidence(memoryId: string, cursor?: string | null, limit = 20): Promise<MemoryEvidencePage> {
    const params = new URLSearchParams({ limit: String(limit) });
    if (cursor) params.set('cursor', cursor);
    return requestJson<MemoryEvidencePage>(`/api/memories/${encodeURIComponent(memoryId)}/evidence?${params}`);
  },

  listMemoryConflicts(cursor?: string | null, limit = 20): Promise<MemoryConflictPage> {
    const params = new URLSearchParams({ status: 'open', limit: String(limit) });
    if (cursor) params.set('cursor', cursor);
    return requestJson<MemoryConflictPage>(`/api/memories/conflicts?${params}`);
  },

  resolveMemoryConflict(conflictId: string, request: MemoryConflictResolutionRequest): Promise<MemoryConflictResolutionResponse> {
    return requestJson<MemoryConflictResolutionResponse>(`/api/memories/conflicts/${encodeURIComponent(conflictId)}/resolve`, {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  listMemoryJobs(limit = 20): Promise<MemoryJobSummary[]> {
    return requestJson<MemoryJobSummary[]>(`/api/memories/jobs?limit=${limit}`);
  },

  getRelationshipCapabilities(): Promise<RelationshipCapabilities> {
    return requestJson<RelationshipCapabilities>('/api/relationship/capabilities');
  },

  getRelationshipProjection(): Promise<RelationshipProjection> {
    return requestJson<RelationshipProjection>('/api/relationship/projection');
  },

  listRelationshipEvents(
    options: { limit?: number; cursor?: string | null } = {},
  ): Promise<RelationshipEventPage> {
    const params = new URLSearchParams({ limit: String(options.limit ?? 20) });
    if (options.cursor) params.set('cursor', options.cursor);
    return requestJson<RelationshipEventPage>(`/api/relationship/events?${params}`);
  },

  listRelationshipJobs(
    options: { limit?: number; cursor?: string | null } = {},
  ): Promise<RelationshipJobPage> {
    const params = new URLSearchParams({ limit: String(options.limit ?? 20) });
    if (options.cursor) params.set('cursor', options.cursor);
    return requestJson<RelationshipJobPage>(`/api/relationship/jobs?${params}`);
  },

  listRelationshipAudits(
    options: { limit?: number; cursor?: string | null } = {},
  ): Promise<RelationshipAuditPage> {
    const params = new URLSearchParams({ limit: String(options.limit ?? 20) });
    if (options.cursor) params.set('cursor', options.cursor);
    return requestJson<RelationshipAuditPage>(`/api/relationship/audits?${params}`);
  },

  reconcileRelationship(
    request: RelationshipReconcileRequest = {},
  ): Promise<RelationshipJobPage> {
    return requestJson<RelationshipJobPage>('/api/relationship/reconcile', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  rebuildRelationship(
    request: RelationshipReconcileRequest = {},
  ): Promise<RelationshipJobPage> {
    return requestJson<RelationshipJobPage>('/api/relationship/rebuild', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  },

  suppressRelationshipApply(
    applyEventId: string,
    request: RelationshipSuppressRequest,
  ): Promise<RelationshipMutationResponse> {
    return requestJson<RelationshipMutationResponse>(
      `/api/relationship/events/${encodeURIComponent(applyEventId)}/suppress`,
      { method: 'POST', body: JSON.stringify(request) },
    );
  },

  redactRelationshipApply(
    applyEventId: string,
    request: RelationshipRedactRequest,
  ): Promise<RelationshipMutationResponse> {
    return requestJson<RelationshipMutationResponse>(
      `/api/relationship/events/${encodeURIComponent(applyEventId)}/redact`,
      { method: 'POST', body: JSON.stringify(request) },
    );
  },

  reenableRelationshipAuthority(
    sourceMemoryId: string,
    eventType: string,
    subjectCode: string,
    request: RelationshipReenableRequest,
  ): Promise<RelationshipMutationResponse> {
    return requestJson<RelationshipMutationResponse>(
      `/api/relationship/authorities/${encodeURIComponent(sourceMemoryId)}/${encodeURIComponent(eventType)}/${encodeURIComponent(subjectCode)}/reenable`,
      { method: 'POST', body: JSON.stringify(request) },
    );
  },

  getEmotionState(): Promise<EmotionState> {
    return requestJson<EmotionState>('/api/emotion/state');
  },

  listEmotionEvents(limit = 20): Promise<EmotionEvent[]> {
    return requestJson<EmotionEvent[]>(`/api/emotion/events?limit=${limit}`);
  },

  updateEmotionSettings(enabled: boolean): Promise<EmotionState> {
    return requestJson<EmotionState>('/api/emotion/settings', {
      method: 'PATCH',
      body: JSON.stringify({ enabled }),
    });
  },

  resetEmotion(): Promise<EmotionState> {
    return requestJson<EmotionState>('/api/emotion/reset', { method: 'POST' });
  },

  getEmotionAnalysisConsent(): Promise<EmotionAnalysisConsent> {
    return requestJson<EmotionAnalysisConsent>('/api/emotion/analysis/consent');
  },

  updateEmotionAnalysisConsent(action: EmotionAnalysisConsentAction): Promise<EmotionAnalysisConsent> {
    return requestJson<EmotionAnalysisConsent>('/api/emotion/analysis/consent', {
      method: 'PUT',
      body: JSON.stringify({ action, disclosure_version: 'emotion-analysis-disclosure-v1' }),
    });
  },

  listEmotionAnalysisAudits(limit = 20): Promise<EmotionAnalysisAudit[]> {
    return requestJson<EmotionAnalysisAudit[]>(`/api/emotion/analysis/audits?limit=${limit}`);
  },

  synthesizeSpeech(text: string, options: SynthesizeSpeechOptions = {}): Promise<SpeechSynthesisResponse> {
    return requestSpeech(
      '/api/audio/speech',
      { text, voice_id: options.voiceId, speed: options.speed },
      options.signal,
    );
  },

  synthesizeMessageSpeech(
    assistantMessageId: string,
    options: SynthesizeSpeechOptions = {},
  ): Promise<SpeechSynthesisResponse> {
    return requestSpeech(
      `/api/messages/${encodeURIComponent(assistantMessageId)}/speech`,
      { voice_id: options.voiceId, speed: options.speed },
      options.signal,
    );
  },

  streamSpeech,

  streamMessageSpeech,

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
