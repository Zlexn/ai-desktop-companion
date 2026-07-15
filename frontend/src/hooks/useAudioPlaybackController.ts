import { useCallback, useEffect, useRef, useState } from 'react';
import { apiClient } from '../api/client';
import type { SpeechSynthesisResponse } from '../api/types';
import { samePlaybackRun } from '../audio/playbackEvents';
import type { PlaybackRun, SpeakingEvent } from '../expression/events';
import {
  createStreamingAudioScheduler,
  type StreamingAudioScheduler,
} from '../audio/streamingAudioScheduler';

type AudioState = 'idle' | 'synthesizing' | 'ready' | 'playing' | 'paused' | 'error';

interface AudioEntry {
  state: AudioState;
  url: string | null;
  error: string | null;
  metadata: Omit<SpeechSynthesisResponse, 'blob'> | null;
}

export interface MessageAudioState {
  state: AudioState;
  isActive: boolean;
  error: string | null;
  metadata: Omit<SpeechSynthesisResponse, 'blob'> | null;
}

export interface UseAudioPlaybackControllerOptions {
  audioOutputDeviceId?: string;
  onRunActivated?: (run: PlaybackRun) => boolean;
  onRunDeactivated?: (run: PlaybackRun) => void;
  onSpeakingEvent?: (event: SpeakingEvent) => void;
}

interface PlayOptions {
  streaming?: boolean;
}

interface PlaybackToken {
  run: PlaybackRun;
  generation: number;
}

interface ActivePlayback {
  token: PlaybackToken;
  abortController: AbortController | null;
  scheduler: StreamingAudioScheduler | null;
  htmlQueue: string[];
  htmlEndedListener: (() => void) | null;
  hasStarted: boolean;
  paused: boolean;
  controlGeneration: number;
  pendingControl: 'pause' | 'resume' | null;
  streaming: boolean;
}

const OUTPUT_DEVICE_ERROR_MESSAGE = '无法切换到选择的输出设备，请改用系统默认输出后重试。';
const NO_AUDIO_ERROR_MESSAGE = '语音合成服务没有返回可播放音频。';
const defaultEntry: AudioEntry = {
  state: 'idle',
  url: null,
  error: null,
  metadata: null,
};

function errorMessage(error: unknown): string {
  if (error instanceof DOMException && error.name === 'AbortError') {
    return '语音生成已取消。';
  }
  return error instanceof Error ? error.message : '语音播放失败，请稍后重试。';
}

function playbackErrorMessage(error: unknown): string {
  return error instanceof DOMException &&
    ['NotAllowedError', 'NotFoundError', 'AbortError'].includes(error.name)
    ? OUTPUT_DEVICE_ERROR_MESSAGE
    : errorMessage(error);
}

async function applySinkId(
  audio: HTMLAudioElement,
  audioOutputDeviceId: string,
): Promise<void> {
  const setSinkId = audio.setSinkId;
  if (typeof setSinkId !== 'function') return;
  await setSinkId.call(audio, audioOutputDeviceId);
}

