import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { displayLabelForAssistantMessage } from './expression/displayLabel';
import { apiClient } from './api/client';
import type {
  CreateMemoryRequest,
  EmotionAnalysisAudit,
  EmotionAnalysisConsent,
  EmotionAnalysisConsentAction,
  EmotionEvent,
  EmotionState,
  MemoryConflict,
  MemoryConflictResolutionRequest,
  MemoryEvidencePage,
  MemoryJobSummary,
  MemoryRecord,
  MemoryVersionPage,
  MemoryWriteConsent,
  MemoryWriteConsentAction,
  Message,
  PersonaActivateRequest,
  PersonaArtifact,
  PersonaCapabilities,
  PersonaCreateRequest,
  PersonaRedactRequest,
  RelationshipAudit,
  RelationshipCapabilities,
  RelationshipEvent,
  RelationshipJob,
  RelationshipMutationResponse,
  RelationshipProjection,
  RelationshipReconcileRequest,
  RelationshipRedactRequest,
  RelationshipReenableRequest,
  RelationshipSubjectCode,
  RelationshipSuppressRequest,
  Session,
  SummaryAudit,
  SummaryAuthorityMutationRequest,
  SummaryCapabilities,
  SummaryInjectionConsent,
  SummaryItem,
  SummaryJob,
  SummaryJobMutationRequest,
  SummaryProcessingConsent,
  SummaryRebuildRequest,
  SummaryRedactRequest,
  SummaryStatus,
  UpdateMemoryRequest,
} from './api/types';
import { ChatLayout } from './components/ChatLayout';
import { useAudioPlaybackController } from './hooks/useAudioPlaybackController';
import { useAudioInputDevices } from './hooks/useAudioInputDevices';
import { useAudioOutputDevices } from './hooks/useAudioOutputDevices';
import { useExpressionPreviewController } from './hooks/useExpressionPreviewController';
import { useManualAudioRecorder } from './hooks/useManualAudioRecorder';
import { useVadAutoStop } from './hooks/useVadAutoStop';

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '请求失败，请稍后重试。';
}

