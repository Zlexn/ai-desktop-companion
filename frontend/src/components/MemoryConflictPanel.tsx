import { useState } from 'react';
import type { MemoryConflict, MemoryConflictResolutionRequest, MemoryType } from '../api/types';

const MEMORY_TYPES: Array<{ value: MemoryType; label: string }> = [
  { value: 'user_fact', label: '用户事实' },
  { value: 'preference', label: '偏好' },
  { value: 'long_term_goal', label: '长期目标' },
  { value: 'important_event', label: '重要事件' },
  { value: 'relationship_event', label: '关系事件' },
  { value: 'other', label: '其他' },
];

interface MemoryConflictPanelProps {
  conflicts: MemoryConflict[];
  loading: boolean;
  onResolve: (conflictId: string, request: MemoryConflictResolutionRequest) => Promise<void>;
}

type ReplacementKind = 'replace_both' | 'both_contextual';

export function MemoryConflictPanel({ conflicts, loading, onResolve }: MemoryConflictPanelProps) {
  const [editing, setEditing] = useState<{ id: string; kind: ReplacementKind } | null>(null);
  const [content, setContent] = useState('');
  const [subject, setSubject] = useState('');
  const [memoryType, setMemoryType] = useState<MemoryType>('preference');

  function openReplacement(id: string, kind: ReplacementKind) {
    setEditing({ id, kind });
    setContent('');
    setSubject('');
    setMemoryType('preference');
  }

  async function submitReplacement() {
    if (!editing || !content.trim() || !subject.trim()) return;
    if (
      editing.kind === 'both_contextual'
      && !/(时|期间|曾经|现在|在|情况下|场景|语境)/u.test(`${subject}${content}`)
    ) return;
    await onResolve(editing.id, {
      kind: editing.kind,
      content: content.trim(),
      subject: subject.trim(),
      memory_type: memoryType,
      importance: 3,
      confidence: 1,
    });
    setEditing(null);
  }

  const contextualValid = /(时|期间|曾经|现在|在|情况下|场景|语境)/u.test(`${subject}${content}`);
  const replacementValid = Boolean(content.trim() && subject.trim())
    && (editing?.kind !== 'both_contextual' || contextualValid);

  if (conflicts.length === 0) return null;

  return (
    <section className="memory-conflict-panel" aria-label="待解决记忆冲突">
      <h3>待解决冲突</h3>
      <p className="memory-panel__warning">冲突中的记忆不会用于对话。请选择明确的解决方式。</p>
      <ul className="memory-panel__list">
        {conflicts.map((conflict) => (
          <li key={conflict.id} className="memory-panel__item memory-panel__item--conflict">
            <p><strong>冲突 {conflict.id}</strong></p>
            <small>左侧：{conflict.left_memory_id} · 右侧：{conflict.right_memory_id}</small>
            <div className="memory-panel__actions">
              <button type="button" disabled={loading} onClick={() => void onResolve(conflict.id, { kind: 'choose_left' })}>采用左侧记忆</button>
              <button type="button" disabled={loading} onClick={() => void onResolve(conflict.id, { kind: 'choose_right' })}>采用右侧记忆</button>
              <button type="button" disabled={loading} onClick={() => openReplacement(conflict.id, 'replace_both')}>替换双方</button>
              <button type="button" disabled={loading} onClick={() => openReplacement(conflict.id, 'both_contextual')}>保留语境区别</button>
              <button type="button" disabled={loading} onClick={() => void onResolve(conflict.id, { kind: 'dismiss_both' })}>双方都不保留</button>
            </div>
            {editing?.id === conflict.id ? (
              <div className="memory-panel__form memory-conflict-panel__replacement">
                <label>
                  解决后的主题
                  <input value={subject} maxLength={200} onChange={(event) => setSubject(event.target.value)} />
                </label>
                <label>
                  解决后的内容
                  <textarea value={content} maxLength={2000} onChange={(event) => setContent(event.target.value)} />
                </label>
                <label>
                  解决后的类型
                  <select value={memoryType} onChange={(event) => setMemoryType(event.target.value as MemoryType)}>
                    {MEMORY_TYPES.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}
                  </select>
                </label>
                {editing.kind === 'both_contextual' && !contextualValid ? (
                  <small className="memory-panel__warning">请在主题或内容中明确时间或使用场景。</small>
                ) : null}
                <div className="memory-panel__actions">
                  <button type="button" disabled={loading || !replacementValid} onClick={() => void submitReplacement()}>
                    {editing.kind === 'both_contextual' ? '提交语境化解决' : '提交替换解决'}
                  </button>
                  <button type="button" onClick={() => setEditing(null)}>取消解决</button>
                </div>
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
