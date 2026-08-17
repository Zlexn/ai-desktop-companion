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
  RelationshipProjection,
  RelationshipReconcileRequest,
  RelationshipRedactRequest,
  RelationshipReenableRequest,
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
} from '../api/types';
import type { ExpressionPreviewState } from '../expression/previewReducer';
import type { UseAudioInputDevicesResult } from '../hooks/useAudioInputDevices';
import type { UseAudioOutputDevicesResult } from '../hooks/useAudioOutputDevices';
import type { useAudioPlaybackController } from '../hooks/useAudioPlaybackController';
import type { UseManualAudioRecorderResult } from '../hooks/useManualAudioRecorder';
import { ErrorBanner } from './ErrorBanner';
import { ExpressionPreview } from './ExpressionPreview';
import { PersonaPanel } from './PersonaPanel';
import { PresentationErrorBoundary } from './PresentationErrorBoundary';
import { EmotionPanel } from './EmotionPanel';
import { MemoryPanel } from './MemoryPanel';
import { MessageInput } from './MessageInput';
import { MessageList } from './MessageList';
import { RelationshipPanel } from './RelationshipPanel';
import { SessionList } from './SessionList';
import { SummaryPanel } from './SummaryPanel';
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
  gateBMemoryConflicts: MemoryConflict[];
  memoryWriteConsent: MemoryWriteConsent | null;
  latestMemoryJob: MemoryJobSummary | null;
  personaCurrent: PersonaArtifact | null;
  personaArtifacts: PersonaArtifact[];
  personaCapabilities: PersonaCapabilities | null;
  personaLoading: boolean;
  personaError: string | null;
  onRetryPersona: () => Promise<void>;
  onCreatePersona: (request: PersonaCreateRequest) => Promise<void>;
  onActivatePersona: (request: PersonaActivateRequest) => Promise<void>;
  onRedactPersona: (artifactId: string, request: PersonaRedactRequest) => Promise<void>;
  summaryCapabilities: SummaryCapabilities | null;
  summaryProcessingConsent: SummaryProcessingConsent | null;
  summaryInjectionConsent: SummaryInjectionConsent | null;
  summaryStatus: SummaryStatus | null;
  summaries: SummaryItem[];
  summaryJobs: SummaryJob[];
  summaryAudits: SummaryAudit[];
  summaryLoading: boolean;
  summaryError: string | null;
  onRetrySummaries: () => Promise<void>;
  onUpdateSummaryProcessing: (request: SummaryAuthorityMutationRequest) => Promise<void>;
  onUpdateSummaryInjection: (request: SummaryAuthorityMutationRequest) => Promise<void>;
  onRedactSummary: (summaryId: string, request: SummaryRedactRequest) => Promise<void>;
  onRebuildSummary: (summaryId: string, request: SummaryRebuildRequest) => Promise<void>;
  onRetrySummaryJob: (jobId: string, request: SummaryJobMutationRequest) => Promise<void>;
  onCancelSummaryJob: (jobId: string, request: SummaryJobMutationRequest) => Promise<void>;
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
  relationshipCapabilities: RelationshipCapabilities | null;
  relationshipProjection: RelationshipProjection | null;
  relationshipEvents: RelationshipEvent[];
  relationshipJobs: RelationshipJob[];
  relationshipAudits: RelationshipAudit[];
  relationshipLoading: boolean;
  relationshipError: string | null;
  onRetryRelationship: () => Promise<void>;
  onReconcileRelationship: (request: RelationshipReconcileRequest) => Promise<void>;
  onRebuildRelationship: (request: RelationshipReconcileRequest) => Promise<void>;
  onSuppressRelationshipApply: (applyEventId: string, request: RelationshipSuppressRequest) => Promise<void>;
  onRedactRelationshipApply: (applyEventId: string, request: RelationshipRedactRequest) => Promise<void>;
  onReenableRelationshipAuthority: (
    sourceMemoryId: string,
    eventType: string,
    subjectCode: string,
    request: RelationshipReenableRequest,
  ) => Promise<void>;
  onCreateMemory: (request: CreateMemoryRequest) => Promise<void>;
  onUpdateMemory: (memoryId: string, request: UpdateMemoryRequest) => Promise<void>;
  onDeleteMemory: (memoryId: string) => Promise<void>;
  onArchiveMemory: (memoryId: string) => Promise<void>;
  onForgetMemory: (memoryId: string) => Promise<void>;
  onUndoLatestAutoMemory: (memoryId: string) => Promise<void>;
  onUpdateMemoryWriteConsent: (action: MemoryWriteConsentAction) => Promise<void>;
  onResolveMemoryConflict: (conflictId: string, request: MemoryConflictResolutionRequest) => Promise<void>;
  loadMemoryVersions: (memoryId: string, cursor?: string | null) => Promise<MemoryVersionPage>;
  loadMemoryEvidence: (memoryId: string, cursor?: string | null) => Promise<MemoryEvidencePage>;
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
  gateBMemoryConflicts,
  memoryWriteConsent,
  latestMemoryJob,
  personaCurrent,
  personaArtifacts,
  personaCapabilities,
  personaLoading,
  personaError,
  onRetryPersona,
  onCreatePersona,
  onActivatePersona,
  onRedactPersona,
  summaryCapabilities,
  summaryProcessingConsent,
  summaryInjectionConsent,
  summaryStatus,
  summaries,
  summaryJobs,
  summaryAudits,
  summaryLoading,
  summaryError,
  onRetrySummaries,
  onUpdateSummaryProcessing,
  onUpdateSummaryInjection,
  onRedactSummary,
  onRebuildSummary,
  onRetrySummaryJob,
  onCancelSummaryJob,
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
  relationshipCapabilities,
  relationshipProjection,
  relationshipEvents,
  relationshipJobs,
  relationshipAudits,
  relationshipLoading,
  relationshipError,
  onRetryRelationship,
  onReconcileRelationship,
  onRebuildRelationship,
  onSuppressRelationshipApply,
  onRedactRelationshipApply,
  onReenableRelationshipAuthority,
  onCreateMemory,
  onUpdateMemory,
  onDeleteMemory,
  onArchiveMemory,
  onForgetMemory,
  onUndoLatestAutoMemory,
  onUpdateMemoryWriteConsent,
  onResolveMemoryConflict,
  loadMemoryVersions,
  loadMemoryEvidence,
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
        <PersonaPanel
          current={personaCurrent}
          artifacts={personaArtifacts}
          capabilities={personaCapabilities}
          loading={personaLoading}
          error={personaError}
          onRetry={onRetryPersona}
          onCreate={onCreatePersona}
          onActivate={onActivatePersona}
          onRedact={onRedactPersona}
        />
        <SummaryPanel
          capabilities={summaryCapabilities}
          processingConsent={summaryProcessingConsent}
          injectionConsent={summaryInjectionConsent}
          status={summaryStatus}
          summaries={summaries}
          jobs={summaryJobs}
          audits={summaryAudits}
          loading={summaryLoading}
          error={summaryError}
          onRetryLoad={onRetrySummaries}
          onUpdateProcessing={onUpdateSummaryProcessing}
          onUpdateInjection={onUpdateSummaryInjection}
          onRedact={onRedactSummary}
          onRebuild={onRebuildSummary}
          onRetryJob={onRetrySummaryJob}
          onCancelJob={onCancelSummaryJob}
        />
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
        <RelationshipPanel
          capabilities={relationshipCapabilities}
          projection={relationshipProjection}
          events={relationshipEvents}
          jobs={relationshipJobs}
          audits={relationshipAudits}
          loading={relationshipLoading}
          error={relationshipError}
          onRetryLoad={onRetryRelationship}
          onReconcile={onReconcileRelationship}
          onRebuild={onRebuildRelationship}
          onSuppress={onSuppressRelationshipApply}
          onRedact={onRedactRelationshipApply}
          onReenable={onReenableRelationshipAuthority}
        />
        <MemoryPanel
          memories={memories}
          candidates={memoryCandidates}
          loading={memoryLoading}
          error={memoryError}
          conflicts={memoryConflicts}
          gateBConflicts={gateBMemoryConflicts}
          writeConsent={memoryWriteConsent}
          latestJob={latestMemoryJob}
          onCreate={onCreateMemory}
          onUpdate={onUpdateMemory}
          onDelete={onDeleteMemory}
          onArchive={onArchiveMemory}
          onForget={onForgetMemory}
          onUndoLatestAuto={onUndoLatestAutoMemory}
          onUpdateWriteConsent={onUpdateMemoryWriteConsent}
          onResolveConflict={onResolveMemoryConflict}
          loadVersions={loadMemoryVersions}
          loadEvidence={loadMemoryEvidence}
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
