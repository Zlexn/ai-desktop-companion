import type { Message } from '../api/types';

const FALLBACK_LABEL = '助手消息';
const MAX_CODE_POINTS = 80;

export function displayLabelForAssistantMessage(
  messages: readonly Message[],
  assistantMessageId: string,
): string {
  const message = messages.find(
    (candidate) =>
      candidate.id === assistantMessageId && candidate.role === 'assistant',
  );
  const normalized = (message?.content ?? '').replace(/\s+/gu, ' ').trim();
  if (!normalized) return FALLBACK_LABEL;
  const codePoints = Array.from(normalized);
  return codePoints.length <= MAX_CODE_POINTS
    ? normalized
    : `${codePoints.slice(0, MAX_CODE_POINTS).join('')}…`;
}
