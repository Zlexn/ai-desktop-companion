import type { CreateMemoryRequest, EmotionAnalysisAudit, EmotionAnalysisConsent, EmotionAnalysisConsentAction, EmotionEvent, EmotionState, MemoryRecord, Message, Session, UpdateMemoryRequest } from '../api/types';
import type { ExpressionPreviewState } from '../expression/previewReducer';
import type { UseAudioInputDevicesResult } from '../hooks/useAudioInputDevices';
import type { UseAudioOutputDevicesResult } from '../hooks/useAudioOutputDevices';
import type { useAudioPlaybackController } from '../hooks/useAudioPlaybackController';
import type { UseManualAudioRecorderResult } from '../hooks/useManualAudioRecorder';
import { ErrorBanner } from './ErrorBanner';
import { ExpressionPreview } from './ExpressionPreview';
import { PresentationErrorBoundary } from './PresentationErrorBoundary';
import { EmotionPanel } from './EmotionPanel';
import { MemoryPanel } from './MemoryPanel';
import { MessageInput } from './MessageInput';
import { MessageList } from './MessageList';
import { SessionList } from './SessionList';
import { VoiceRecorder } from './VoiceRecorder';

interface ChatLayoutProps {
  sessions: Session[];
  activeSessionId: string | null;
  messages: Message[];
  loading: boolean;
  error: string | null;
  expressionPreviewState: ExpressionPreviewState;
  expressionPreviewLabel: string;
  audioController: ReturnType<typeof useAudioPlaybackController>;
  audioInputDevices: UseAudioInputDevicesResult;
  audioOutputDevices: UseAudioOutputDevicesResult;
  recorder: UseManualAudioRecorderResult;
  pendingTranscript: string | null;
  playbackBlocked: boolean;
  recorderDisabled: boolean;
  onCreateSession: () => void;
  onSelectSession: (sessionId: string) => void;
  onDeleteSession: (sessionId: string) => void;
  onSendMessage: (content: string) => Promise<void>;
  onSendAndSpeakTranscript: (transcript: string) => Promise<void>;
  voiceTurnBusy: boolean;
  voiceTurnError: string | null;
  vadStatusMessage: string | null;
  recorderHintMessage: string | null;
  memories: MemoryRecord[];
  memoryCandidates: MemoryRecord[];
  memoryLoading: boolean;
  memoryError: string | null;
  memoryConflicts: MemoryRecord[];
  emotionState: EmotionState | null;
  emotionEvents: EmotionEvent[];
  emotionLoading: boolean;
  emotionError: string | null;
  emotionAnalysisConsent: EmotionAnalysisConsent | null;
  emotionAnalysisAudits: EmotionAnalysisAudit[];
  emotionAnalysisConsentLoading: boolean;
  emotionAnalysisAuditLoading: boolean;
  onSetEmotionEnabled: (enabled: boolean) => Promise<void>;
  onResetEmotion: () => Promise<void>;
  onRetryEmotion: () => Promise<void>;
  onUpdateEmotionAnalysisConsent: (action: EmotionAnalysisConsentAction) => Promise<void>;
  onRefreshEmotionAnalysisAudits: () => Promise<void>;
  onCreateMemory: (request: CreateMemoryRequest) => Promise<void>;
  onUpdateMemory: (memoryId: string, request: UpdateMemoryRequest) => Promise<void>;
  onDeleteMemory: (memoryId: string) => Promise<void>;
  onConfirmMemoryCandidate: (memoryId: string) => Promise<void>;
  onDismissMemoryCandidate: (memoryId: string) => Promise<void>;
  onDismissError: () => void;
  onClearPendingTranscript: () => void;
}

export function ChatLayout({
  sessions,
  activeSessionId,
  messages,
  loading,
  error,
  expressionPreviewState,
  expressionPreviewLabel,
  audioController,
  audioInputDevices,
  audioOutputDevices,
  recorder,
  pendingTranscript,
  playbackBlocked,
  recorderDisabled,
  onCreateSession,
  onSelectSession,
  onDeleteSession,
  onSendMessage,
  onSendAndSpeakTranscript,
  voiceTurnBusy,
  voiceTurnError,
  vadStatusMessage,
  recorderHintMessage,
  memories,
  memoryCandidates,
  memoryLoading,
  memoryError,
  memoryConflicts,
  emotionState,
  emotionEvents,
  emotionLoading,
  emotionError,
  emotionAnalysisConsent,
  emotionAnalysisAudits,
  emotionAnalysisConsentLoading,
  emotionAnalysisAuditLoading,
  onSetEmotionEnabled,
  onResetEmotion,
  onRetryEmotion,
  onUpdateEmotionAnalysisConsent,
  onRefreshEmotionAnalysisAudits,
  onCreateMemory,
  onUpdateMemory,
  onDeleteMemory,
  onConfirmMemoryCandidate,
  onDismissMemoryCandidate,
  onDismissError,
  onClearPendingTranscript,
}: ChatLayoutProps) {
  const activeSession = sessions.find((session) => session.id === activeSessionId) ?? null;

  return (
    <main className="chat-layout">
      <SessionList
        sessions={sessions}
        activeSessionId={activeSessionId}
        onCreateSession={onCreateSession}
        onSelectSession={onSelectSession}
        onDeleteSession={onDeleteSession}
      />
      <section className="chat-panel">
        <header className="chat-panel__header">
          <h2>{activeSession ? activeSession.title : '请选择或新建会话'}</h2>
          {loading ? <span className="loading">处理中……</span> : null}
        </header>
        <ErrorBanner message={error} onDismiss={onDismissError} />
        <PresentationErrorBoundary>
          <ExpressionPreview
            state={expressionPreviewState}
            displayLabel={expressionPreviewLabel}
          />
        </PresentationErrorBoundary>
        <EmotionPanel
          state={emotionState}
          events={emotionEvents}
          loading={emotionLoading}
          error={emotionError}
          onSetEnabled={onSetEmotionEnabled}
          onReset={onResetEmotion}
          onRetry={onRetryEmotion}
          analysisConsent={emotionAnalysisConsent}
          analysisAudits={emotionAnalysisAudits}
          analysisConsentLoading={emotionAnalysisConsentLoading}
          analysisAuditLoading={emotionAnalysisAuditLoading}
          onUpdateAnalysisConsent={onUpdateEmotionAnalysisConsent}
          onRefreshAnalysisAudits={onRefreshEmotionAnalysisAudits}
        />
        <MemoryPanel
          memories={memories}
          candidates={memoryCandidates}
          loading={memoryLoading}
          error={memoryError}
          conflicts={memoryConflicts}
          onCreate={onCreateMemory}
          onUpdate={onUpdateMemory}
          onDelete={onDeleteMemory}
          onConfirmCandidate={onConfirmMemoryCandidate}
          onDismissCandidate={onDismissMemoryCandidate}
        />
        <MessageList messages={messages} audioController={audioController} playbackBlocked={playbackBlocked} />
        <VoiceRecorder
          recorder={recorder}
          disabled={recorderDisabled}
          vadStatusMessage={vadStatusMessage}
          hintMessage={recorderHintMessage}
          audioInputDevices={audioInputDevices}
          audioOutputDevices={audioOutputDevices}
        />
        <MessageInput
          disabled={loading || !activeSessionId}
          onSend={onSendMessage}
          pendingTranscript={pendingTranscript}
          onClearPendingTranscript={onClearPendingTranscript}
          onSendAndSpeakTranscript={onSendAndSpeakTranscript}
          voiceTurnBusy={voiceTurnBusy}
          voiceTurnError={voiceTurnError}
        />
      </section>
    </main>
  );
}