export function App() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [memoryCandidates, setMemoryCandidates] = useState<MemoryRecord[]>([]);
  const [memoryLoading, setMemoryLoading] = useState(false);
  const [memoryGateBLoading, setMemoryGateBLoading] = useState(false);
  const [memoryError, setMemoryError] = useState<string | null>(null);
  const [memoryConflicts, setMemoryConflicts] = useState<MemoryRecord[]>([]);
  const [gateBMemoryConflicts, setGateBMemoryConflicts] = useState<MemoryConflict[]>([]);
  const [memoryWriteConsent, setMemoryWriteConsent] = useState<MemoryWriteConsent | null>(null);
  const [latestMemoryJob, setLatestMemoryJob] = useState<MemoryJobSummary | null>(null);
  const [personaCurrent, setPersonaCurrent] = useState<PersonaArtifact | null>(null);
  const [personaArtifacts, setPersonaArtifacts] = useState<PersonaArtifact[]>([]);
  const [personaCapabilities, setPersonaCapabilities] = useState<PersonaCapabilities | null>(null);
  const [personaLoading, setPersonaLoading] = useState(false);
  const [personaError, setPersonaError] = useState<string | null>(null);
  const [summaryCapabilities, setSummaryCapabilities] = useState<SummaryCapabilities | null>(null);
  const [summaryProcessingConsent, setSummaryProcessingConsent] = useState<SummaryProcessingConsent | null>(null);
  const [summaryInjectionConsent, setSummaryInjectionConsent] = useState<SummaryInjectionConsent | null>(null);
  const [summaryStatus, setSummaryStatus] = useState<SummaryStatus | null>(null);
  const [summaries, setSummaries] = useState<SummaryItem[]>([]);
  const [summaryJobs, setSummaryJobs] = useState<SummaryJob[]>([]);
  const [summaryAudits, setSummaryAudits] = useState<SummaryAudit[]>([]);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [emotionState, setEmotionState] = useState<EmotionState | null>(null);
  const [emotionEvents, setEmotionEvents] = useState<EmotionEvent[]>([]);
  const [emotionAnalysisConsent, setEmotionAnalysisConsent] = useState<EmotionAnalysisConsent | null>(null);
  const [emotionAnalysisAudits, setEmotionAnalysisAudits] = useState<EmotionAnalysisAudit[]>([]);
  const [emotionLoading, setEmotionLoading] = useState(false);
  const [emotionConsentLoading, setEmotionConsentLoading] = useState(false);
  const [emotionAuditLoading, setEmotionAuditLoading] = useState(false);
  const [emotionError, setEmotionError] = useState<string | null>(null);
  const [relationshipCapabilities, setRelationshipCapabilities] = useState<RelationshipCapabilities | null>(null);
  const [relationshipProjection, setRelationshipProjection] = useState<RelationshipProjection | null>(null);
  const [relationshipEvents, setRelationshipEvents] = useState<RelationshipEvent[]>([]);
  const [relationshipJobs, setRelationshipJobs] = useState<RelationshipJob[]>([]);
  const [relationshipAudits, setRelationshipAudits] = useState<RelationshipAudit[]>([]);
  const [relationshipLoading, setRelationshipLoading] = useState(false);
  const [relationshipError, setRelationshipError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const audioOutputDevices = useAudioOutputDevices();
  const expressionPreview = useExpressionPreviewController(activeSessionId);
  const audioController = useAudioPlaybackController({
    audioOutputDeviceId: audioOutputDevices.selectedDeviceId,
    onRunActivated: expressionPreview.onRunActivated,
    onRunDeactivated: expressionPreview.onRunDeactivated,
    onSpeakingEvent: expressionPreview.onSpeakingEvent,
  });
  const audioInputDevices = useAudioInputDevices();
  const recorder = useManualAudioRecorder({ audioInputDeviceId: audioInputDevices.selectedDeviceId });
  const [pendingTranscript, setPendingTranscript] = useState<string | null>(null);
  const [voiceTurnStatus, setVoiceTurnStatus] = useState<'idle' | 'sending_chat' | 'synthesizing_or_playing' | 'error'>('idle');
  const [voiceTurnError, setVoiceTurnError] = useState<string | null>(null);
  const activeSessionIdRef = useRef<string | null>(activeSessionId);
  const emotionRequestGenerationRef = useRef(0);
  const emotionConsentGenerationRef = useRef(0);
  const emotionAuditGenerationRef = useRef(0);
  const memoryConsentGenerationRef = useRef(0);
  const personaRequestGenerationRef = useRef(0);
  const summaryRequestGenerationRef = useRef(0);
  const summaryMutationGenerationRef = useRef(0);
  const relationshipRequestGenerationRef = useRef(0);
  const relationshipMutationGenerationRef = useRef(0);
  const voiceTurnGenerationRef = useRef(0);
  const textSendGenerationRef = useRef(0);
  const messageLoadGenerationRef = useRef(0);
  const voiceTurnInFlightRef = useRef(false);
  const vadAutoStop = useVadAutoStop({
    enabled: import.meta.env.MODE !== 'test' || import.meta.env.VITE_ENABLE_FAKE_VAD_IN_TEST === '1',
    recordingStatus: recorder.status,
    stopRecording: recorder.stopRecording,
  });

  // When recorder produces a transcript, store it as pending
  useEffect(() => {
    if (recorder.status === 'ready' && recorder.pendingTranscript !== null) {
      setPendingTranscript(recorder.pendingTranscript);
    }
  }, [recorder.status, recorder.pendingTranscript]);

  function isCurrentVoiceTurn(sessionId: string, generation: number): boolean {
    return activeSessionIdRef.current === sessionId && voiceTurnGenerationRef.current === generation;
  }

  function resetVoiceState() {
    voiceTurnGenerationRef.current += 1;
    voiceTurnInFlightRef.current = false;
    recorder.cancelRecording();
    setPendingTranscript(null);
    setVoiceTurnStatus('idle');
    setVoiceTurnError(null);
  }

  // TTS mutex: stop all playback before starting recording
  const handleStartRecording = useCallback(async () => {
    if (voiceTurnStatus === 'sending_chat') return;

    if (voiceTurnStatus === 'synthesizing_or_playing') {
      voiceTurnGenerationRef.current += 1;
      voiceTurnInFlightRef.current = false;
      setVoiceTurnStatus('idle');
      setVoiceTurnError(null);
      setLoading(false);
    }

    audioController.reset('interrupted');
    expressionPreview.clear();
    await recorder.startRecording('');
  }, [audioController, recorder, voiceTurnStatus]);

  const handleStopRecording = useCallback(() => {
    recorder.stopRecording();
  }, [recorder]);

  const handleClearPendingTranscript = useCallback(() => {
    voiceTurnGenerationRef.current += 1;
    voiceTurnInFlightRef.current = false;
    setPendingTranscript(null);
    recorder.clearResult();
  }, [recorder]);

  async function loadSessions() {
    setLoading(true);
    try {
      const loaded = await apiClient.listSessions();
      setSessions(loaded);
      if (!activeSessionId && loaded.length > 0) {
        setActiveSessionId(loaded[0].id);
      }
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  async function loadMessages(sessionId: string) {
    const generation = ++messageLoadGenerationRef.current;
    setLoading(true);
    try {
      const loaded = await apiClient.listMessages(sessionId);
      if (
        generation !== messageLoadGenerationRef.current ||
        activeSessionIdRef.current !== sessionId
      ) return;
      setMessages(loaded);
      const latestAssistant = [...loaded]
        .reverse()
        .find((item) => item.role === 'assistant');
      if (latestAssistant) {
        expressionPreview.selectAssistantMessage(sessionId, latestAssistant.id);
      } else {
        expressionPreview.clear();
      }
    } catch (caught) {
      if (
        generation === messageLoadGenerationRef.current &&
        activeSessionIdRef.current === sessionId
      ) setError(errorMessage(caught));
    } finally {
      if (
        generation === messageLoadGenerationRef.current &&
        activeSessionIdRef.current === sessionId
      ) setLoading(false);
    }
  }

  async function loadMemories() {
    setMemoryLoading(true);
    try {
      setMemories(await apiClient.listMemories());
      setMemoryError(null);
    } catch (caught) {
      setMemoryError(errorMessage(caught));
    } finally {
      setMemoryLoading(false);
    }
  }

  async function loadMemoryCandidates() {
    setMemoryLoading(true);
    try {
      setMemoryCandidates(await apiClient.listMemories('pending'));
      setMemoryError(null);
    } catch (caught) {
      setMemoryError(errorMessage(caught));
    } finally {
      setMemoryLoading(false);
    }
  }

  async function loadMemoryGateB() {
    const consentGeneration = memoryConsentGenerationRef.current;
    setMemoryGateBLoading(true);
    try {
      const [consent, conflictPage, jobs] = await Promise.all([
        apiClient.getMemoryWriteConsent(),
        apiClient.listMemoryConflicts(),
        apiClient.listMemoryJobs(1),
      ]);
      if (consentGeneration === memoryConsentGenerationRef.current) {
        setMemoryWriteConsent(consent);
      }
      setGateBMemoryConflicts(conflictPage.items);
      setLatestMemoryJob(jobs[0] ?? null);
    } catch (caught) {
      setMemoryError(errorMessage(caught));
    } finally {
      setMemoryGateBLoading(false);
    }
  }

  async function refreshMemoryCollections() {
    const [active, pending, conflictPage, jobs] = await Promise.all([
      apiClient.listMemories(),
      apiClient.listMemories('pending'),
      apiClient.listMemoryConflicts(),
      apiClient.listMemoryJobs(1),
    ]);
    setMemories(active);
    setMemoryCandidates(pending);
    setGateBMemoryConflicts(conflictPage.items);
    setLatestMemoryJob(jobs[0] ?? null);
  }

  function refreshAutomaticMemoryAfterTurn() {
    if (import.meta.env.MODE === 'test' && import.meta.env.VITE_ENABLE_GATE_B_MEMORY_LOAD_IN_TEST !== '1') return;
    void loadMemories();
    void loadMemoryCandidates();
    void loadMemoryGateB();
  }

  async function loadPersona() {
    const generation = ++personaRequestGenerationRef.current;
    setPersonaLoading(true);
    try {
      const [current, artifacts, capabilities] = await Promise.all([
        apiClient.getCurrentPersona(),
        apiClient.listPersonaArtifacts(),
        apiClient.getPersonaCapabilities(),
      ]);
      if (generation !== personaRequestGenerationRef.current) return;
      setPersonaCurrent(current);
      setPersonaArtifacts(artifacts);
      setPersonaCapabilities(capabilities);
      setPersonaError(null);
    } catch (caught) {
      if (generation !== personaRequestGenerationRef.current) return;
      setPersonaError(errorMessage(caught));
    } finally {
      if (generation === personaRequestGenerationRef.current) setPersonaLoading(false);
    }
  }

  async function runPersonaMutation(
    operation: () => Promise<unknown>,
  ) {
    const generation = ++personaRequestGenerationRef.current;
    setPersonaLoading(true);
    setPersonaError(null);
    try {
      await operation();
      if (generation !== personaRequestGenerationRef.current) return;
      const [current, artifacts, capabilities] = await Promise.all([
        apiClient.getCurrentPersona(),
        apiClient.listPersonaArtifacts(),
        apiClient.getPersonaCapabilities(),
      ]);
      if (generation !== personaRequestGenerationRef.current) return;
      setPersonaCurrent(current);
      setPersonaArtifacts(artifacts);
      setPersonaCapabilities(capabilities);
    } catch (caught) {
      if (generation !== personaRequestGenerationRef.current) return;
      setPersonaError(errorMessage(caught));
      try {
        const [current, artifacts, capabilities] = await Promise.all([
          apiClient.getCurrentPersona(),
          apiClient.listPersonaArtifacts(),
          apiClient.getPersonaCapabilities(),
        ]);
        if (generation !== personaRequestGenerationRef.current) return;
        setPersonaCurrent(current);
        setPersonaArtifacts(artifacts);
        setPersonaCapabilities(capabilities);
      } catch {
        // Preserve the mutation error while best-effort conflict refresh fails.
      }
    } finally {
      if (generation === personaRequestGenerationRef.current) setPersonaLoading(false);
    }
  }

  async function handleCreatePersona(request: PersonaCreateRequest) {
    await runPersonaMutation(() => apiClient.createPersonaArtifact(request));
  }

  async function handleActivatePersona(request: PersonaActivateRequest) {
    await runPersonaMutation(() => apiClient.activatePersona(request));
  }

  async function handleRedactPersona(
    artifactId: string,
    request: PersonaRedactRequest,
  ) {
    await runPersonaMutation(() => apiClient.redactPersonaArtifact(artifactId, request));
  }

  async function fetchSummaryState() {
    const [capabilities, processingConsent, injectionConsent, status, summaryPage, jobPage, auditPage] = await Promise.all([
      apiClient.getSummaryCapabilities(),
      apiClient.getSummaryProcessingConsent(),
      apiClient.getSummaryInjectionConsent(),
      apiClient.getSummaryStatus(),
      apiClient.listSummaries({ limit: 100 }),
      apiClient.listSummaryJobs({ limit: 100 }),
      apiClient.listSummaryAudits({ limit: 100 }),
    ]);
    return { capabilities, processingConsent, injectionConsent, status, summaryPage, jobPage, auditPage };
  }

  function applySummaryState(state: Awaited<ReturnType<typeof fetchSummaryState>>) {
    setSummaryCapabilities(state.capabilities);
    setSummaryProcessingConsent(state.processingConsent);
    setSummaryInjectionConsent(state.injectionConsent);
    setSummaryStatus(state.status);
    setSummaries(state.summaryPage.items);
    setSummaryJobs(state.jobPage.items);
    setSummaryAudits(state.auditPage.items);
  }

  async function loadSummaries() {
    const requestGeneration = ++summaryRequestGenerationRef.current;
    const mutationGeneration = summaryMutationGenerationRef.current;
    setSummaryLoading(true);
    try {
      const state = await fetchSummaryState();
      if (
        requestGeneration !== summaryRequestGenerationRef.current ||
        mutationGeneration !== summaryMutationGenerationRef.current
      ) return;
      applySummaryState(state);
      setSummaryError(null);
    } catch (caught) {
      if (
        requestGeneration === summaryRequestGenerationRef.current &&
        mutationGeneration === summaryMutationGenerationRef.current
      ) setSummaryError(errorMessage(caught));
    } finally {
      if (requestGeneration === summaryRequestGenerationRef.current) {
        setSummaryLoading(false);
      }
    }
  }

  async function runSummaryMutation(operation: () => Promise<unknown>) {
    const mutationGeneration = ++summaryMutationGenerationRef.current;
    summaryRequestGenerationRef.current += 1;
    setSummaryLoading(true);
    setSummaryError(null);
    try {
      await operation();
      if (mutationGeneration !== summaryMutationGenerationRef.current) return;
      const state = await fetchSummaryState();
      if (mutationGeneration !== summaryMutationGenerationRef.current) return;
      applySummaryState(state);
    } catch (caught) {
      if (mutationGeneration !== summaryMutationGenerationRef.current) return;
      setSummaryError(errorMessage(caught));
      try {
        const state = await fetchSummaryState();
        if (mutationGeneration !== summaryMutationGenerationRef.current) return;
        applySummaryState(state);
      } catch {
        // Preserve the mutation error while best-effort conflict refresh fails.
      }
    } finally {
      if (mutationGeneration === summaryMutationGenerationRef.current) {
        setSummaryLoading(false);
      }
    }
  }

  async function handleUpdateSummaryProcessing(request: SummaryAuthorityMutationRequest) {
    await runSummaryMutation(() => apiClient.updateSummaryProcessingConsent(request));
  }

  async function handleUpdateSummaryInjection(request: SummaryAuthorityMutationRequest) {
    await runSummaryMutation(() => apiClient.updateSummaryInjectionConsent(request));
  }

  async function handleRedactSummary(summaryId: string, request: SummaryRedactRequest) {
    await runSummaryMutation(() => apiClient.redactSummary(summaryId, request));
  }

  async function handleRebuildSummary(summaryId: string, request: SummaryRebuildRequest) {
    await runSummaryMutation(() => apiClient.rebuildSummary(summaryId, request));
  }

  async function handleRetrySummaryJob(jobId: string, request: SummaryJobMutationRequest) {
    await runSummaryMutation(() => apiClient.retrySummaryJob(jobId, request));
  }

  async function handleCancelSummaryJob(jobId: string, request: SummaryJobMutationRequest) {
    await runSummaryMutation(() => apiClient.cancelSummaryJob(jobId, request));
  }

  async function fetchRelationshipState() {
    const [capabilities, projection, eventPage, jobPage, auditPage] = await Promise.all([
      apiClient.getRelationshipCapabilities(),
      apiClient.getRelationshipProjection(),
      apiClient.listRelationshipEvents({ limit: 100 }),
      apiClient.listRelationshipJobs({ limit: 100 }),
      apiClient.listRelationshipAudits({ limit: 100 }),
    ]);
    return { capabilities, projection, eventPage, jobPage, auditPage };
  }

  function applyRelationshipState(state: Awaited<ReturnType<typeof fetchRelationshipState>>) {
    setRelationshipCapabilities(state.capabilities);
    setRelationshipProjection(state.projection);
    setRelationshipEvents(state.eventPage.items);
    setRelationshipJobs(state.jobPage.items);
    setRelationshipAudits(state.auditPage.items);
  }

  async function loadRelationshipState() {
    const requestGeneration = ++relationshipRequestGenerationRef.current;
    const mutationGeneration = relationshipMutationGenerationRef.current;
    setRelationshipLoading(true);
    try {
      const state = await fetchRelationshipState();
      if (
        requestGeneration !== relationshipRequestGenerationRef.current ||
        mutationGeneration !== relationshipMutationGenerationRef.current
      ) return;
      applyRelationshipState(state);
      setRelationshipError(null);
    } catch (caught) {
      if (
        requestGeneration === relationshipRequestGenerationRef.current &&
        mutationGeneration === relationshipMutationGenerationRef.current
      ) setRelationshipError(errorMessage(caught));
    } finally {
      if (requestGeneration === relationshipRequestGenerationRef.current) {
        setRelationshipLoading(false);
      }
    }
  }

  async function runRelationshipMutation(operation: () => Promise<unknown>) {
    const mutationGeneration = ++relationshipMutationGenerationRef.current;
    relationshipRequestGenerationRef.current += 1;
    setRelationshipLoading(true);
    setRelationshipError(null);
    try {
      await operation();
      if (mutationGeneration !== relationshipMutationGenerationRef.current) return;
      const state = await fetchRelationshipState();
      if (mutationGeneration !== relationshipMutationGenerationRef.current) return;
      applyRelationshipState(state);
    } catch (caught) {
      if (mutationGeneration !== relationshipMutationGenerationRef.current) return;
      setRelationshipError(errorMessage(caught));
      try {
        const state = await fetchRelationshipState();
        if (mutationGeneration !== relationshipMutationGenerationRef.current) return;
        applyRelationshipState(state);
      } catch {
        // Preserve the mutation error while best-effort conflict refresh fails.
      }
    } finally {
      if (mutationGeneration === relationshipMutationGenerationRef.current) {
        setRelationshipLoading(false);
      }
    }
  }

  async function handleRelationshipReconcile(request: RelationshipReconcileRequest) {
    await runRelationshipMutation(() => apiClient.reconcileRelationship(request));
  }

  async function handleRelationshipRebuild(request: RelationshipReconcileRequest) {
    await runRelationshipMutation(() => apiClient.rebuildRelationship(request));
  }

  async function handleRelationshipSuppress(
    applyEventId: string,
    request: RelationshipSuppressRequest,
  ) {
    await runRelationshipMutation(() => apiClient.suppressRelationshipApply(applyEventId, request));
  }

  async function handleRelationshipRedact(
    applyEventId: string,
    request: RelationshipRedactRequest,
  ) {
    await runRelationshipMutation(() => apiClient.redactRelationshipApply(applyEventId, request));
  }

  async function handleRelationshipReenable(
    sourceMemoryId: string,
    eventType: string,
    subjectCode: string,
    request: RelationshipReenableRequest,
  ) {
    await runRelationshipMutation(() => apiClient.reenableRelationshipAuthority(
      sourceMemoryId,
      eventType,
      subjectCode,
      request,
    ));
  }

  async function loadEmotion() {
    const generation = ++emotionRequestGenerationRef.current;
    const consentGeneration = emotionConsentGenerationRef.current;
    setEmotionLoading(true);
    try {
      const [state, events, analysisConsent, analysisAudits] = await Promise.all([
        apiClient.getEmotionState(),
        apiClient.listEmotionEvents(),
        apiClient.getEmotionAnalysisConsent(),
        apiClient.listEmotionAnalysisAudits(),
      ]);
      if (generation !== emotionRequestGenerationRef.current) return;
      setEmotionState((current) => current && current.version > state.version ? current : state);
      setEmotionEvents(events);
      if (consentGeneration === emotionConsentGenerationRef.current) {
        setEmotionAnalysisConsent(analysisConsent);
      }
      setEmotionAnalysisAudits(analysisAudits);
      setEmotionError(null);
    } catch (caught) {
      if (generation !== emotionRequestGenerationRef.current) return;
      setEmotionError(errorMessage(caught));
    } finally {
      if (generation === emotionRequestGenerationRef.current) setEmotionLoading(false);
    }
  }

  useEffect(() => {
    void loadSessions();
    if (import.meta.env.MODE !== 'test' || import.meta.env.VITE_ENABLE_MEMORY_LOAD_IN_TEST === '1') {
      void loadMemories();
      void loadMemoryCandidates();
      if (import.meta.env.MODE !== 'test' || import.meta.env.VITE_ENABLE_GATE_B_MEMORY_LOAD_IN_TEST === '1') {
        void loadMemoryGateB();
      }
    }
    if (import.meta.env.MODE !== 'test' || import.meta.env.VITE_ENABLE_PERSONA_LOAD_IN_TEST === '1') {
      void loadPersona();
    }
    if (import.meta.env.MODE !== 'test' || import.meta.env.VITE_ENABLE_SUMMARY_LOAD_IN_TEST === '1') {
      void loadSummaries();
    }
    if (import.meta.env.MODE !== 'test' || import.meta.env.VITE_ENABLE_EMOTION_LOAD_IN_TEST === '1') {
      void loadEmotion();
    }
    if (import.meta.env.MODE !== 'test' || import.meta.env.VITE_ENABLE_RELATIONSHIP_LOAD_IN_TEST === '1') {
      void loadRelationshipState();
    }
  }, []);

  useEffect(() => {
    if (activeSessionId) {
      void loadMessages(activeSessionId);
    } else {
      setMessages([]);
    }
  }, [activeSessionId]);

  useEffect(() => {
    activeSessionIdRef.current = activeSessionId;
  }, [activeSessionId]);

  async function handleCreateSession() {
    voiceTurnGenerationRef.current += 1;
    textSendGenerationRef.current += 1;
    messageLoadGenerationRef.current += 1;
    voiceTurnInFlightRef.current = false;
    setLoading(true);
    try {
      const session = await apiClient.createSession('新会话');
      audioController.reset('interrupted');
      expressionPreview.clear();
      resetVoiceState();
      activeSessionIdRef.current = session.id;
      setSessions((current) => [session, ...current]);
      setActiveSessionId(session.id);
      setMessages([]);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  function handleSelectSession(sessionId: string) {
    voiceTurnGenerationRef.current += 1;
    textSendGenerationRef.current += 1;
    messageLoadGenerationRef.current += 1;
    voiceTurnInFlightRef.current = false;
    activeSessionIdRef.current = sessionId;
    audioController.reset('interrupted');
    expressionPreview.clear();
    resetVoiceState();
    setActiveSessionId(sessionId);
  }

  async function handleDeleteSession(sessionId: string) {
    voiceTurnGenerationRef.current += 1;
    textSendGenerationRef.current += 1;
    messageLoadGenerationRef.current += 1;
    voiceTurnInFlightRef.current = false;
    if (activeSessionId === sessionId) {
      activeSessionIdRef.current = null;
    }
    setLoading(true);
    try {
      await apiClient.deleteSession(sessionId);
      expressionPreview.dropSession(sessionId);
      audioController.reset('interrupted');
      if (activeSessionId === sessionId) expressionPreview.clear();
      resetVoiceState();
      setSessions((current) => current.filter((session) => session.id !== sessionId));
      if (activeSessionId === sessionId) {
        setActiveSessionId(null);
        setMessages([]);
      }
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  async function handleSendMessage(content: string) {
    const sessionId = activeSessionId;
    if (!sessionId) return;
    const generation = ++textSendGenerationRef.current;
    setLoading(true);
    setError(null);
    try {
      const chatResponse = await apiClient.sendMessage(sessionId, content);
      const [updatedSessions, updatedMessages] = await Promise.all([
        apiClient.listSessions(),
        apiClient.listMessages(sessionId),
      ]);
      if (
        generation !== textSendGenerationRef.current ||
        activeSessionIdRef.current !== sessionId
      ) return;
      setSessions(updatedSessions);
      setMessages(updatedMessages);
      expressionPreview.selectAssistantMessage(
        sessionId,
        chatResponse.assistant_message_id,
      );
      refreshAutomaticMemoryAfterTurn();
      void loadEmotion();
    } catch (caught) {
      if (
        generation === textSendGenerationRef.current &&
        activeSessionIdRef.current === sessionId
      ) setError(errorMessage(caught));
    } finally {
      if (
        generation === textSendGenerationRef.current &&
        activeSessionIdRef.current === sessionId
      ) setLoading(false);
    }
  }

  async function handleCreateMemory(request: CreateMemoryRequest) {
    setMemoryLoading(true);
    setMemoryError(null);
    try {
      const response = await apiClient.createMemory(request);
      setMemoryConflicts(response.conflicts);
      setMemories((current) => [response.memory, ...current]);
    } catch (caught) {
      setMemoryError(errorMessage(caught));
    } finally {
      setMemoryLoading(false);
    }
  }

  async function handleUpdateMemory(memoryId: string, request: UpdateMemoryRequest) {
    setMemoryLoading(true);
    setMemoryError(null);
    try {
      const response = await apiClient.updateMemory(memoryId, request);
      setMemoryConflicts(response.conflicts);
      setMemories((current) => current.map((memory) => memory.id === memoryId ? response.memory : memory));
    } catch (caught) {
      setMemoryError(errorMessage(caught));
      throw caught;
    } finally {
      setMemoryLoading(false);
    }
  }

  async function handleDeleteMemory(memoryId: string) {
    setMemoryLoading(true);
    setMemoryError(null);
    try {
      await apiClient.deleteMemory(memoryId);
      setMemoryConflicts([]);
      setMemories((current) => current.filter((memory) => memory.id !== memoryId));
    } catch (caught) {
      setMemoryError(errorMessage(caught));
    } finally {
      setMemoryLoading(false);
    }
  }

  async function handleConfirmMemoryCandidate(
    memoryId: string,
    subjectCode?: RelationshipSubjectCode | null,
  ) {
    setMemoryLoading(true);
    setMemoryError(null);
    try {
      const response = await apiClient.confirmMemoryCandidate(memoryId, subjectCode);
      setMemoryConflicts(response.conflicts);
      setMemoryCandidates((current) => current.filter((memory) => memory.id !== memoryId));
      setMemories((current) => [response.memory, ...current.filter((memory) => memory.id !== response.memory.id)]);
      if (relationshipCapabilities !== null) void loadRelationshipState();
    } catch (caught) {
      setMemoryError(errorMessage(caught));
    } finally {
      setMemoryLoading(false);
    }
  }

  async function handleDismissMemoryCandidate(memoryId: string) {
    setMemoryLoading(true);
    setMemoryError(null);
    try {
      await apiClient.dismissMemoryCandidate(memoryId);
      setMemoryCandidates((current) => current.filter((memory) => memory.id !== memoryId));
    } catch (caught) {
      setMemoryError(errorMessage(caught));
    } finally {
      setMemoryLoading(false);
    }
  }

  async function handleArchiveMemory(memoryId: string) {
    setMemoryLoading(true);
    setMemoryError(null);
    try {
      await apiClient.archiveMemory(memoryId);
      setMemories((current) => current.filter((memory) => memory.id !== memoryId));
      setGateBMemoryConflicts((current) => current.filter(
        (conflict) => conflict.left_memory_id !== memoryId && conflict.right_memory_id !== memoryId,
      ));
    } catch (caught) {
      setMemoryError(errorMessage(caught));
    } finally {
      setMemoryLoading(false);
    }
  }

  async function handleForgetMemory(memoryId: string) {
    setMemoryLoading(true);
    setMemoryError(null);
    try {
      await apiClient.forgetMemory(memoryId);
      await refreshMemoryCollections();
    } catch (caught) {
      setMemoryError(errorMessage(caught));
    } finally {
      setMemoryLoading(false);
    }
  }

  async function handleUndoLatestAutoMemory(memoryId: string) {
    setMemoryLoading(true);
    setMemoryError(null);
    try {
      await apiClient.undoLatestAutoMemory(memoryId);
      await refreshMemoryCollections();
    } catch (caught) {
      setMemoryError(errorMessage(caught));
      try {
        await refreshMemoryCollections();
      } catch {
        // Preserve the mutation error; a failed refresh must not replace it.
      }
    } finally {
      setMemoryLoading(false);
    }
  }

  async function handleResolveMemoryConflict(conflictId: string, request: MemoryConflictResolutionRequest) {
    setMemoryLoading(true);
    setMemoryError(null);
    try {
      await apiClient.resolveMemoryConflict(conflictId, request);
      await refreshMemoryCollections();
    } catch (caught) {
      setMemoryError(errorMessage(caught));
    } finally {
      setMemoryLoading(false);
    }
  }

  async function handleUpdateMemoryWriteConsent(action: MemoryWriteConsentAction) {
    const generation = ++memoryConsentGenerationRef.current;
    setMemoryGateBLoading(true);
    setMemoryError(null);
    try {
      const updated = await apiClient.updateMemoryWriteConsent(action);
      if (generation === memoryConsentGenerationRef.current) {
        setMemoryWriteConsent(updated);
      }
    } catch (caught) {
      if (generation === memoryConsentGenerationRef.current) {
        setMemoryError(errorMessage(caught));
      }
    } finally {
      if (generation === memoryConsentGenerationRef.current) setMemoryGateBLoading(false);
    }
  }

  function loadMemoryVersions(memoryId: string, cursor?: string | null): Promise<MemoryVersionPage> {
    return apiClient.listMemoryVersions(memoryId, cursor);
  }

  function loadMemoryEvidence(memoryId: string, cursor?: string | null): Promise<MemoryEvidencePage> {
    return apiClient.listMemoryEvidence(memoryId, cursor);
  }

  async function runEmotionStateMutation(mutate: () => Promise<EmotionState>) {
    emotionRequestGenerationRef.current += 1;
    setEmotionLoading(true);
    setEmotionError(null);
    try {
      setEmotionState(await mutate());
      setEmotionEvents(await apiClient.listEmotionEvents());
    } catch (caught) {
      setEmotionError(errorMessage(caught));
    } finally {
      setEmotionLoading(false);
    }
  }

  async function handleSetEmotionEnabled(enabled: boolean) {
    await runEmotionStateMutation(() => apiClient.updateEmotionSettings(enabled));
  }

  async function handleResetEmotion() {
    await runEmotionStateMutation(() => apiClient.resetEmotion());
  }

  async function refreshEmotionAnalysisAudits() {
    const generation = ++emotionAuditGenerationRef.current;
    setEmotionAuditLoading(true);
    setEmotionError(null);
    try {
      const audits = await apiClient.listEmotionAnalysisAudits();
      if (generation === emotionAuditGenerationRef.current) {
        setEmotionAnalysisAudits(audits);
      }
    } catch (caught) {
      if (generation === emotionAuditGenerationRef.current) {
        setEmotionError(errorMessage(caught));
      }
    } finally {
      if (generation === emotionAuditGenerationRef.current) {
        setEmotionAuditLoading(false);
      }
    }
  }

  async function handleUpdateEmotionAnalysisConsent(action: EmotionAnalysisConsentAction) {
    emotionConsentGenerationRef.current += 1;
    setEmotionConsentLoading(true);
    setEmotionError(null);
    try {
      const updated = await apiClient.updateEmotionAnalysisConsent(action);
      emotionConsentGenerationRef.current += 1;
      setEmotionAnalysisConsent(updated);
      setEmotionAnalysisAudits(await apiClient.listEmotionAnalysisAudits());
    } catch (caught) {
      setEmotionError(errorMessage(caught));
    } finally {
      setEmotionConsentLoading(false);
    }
  }

  async function handleSendAndSpeakTranscript(transcript: string) {
    const sessionId = activeSessionId;
    const cleanTranscript = transcript.trim();
    if (!sessionId || !cleanTranscript) return;
    if (voiceTurnInFlightRef.current) return;
    if (voiceTurnStatus === 'sending_chat' || voiceTurnStatus === 'synthesizing_or_playing') return;

    voiceTurnInFlightRef.current = true;
    voiceTurnGenerationRef.current += 1;
    const generation = voiceTurnGenerationRef.current;
    setLoading(true);
    setError(null);
    setVoiceTurnError(null);
    setVoiceTurnStatus('sending_chat');

    try {
      const chatResponse = await apiClient.sendMessage(sessionId, cleanTranscript);
      const [updatedSessions, updatedMessages] = await Promise.all([
        apiClient.listSessions(),
        apiClient.listMessages(sessionId),
      ]);

      if (!isCurrentVoiceTurn(sessionId, generation)) return;

      setSessions(updatedSessions);
      setMessages(updatedMessages);
      setPendingTranscript(null);
      recorder.clearResult();
      expressionPreview.selectAssistantMessage(
        sessionId,
        chatResponse.assistant_message_id,
      );
      refreshAutomaticMemoryAfterTurn();
      if (import.meta.env.MODE !== 'test' || import.meta.env.VITE_ENABLE_EMOTION_LOAD_IN_TEST === '1') {
        void loadEmotion();
      }

      setVoiceTurnStatus('synthesizing_or_playing');
      const played = await audioController.play(chatResponse.assistant_message_id, {
        streaming: true,
      });
      if (!isCurrentVoiceTurn(sessionId, generation)) return;

      if (!played) {
        setVoiceTurnStatus('error');
        setVoiceTurnError('文字回复已生成，但语音合成或播放失败。可稍后重试播放。');
        return;
      }

      setVoiceTurnStatus('idle');
    } catch (caught) {
      if (!isCurrentVoiceTurn(sessionId, generation)) return;
      setVoiceTurnStatus('error');
      setError(errorMessage(caught));
    } finally {
      if (voiceTurnGenerationRef.current === generation) {
        voiceTurnInFlightRef.current = false;
      }
      if (isCurrentVoiceTurn(sessionId, generation)) {
        setLoading(false);
      }
    }
  }

  const isVoiceTurnSendingChat = voiceTurnStatus === 'sending_chat';
  const isVoiceTurnSynthesizingOrPlaying = voiceTurnStatus === 'synthesizing_or_playing';
  const recorderDisabled =
    !activeSessionId ||
    isVoiceTurnSendingChat ||
    (loading && !isVoiceTurnSynthesizingOrPlaying);
  const recorderHintMessage = audioController.isAudioBusy || isVoiceTurnSynthesizingOrPlaying
    ? '点击开始录音会停止当前朗读'
    : null;
  const expressionPreviewLabel = useMemo(() => {
    const assistantMessageId = expressionPreview.state.selectedAssistantMessageId;
    return assistantMessageId
      ? displayLabelForAssistantMessage(messages, assistantMessageId)
      : '助手消息';
  }, [expressionPreview.state.selectedAssistantMessageId, messages]);

  return (
    <ChatLayout
      sessions={sessions}
      activeSessionId={activeSessionId}
      messages={messages}
      loading={loading}
      error={error}
      expressionPreviewState={expressionPreview.state}
      expressionPreviewLabel={expressionPreviewLabel}
      memories={memories}
      memoryCandidates={memoryCandidates}
      memoryLoading={memoryLoading || memoryGateBLoading}
      memoryError={memoryError}
      memoryConflicts={memoryConflicts}
      gateBMemoryConflicts={gateBMemoryConflicts}
      memoryWriteConsent={memoryWriteConsent}
      latestMemoryJob={latestMemoryJob}
      personaCurrent={personaCurrent}
      personaArtifacts={personaArtifacts}
      personaCapabilities={personaCapabilities}
      personaLoading={personaLoading}
      personaError={personaError}
      onRetryPersona={loadPersona}
      onCreatePersona={handleCreatePersona}
      onActivatePersona={handleActivatePersona}
      onRedactPersona={handleRedactPersona}
      summaryCapabilities={summaryCapabilities}
      summaryProcessingConsent={summaryProcessingConsent}
      summaryInjectionConsent={summaryInjectionConsent}
      summaryStatus={summaryStatus}
      summaries={summaries}
      summaryJobs={summaryJobs}
      summaryAudits={summaryAudits}
      summaryLoading={summaryLoading}
      summaryError={summaryError}
      onRetrySummaries={loadSummaries}
      onUpdateSummaryProcessing={handleUpdateSummaryProcessing}
      onUpdateSummaryInjection={handleUpdateSummaryInjection}
      onRedactSummary={handleRedactSummary}
      onRebuildSummary={handleRebuildSummary}
      onRetrySummaryJob={handleRetrySummaryJob}
      onCancelSummaryJob={handleCancelSummaryJob}
      emotionState={emotionState}
      emotionEvents={emotionEvents}
      emotionLoading={emotionLoading}
      emotionError={emotionError}
      emotionAnalysisConsent={emotionAnalysisConsent}
      emotionAnalysisAudits={emotionAnalysisAudits}
      emotionAnalysisConsentLoading={emotionConsentLoading}
      emotionAnalysisAuditLoading={emotionAuditLoading}
      onSetEmotionEnabled={handleSetEmotionEnabled}
      onResetEmotion={handleResetEmotion}
      onRetryEmotion={loadEmotion}
      onUpdateEmotionAnalysisConsent={handleUpdateEmotionAnalysisConsent}
      onRefreshEmotionAnalysisAudits={refreshEmotionAnalysisAudits}
      relationshipCapabilities={relationshipCapabilities}
      relationshipProjection={relationshipProjection}
      relationshipEvents={relationshipEvents}
      relationshipJobs={relationshipJobs}
      relationshipAudits={relationshipAudits}
      relationshipLoading={relationshipLoading}
      relationshipError={relationshipError}
      onRetryRelationship={loadRelationshipState}
      onReconcileRelationship={handleRelationshipReconcile}
      onRebuildRelationship={handleRelationshipRebuild}
      onSuppressRelationshipApply={handleRelationshipSuppress}
      onRedactRelationshipApply={handleRelationshipRedact}
      onReenableRelationshipAuthority={handleRelationshipReenable}
      audioController={audioController}
      audioInputDevices={audioInputDevices}
      audioOutputDevices={audioOutputDevices}
      recorder={{
        ...recorder,
        startRecording: handleStartRecording,
        stopRecording: handleStopRecording,
      }}
      pendingTranscript={pendingTranscript}
      playbackBlocked={recorder.isPlaybackBlocked}
      recorderDisabled={recorderDisabled}
      onCreateSession={handleCreateSession}
      onSelectSession={handleSelectSession}
      onDeleteSession={handleDeleteSession}
      onSendMessage={handleSendMessage}
      onCreateMemory={handleCreateMemory}
      onUpdateMemory={handleUpdateMemory}
      onDeleteMemory={handleDeleteMemory}
      onArchiveMemory={handleArchiveMemory}
      onForgetMemory={handleForgetMemory}
      onUndoLatestAutoMemory={handleUndoLatestAutoMemory}
      onUpdateMemoryWriteConsent={handleUpdateMemoryWriteConsent}
      onResolveMemoryConflict={handleResolveMemoryConflict}
      loadMemoryVersions={loadMemoryVersions}
      loadMemoryEvidence={loadMemoryEvidence}
      onConfirmMemoryCandidate={handleConfirmMemoryCandidate}
      onDismissMemoryCandidate={handleDismissMemoryCandidate}
      onSendAndSpeakTranscript={handleSendAndSpeakTranscript}
      voiceTurnBusy={voiceTurnStatus === 'sending_chat' || voiceTurnStatus === 'synthesizing_or_playing'}
      voiceTurnError={voiceTurnError}
      vadStatusMessage={vadAutoStop.message}
      recorderHintMessage={recorderHintMessage}
      onDismissError={() => setError(null)}
      onClearPendingTranscript={handleClearPendingTranscript}
    />
  );
}
