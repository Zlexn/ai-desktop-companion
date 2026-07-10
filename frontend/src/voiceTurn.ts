import type { Message } from './api/types';

interface FindAssistantReplyArgs {
  before: Message[];
  after: Message[];
  transcript: string;
  sessionId: string;
}

export function findAssistantReplyForVoiceTurn({ before, after, transcript, sessionId }: FindAssistantReplyArgs): Message | null {
  const cleanTranscript = transcript.trim();
  if (!cleanTranscript) return null;

  const beforeIds = new Set(before.map((item) => item.id));
  const isNewInSession = (message: Message) => message.session_id === sessionId && !beforeIds.has(message.id);

  const userIndex = after.findIndex(
    (item) => isNewInSession(item) && item.role === 'user' && item.content.trim() === cleanTranscript,
  );
  if (userIndex < 0) return null;

  for (const item of after.slice(userIndex + 1)) {
    if (!isNewInSession(item)) continue;
    if (item.role === 'assistant') return item;
    if (item.role === 'user') return null;
  }

  return null;
}
