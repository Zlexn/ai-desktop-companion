import { describe, expect, it } from 'vitest';
import type { Message } from './api/types';
import { findAssistantReplyForVoiceTurn } from './voiceTurn';

function message(overrides: Partial<Message>): Message {
  return {
    id: overrides.id ?? 'm',
    session_id: overrides.session_id ?? 's1',
    role: overrides.role ?? 'user',
    content: overrides.content ?? '',
    created_at: overrides.created_at ?? '',
    metadata: overrides.metadata ?? {},
  };
}

describe('findAssistantReplyForVoiceTurn', () => {
  it('selects the new assistant message directly after the new transcript user message', () => {
    const before = [
      message({ id: 'u1', role: 'user', content: '旧消息' }),
      message({ id: 'a1', role: 'assistant', content: '旧回复' }),
    ];
    const after = [
      ...before,
      message({ id: 'u2', role: 'user', content: '语音转写文本' }),
      message({ id: 'a2', role: 'assistant', content: '新的助手回复' }),
    ];

    expect(findAssistantReplyForVoiceTurn({ before, after, transcript: '语音转写文本', sessionId: 's1' }))
      .toEqual(after[3]);
  });

  it('returns null when the active session changed', () => {
    const before = [message({ id: 'u1', session_id: 's1', role: 'user', content: '旧消息' })];
    const after = [
      ...before,
      message({ id: 'u2', session_id: 's2', role: 'user', content: '语音转写文本' }),
      message({ id: 'a2', session_id: 's2', role: 'assistant', content: '错误会话回复' }),
    ];

    expect(findAssistantReplyForVoiceTurn({ before, after, transcript: '语音转写文本', sessionId: 's1' }))
      .toBeNull();
  });

  it('returns null instead of using a blind newest-assistant heuristic', () => {
    const before = [message({ id: 'u1', role: 'user', content: '旧消息' })];
    const after = [
      ...before,
      message({ id: 'a2', role: 'assistant', content: '无对应用户消息的新回复' }),
    ];

    expect(findAssistantReplyForVoiceTurn({ before, after, transcript: '语音转写文本', sessionId: 's1' }))
      .toBeNull();
  });

  it('chooses the assistant after the matching new user transcript when multiple new messages exist', () => {
    const before = [message({ id: 'u1', role: 'user', content: '旧消息' })];
    const after = [
      ...before,
      message({ id: 'u2', role: 'user', content: '其他输入' }),
      message({ id: 'a2', role: 'assistant', content: '其他回复' }),
      message({ id: 'u3', role: 'user', content: '语音转写文本' }),
      message({ id: 'a3', role: 'assistant', content: '语音回合回复' }),
    ];

    expect(findAssistantReplyForVoiceTurn({ before, after, transcript: '语音转写文本', sessionId: 's1' }))
      .toEqual(after[4]);
  });
});
