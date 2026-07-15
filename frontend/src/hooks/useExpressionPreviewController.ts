import { useCallback, useEffect, useReducer, useRef } from 'react';
import { apiClient } from '../api/client';
import type { ExpressionEvent, PlaybackRun, SpeakingEvent } from '../expression/events';
import {
  expressionEventFromApi,
  localNeutralExpression,
} from '../expression/events';
import {
  expressionPreviewReducer,
  initialExpressionPreviewState,
} from '../expression/previewReducer';

interface CacheEntry {
  sessionId: string;
  event: ExpressionEvent;
}

interface InFlightRequest {
  assistantMessageId: string;
  controller: AbortController;
  generation: number;
}

export function useExpressionPreviewController(currentSessionId: string | null) {
  const [state, dispatch] = useReducer(
    expressionPreviewReducer,
    initialExpressionPreviewState,
  );
  const targetRef = useRef<string | null>(null);
  const requestGenerationRef = useRef(0);
  const inFlightRef = useRef<InFlightRequest | null>(null);
  const cacheRef = useRef(new Map<string, CacheEntry>());
  const sessionRef = useRef(currentSessionId);
  sessionRef.current = currentSessionId;

  const selectAssistantMessage = useCallback((
    sessionId: string,
    assistantMessageId: string,
    options: { forceReload?: boolean } = {},
  ) => {
    targetRef.current = assistantMessageId;
    dispatch({ type: 'targetSelected', assistantMessageId });

    const cached = options.forceReload
      ? undefined
      : cacheRef.current.get(assistantMessageId);
    if (cached) {
      dispatch({ type: 'expressionResolved', expression: cached.event });
      return;
    }
    if (
      !options.forceReload &&
      inFlightRef.current?.assistantMessageId === assistantMessageId
    ) return;

    inFlightRef.current?.controller.abort();
    const controller = new AbortController();
    const generation = ++requestGenerationRef.current;
    inFlightRef.current = { assistantMessageId, controller, generation };

    void apiClient.getMessageExpression(assistantMessageId, {
      signal: controller.signal,
    }).then((response) => {
      if (
        controller.signal.aborted ||
        generation !== requestGenerationRef.current ||
        targetRef.current !== assistantMessageId
      ) return;
      const event = expressionEventFromApi(response);
      cacheRef.current.set(assistantMessageId, { sessionId, event });
      dispatch({ type: 'expressionResolved', expression: event });
    }).catch(() => {
      if (
        controller.signal.aborted ||
        generation !== requestGenerationRef.current ||
        targetRef.current !== assistantMessageId
      ) return;
      dispatch({
        type: 'expressionResolved',
        expression: localNeutralExpression(assistantMessageId).event,
      });
    }).finally(() => {
      if (inFlightRef.current?.generation === generation) {
        inFlightRef.current = null;
      }
    });
  }, []);

  const onRunActivated = useCallback((run: PlaybackRun): boolean => {
    const sessionId = sessionRef.current;
    if (!sessionId || !run.assistantMessageId) return false;
    dispatch({ type: 'runActivated', run });
    if (
      targetRef.current !== run.assistantMessageId ||
      (!cacheRef.current.has(run.assistantMessageId) &&
        inFlightRef.current?.assistantMessageId !== run.assistantMessageId)
    ) {
      selectAssistantMessage(sessionId, run.assistantMessageId);
    }
    return true;
  }, [selectAssistantMessage]);

  const onRunDeactivated = useCallback((run: PlaybackRun) => {
    dispatch({ type: 'runDeactivated', run });
  }, []);

  const onSpeakingEvent = useCallback((event: SpeakingEvent) => {
    dispatch({ type: 'speaking', event });
  }, []);

  const clear = useCallback(() => {
    requestGenerationRef.current += 1;
    inFlightRef.current?.controller.abort();
    inFlightRef.current = null;
    targetRef.current = null;
    dispatch({ type: 'cleared' });
  }, []);

  const dropSession = useCallback((sessionId: string) => {
    for (const [messageId, entry] of cacheRef.current) {
      if (entry.sessionId === sessionId) cacheRef.current.delete(messageId);
    }
  }, []);

  useEffect(() => clear, [clear]);

  return {
    state,
    selectAssistantMessage,
    onRunActivated,
    onRunDeactivated,
    onSpeakingEvent,
    clear,
    dropSession,
  };
}
