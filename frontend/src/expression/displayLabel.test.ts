import { describe, expect, it } from 'vitest';
import type { Message } from '../api/types';
import { displayLabelForAssistantMessage } from './displayLabel';

function message(id: string, role: Message['role'], content: string): Message {
  return {
    id,
    session_id: 'session-1',
    role,
    content,
    created_at: '2026-07-14T00:00:00Z',
    metadata: {},
  };
}

describe('displayLabelForAssistantMessage', () => {
  it('folds whitespace and trims', () => {
    expect(
      displayLabelForAssistantMessage(
        [message('a', 'assistant', '  第一行\n\t第二行  ')],
        'a',
      ),
    ).toBe('第一行 第二行');
  });

  it('truncates by Unicode code point and appends one ellipsis', () => {
    const content = `${'雪'.repeat(79)}😀尾`;
    const label = displayLabelForAssistantMessage(
      [message('a', 'assistant', content)],
      'a',
    );
    expect(Array.from(label.slice(0, -1))).toHaveLength(80);
    expect(Array.from(label.slice(0, -1)).at(-1)).toBe('😀');
    expect(label.endsWith('😀…')).toBe(true);
  });

  it.each([
    [[], 'a'],
    [[message('a', 'user', 'not allowed')], 'a'],
    [[message('a', 'assistant', ' \n\t ')], 'a'],
  ] as const)(
    'uses the fixed fallback for missing, wrong-role, or empty content',
    (messages, id) => {
      expect(displayLabelForAssistantMessage(messages, id)).toBe('助手消息');
    },
  );
});
