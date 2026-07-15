import { describe, expect, it } from 'vitest';
import {
  expressionEventFromApi,
  localNeutralExpression,
  parseMessageExpressionResponse,
} from './events';

const valid = {
  assistant_message_id: 'assistant-1',
  schema_version: 1,
  delivery: 'reassuring',
  intensity: 'medium',
  rate: 0.96,
  source: 'persisted_plan',
};

describe('parseMessageExpressionResponse', () => {
  it('accepts and maps the complete v1 response', () => {
    const parsed = parseMessageExpressionResponse(valid);
    expect(expressionEventFromApi(parsed)).toEqual({
      type: 'expression',
      assistantMessageId: 'assistant-1',
      schemaVersion: 1,
      delivery: 'reassuring',
      intensity: 'medium',
      rate: 0.96,
      source: 'persisted_plan',
    });
  });

  it.each([
    null,
    {},
    { ...valid, assistant_message_id: '' },
    { ...valid, schema_version: 2 },
    { ...valid, delivery: 'excited' },
    { ...valid, intensity: 'high' },
    { ...valid, rate: Number.NaN },
    { ...valid, rate: 0.89 },
    { ...valid, rate: 1.11 },
    { ...valid, source: 'client' },
  ])('rejects an invalid wire payload %#', (payload) => {
    expect(() => parseMessageExpressionResponse(payload)).toThrow(
      '表达服务返回了无法处理的结果。',
    );
  });

  it('creates a neutral local fallback with a distinct internal origin', () => {
    expect(localNeutralExpression('assistant-2')).toEqual({
      origin: 'local_fallback',
      event: {
        type: 'expression',
        assistantMessageId: 'assistant-2',
        schemaVersion: 1,
        delivery: 'neutral',
        intensity: 'low',
        rate: 1,
        source: 'default',
      },
    });
  });
});
