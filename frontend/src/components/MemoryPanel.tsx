import { useState } from 'react';
import type { CreateMemoryRequest, MemoryRecord, MemoryType, UpdateMemoryRequest } from '../api/types';

const MEMORY_TYPE_OPTIONS: Array<{ value: MemoryType; label: string }> = [
  { value: 'user_fact', label: '用户事实' },
  { value: 'preference', label: '偏好' },
  { value: 'long_term_goal', label: '长期目标' },
  { value: 'important_event', label: '重要事件' },
  { value: 'relationship_event', label: '关系事件' },
  { value: 'other', label: '其他' },
];

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
  onCreate: (request: CreateMemoryRequest) => Promise<void>;
  onUpdate: (memoryId: string, request: UpdateMemoryRequest) => Promise<void>;
  onDelete: (memoryId: string) => Promise<void>;
  onConfirmCandidate: (memoryId: string) => Promise<void>;
  onDismissCandidate: (memoryId: string) => Promise<void>;
}

export function MemoryPanel({
  memories,
  candidates,
  loading,
  error,
  conflicts,
  onCreate,
  onUpdate,
  onDelete,
  onConfirmCandidate,
  onDismissCandidate,
}: MemoryPanelProps) {
  const [content, setContent] = useState('');
  const [memoryType, setMemoryType] = useState<MemoryType>('preference');
  const [editingMemoryId, setEditingMemoryId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState('');
  const [editMemoryType, setEditMemoryType] = useState<MemoryType>('preference');
  const [editImportance, setEditImportance] = useState<number | ''>(3);
  const [editConfidence, setEditConfidence] = useState<number | ''>(1);
  const [isUpdating, setIsUpdating] = useState(false);

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
      await onUpdate(memoryId, {
        content: cleanContent,
        memory_type: editMemoryType,
        importance: editImportance,
        confidence: editConfidence,
      });
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
    await onCreate({ content: cleanContent, memory_type: memoryType, importance: 3, confidence: 1 });
    setContent('');
    setMemoryType('preference');
  }

  return (
    <section className="memory-panel" aria-label="长期记忆">
      <h2>长期记忆</h2>
      <p className="memory-panel__hint">只保存你明确创建或确认的内容；聊天记录不会自动变成长期记忆。</p>
      {error ? <p role="alert" className="memory-panel__error">{error}</p> : null}
      {loading ? <p>记忆加载中……</p> : null}
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
        <button type="submit" disabled={!content.trim()}>保存记忆</button>
      </form>
      <section className="memory-panel__candidates" aria-label="待确认记忆">
        <h3>待确认记忆</h3>
        <p className="memory-panel__hint">以下是系统建议保存的长期记忆，确认前不会用于对话。</p>
        {candidates.length === 0 ? <p>暂无待确认记忆。</p> : null}
        <ul className="memory-panel__list">
          {candidates.map((candidate) => (
            <li key={candidate.id} className="memory-panel__item memory-panel__item--candidate">
              <p>{candidate.content}</p>
              <small>{candidate.memory_type} · importance {candidate.importance} · confidence {candidate.confidence.toFixed(2)}</small>
              <div className="memory-panel__actions">
                <button type="button" onClick={() => void onConfirmCandidate(candidate.id)}>保存为长期记忆</button>
                <button type="button" onClick={() => void onDismissCandidate(candidate.id)}>忽略</button>
              </div>
            </li>
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
                <small>{memory.memory_type} · importance {memory.importance} · confidence {memory.confidence.toFixed(2)}</small>
                <div className="memory-panel__actions">
                  <button type="button" disabled={loading} onClick={() => startEditing(memory)}>编辑记忆</button>
                  <button type="button" disabled={loading} onClick={() => void onDelete(memory.id)}>删除记忆</button>
                </div>
              </>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
