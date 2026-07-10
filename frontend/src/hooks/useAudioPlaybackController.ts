import { useCallback, useEffect, useRef, useState } from 'react';
import { apiClient } from '../api/client';
import type { SpeechSynthesisResponse } from '../api/types';
import { createStreamingAudioScheduler, type StreamingAudioScheduler } from '../audio/streamingAudioScheduler';

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

interface UseAudioPlaybackControllerOptions {
  audioOutputDeviceId?: string;
}

interface PlayOptions {
  streaming?: boolean;
}

const OUTPUT_DEVICE_ERROR_MESSAGE = '无法切换到选择的输出设备，请改用系统默认输出后重试。';

const defaultEntry: AudioEntry = { state: 'idle', url: null, error: null, metadata: null };

function errorMessage(error: unknown): string {
  if (error instanceof DOMException && error.name === 'AbortError') return '语音生成已取消。';
  return error instanceof Error ? error.message : '语音播放失败，请稍后重试。';
}

async function applySinkId(audio: HTMLAudioElement, audioOutputDeviceId: string): Promise<void> {
  const setSinkId = audio.setSinkId;
  if (typeof setSinkId !== 'function') return;
  await setSinkId.call(audio, audioOutputDeviceId);
}

export function useAudioPlaybackController(options: UseAudioPlaybackControllerOptions = {}) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const activeMessageIdRef = useRef<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const urlsRef = useRef<Map<string, Set<string>>>(new Map());
  const streamingQueuesRef = useRef<Map<string, string[]>>(new Map());
  const streamingMessageIdsRef = useRef<Set<string>>(new Set());
  const pausedStreamingMessageIdsRef = useRef<Set<string>>(new Set());
  const streamingSchedulerRef = useRef<StreamingAudioScheduler | null>(null);
  const audioOutputDeviceIdRef = useRef(options.audioOutputDeviceId ?? '');
  audioOutputDeviceIdRef.current = options.audioOutputDeviceId ?? '';
  const [activeMessageId, setActiveMessageId] = useState<string | null>(null);
  const [entries, setEntries] = useState<Record<string, AudioEntry>>({});

  if (!audioRef.current) {
    const audio = new Audio();
    audio.addEventListener('ended', async () => {
      const messageId = activeMessageIdRef.current;
      if (messageId) {
        const queue = streamingQueuesRef.current.get(messageId) ?? [];
        const nextUrl = queue.shift();
        if (nextUrl) {
          streamingQueuesRef.current.set(messageId, queue);
          audio.src = nextUrl;
          try {
            await applySinkId(audio, audioOutputDeviceIdRef.current);
            await audio.play();
            setEntries((current) => ({
              ...current,
              [messageId]: { ...(current[messageId] ?? defaultEntry), state: 'playing', url: nextUrl, error: null },
            }));
          } catch (caught) {
            const message = caught instanceof DOMException && ['NotAllowedError', 'NotFoundError', 'AbortError'].includes(caught.name)
              ? OUTPUT_DEVICE_ERROR_MESSAGE
              : errorMessage(caught);
            setEntries((current) => ({
              ...current,
              [messageId]: { ...(current[messageId] ?? defaultEntry), state: 'error', error: message },
            }));
            setActive(null);
          }
          return;
        }
        setEntries((current) => ({
          ...current,
          [messageId]: { ...(current[messageId] ?? defaultEntry), state: 'ready' },
        }));
      }
    });
    audioRef.current = audio;
  }

  const setActive = useCallback((messageId: string | null) => {
    activeMessageIdRef.current = messageId;
    setActiveMessageId(messageId);
  }, []);

  const updateEntry = useCallback((messageId: string, patch: Partial<AudioEntry>) => {
    setEntries((current) => ({
      ...current,
      [messageId]: { ...(current[messageId] ?? defaultEntry), ...patch },
    }));
  }, []);

  const revokeUrl = useCallback((messageId: string) => {
    const urls = urlsRef.current.get(messageId);
    if (urls) {
      for (const url of urls) {
        URL.revokeObjectURL(url);
      }
      urlsRef.current.delete(messageId);
    }
    streamingQueuesRef.current.delete(messageId);
    streamingMessageIdsRef.current.delete(messageId);
    pausedStreamingMessageIdsRef.current.delete(messageId);
  }, []);

  const rememberUrl = useCallback((messageId: string, url: string) => {
    const urls = urlsRef.current.get(messageId) ?? new Set<string>();
    urls.add(url);
    urlsRef.current.set(messageId, urls);
  }, []);

  const stopActive = useCallback((options: { revokeMessageUrls?: boolean } = {}) => {
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    streamingSchedulerRef.current?.stop();
    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      audio.currentTime = 0;
    }
    const messageId = activeMessageIdRef.current;
    if (messageId) {
      pausedStreamingMessageIdsRef.current.delete(messageId);
      const shouldRevokeUrls = options.revokeMessageUrls && streamingMessageIdsRef.current.has(messageId);
      if (shouldRevokeUrls) {
        revokeUrl(messageId);
      }
      setEntries((current) => ({
        ...current,
        [messageId]: { ...(current[messageId] ?? defaultEntry), state: shouldRevokeUrls ? 'idle' : current[messageId]?.url ? 'ready' : 'idle' },
      }));
    }
    setActive(null);
  }, [revokeUrl, setActive]);

  const playExisting = useCallback(async (messageId: string, url: string): Promise<boolean> => {
    if (activeMessageIdRef.current && activeMessageIdRef.current !== messageId) {
      stopActive();
    }
    const audio = audioRef.current;
    if (!audio) return false;
    setActive(messageId);
    audio.src = url;
    try {
      await applySinkId(audio, audioOutputDeviceIdRef.current);
      await audio.play();
      updateEntry(messageId, { state: 'playing', error: null });
      return true;
    } catch (caught) {
      const message = caught instanceof DOMException && ['NotAllowedError', 'NotFoundError', 'AbortError'].includes(caught.name)
        ? OUTPUT_DEVICE_ERROR_MESSAGE
        : errorMessage(caught);
      updateEntry(messageId, { state: 'error', error: message });
      setActive(null);
      return false;
    }
  }, [setActive, stopActive, updateEntry]);

  const queueHtmlStreamingSegment = useCallback(async (
    messageId: string,
    event: { audioBytes: Uint8Array; mediaType: 'audio/wav'; durationMs: number; sampleRate: number },
    metadata: { provider: string | null; model: string | null },
    startedPlayback: boolean,
  ): Promise<boolean> => {
    const audioBytes = new Uint8Array(event.audioBytes);
    const url = URL.createObjectURL(new Blob([audioBytes.buffer], { type: event.mediaType }));
    rememberUrl(messageId, url);
    updateEntry(messageId, {
      state: startedPlayback ? 'playing' : 'ready',
      url,
      error: null,
      metadata: {
        provider: metadata.provider,
        model: metadata.model,
        durationMs: event.durationMs,
        sampleRate: event.sampleRate,
      },
    });
    if (!startedPlayback) {
      return playExisting(messageId, url);
    }
    const queue = streamingQueuesRef.current.get(messageId) ?? [];
    queue.push(url);
    streamingQueuesRef.current.set(messageId, queue);
    return true;
  }, [playExisting, rememberUrl, updateEntry]);

  const play = useCallback(async (messageId: string, text: string, options: PlayOptions = {}): Promise<boolean> => {
    const existing = entries[messageId];
    if (existing?.state === 'synthesizing') return false;
    if (!options.streaming && existing?.url) {
      return playExisting(messageId, existing.url);
    }

    if (activeMessageIdRef.current && activeMessageIdRef.current !== messageId) {
      stopActive();
    }
    abortControllerRef.current?.abort();
    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    setActive(messageId);
    updateEntry(messageId, { state: 'synthesizing', error: null });

    if (options.streaming) {
      streamingMessageIdsRef.current.add(messageId);
      pausedStreamingMessageIdsRef.current.delete(messageId);
      const previousScheduler = streamingSchedulerRef.current;
      previousScheduler?.stop();
      void previousScheduler?.dispose();
      streamingSchedulerRef.current = null;
      try {
        streamingSchedulerRef.current = createStreamingAudioScheduler({ audioOutputDeviceId: audioOutputDeviceIdRef.current });
        if (!streamingSchedulerRef.current.isSupported()) {
          void streamingSchedulerRef.current.dispose();
          streamingSchedulerRef.current = null;
        }
        let startedPlayback = false;
        let provider: string | null = null;
        let model: string | null = null;
        for await (const event of apiClient.streamSpeech(text, { signal: abortController.signal })) {
          if (abortController.signal.aborted || activeMessageIdRef.current !== messageId) return false;
          if (event.type === 'start') {
            provider = event.provider;
            model = event.model;
          }
          if (event.type === 'segment') {
            const segment = {
              audioBytes: new Uint8Array(event.audioBytes),
              mediaType: event.mediaType,
              durationMs: event.durationMs,
              sampleRate: event.sampleRate,
            };

            if (streamingSchedulerRef.current?.isSupported()) {
              try {
                await streamingSchedulerRef.current.enqueue(segment);
                if (abortController.signal.aborted || activeMessageIdRef.current !== messageId) {
                  streamingSchedulerRef.current?.stop();
                  return false;
                }
                startedPlayback = true;
                updateEntry(messageId, {
                  state: pausedStreamingMessageIdsRef.current.has(messageId) ? 'paused' : 'playing',
                  url: null,
                  error: null,
                  metadata: {
                    provider,
                    model,
                    durationMs: event.durationMs,
                    sampleRate: event.sampleRate,
                  },
                });
                continue;
              } catch {
                streamingSchedulerRef.current.stop();
                streamingSchedulerRef.current = null;
                startedPlayback = false;
              }
            }

            const htmlStarted = await queueHtmlStreamingSegment(messageId, segment, { provider, model }, startedPlayback);
            if (!htmlStarted) {
              abortController.abort();
              revokeUrl(messageId);
              return false;
            }
            startedPlayback = true;
          }
          if (event.type === 'error') {
            throw new Error(event.message);
          }
        }
        const schedulerAtEnd = streamingSchedulerRef.current;
        if (startedPlayback && schedulerAtEnd) {
          void schedulerAtEnd.waitForIdle().then(() => {
            if (activeMessageIdRef.current !== messageId || streamingSchedulerRef.current !== schedulerAtEnd) return;
            setEntries((current) => ({
              ...current,
              [messageId]: { ...(current[messageId] ?? defaultEntry), state: 'ready' },
            }));
            setActive(null);
          });
          return true;
        }
        if (startedPlayback) return true;
        updateEntry(messageId, { state: 'error', error: '语音合成服务没有返回可播放音频。' });
        setActive(null);
        return false;
      } catch (caught) {
        if (abortController.signal.aborted) return false;
        updateEntry(messageId, { state: 'error', error: errorMessage(caught) });
        setActive(null);
        return false;
      } finally {
        if (abortControllerRef.current === abortController) {
          abortControllerRef.current = null;
        }
      }
    }

    try {
      const result = await apiClient.synthesizeSpeech(text, { signal: abortController.signal });
      if (abortController.signal.aborted || activeMessageIdRef.current !== messageId) return false;
      revokeUrl(messageId);
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
      return playExisting(messageId, url);
    } catch (caught) {
      if (abortController.signal.aborted) return false;
      updateEntry(messageId, { state: 'error', error: errorMessage(caught) });
      setActive(null);
      return false;
    } finally {
      if (abortControllerRef.current === abortController) {
        abortControllerRef.current = null;
      }
    }
  }, [entries, playExisting, queueHtmlStreamingSegment, revokeUrl, setActive, stopActive, updateEntry]);

  const pause = useCallback((messageId: string) => {
    if (activeMessageIdRef.current !== messageId) return;
    const scheduler = streamingSchedulerRef.current;
    if (scheduler) {
      pausedStreamingMessageIdsRef.current.add(messageId);
      void scheduler.pause();
    } else {
      audioRef.current?.pause();
    }
    updateEntry(messageId, { state: 'paused' });
  }, [updateEntry]);

  const resume = useCallback(async (messageId: string): Promise<boolean> => {
    const entry = entries[messageId];
    const scheduler = streamingSchedulerRef.current;
    if (scheduler && entry?.state === 'paused') {
      pausedStreamingMessageIdsRef.current.delete(messageId);
      await scheduler.resume();
      updateEntry(messageId, { state: 'playing', error: null });
      return true;
    }
    if (!entry?.url) return false;
    return playExisting(messageId, entry.url);
  }, [entries, playExisting, updateEntry]);

  const stop = useCallback((messageId: string) => {
    if (activeMessageIdRef.current !== messageId) return;
    stopActive({ revokeMessageUrls: true });
  }, [stopActive]);

  const replay = useCallback(async (messageId: string, text: string): Promise<boolean> => {
    const entry = entries[messageId];
    if (!entry?.url) {
      return play(messageId, text);
    }
    if (audioRef.current) {
      audioRef.current.currentTime = 0;
    }
    return playExisting(messageId, entry.url);
  }, [entries, play, playExisting]);

  const reset = useCallback(() => {
    stopActive();
    void streamingSchedulerRef.current?.dispose();
    streamingSchedulerRef.current = null;
    for (const urls of urlsRef.current.values()) {
      for (const url of urls) {
        URL.revokeObjectURL(url);
      }
    }
    urlsRef.current.clear();
    streamingQueuesRef.current.clear();
    streamingMessageIdsRef.current.clear();
    pausedStreamingMessageIdsRef.current.clear();
    setEntries({});
  }, [stopActive]);

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
    entry.state === 'synthesizing' || entry.state === 'playing' || entry.state === 'paused',
  );

  return { isAudioBusy, pause, play, replay, reset, resume, stateFor, stop };
}
