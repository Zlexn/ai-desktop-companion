import { describe, expect, it } from 'vitest';
import type { ExpressionEvent, PlaybackRun, SpeakingEvent } from './events';
import {
  expressionPreviewReducer,
  initialExpressionPreviewState,
} from './previewReducer';

const expression: ExpressionEvent = {
  type: 'expression',
  assistantMessageId: 'a',
  schemaVersion: 1,
  delivery: 'warm',
  intensity: 'medium',
  rate: 1.04,
  source: 'persisted_plan',
};
const run1: PlaybackRun = { assistantMessageId: 'a', playbackRunId: 1 };
const run2: PlaybackRun = { assistantMessageId: 'a', playbackRunId: 2 };
const speaking = (
  run: PlaybackRun,
  phase: SpeakingEvent['phase'],
): SpeakingEvent => ({ type: 'speaking', ...run, phase });

it('moves idle to ready to speaking to paused and back to ready', () => {
  let state = expressionPreviewReducer(initialExpressionPreviewState, {
    type: 'targetSelected',
    assistantMessageId: 'a',
  });
  state = expressionPreviewReducer(state, {
    type: 'expressionResolved',
    expression,
  });
  state = expressionPreviewReducer(state, { type: 'runActivated', run: run1 });
  state = expressionPreviewReducer(state, {
    type: 'speaking',
    event: speaking(run1, 'started'),
  });
  expect(state.phase).toBe('speaking');
  state = expressionPreviewReducer(state, {
    type: 'speaking',
    event: speaking(run1, 'paused'),
  });
  expect(state.phase).toBe('paused');
  state = expressionPreviewReducer(state, {
    type: 'speaking',
    event: speaking(run1, 'resumed'),
  });
  expect(state.phase).toBe('speaking');
  state = expressionPreviewReducer(state, {
    type: 'speaking',
    event: speaking(run1, 'stopped'),
  });
  expect(state).toMatchObject({ phase: 'ready', activeRun: null, expression });
});

it('ignores late expression and every event from an old run', () => {
  let state = expressionPreviewReducer(initialExpressionPreviewState, {
    type: 'targetSelected',
    assistantMessageId: 'a',
  });
  state = expressionPreviewReducer(state, {
    type: 'expressionResolved',
    expression,
  });
  state = expressionPreviewReducer(state, { type: 'runActivated', run: run2 });
  const before = state;

  expect(
    expressionPreviewReducer(state, {
      type: 'speaking',
      event: speaking(run1, 'started'),
    }),
  ).toBe(before);
  expect(
    expressionPreviewReducer(state, {
      type: 'expressionResolved',
      expression: { ...expression, assistantMessageId: 'old' },
    }),
  ).toBe(before);
});

describe('terminal and clearing behavior', () => {
  it.each(['failed', 'interrupted'] as const)('handles %s for the active run', (phase) => {
    let state = expressionPreviewReducer(initialExpressionPreviewState, {
      type: 'targetSelected',
      assistantMessageId: 'a',
    });
    state = expressionPreviewReducer(state, {
      type: 'expressionResolved',
      expression,
    });
    state = expressionPreviewReducer(state, { type: 'runActivated', run: run1 });
    state = expressionPreviewReducer(state, {
      type: 'speaking',
      event: speaking(run1, phase),
    });
    expect(state).toMatchObject({ phase: 'ready', activeRun: null, expression });
  });

  it('ignores stale deactivation and clears all state explicitly', () => {
    let state = expressionPreviewReducer(initialExpressionPreviewState, {
      type: 'targetSelected',
      assistantMessageId: 'a',
    });
    state = expressionPreviewReducer(state, {
      type: 'expressionResolved',
      expression,
    });
    state = expressionPreviewReducer(state, { type: 'runActivated', run: run2 });
    expect(expressionPreviewReducer(state, { type: 'runDeactivated', run: run1 })).toBe(state);
    expect(expressionPreviewReducer(state, { type: 'cleared' })).toEqual(
      initialExpressionPreviewState,
    );
  });
});
