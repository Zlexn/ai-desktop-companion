import { useState } from 'react';
import type { MemoryEvidence, MemoryEvidencePage, MemoryVersion, MemoryVersionPage } from '../api/types';

interface MemoryHistoryDetailsProps {
  memoryId: string;
  loadVersions: (memoryId: string, cursor?: string | null) => Promise<MemoryVersionPage>;
  loadEvidence: (memoryId: string, cursor?: string | null) => Promise<MemoryEvidencePage>;
}

const OPERATION_LABELS: Record<string, string> = {
  bootstrap: '旧记忆接入',
  create: '创建',
  user_edit: '用户编辑',
  auto_supersede: '自动更新',
  conflict_candidate: '冲突候选',
  conflict_resolution: '冲突解决',
  user_revert: '用户撤销',
  archive: '归档',
  delete: '真正忘记',
};

const RELATION_LABELS: Record<string, string> = {
  supports: '支持',
  contradicts: '矛盾',
  corrects: '更正',
};

const EXTRACTOR_LABELS: Record<string, string> = {
  local: '本地规则',
  fake: '测试抽取器',
  remote: '远程抽取器',
  manual: '手动',
  candidate: '候选确认',
};

export function MemoryHistoryDetails({
  memoryId,
  loadVersions,
  loadEvidence,
}: MemoryHistoryDetailsProps) {
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [versions, setVersions] = useState<MemoryVersion[]>([]);
  const [evidence, setEvidence] = useState<MemoryEvidence[]>([]);
  const [versionCursor, setVersionCursor] = useState<string | null>(null);
  const [evidenceCursor, setEvidenceCursor] = useState<string | null>(null);

  async function open() {
    if (expanded) {
      setExpanded(false);
      return;
    }
    setExpanded(true);
    if (versions.length > 0 || evidence.length > 0) return;
    setLoading(true);
    setError(null);
    try {
      const [versionPage, evidencePage] = await Promise.all([
        loadVersions(memoryId),
        loadEvidence(memoryId),
      ]);
      setVersions(versionPage.items);
      setEvidence(evidencePage.items);
      setVersionCursor(versionPage.next_cursor);
      setEvidenceCursor(evidencePage.next_cursor);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '历史记录加载失败。');
    } finally {
      setLoading(false);
    }
  }

  async function loadMoreVersions() {
    if (!versionCursor) return;
    setLoading(true);
    try {
      const page = await loadVersions(memoryId, versionCursor);
      setVersions((current) => [...current, ...page.items]);
      setVersionCursor(page.next_cursor);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '版本加载失败。');
    } finally {
      setLoading(false);
    }
  }

  async function loadMoreEvidence() {
    if (!evidenceCursor) return;
    setLoading(true);
    try {
      const page = await loadEvidence(memoryId, evidenceCursor);
      setEvidence((current) => [...current, ...page.items]);
      setEvidenceCursor(page.next_cursor);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : '证据加载失败。');
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="memory-history">
      <button type="button" aria-expanded={expanded} onClick={() => void open()}>
        {expanded ? '收起版本和证据' : '查看版本和证据'}
      </button>
      {expanded ? (
        <div className="memory-history__content">
          {loading ? <p aria-live="polite">历史加载中……</p> : null}
          {error ? <p role="alert" className="memory-panel__error">{error}</p> : null}
          <section aria-label="版本历史">
            <h4>版本历史</h4>
            {versions.length === 0 && !loading ? <p>暂无版本。</p> : null}
            <ol className="memory-history__list">
              {versions.map((version) => (
                <li key={version.id}>
                  <strong>版本 {version.version_number} · {OPERATION_LABELS[version.operation] ?? version.operation}</strong>
                  {version.content === null || version.redacted_at !== null ? (
                    <p className="memory-history__redacted">内容已忘记</p>
                  ) : (
                    <p>{version.content}</p>
                  )}
                  <small>{version.source_kind} · {version.created_at}</small>
                </li>
              ))}
            </ol>
            {versionCursor ? <button type="button" disabled={loading} onClick={() => void loadMoreVersions()}>加载更多版本</button> : null}
          </section>
          <section aria-label="来源证据">
            <h4>来源证据</h4>
            {evidence.length === 0 && !loading ? <p>暂无证据。</p> : null}
            <ul className="memory-history__list">
              {evidence.map((item) => (
                <li key={item.id}>
                  <strong>{RELATION_LABELS[item.relation] ?? item.relation} · {EXTRACTOR_LABELS[item.extractor_kind] ?? item.extractor_kind}</strong>
                  <p>{item.source_available ? '来源仍可用' : '来源已删除'}</p>
                  {item.source_available && item.source_session_id && item.source_message_id ? (
                    <small>会话 {item.source_session_id} · 消息 {item.source_message_id}</small>
                  ) : null}
                  <small>可信度 {item.confidence.toFixed(2)} · {item.observed_at}</small>
                </li>
              ))}
            </ul>
            {evidenceCursor ? <button type="button" disabled={loading} onClick={() => void loadMoreEvidence()}>加载更多证据</button> : null}
          </section>
        </div>
      ) : null}
    </section>
  );
}