export function useAudioPlaybackController(
  options: UseAudioPlaybackControllerOptions = {},
) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  if (!audioRef.current) audioRef.current = new Audio();

  const callbacksRef = useRef(options);
  callbacksRef.current = options;
  const audioOutputDeviceIdRef = useRef(options.audioOutputDeviceId ?? '');
  audioOutputDeviceIdRef.current = options.audioOutputDeviceId ?? '';

  const nextPlaybackRunIdRef = useRef(0);
  const nextGenerationRef = useRef(0);
  const activePlaybackRef = useRef<ActivePlayback | null>(null);
  const urlsRef = useRef<Map<string, Set<string>>>(new Map());

  const [activeMessageId, setActiveMessageId] = useState<string | null>(null);
  const [entries, setEntries] = useState<Record<string, AudioEntry>>({});

  const updateEntry = useCallback((messageId: string, patch: Partial<AudioEntry>) => {
    setEntries((current) => ({
      ...current,
      [messageId]: { ...(current[messageId] ?? defaultEntry), ...patch },
    }));
  }, []);

  const rememberUrl = useCallback((messageId: string, url: string) => {
    const urls = urlsRef.current.get(messageId) ?? new Set<string>();
    urls.add(url);
    urlsRef.current.set(messageId, urls);
  }, []);

  const revokeUrls = useCallback((messageId: string) => {
    const urls = urlsRef.current.get(messageId);
    if (!urls) return;
    for (const url of urls) URL.revokeObjectURL(url);
    urlsRef.current.delete(messageId);
  }, []);

  const isCurrentToken = useCallback((token: PlaybackToken): boolean => {
    const active = activePlaybackRef.current;
    return (
      active !== null &&
      active.token.generation === token.generation &&
      samePlaybackRun(active.token.run, token.run)
    );
  }, []);

  const emitSpeaking = useCallback(
    (token: PlaybackToken, phase: SpeakingEvent['phase']) => {
      if (!isCurrentToken(token)) return;
      callbacksRef.current.onSpeakingEvent?.({
        type: 'speaking',
        ...token.run,
        phase,
      });
    },
    [isCurrentToken],
  );

  const removeHtmlListener = useCallback((active: ActivePlayback) => {
    const audio = audioRef.current;
    if (!audio || !active.htmlEndedListener) return;
    audio.removeEventListener('ended', active.htmlEndedListener);
    active.htmlEndedListener = null;
  }, []);

  const finishRun = useCallback(
    (
      token: PlaybackToken,
      phase: 'stopped' | 'interrupted' | 'failed',
      patch: Partial<AudioEntry>,
      options: { revokeStreamingUrls?: boolean } = {},
    ) => {
      if (!isCurrentToken(token)) return;
      const active = activePlaybackRef.current;
      if (!active) return;

      activePlaybackRef.current = null;
      nextGenerationRef.current += 1;
      active.abortController?.abort();
      active.scheduler?.stop();
      void active.scheduler?.dispose();
      removeHtmlListener(active);

      const audio = audioRef.current;
      if (audio) {
        audio.muted = true;
        audio.pause();
        audio.currentTime = 0;
      }
      if (options.revokeStreamingUrls && active.streaming) {
        revokeUrls(token.run.assistantMessageId);
      } else if (phase === 'failed' && active.streaming) {
        revokeUrls(token.run.assistantMessageId);
      }
      updateEntry(token.run.assistantMessageId, patch);
      setActiveMessageId(null);
      callbacksRef.current.onSpeakingEvent?.({
        type: 'speaking',
        ...token.run,
        phase,
      });
      callbacksRef.current.onRunDeactivated?.(token.run);
    },
    [isCurrentToken, removeHtmlListener, revokeUrls, updateEntry],
  );

  const interruptActive = useCallback(() => {
    const active = activePlaybackRef.current;
    if (!active) return;
    const messageId = active.token.run.assistantMessageId;
    const cachedUrl = entries[messageId]?.url ?? null;
    finishRun(
      active.token,
      'interrupted',
      {
        state: active.streaming ? 'idle' : cachedUrl ? 'ready' : 'idle',
        error: null,
      },
      { revokeStreamingUrls: true },
    );
  }, [entries, finishRun]);

  const beginRun = useCallback(
    (messageId: string, streaming: boolean): PlaybackToken | null => {
      interruptActive();
      const token: PlaybackToken = {
        run: {
          assistantMessageId: messageId,
          playbackRunId: ++nextPlaybackRunIdRef.current,
        },
        generation: ++nextGenerationRef.current,
      };
      if (callbacksRef.current.onRunActivated?.(token.run) === false) {
        return null;
      }
      activePlaybackRef.current = {
        token,
        abortController: null,
        scheduler: null,
        htmlQueue: [],
        htmlEndedListener: null,
        hasStarted: false,
        paused: false,
        controlGeneration: 0,
        pendingControl: null,
        streaming,
      };
      setActiveMessageId(messageId);
      return token;
    },
    [interruptActive],
  );

  const markStarted = useCallback(
    (token: PlaybackToken) => {
      if (!isCurrentToken(token)) return;
      const active = activePlaybackRef.current;
      if (!active || active.hasStarted) return;
      active.hasStarted = true;
      emitSpeaking(token, 'started');
    },
    [emitSpeaking, isCurrentToken],
  );

  const playHtmlUrl = useCallback(
    async (token: PlaybackToken, url: string): Promise<boolean> => {
      if (!isCurrentToken(token)) return false;
      const active = activePlaybackRef.current;
      const audio = audioRef.current;
      if (!active || !audio) return false;

      removeHtmlListener(active);
      const endedListener = () => {
        if (!isCurrentToken(token)) return;
        const current = activePlaybackRef.current;
        const nextUrl = current?.htmlQueue.shift();
        if (nextUrl) {
          void playHtmlUrl(token, nextUrl);
          return;
        }
        finishRun(
          token,
          'stopped',
          {
            state: active.streaming ? 'idle' : 'ready',
            url: active.streaming ? null : url,
            error: null,
          },
          { revokeStreamingUrls: active.streaming },
        );
      };
      active.htmlEndedListener = endedListener;
      audio.addEventListener('ended', endedListener);
      audio.muted = false;
      audio.src = url;

      try {
        await applySinkId(audio, audioOutputDeviceIdRef.current);
        if (!isCurrentToken(token)) return false;
        await audio.play();
        if (!isCurrentToken(token)) return false;
        updateEntry(token.run.assistantMessageId, {
          state: 'playing',
          url,
          error: null,
        });
        markStarted(token);
        return true;
      } catch (caught) {
        if (!isCurrentToken(token)) return false;
        finishRun(token, 'failed', {
          state: 'error',
          error: playbackErrorMessage(caught),
        });
        return false;
      }
    },
    [finishRun, isCurrentToken, markStarted, removeHtmlListener, updateEntry],
  );

  const queueHtmlSegment = useCallback(
    async (
      token: PlaybackToken,
      event: {
        audioBytes: Uint8Array;
        mediaType: 'audio/wav';
        durationMs: number;
        sampleRate: number;
      },
      metadata: { provider: string | null; model: string | null },
    ): Promise<boolean> => {
      if (!isCurrentToken(token)) return false;
      const bytes = new Uint8Array(event.audioBytes);
      const url = URL.createObjectURL(
        new Blob([bytes.buffer], { type: event.mediaType }),
      );
      rememberUrl(token.run.assistantMessageId, url);
      const active = activePlaybackRef.current;
      if (!active) return false;
      updateEntry(token.run.assistantMessageId, {
        state: active.paused ? 'paused' : active.hasStarted ? 'playing' : 'ready',
        url,
        error: null,
        metadata: {
          provider: metadata.provider,
          model: metadata.model,
          durationMs: event.durationMs,
          sampleRate: event.sampleRate,
        },
      });
      const htmlAlreadyPlaying = active.htmlEndedListener !== null;
      if (htmlAlreadyPlaying) {
        active.htmlQueue.push(url);
        return true;
      }
      return playHtmlUrl(token, url);
    },
    [isCurrentToken, playHtmlUrl, rememberUrl, updateEntry],
  );

  const play = useCallback(
    async (messageId: string, playOptions: PlayOptions = {}): Promise<boolean> => {
      const existing = entries[messageId];
      const streaming = playOptions.streaming === true;
      const token = beginRun(messageId, streaming);
      if (!token) return false;

      if (!streaming && existing?.url) {
        return playHtmlUrl(token, existing.url);
      }

      const abortController = new AbortController();
      const active = activePlaybackRef.current;
      if (!active || !isCurrentToken(token)) return false;
      active.abortController = abortController;
      updateEntry(messageId, { state: 'synthesizing', error: null });

      if (!streaming) {
        try {
          const result = await apiClient.synthesizeMessageSpeech(messageId, {
            signal: abortController.signal,
          });
          if (!isCurrentToken(token) || abortController.signal.aborted) return false;
          revokeUrls(messageId);
          const url = URL.createObjectURL(result.blob);
          rememberUrl(messageId, url);
          updateEntry(messageId, {
            state: 'ready',
            url,
            error: null,
            metadata: {
              provider: result.provider,
              model: result.model,
              durationMs: result.durationMs,
              sampleRate: result.sampleRate,
            },
          });
          return playHtmlUrl(token, url);
        } catch (caught) {
          if (!isCurrentToken(token) || abortController.signal.aborted) return false;
          finishRun(token, 'failed', {
            state: 'error',
            error: errorMessage(caught),
          });
          return false;
        }
      }

      let scheduler: StreamingAudioScheduler | null = null;
      try {
        scheduler = createStreamingAudioScheduler({
          audioOutputDeviceId: audioOutputDeviceIdRef.current,
        });
        if (!scheduler.isSupported()) {
          void scheduler.dispose();
          scheduler = null;
        }
        if (!isCurrentToken(token)) {
          scheduler?.stop();
          return false;
        }
        activePlaybackRef.current!.scheduler = scheduler;

        let provider: string | null = null;
        let model: string | null = null;
        for await (const event of apiClient.streamMessageSpeech(messageId, {
          signal: abortController.signal,
        })) {
          if (!isCurrentToken(token) || abortController.signal.aborted) return false;
          if (event.type === 'start') {
            provider = event.provider;
            model = event.model;
            continue;
          }
          if (event.type === 'error') throw new Error(event.message);
          if (event.type !== 'segment') continue;

          const segment = {
            audioBytes: event.audioBytes,
            mediaType: event.mediaType,
            durationMs: event.durationMs,
            sampleRate: event.sampleRate,
          };
          if (scheduler) {
            try {
              await scheduler.enqueue(segment);
              if (
                !isCurrentToken(token) ||
                abortController.signal.aborted ||
                activePlaybackRef.current?.scheduler !== scheduler
              ) {
                return false;
              }
              updateEntry(messageId, {
                state: activePlaybackRef.current.paused ? 'paused' : 'playing',
                url: null,
                error: null,
                metadata: {
                  provider,
                  model,
                  durationMs: event.durationMs,
                  sampleRate: event.sampleRate,
                },
              });
              markStarted(token);
              continue;
            } catch {
              if (!isCurrentToken(token)) return false;
              scheduler.stop();
              void scheduler.dispose();
              if (activePlaybackRef.current?.scheduler === scheduler) {
                activePlaybackRef.current.scheduler = null;
              }
              scheduler = null;
            }
          }
          if (!(await queueHtmlSegment(token, segment, { provider, model }))) {
            return false;
          }
        }

        if (!isCurrentToken(token)) return false;
        const current = activePlaybackRef.current;
        if (!current?.hasStarted) {
          finishRun(token, 'failed', {
            state: 'error',
            error: NO_AUDIO_ERROR_MESSAGE,
          });
          return false;
        }
        if (scheduler && current.scheduler === scheduler) {
          void scheduler.waitForIdle().then(
            () => {
              if (
                !isCurrentToken(token) ||
                activePlaybackRef.current?.scheduler !== scheduler
              ) return;
              finishRun(token, 'stopped', { state: 'ready', error: null });
            },
            (caught: unknown) => {
              if (!isCurrentToken(token)) return;
              finishRun(token, 'failed', {
                state: 'error',
                error: errorMessage(caught),
              });
            },
          );
        }
        return true;
      } catch (caught) {
        if (!isCurrentToken(token) || abortController.signal.aborted) return false;
        finishRun(token, 'failed', {
          state: 'error',
          error: errorMessage(caught),
        });
        return false;
      }
    },
    [
      beginRun,
      entries,
      finishRun,
      isCurrentToken,
      markStarted,
      playHtmlUrl,
      queueHtmlSegment,
      rememberUrl,
      revokeUrls,
      updateEntry,
    ],
  );

  const pause = useCallback(
    (messageId: string) => {
      const active = activePlaybackRef.current;
      if (!active || active.token.run.assistantMessageId !== messageId) return;
      const { token, scheduler } = active;
      const controlGeneration = ++active.controlGeneration;
      active.pendingControl = 'pause';
      if (scheduler) {
        void scheduler.pause().then(
          () => {
            const current = activePlaybackRef.current;
            if (
              !isCurrentToken(token) ||
              current?.scheduler !== scheduler ||
              current.controlGeneration !== controlGeneration ||
              current.pendingControl !== 'pause'
            ) return;
            current.pendingControl = null;
            current.paused = true;
            updateEntry(messageId, { state: 'paused' });
            emitSpeaking(token, 'paused');
          },
          (caught: unknown) => {
            const current = activePlaybackRef.current;
            if (
              !isCurrentToken(token) ||
              current?.scheduler !== scheduler ||
              current.controlGeneration !== controlGeneration ||
              current.pendingControl !== 'pause'
            ) return;
            current.pendingControl = null;
            finishRun(token, 'failed', {
              state: 'error',
              error: errorMessage(caught),
            });
          },
        );
        return;
      }
      audioRef.current?.pause();
      active.pendingControl = null;
      active.paused = true;
      updateEntry(messageId, { state: 'paused' });
      emitSpeaking(token, 'paused');
    },
    [emitSpeaking, finishRun, isCurrentToken, updateEntry],
  );

  const resume = useCallback(
    async (messageId: string): Promise<boolean> => {
      const active = activePlaybackRef.current;
      const entry = entries[messageId];
      if (
        !active ||
        active.token.run.assistantMessageId !== messageId ||
        entry?.state !== 'paused'
      ) return false;
      const { token, scheduler } = active;
      const controlGeneration = ++active.controlGeneration;
      active.pendingControl = 'resume';
      try {
        if (scheduler) {
          await scheduler.resume();
          const current = activePlaybackRef.current;
          if (
            !isCurrentToken(token) ||
            current?.scheduler !== scheduler ||
            current.controlGeneration !== controlGeneration ||
            current.pendingControl !== 'resume'
          ) return false;
        } else {
          const audio = audioRef.current;
          if (!audio) return false;
          await audio.play();
          const current = activePlaybackRef.current;
          if (
            !isCurrentToken(token) ||
            current?.controlGeneration !== controlGeneration ||
            current.pendingControl !== 'resume'
          ) return false;
        }
        const current = activePlaybackRef.current;
        if (
          !current ||
          !samePlaybackRun(current.token.run, token.run) ||
          current.controlGeneration !== controlGeneration ||
          current.pendingControl !== 'resume'
        ) return false;
        current.pendingControl = null;
        current.paused = false;
        updateEntry(messageId, { state: 'playing', error: null });
        emitSpeaking(token, 'resumed');
        return true;
      } catch (caught) {
        const current = activePlaybackRef.current;
        if (
          !isCurrentToken(token) ||
          current?.controlGeneration !== controlGeneration ||
          current.pendingControl !== 'resume' ||
          current.scheduler !== scheduler
        ) return false;
        current.pendingControl = null;
        finishRun(token, 'failed', {
          state: 'error',
          error: playbackErrorMessage(caught),
        });
        return false;
      }
    },
    [emitSpeaking, entries, finishRun, isCurrentToken, updateEntry],
  );

  const stop = useCallback(
    (messageId: string) => {
      const active = activePlaybackRef.current;
      if (!active || active.token.run.assistantMessageId !== messageId) return;
      const cachedUrl = entries[messageId]?.url ?? null;
      finishRun(
        active.token,
        'stopped',
        {
          state: active.streaming ? 'idle' : cachedUrl ? 'ready' : 'idle',
          error: null,
        },
        { revokeStreamingUrls: true },
      );
    },
    [entries, finishRun],
  );

  const replay = useCallback(
    (messageId: string): Promise<boolean> => play(messageId),
    [play],
  );

  const reset = useCallback(
    (reason: 'interrupted' | 'stopped' = 'interrupted') => {
      const active = activePlaybackRef.current;
      if (active) {
        finishRun(
          active.token,
          reason,
          { state: 'idle', error: null },
          { revokeStreamingUrls: true },
        );
      }
      for (const messageId of urlsRef.current.keys()) revokeUrls(messageId);
      setEntries({});
      setActiveMessageId(null);
    },
    [finishRun, revokeUrls],
  );

  useEffect(() => reset, [reset]);

  function stateFor(messageId: string): MessageAudioState {
    const entry = entries[messageId] ?? defaultEntry;
    return {
      state: entry.state,
      isActive: activeMessageId === messageId,
      error: entry.error,
      metadata: entry.metadata,
    };
  }

  const isAudioBusy = Object.values(entries).some((entry) =>
    entry.state === 'synthesizing' ||
    entry.state === 'playing' ||
    entry.state === 'paused',
  );

  return { isAudioBusy, pause, play, replay, reset, resume, stateFor, stop };
}
