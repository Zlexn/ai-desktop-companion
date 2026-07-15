import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { displayLabelForAssistantMessage } from './expression/displayLabel';
import { apiClient } from './api/client';
import type { CreateMemoryRequest, EmotionAnalysisAudit, EmotionAnalysisConsent, EmotionAnalysisConsentAction, EmotionEvent, EmotionState, MemoryRecord, Message, Session, UpdateMemoryRequest } from './api/types';
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
  const [memoryError, setMemoryError] = useState<string | null>(null);
  const [memoryConflicts, setMemoryConflicts] = useState<MemoryRecord[]>([]);
  const [emotionState, setEmotionState] = useState<EmotionState | null>(null);
  const [emotionEvents, setEmotionEvents] = useState<EmotionEvent[]>([]);
  const [emotionAnalysisConsent, setEmotionAnalysisConsent] = useState<EmotionAnalysisConsent | null>(null);
  const [emotionAnalysisAudits, setEmotionAnalysisAudits] = useState<EmotionAnalysisAudit[]>([]);
  const [emotionLoading, setEmotionLoading] = useState(false);
  const [emotionConsentLoading, setEmotionConsentLoading] = useState(false);
  const [emotionAuditLoading, setEmotionAuditLoading] = useState(false);
  const [emotionError, setEmotionError] = useState<string | null>(null);
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
    }
    if (import.meta.env.MODE !== 'test' || import.meta.env.VITE_ENABLE_EMOTION_LOAD_IN_TEST === '1') {
      void loadEmotion();
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
      void loadMemoryCandidates();
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

  async function handleConfirmMemoryCandidate(memoryId: string) {
    setMemoryLoading(true);
    setMemoryError(null);
    try {
      const response = await apiClient.confirmMemoryCandidate(memoryId);
      setMemoryConflicts(response.conflicts);
      setMemoryCandidates((current) => current.filter((memory) => memory.id !== memoryId));
      setMemories((current) => [response.memory, ...current.filter((memory) => memory.id !== response.memory.id)]);
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
      if (import.meta.env.MODE !== 'test' || import.meta.env.VITE_ENABLE_EMOTION_LOAD_IN_TEST === '1') {
        void loadEmotion();
      }

      setVoiceTurnStatus('synthesizing_or_playing');
      const played = await audioController.play(chatResponse.assistant_message_id, {
        streaming: true,
      });
      void loadMemoryCandidates();
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
      memoryLoading={memoryLoading}
      memoryError={memoryError}
      memoryConflicts={memoryConflicts}
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
