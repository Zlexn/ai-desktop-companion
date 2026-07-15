import { samePlaybackRun } from '../audio/playbackEvents';
import type { ExpressionEvent, PlaybackRun, SpeakingEvent } from './events';

export type PreviewPhase = 'idle' | 'ready' | 'speaking' | 'paused';

export interface ExpressionPreviewState {
  selectedAssistantMessageId: string | null;
  expression: ExpressionEvent | null;
  activeRun: PlaybackRun | null;
  phase: PreviewPhase;
}

export type PreviewAction =
  | { type: 'targetSelected'; assistantMessageId: string }
  | { type: 'expressionResolved'; expression: ExpressionEvent }
  | { type: 'runActivated'; run: PlaybackRun }
  | { type: 'speaking'; event: SpeakingEvent }
  | { type: 'runDeactivated'; run: PlaybackRun }
  | { type: 'cleared' };

export const initialExpressionPreviewState: ExpressionPreviewState = {
  selectedAssistantMessageId: null,
  expression: null,
  activeRun: null,
  phase: 'idle',
};

export function expressionPreviewReducer(
  state: ExpressionPreviewState,
  action: PreviewAction,
): ExpressionPreviewState {
  if (action.type === 'cleared') return initialExpressionPreviewState;
  if (action.type === 'targetSelected') {
    if (state.selectedAssistantMessageId === action.assistantMessageId) return state;
    return {
      selectedAssistantMessageId: action.assistantMessageId,
      expression: null,
      activeRun: null,
      phase: 'idle',
    };
  }
  if (action.type === 'expressionResolved') {
    if (action.expression.assistantMessageId !== state.selectedAssistantMessageId) {
      return state;
    }
    return {
      ...state,
      expression: action.expression,
      phase: state.activeRun ? state.phase : 'ready',
    };
  }
  if (action.type === 'runActivated') {
    const changedMessage =
      state.selectedAssistantMessageId !== action.run.assistantMessageId;
    return {
      selectedAssistantMessageId: action.run.assistantMessageId,
      expression: changedMessage ? null : state.expression,
      activeRun: action.run,
      phase: changedMessage || !state.expression ? 'idle' : 'ready',
    };
  }
  if (action.type === 'runDeactivated') {
    if (!samePlaybackRun(state.activeRun, action.run)) return state;
    return {
      ...state,
      activeRun: null,
      phase: state.expression ? 'ready' : 'idle',
    };
  }
  if (!samePlaybackRun(state.activeRun, action.event)) return state;
  if (action.event.phase === 'started' || action.event.phase === 'resumed') {
    return { ...state, phase: 'speaking' };
  }
  if (action.event.phase === 'paused') {
    return { ...state, phase: 'paused' };
  }
  return {
    ...state,
    activeRun: null,
    phase: state.expression ? 'ready' : 'idle',
  };
}
