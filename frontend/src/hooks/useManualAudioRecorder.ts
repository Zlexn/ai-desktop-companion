import { useCallback, useEffect, useRef, useState } from 'react';
import { apiClient } from '../api/client';

// ── types ────────────────────────────────────────────────────────────────────

export type RecordingStatus =
  | 'idle'
  | 'requesting_permission'
  | 'recording'
  | 'stopping'
  | 'uploading'
  | 'transcribing'
  | 'ready'
  | 'error';

export interface VoiceInputError {
  code: string;
  message: string;
}

export interface UseManualAudioRecorderResult {
  status: RecordingStatus;
  elapsedMs: number;
  partialTranscript: string | null;
  pendingTranscript: string | null;
  error: VoiceInputError | null;
  /** Returns true when recording-related operations should block TTS playback. */
  isPlaybackBlocked: boolean;
  startRecording(draftSnapshot: string): Promise<void>;
  stopRecording(): void;
  cancelRecording(): void;
  clearResult(): void;
}

interface UseManualAudioRecorderOptions {
  audioInputDeviceId?: string;
}

// ── constants ────────────────────────────────────────────────────────────────

const MAX_DURATION_MS = 30_000;
const MIN_DURATION_MS = 300;
const MAX_BLOB_BYTES = 10 * 1024 * 1024; // 10 MiB
const STOP_EVENT_TIMEOUT_MS = 5_000;
const STREAMING_ASR_TIMESLICE_MS = 1000;

const MIME_CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4',
] as const;

// ── helpers ──────────────────────────────────────────────────────────────────

function mapDOMExceptionToError(e: DOMException): VoiceInputError {
  switch (e.name) {
    case 'NotAllowedError':
      return { code: 'microphone_permission_denied', message: '未获得麦克风权限，请在浏览器设置中允许后重试。' };
    case 'NotFoundError':
      return { code: 'microphone_not_found', message: '未检测到麦克风设备。' };
    case 'NotReadableError':
      return { code: 'microphone_in_use_or_unavailable', message: '麦克风被其他应用占用或不可用。' };
    case 'SecurityError':
      return { code: 'microphone_security_error', message: '当前页面不支持麦克风（需要 HTTPS 或 localhost）。' };
    case 'AbortError':
      return { code: 'microphone_start_aborted', message: '录音请求已取消。' };
    case 'TypeError':
      return { code: 'microphone_unsupported_context', message: '当前浏览器环境不支持录音功能。' };
    default:
      return { code: 'microphone_unknown_error', message: '麦克风无法启动，请检查设备后重试。' };
  }
}

function isRecordingBlocking(status: RecordingStatus): boolean {
  return (
    status === 'requesting_permission' ||
    status === 'recording' ||
    status === 'stopping' ||
    status === 'uploading' ||
    status === 'transcribing'
  );
}

// ── hook ─────────────────────────────────────────────────────────────────────

