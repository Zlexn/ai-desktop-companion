import { useState } from 'react';
import type {
  CreateMemoryRequest,
  MemoryConflict,
  MemoryConflictResolutionRequest,
  MemoryEvidencePage,
  MemoryJobSummary,
  MemoryRecord,
  MemoryType,
  MemoryVersionPage,
  MemoryWriteConsent,
  MemoryWriteConsentAction,
  RelationshipSubjectCode,
  UpdateMemoryRequest,
} from '../api/types';
import { MemoryAutomationControls } from './MemoryAutomationControls';
import { MemoryConflictPanel } from './MemoryConflictPanel';
import { MemoryHistoryDetails } from './MemoryHistoryDetails';

const V2_SOURCE_LABELS: Record<string, string> = {
  legacy: '旧版接入',
  manual: '手动',
  candidate: '候选确认',
  automatic: '自动写入',
  user_edit: '用户编辑',
  user_revert: '用户撤销',
};

const V2_STATE_LABELS: Record<string, string> = {
  active: 'V2 当前有效',
  archived: 'V2 已归档',
  conflicted: 'V2 冲突中',
  deleted: 'V2 已忘记',
};

function memorySourceLabel(memory: MemoryRecord): string {
  if (memory.v2_source_kind) return V2_SOURCE_LABELS[memory.v2_source_kind];
  return memory.source === 'automatic'
    ? '自动写入'
    : memory.source === 'candidate'
      ? '候选确认'
      : '手动';
}

const MEMORY_TYPE_OPTIONS: Array<{ value: MemoryType; label: string }> = [
  { value: 'user_fact', label: '用户事实' },
  { value: 'preference', label: '偏好' },
  { value: 'long_term_goal', label: '长期目标' },
  { value: 'important_event', label: '重要事件' },
  { value: 'relationship_event', label: '关系事件' },
  { value: 'other', label: '其他' },
];

export const RELATIONSHIP_SUBJECT_OPTIONS: Array<{
  value: RelationshipSubjectCode;
  label: string;
}> = [
  { value: 'preferred_address', label: '偏好的称呼' },
  { value: 'shared_experience', label: '共同经历' },
  { value: 'non_external_commitment', label: '不对外承诺' },
];

const RELATIONSHIP_SUBJECTS_BY_MEMORY_TYPE: Partial<Record<MemoryType, RelationshipSubjectCode[]>> = {
  user_fact: ['preferred_address'],
  preference: ['preferred_address'],
  relationship_event: ['preferred_address', 'shared_experience', 'non_external_commitment'],
};

export function relationshipSubjectOptions(
  memoryType: MemoryType,
): Array<{ value: RelationshipSubjectCode; label: string }> {
  const allowed = RELATIONSHIP_SUBJECTS_BY_MEMORY_TYPE[memoryType];
  if (!allowed) return [];
  return RELATIONSHIP_SUBJECT_OPTIONS.filter((option) => allowed.includes(option.value));
}

