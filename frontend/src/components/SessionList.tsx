import type { Session } from '../api/types';

interface SessionListProps {
  sessions: Session[];
  activeSessionId: string | null;
  onCreateSession: () => void;
  onSelectSession: (sessionId: string) => void;
  onDeleteSession: (sessionId: string) => void;
}

export function SessionList({
  sessions,
  activeSessionId,
  onCreateSession,
  onSelectSession,
  onDeleteSession,
}: SessionListProps) {
  return (
    <aside className="session-list" aria-label="会话列表">
      <div className="session-list__header">
        <h1>AI 桌宠</h1>
        <button type="button" onClick={onCreateSession}>新建会话</button>
      </div>
      <div className="session-list__items">
        {sessions.length === 0 ? (
          <p className="empty-state">还没有会话。</p>
        ) : (
          sessions.map((session) => (
            <div
              className={session.id === activeSessionId ? 'session-item session-item--active' : 'session-item'}
              key={session.id}
            >
              <button type="button" onClick={() => onSelectSession(session.id)}>
                {session.title}
              </button>
              <button
                aria-label={`删除 ${session.title}`}
                className="session-item__delete"
                type="button"
                onClick={() => onDeleteSession(session.id)}
              >
                删除
              </button>
            </div>
          ))
        )}
      </div>
    </aside>
  );
}