export function useManualAudioRecorder(options: UseManualAudioRecorderOptions = {}): UseManualAudioRecorderResult {
  const [status, setStatus] = useState<RecordingStatus>('idle');
  const [elapsedMs, setElapsedMs] = useState(0);
  const [partialTranscript, setPartialTranscript] = useState<string | null>(null);
  const [pendingTranscript, setPendingTranscript] = useState<string | null>(null);
  const [error, setError] = useState<VoiceInputError | null>(null);

  // mutable refs — never in React state
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const previewAbortControllersRef = useRef<Set<AbortController>>(new Set());
  const startTimeRef = useRef<number>(0);
  const elapsedTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const maxTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const stopTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const discardRef = useRef(false);
  const generationRef = useRef(0);
  const mountedRef = useRef(true);
  const maxFiredRef = useRef(false);

  // ── cleanup ────────────────────────────────────────────────────────────────

  const clearTimers = useCallback(() => {
    if (elapsedTimerRef.current !== null) {
      clearInterval(elapsedTimerRef.current);
      elapsedTimerRef.current = null;
    }
    if (maxTimerRef.current !== null) {
      clearTimeout(maxTimerRef.current);
      maxTimerRef.current = null;
    }
    if (stopTimerRef.current !== null) {
      clearTimeout(stopTimerRef.current);
      stopTimerRef.current = null;
    }
  }, []);

  const stopAllTracks = useCallback(() => {
    const stream = streamRef.current;
    if (stream) {
      for (const track of stream.getTracks()) {
        track.stop();
      }
    }
    streamRef.current = null;
    recorderRef.current = null;
    chunksRef.current = [];
  }, []);

  const abortUpload = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    for (const controller of previewAbortControllersRef.current) {
      controller.abort();
    }
    previewAbortControllersRef.current.clear();
  }, []);

  const fullCleanup = useCallback(() => {
    clearTimers();
    stopAllTracks();
    abortUpload();
    discardRef.current = false;
    maxFiredRef.current = false;
  }, [clearTimers, stopAllTracks, abortUpload]);

  // ── reset to idle ──────────────────────────────────────────────────────────

  const resetToIdle = useCallback((preserveTranscript: boolean = false) => {
    if (!mountedRef.current) return;
    setElapsedMs(0);
    setStatus('idle');
    if (!preserveTranscript) {
      setPartialTranscript(null);
      setPendingTranscript(null);
    }
    setError(null);
  }, []);

  // ── cancel ─────────────────────────────────────────────────────────────────

  const cancelRecording = useCallback(() => {
    generationRef.current += 1;
    discardRef.current = true;
    abortUpload();

    const recorder = recorderRef.current;
    if (recorder && recorder.state === 'recording') {
      recorder.stop();
    } else if (!recorder) {
      // No recorder active — clean up directly
      fullCleanup();
      resetToIdle();
    }
    // If recorder is in stopping state, the stop handler will see discardRef and skip upload
  }, [abortUpload, fullCleanup, resetToIdle]);

  // ── upload ─────────────────────────────────────────────────────────────────

  const uploadPreviewChunk = useCallback(async (chunk: Blob, gen: number) => {
    if (!mountedRef.current || gen !== generationRef.current) return;
    const abortController = new AbortController();
    previewAbortControllersRef.current.add(abortController);

    try {
      for await (const event of apiClient.streamTranscription([chunk], {
        language: 'zh',
        signal: abortController.signal,
      })) {
        if (!mountedRef.current || gen !== generationRef.current) return;
        if (abortController.signal.aborted) return;
        if (event.type === 'partial') {
          setPartialTranscript(event.text);
          return;
        }
        if (event.type === 'error') {
          return;
        }
      }
    } catch (caught: unknown) {
      if (caught instanceof DOMException && caught.name === 'AbortError') return;
      // Preview failures are recoverable; final transcription after stop remains authoritative.
    } finally {
      previewAbortControllersRef.current.delete(abortController);
    }
  }, []);

  const uploadBlob = useCallback(async (blob: Blob, gen: number) => {
    if (!mountedRef.current || gen !== generationRef.current) return;

    abortRef.current?.abort();
    const abortController = new AbortController();
    abortRef.current = abortController;

    setStatus('uploading');
    setPartialTranscript(null);

    try {
      setStatus('transcribing');
      for await (const event of apiClient.streamTranscription([blob], {
        language: 'zh',
        signal: abortController.signal,
      })) {
        if (!mountedRef.current || gen !== generationRef.current) return;
        if (abortController.signal.aborted) return;
        if (event.type === 'partial') {
          setPartialTranscript(event.text);
        }
        if (event.type === 'final') {
          setStatus('ready');
          setPendingTranscript(event.text);
          setElapsedMs(0);
        }
        if (event.type === 'error') {
          throw new Error(event.message);
        }
      }
    } catch (caught: unknown) {
      if (!mountedRef.current || gen !== generationRef.current) return;
      if (caught instanceof DOMException && caught.name === 'AbortError') return;

      setStatus('error');
      setError({
        code: 'asr_error',
        message: caught instanceof Error ? caught.message : '语音转写失败，请重新录制或手动输入。',
      });
      fullCleanup();
    } finally {
      if (abortRef.current === abortController) {
        abortRef.current = null;
      }
    }
  }, [fullCleanup]);

  // ── stop recording ─────────────────────────────────────────────────────────

  const stopRecording = useCallback(() => {
    clearTimers();
    const recorder = recorderRef.current;
    if (!recorder || recorder.state !== 'recording') return;

    setStatus('stopping');

    // stop-event timeout guard
    stopTimerRef.current = setTimeout(() => {
      if (!mountedRef.current) return;
      // Force cleanup — stop event didn't fire in time
      stopAllTracks();
      clearTimers();
      if (mountedRef.current) {
        setStatus('error');
        setError({ code: 'microphone_unknown_error', message: '录音结束超时，请重试。' });
      }
    }, STOP_EVENT_TIMEOUT_MS);

    recorder.stop();
  }, [clearTimers, stopAllTracks]);

  // ── start recording ────────────────────────────────────────────────────────

  const startRecording = useCallback(async (_draftSnapshot: string) => {
    // Gate: only start from idle or error
    if (status !== 'idle' && status !== 'error') return;

    // Clean up any residual state
    fullCleanup();
    generationRef.current += 1;
    const gen = generationRef.current;

    // Check browser support
    if (!navigator.mediaDevices?.getUserMedia) {
      setStatus('error');
      setError({ code: 'microphone_unsupported_context', message: '当前浏览器环境不支持录音功能。' });
      return;
    }
    if (typeof MediaRecorder === 'undefined') {
      setStatus('error');
      setError({ code: 'microphone_unsupported_context', message: '当前浏览器环境不支持录音功能。' });
      return;
    }

    setStatus('requesting_permission');
    setError(null);
    setPartialTranscript(null);
    setPendingTranscript(null);
    setElapsedMs(0);

    // Select MIME
    let chosenMime = '';
    for (const candidate of MIME_CANDIDATES) {
      if (MediaRecorder.isTypeSupported(candidate)) {
        chosenMime = candidate;
        break;
      }
    }
    if (!chosenMime) {
      setStatus('error');
      setError({ code: 'microphone_unsupported_format', message: '暂不支持此浏览器的录音格式。' });
      return;
    }

    // Request permission
    const audioConstraints: MediaTrackConstraints = {
      echoCancellation: { ideal: true },
      noiseSuppression: { ideal: true },
      autoGainControl: { ideal: true },
    };
    if (options.audioInputDeviceId) {
      audioConstraints.deviceId = { ideal: options.audioInputDeviceId };
    }

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: audioConstraints,
      });
    } catch (e: unknown) {
      if (!mountedRef.current || gen !== generationRef.current) return;
      if (e instanceof DOMException) {
        const mapped = mapDOMExceptionToError(e);
        // AbortError from getUserMedia means user dismissed — treat as cancel, go to idle
        if (e.name === 'AbortError') {
          resetToIdle();
          return;
        }
        setStatus('error');
        setError(mapped);
      } else {
        setStatus('error');
        setError({ code: 'microphone_unknown_error', message: '麦克风无法启动，请检查设备后重试。' });
      }
      return;
    }

    // Check late resolution
    if (!mountedRef.current || gen !== generationRef.current) {
      for (const track of stream.getTracks()) {
        track.stop();
      }
      return;
    }

    streamRef.current = stream;

    // Listen for track ended
    for (const track of stream.getTracks()) {
      track.addEventListener('ended', () => {
        if (!mountedRef.current) return;
        if (streamRef.current === stream) {
          fullCleanup();
          if (mountedRef.current) {
            setStatus('error');
            setError({ code: 'microphone_device_disconnected', message: '麦克风设备已断开。' });
          }
        }
      }, { once: true });
    }

    // Create recorder
    let recorder: MediaRecorder;
    try {
      recorder = new MediaRecorder(stream, { mimeType: chosenMime });
    } catch {
      for (const track of stream.getTracks()) {
        track.stop();
      }
      streamRef.current = null;
      if (!mountedRef.current || gen !== generationRef.current) return;
      setStatus('error');
      setError({ code: 'microphone_unsupported_format', message: '暂不支持此浏览器的录音格式。' });
      return;
    }

    const actualMimeType = recorder.mimeType;
    recorderRef.current = recorder;
    chunksRef.current = [];

    // dataavailable handler
    recorder.ondataavailable = (event: BlobEvent) => {
      if (event.data && event.data.size > 0) {
        chunksRef.current.push(event.data);
        if (!discardRef.current && recorderRef.current?.state === 'recording') {
          void uploadPreviewChunk(event.data, gen);
        }
      }
    };

    // stop handler
    recorder.onstop = () => {
      clearTimers();

      if (stopTimerRef.current !== null) {
        clearTimeout(stopTimerRef.current);
        stopTimerRef.current = null;
      }

      const chunks = chunksRef.current;
      const shouldDiscard = discardRef.current;

      // Stop all tracks first (before any async work)
      stopAllTracks();

      if (shouldDiscard) {
        discardRef.current = false;
        if (mountedRef.current) resetToIdle();
        return;
      }

      if (chunks.length === 0) {
        if (mountedRef.current) {
          setStatus('error');
          setError({ code: 'recording_empty', message: '录音内容为空，请重新录制。' });
        }
        return;
      }

      const blob = new Blob(chunks, { type: actualMimeType || chosenMime });

      if (blob.size === 0) {
        if (mountedRef.current) {
          setStatus('error');
          setError({ code: 'recording_empty', message: '录音内容为空，请重新录制。' });
        }
        return;
      }

      if (blob.size > MAX_BLOB_BYTES) {
        if (mountedRef.current) {
          setStatus('error');
          setError({ code: 'recording_too_large', message: '录音文件过大，请缩短录音时间后重试。' });
        }
        return;
      }

      const elapsed = performance.now() - startTimeRef.current;
      if (elapsed < MIN_DURATION_MS) {
        if (mountedRef.current) {
          setStatus('error');
          setError({ code: 'recording_too_short', message: '录音时间太短，请重新录制。' });
        }
        return;
      }

      // Start upload
      void uploadBlob(blob, generationRef.current);
    };

    // recorder error handler
    recorder.onerror = () => {
      clearTimers();
      stopAllTracks();
      if (mountedRef.current) {
        setStatus('error');
        setError({ code: 'microphone_unknown_error', message: '录音设备出现错误，请重试。' });
      }
    };

    // Start recording
    try {
      recorder.start(STREAMING_ASR_TIMESLICE_MS);
    } catch {
      for (const track of stream.getTracks()) {
        track.stop();
      }
      streamRef.current = null;
      recorderRef.current = null;
      if (!mountedRef.current || gen !== generationRef.current) return;
      setStatus('error');
      setError({ code: 'microphone_unknown_error', message: '录音无法启动，请重试。' });
      return;
    }

    if (!mountedRef.current || gen !== generationRef.current) {
      recorder.stop();
      return;
    }

    // Set state
    startTimeRef.current = performance.now();
    discardRef.current = false;
    maxFiredRef.current = false;
    setStatus('recording');
    setElapsedMs(0);

    // Elapsed timer
    elapsedTimerRef.current = setInterval(() => {
      if (!mountedRef.current) return;
      setElapsedMs(Math.floor(performance.now() - startTimeRef.current));
    }, 100);

    // Max duration timer (30s auto-stop)
    maxTimerRef.current = setTimeout(() => {
      if (!mountedRef.current) return;
      if (maxFiredRef.current) return;
      maxFiredRef.current = true;
      if (recorderRef.current?.state === 'recording') {
        stopRecording();
      }
    }, MAX_DURATION_MS);
  }, [status, options.audioInputDeviceId, fullCleanup, resetToIdle, stopAllTracks, clearTimers, stopRecording, uploadBlob, uploadPreviewChunk]);

  // ── clear result ───────────────────────────────────────────────────────────

  const clearResult = useCallback(() => {
    setPartialTranscript(null);
    setPendingTranscript(null);
    setError(null);
    setStatus('idle');
  }, []);

  // ── unmount cleanup ────────────────────────────────────────────────────────

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      fullCleanup();
    };
  }, [fullCleanup]);

  // ── public interface ──────────────────────────────────────────────────────

  return {
    status,
    elapsedMs,
    partialTranscript,
    pendingTranscript,
    error,
    isPlaybackBlocked: isRecordingBlocking(status),
    startRecording,
    stopRecording,
    cancelRecording,
    clearResult,
  };
}