function MemorySubjectSelect({
  label = '关系主题',
  memoryType,
  value,
  onChange,
  allowClear = false,
}: {
  label?: string;
  memoryType: MemoryType;
  value: RelationshipSubjectCode | '' | 'clear';
  onChange: (value: RelationshipSubjectCode | '' | 'clear') => void;
  allowClear?: boolean;
}) {
  const options = relationshipSubjectOptions(memoryType);
  if (options.length === 0) return null;
  return (
    <label>
      {label}
      <select
        value={value}
        onChange={(event) => onChange(event.target.value as RelationshipSubjectCode | '' | 'clear')}
      >
        <option value="">{allowClear ? '不指定（保留现有）' : '不指定'}</option>
        {allowClear ? <option value="clear">清除关系主题</option> : null}
        {options.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
    </label>
  );
}

function PreferredAddressHint({ value }: { value: RelationshipSubjectCode | '' | 'clear' }) {
  if (value !== 'preferred_address') return null;
  return (
    <p className="memory-panel__hint">偏好的称呼必须填写希望使用的准确称呼，不要填写解释或描述。</p>
  );
}

function CandidateItem({
  candidate,
  loading,
  onConfirm,
  onDismiss,
}: {
  candidate: MemoryRecord;
  loading: boolean;
  onConfirm: (memoryId: string, subjectCode?: RelationshipSubjectCode | null) => Promise<void>;
  onDismiss: (memoryId: string) => Promise<void>;
}) {
  const [subjectCode, setSubjectCode] = useState<RelationshipSubjectCode | '' | 'clear'>(
    candidate.canonical_subject_code ?? '',
  );
  return (
    <li className="memory-panel__item memory-panel__item--candidate">
      <p>{candidate.content}</p>
      <small>{candidate.memory_type} · importance {candidate.importance} · confidence {candidate.confidence.toFixed(2)}</small>
      <MemorySubjectSelect
        label="候选关系主题"
        memoryType={candidate.memory_type}
        value={subjectCode}
        onChange={setSubjectCode}
        allowClear
      />
      <PreferredAddressHint value={subjectCode} />
      <div className="memory-panel__actions">
        <button
          type="button"
          disabled={loading}
          onClick={() => void onConfirm(
            candidate.id,
            subjectCode === '' || subjectCode === 'clear' ? null : subjectCode,
          )}
        >
          保存为长期记忆
        </button>
        <button type="button" disabled={loading} onClick={() => void onDismiss(candidate.id)}>忽略</button>
      </div>
    </li>
  );
}

export function numberDraftFromInput(input: HTMLInputElement): number | '' {
  if (input.value === '') return '';
  return Number.isFinite(input.valueAsNumber) ? input.valueAsNumber : '';
}

interface MemoryPanelProps {
  memories: MemoryRecord[];
  candidates: MemoryRecord[];
  loading: boolean;
  error: string | null;
  conflicts: MemoryRecord[];
  gateBConflicts?: MemoryConflict[];
  writeConsent?: MemoryWriteConsent | null;
  latestJob?: MemoryJobSummary | null;
  onCreate: (request: CreateMemoryRequest) => Promise<void>;
  onUpdate: (memoryId: string, request: UpdateMemoryRequest) => Promise<void>;
  onDelete: (memoryId: string) => Promise<void>;
  onArchive?: (memoryId: string) => Promise<void>;
  onForget?: (memoryId: string) => Promise<void>;
  onUndoLatestAuto?: (memoryId: string) => Promise<void>;
  onUpdateWriteConsent?: (action: MemoryWriteConsentAction) => Promise<void>;
  onResolveConflict?: (conflictId: string, request: MemoryConflictResolutionRequest) => Promise<void>;
  loadVersions?: (memoryId: string, cursor?: string | null) => Promise<MemoryVersionPage>;
  loadEvidence?: (memoryId: string, cursor?: string | null) => Promise<MemoryEvidencePage>;
  onConfirmCandidate: (memoryId: string, subjectCode?: RelationshipSubjectCode | null) => Promise<void>;
  onDismissCandidate: (memoryId: string) => Promise<void>;
}

export function MemoryPanel({
  memories,
  candidates,
  loading,
  error,
  conflicts,
  gateBConflicts = [],
  writeConsent = null,
  latestJob = null,
  onCreate,
  onUpdate,
  onDelete,
  onArchive,
  onForget,
  onUndoLatestAuto,
  onUpdateWriteConsent,
  onResolveConflict,
  loadVersions,
  loadEvidence,
  onConfirmCandidate,
  onDismissCandidate,
}: MemoryPanelProps) {
  const [content, setContent] = useState('');
  const [memoryType, setMemoryType] = useState<MemoryType>('preference');
  const [subjectCode, setSubjectCode] = useState<RelationshipSubjectCode | '' | 'clear'>('');
  const [editingMemoryId, setEditingMemoryId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState('');
  const [editMemoryType, setEditMemoryType] = useState<MemoryType>('preference');
  const [editSubjectCode, setEditSubjectCode] = useState<RelationshipSubjectCode | '' | 'clear'>('');
  const [editImportance, setEditImportance] = useState<number | ''>(3);
  const [editConfidence, setEditConfidence] = useState<number | ''>(1);
  const [isUpdating, setIsUpdating] = useState(false);
  const [forgettingMemoryId, setForgettingMemoryId] = useState<string | null>(null);

  const canSaveEdit = editContent.trim().length > 0
    && typeof editImportance === 'number'
    && Number.isInteger(editImportance)
    && editImportance >= 1
    && editImportance <= 5
    && typeof editConfidence === 'number'
    && Number.isFinite(editConfidence)
    && editConfidence >= 0
    && editConfidence <= 1;

  function startEditing(memory: MemoryRecord) {
    setEditingMemoryId(memory.id);
    setEditContent(memory.content);
    setEditMemoryType(memory.memory_type);
    setEditSubjectCode(memory.canonical_subject_code ?? '');
    setEditImportance(memory.importance);
    setEditConfidence(memory.confidence);
  }

  function cancelEditing() {
    setEditingMemoryId(null);
  }

  async function handleUpdate(memoryId: string) {
    const cleanContent = editContent.trim();
    if (!canSaveEdit) return;
    if (typeof editImportance !== 'number' || typeof editConfidence !== 'number') return;

    setIsUpdating(true);
    try {
      const request: UpdateMemoryRequest = {
        content: cleanContent,
        memory_type: editMemoryType,
        importance: editImportance,
        confidence: editConfidence,
      };
      if (editSubjectCode === 'clear') {
        request.canonical_subject_code = null;
      } else if (editSubjectCode !== '') {
        request.canonical_subject_code = editSubjectCode;
      }
      await onUpdate(memoryId, request);
      setEditingMemoryId(null);
    } catch {
      // The parent displays the shared error; keep the draft open for retry.
    } finally {
      setIsUpdating(false);
    }
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const cleanContent = content.trim();
    if (!cleanContent) return;
    const request: CreateMemoryRequest = {
      content: cleanContent,
      memory_type: memoryType,
      importance: 3,
      confidence: 1,
    };
    if (subjectCode !== '' && subjectCode !== 'clear') {
      request.canonical_subject_code = subjectCode;
    }
    await onCreate(request);
    setContent('');
    setMemoryType('preference');
    setSubjectCode('');
  }

  return (
    <section className="memory-panel" aria-label="长期记忆">
      <h2>长期记忆</h2>
      <p className="memory-panel__hint">长期记忆来源会明确标注；自动写入仅在你单独授权本地写入且规则允许时发生。</p>
      {error ? <p role="alert" className="memory-panel__error">{error}</p> : null}
      {loading ? <p>记忆加载中……</p> : null}
      {onUpdateWriteConsent ? (
        <MemoryAutomationControls
          consent={writeConsent}
          loading={loading}
          latestJob={latestJob}
          onUpdate={onUpdateWriteConsent}
        />
      ) : null}
      {onResolveConflict ? (
        <MemoryConflictPanel
          conflicts={gateBConflicts}
          loading={loading}
          onResolve={onResolveConflict}
        />
      ) : null}
      {conflicts.length > 0 ? (
        <section className="memory-panel__conflicts" aria-label="冲突记忆明细">
          <p className="memory-panel__warning">发现相似记忆，请确认是否需要保留多条。</p>
          <ul className="memory-panel__list">
            {conflicts.map((conflict) => (
              <li key={conflict.id} className="memory-panel__item memory-panel__item--conflict">
                <p>{conflict.content}</p>
                <small>{conflict.memory_type} · importance {conflict.importance} · confidence {conflict.confidence.toFixed(2)}</small>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <form className="memory-panel__form" onSubmit={handleSubmit}>
        <label>
          记忆内容
          <textarea value={content} onChange={(event) => setContent(event.target.value)} maxLength={1000} />
        </label>
        <label>
          记忆类型
          <select value={memoryType} onChange={(event) => setMemoryType(event.target.value as MemoryType)}>
            {MEMORY_TYPE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
        <MemorySubjectSelect
          memoryType={memoryType}
          value={subjectCode}
          onChange={setSubjectCode}
        />
        <PreferredAddressHint value={subjectCode} />
        <button type="submit" disabled={!content.trim()}>保存记忆</button>
      </form>
      <section className="memory-panel__candidates" aria-label="待确认记忆">
        <h3>待确认记忆</h3>
        <p className="memory-panel__hint">以下是系统建议保存的长期记忆，确认前不会用于对话。</p>
        {candidates.length === 0 ? <p>暂无待确认记忆。</p> : null}
        <ul className="memory-panel__list">
          {candidates.map((candidate) => (
            <CandidateItem
              key={candidate.id}
              candidate={candidate}
              loading={loading}
              onConfirm={onConfirmCandidate}
              onDismiss={onDismissCandidate}
            />
          ))}
        </ul>
      </section>
      {memories.length === 0 ? <p>暂无长期记忆。</p> : null}
      <ul className="memory-panel__list">
        {memories.map((memory) => (
          <li key={memory.id} className="memory-panel__item">
            {editingMemoryId === memory.id ? (
              <div className="memory-panel__form">
                <label>
                  编辑记忆内容
                  <textarea value={editContent} onChange={(event) => setEditContent(event.target.value)} maxLength={1000} />
                </label>
                <label>
                  编辑记忆类型
                  <select value={editMemoryType} onChange={(event) => setEditMemoryType(event.target.value as MemoryType)}>
                    {MEMORY_TYPE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                  </select>
                </label>
                <MemorySubjectSelect
                  label="编辑关系主题"
                  memoryType={editMemoryType}
                  value={editSubjectCode}
                  onChange={setEditSubjectCode}
                  allowClear
                />
                <PreferredAddressHint value={editSubjectCode} />
                <label>
                  编辑重要度
                  <input type="number" min={1} max={5} step={1} value={editImportance} onChange={(event) => setEditImportance(numberDraftFromInput(event.currentTarget))} />
                </label>
                <label>
                  编辑可信度
                  <input type="number" min={0} max={1} step={0.05} value={editConfidence} onChange={(event) => setEditConfidence(numberDraftFromInput(event.currentTarget))} />
                </label>
                <div className="memory-panel__actions">
                  <button type="button" disabled={!canSaveEdit || isUpdating} onClick={() => void handleUpdate(memory.id)}>保存修改</button>
                  <button type="button" onClick={cancelEditing}>取消编辑</button>
                </div>
              </div>
            ) : (
              <>
                <p>{memory.content}</p>
                <div className="memory-panel__badges" aria-label="记忆属性">
                  <span className="memory-panel__badge">{memorySourceLabel(memory)}</span>
                  <span className="memory-panel__badge">
                    {memory.v2_state
                      ? V2_STATE_LABELS[memory.v2_state]
                      : memory.status === 'active'
                        ? '当前有效'
                        : memory.status}
                  </span>
                  <span className="memory-panel__badge">{memory.version_count} 个版本</span>
                  <span className="memory-panel__badge">{memory.evidence_count} 条证据</span>
                  {memory.has_open_conflict ? (
                    <span className="memory-panel__badge memory-panel__badge--warning">存在待解决冲突</span>
                  ) : null}
                </div>
                <small>{memory.memory_type} · importance {memory.importance} · confidence {memory.confidence.toFixed(2)}</small>
                <div className="memory-panel__actions">
                  <button type="button" disabled={loading} onClick={() => startEditing(memory)}>编辑记忆</button>
                  <button type="button" disabled={loading} onClick={() => void (onArchive ?? onDelete)(memory.id)}>归档记忆</button>
                  {onUndoLatestAuto && memory.can_undo_latest_auto ? (
                    <button type="button" disabled={loading} onClick={() => void onUndoLatestAuto(memory.id)}>撤销最近自动变化</button>
                  ) : null}
                  {onForget ? (
                    <button type="button" disabled={loading} className="memory-panel__danger" onClick={() => setForgettingMemoryId(memory.id)}>真正忘记</button>
                  ) : null}
                </div>
                {forgettingMemoryId === memory.id && onForget ? (
                  <div className="memory-panel__confirmation" role="group" aria-label="确认真正忘记">
                    <p>真正忘记会清除该记忆的可读历史并阻止自动恢复，但不会删除原始聊天消息。此操作不可撤销。</p>
                    <div className="memory-panel__actions">
                      <button type="button" className="memory-panel__danger" disabled={loading} onClick={() => {
                        setForgettingMemoryId(null);
                        void onForget(memory.id);
                      }}>确认真正忘记</button>
                      <button type="button" onClick={() => setForgettingMemoryId(null)}>取消忘记</button>
                    </div>
                  </div>
                ) : null}
                {loadVersions && loadEvidence ? (
                  <MemoryHistoryDetails
                    memoryId={memory.id}
                    loadVersions={loadVersions}
                    loadEvidence={loadEvidence}
                  />
                ) : null}
              </>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
