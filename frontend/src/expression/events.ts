import type {
  ExpressionDelivery,
  ExpressionIntensity,
  MessageExpressionResponse,
} from '../api/types';

const DELIVERIES = new Set<ExpressionDelivery>([
  'neutral',
  'warm',
  'reassuring',
  'reserved',
  'firm',
]);
const INTENSITIES = new Set<ExpressionIntensity>(['low', 'medium']);
const SOURCES = new Set<MessageExpressionResponse['source']>([
  'persisted_plan',
  'default',
]);
const INVALID_RESPONSE_MESSAGE = '表达服务返回了无法处理的结果。';

export interface ExpressionEvent {
  type: 'expression';
  assistantMessageId: string;
  schemaVersion: 1;
  delivery: ExpressionDelivery;
  intensity: ExpressionIntensity;
  rate: number;
  source: MessageExpressionResponse['source'];
}

export interface PlaybackRun {
  assistantMessageId: string;
  playbackRunId: number;
}

export interface SpeakingEvent extends PlaybackRun {
  type: 'speaking';
  phase: 'started' | 'paused' | 'resumed' | 'stopped' | 'interrupted' | 'failed';
}

export interface ResolvedExpression {
  event: ExpressionEvent;
  origin: 'api' | 'local_fallback';
}

export function parseMessageExpressionResponse(
  value: unknown,
): MessageExpressionResponse {
  if (typeof value !== 'object' || value === null) {
    throw new Error(INVALID_RESPONSE_MESSAGE);
  }
  const item = value as Record<string, unknown>;
  if (
    typeof item.assistant_message_id !== 'string' ||
    item.assistant_message_id.length === 0 ||
    item.schema_version !== 1 ||
    !DELIVERIES.has(item.delivery as ExpressionDelivery) ||
    !INTENSITIES.has(item.intensity as ExpressionIntensity) ||
    typeof item.rate !== 'number' ||
    !Number.isFinite(item.rate) ||
    item.rate < 0.9 ||
    item.rate > 1.1 ||
    !SOURCES.has(item.source as MessageExpressionResponse['source'])
  ) {
    throw new Error(INVALID_RESPONSE_MESSAGE);
  }
  return item as unknown as MessageExpressionResponse;
}

export function expressionEventFromApi(
  value: MessageExpressionResponse,
): ExpressionEvent {
  return {
    type: 'expression',
    assistantMessageId: value.assistant_message_id,
    schemaVersion: value.schema_version,
    delivery: value.delivery,
    intensity: value.intensity,
    rate: value.rate,
    source: value.source,
  };
}

export function localNeutralExpression(
  assistantMessageId: string,
): ResolvedExpression {
  return {
    origin: 'local_fallback',
    event: {
      type: 'expression',
      assistantMessageId,
      schemaVersion: 1,
      delivery: 'neutral',
      intensity: 'low',
      rate: 1,
      source: 'default',
    },
  };
}
