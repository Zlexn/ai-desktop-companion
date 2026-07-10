import { useCallback, useEffect, useRef, useState } from 'react';
import { apiClient } from './api/client';
import type { CreateMemoryRequest, MemoryRecord, Message, Session, UpdateMemoryRequest } from './api/types';
import { ChatLayout } from './components/ChatLayout';
import { useAudioPlaybackController } from './hooks/useAudioPlaybackController';
import { useAudioInputDevices } from './hooks/useAudioInputDevices';
import { useAudioOutputDevices } from './hooks/useAudioOutputDevices';
import { useManualAudioRecorder } from './hooks/useManualAudioRecorder';
import { useVadAutoStop } from './hooks/useVadAutoStop';
import { findAssistantReplyForVoiceTurn } from './voiceTurn';

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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const audioOutputDevices = useAudioOutputDevices();
  const audioController = useAudioPlaybackController({ audioOutputDeviceId: audioOutputDevices.selectedDeviceId });
  const audioInputDevices = useAudioInputDevices();
  const recorder = useManualAudioRecorder({ audioInputDeviceId: audioInputDevices.selectedDeviceId });
  const [pendingTranscript, setPendingTranscript] = useState<string | null>(null);
  const [voiceTurnStatus, setVoiceTurnStatus] = useState<'idle' | 'sending_chat' | 'synthesizing_or_playing' | 'error'>('idle');
  const [voiceTurnError, setVoiceTurnError] = useState<string | null>(null);
  const activeSessionIdRef = useRef<string | null>(activeSessionId);
  const voiceTurnGenerationRef = useRef(0);
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

    audioController.reset();
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
    setLoading(true);
    try {
      setMessages(await apiClient.listMessages(sessionId));
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
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

  useEffect(() => {
    void loadSessions();
    if (import.meta.env.MODE !== 'test' || import.meta.env.VITE_ENABLE_MEMORY_LOAD_IN_TEST === '1') {
      void loadMemories();
      void loadMemoryCandidates();
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
    voiceTurnInFlightRef.current = false;
    setLoading(true);
    try {
      const session = await apiClient.createSession('新会话');
      audioController.reset();
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
    voiceTurnInFlightRef.current = false;
    activeSessionIdRef.current = sessionId;
    audioController.reset();
    resetVoiceState();
    setActiveSessionId(sessionId);
  }

  async function handleDeleteSession(sessionId: string) {
    voiceTurnGenerationRef.current += 1;
    voiceTurnInFlightRef.current = false;
    if (activeSessionId === sessionId) {
      activeSessionIdRef.current = null;
    }
    setLoading(true);
    try {
      await apiClient.deleteSession(sessionId);
      audioController.reset();
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
    if (!activeSessionId) return;
    setLoading(true);
    setError(null);
    try {
      await apiClient.sendMessage(activeSessionId, content);
      const [updatedSessions, updatedMessages] = await Promise.all([
        apiClient.listSessions(),
        apiClient.listMessages(activeSessionId),
      ]);
      setSessions(updatedSessions);
      setMessages(updatedMessages);
      void loadMemoryCandidates();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
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

  async function handleSendAndSpeakTranscript(transcript: string) {
    const sessionId = activeSessionId;
    const cleanTranscript = transcript.trim();
    if (!sessionId || !cleanTranscript) return;
    if (voiceTurnInFlightRef.current) return;
    if (voiceTurnStatus === 'sending_chat' || voiceTurnStatus === 'synthesizing_or_playing') return;

    voiceTurnInFlightRef.current = true;
    voiceTurnGenerationRef.current += 1;
    const generation = voiceTurnGenerationRef.current;
    const beforeMessages = messages;
    setLoading(true);
    setError(null);
    setVoiceTurnError(null);
    setVoiceTurnStatus('sending_chat');

    try {
      await apiClient.sendMessage(sessionId, cleanTranscript);
      const [updatedSessions, updatedMessages] = await Promise.all([
        apiClient.listSessions(),
        apiClient.listMessages(sessionId),
      ]);

      if (!isCurrentVoiceTurn(sessionId, generation)) return;

      setSessions(updatedSessions);
      setMessages(updatedMessages);
      setPendingTranscript(null);
      recorder.clearResult();

      const assistantMessage = findAssistantReplyForVoiceTurn({
        before: beforeMessages,
        after: updatedMessages,
        transcript: cleanTranscript,
        sessionId,
      });

      if (!assistantMessage) {
        setVoiceTurnStatus('error');
        setVoiceTurnError('文字回复已生成，但没有找到对应的语音回复，请使用消息上的播放按钮。');
        return;
      }

      setVoiceTurnStatus('synthesizing_or_playing');
      const played = await audioController.play(assistantMessage.id, assistantMessage.content, { streaming: true });
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

  return (
    <ChatLayout
      sessions={sessions}
      activeSessionId={activeSessionId}
      messages={messages}
      loading={loading}
      error={error}
      memories={memories}
      memoryCandidates={memoryCandidates}
      memoryLoading={memoryLoading}
      memoryError={memoryError}
      memoryConflicts={memoryConflicts}
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
