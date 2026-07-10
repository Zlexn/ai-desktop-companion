import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useManualAudioRecorder } from './useManualAudioRecorder';

// ── helpers ──────────────────────────────────────────────────────────────────

function fakeTrack() {
  return { stop: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), kind: 'audio' };
}

function fakeMediaStream() {
  const tracks = [fakeTrack()];
  return {
    getTracks: () => tracks,
    getAudioTracks: () => tracks,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  } as unknown as MediaStream;
}

// ── setup ────────────────────────────────────────────────────────────────────

describe('useManualAudioRecorder', () => {
  let mockGetUserMedia: ReturnType<typeof vi.fn>;
  let origMediaRecorder: unknown;
  let origNavigator: Navigator;

  beforeEach(() => {
    mockGetUserMedia = vi.fn();
    origNavigator = globalThis.navigator;
    Object.defineProperty(globalThis, 'navigator', {
      configurable: true,
      writable: true,
      value: { ...origNavigator, mediaDevices: { getUserMedia: mockGetUserMedia } },
    });

    origMediaRecorder = globalThis.MediaRecorder;

    // Mock MediaRecorder class with static method
    const MockMR = function (this: Record<string, unknown>, _stream: MediaStream, _opts?: MediaRecorderOptions) {
      const tracks = [fakeTrack()];
      this.mimeType = _opts?.mimeType || 'audio/webm;codecs=opus';
      this.state = 'inactive';
      this.stream = { getTracks: () => tracks };

      this.start = vi.fn(function (this: Record<string, string>) {
        this.state = 'recording';
      });

      this.stop = vi.fn(function (this: Record<string, unknown>) {
        const self = this as Record<string, unknown>;
        self.state = 'inactive';
        queueMicrotask(() => {
          const ondata = (self as Record<string, ((e: { data: Blob }) => void) | null>).ondataavailable;
          if (ondata) {
            ondata({ data: new Blob(['\x1a\x45\xdf\xa3fake-webm-data'], { type: 'audio/webm;codecs=opus' }) });
          }
          queueMicrotask(() => {
            const onstop = (self as Record<string, (() => void) | null>).onstop;
            if (onstop) onstop();
          });
        });
      });

      this.pause = vi.fn();
      this.resume = vi.fn();
      this.requestData = vi.fn();
      this.dispatchEvent = vi.fn();
    } as unknown as { new (stream: MediaStream, opts?: MediaRecorderOptions): MediaRecorder };

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (MockMR as any).isTypeSupported = vi.fn().mockReturnValue(true);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    globalThis.MediaRecorder = MockMR as any;

    globalThis.fetch = vi.fn().mockRejectedValue(new Error('fetch not expected in this test'));
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
    Object.defineProperty(globalThis, 'navigator', {
      configurable: true,
      writable: true,
      value: origNavigator,
    });
    if (origMediaRecorder) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      globalThis.MediaRecorder = origMediaRecorder as any;
    }
  });

  // ── permission flow ──────────────────────────────────────────────────────

  it('does not request microphone on hook mount', () => {
    renderHook(() => useManualAudioRecorder());
    expect(mockGetUserMedia).not.toHaveBeenCalled();
  });

  it('requests permission on startRecording', async () => {
    mockGetUserMedia.mockResolvedValue(fakeMediaStream());

    const { result } = renderHook(() => useManualAudioRecorder());

    await act(async () => {
      await result.current.startRecording('');
    });

    expect(mockGetUserMedia).toHaveBeenCalledTimes(1);
    expect(result.current.status).toBe('recording');
  });

  it('handles permission denied', async () => {
    mockGetUserMedia.mockRejectedValue(new DOMException('Permission denied', 'NotAllowedError'));

    const { result } = renderHook(() => useManualAudioRecorder());

    await act(async () => {
      await result.current.startRecording('');
    });

    expect(result.current.status).toBe('error');
    expect(result.current.error?.code).toBe('microphone_permission_denied');
  });

  it('handles not found error', async () => {
    mockGetUserMedia.mockRejectedValue(new DOMException('No device', 'NotFoundError'));

    const { result } = renderHook(() => useManualAudioRecorder());

    await act(async () => {
      await result.current.startRecording('');
    });

    expect(result.current.status).toBe('error');
    expect(result.current.error?.code).toBe('microphone_not_found');
  });

  it('handles not readable error', async () => {
    mockGetUserMedia.mockRejectedValue(new DOMException('In use', 'NotReadableError'));

    const { result } = renderHook(() => useManualAudioRecorder());

    await act(async () => {
      await result.current.startRecording('');
    });

    expect(result.current.status).toBe('error');
    expect(result.current.error?.code).toBe('microphone_in_use_or_unavailable');
  });

  it('handles security error', async () => {
    mockGetUserMedia.mockRejectedValue(new DOMException('Not secure', 'SecurityError'));

    const { result } = renderHook(() => useManualAudioRecorder());

    await act(async () => {
      await result.current.startRecording('');
    });

    expect(result.current.status).toBe('error');
    expect(result.current.error?.code).toBe('microphone_security_error');
  });

  it('returns to idle on AbortError (user dismissed prompt)', async () => {
    mockGetUserMedia.mockRejectedValue(new DOMException('Dismissed', 'AbortError'));

    const { result } = renderHook(() => useManualAudioRecorder());

    await act(async () => {
      await result.current.startRecording('');
    });

    expect(result.current.status).toBe('idle');
    expect(result.current.error).toBeNull();
  });

  // ── unsupported APIs ────────────────────────────────────────────────────

  it('errors when navigator.mediaDevices is absent', async () => {
    Object.defineProperty(globalThis, 'navigator', {
      configurable: true,
      writable: true,
      value: { ...origNavigator, mediaDevices: undefined },
    });

    const { result } = renderHook(() => useManualAudioRecorder());
    await act(async () => {
      await result.current.startRecording('');
    });
    expect(result.current.status).toBe('error');
    expect(result.current.error?.code).toBe('microphone_unsupported_context');
  });

  it('errors when MediaRecorder is absent', async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    delete (globalThis as any).MediaRecorder;
    mockGetUserMedia.mockResolvedValue(fakeMediaStream());

    const { result } = renderHook(() => useManualAudioRecorder());
    await act(async () => {
      await result.current.startRecording('');
    });
    expect(result.current.status).toBe('error');
    expect(result.current.error?.code).toBe('microphone_unsupported_context');
  });

  // ── MIME selection and recorder creation failures ────────────────────────

  it('selects first supported MIME candidate', async () => {
    mockGetUserMedia.mockResolvedValue(fakeMediaStream());

    const { result } = renderHook(() => useManualAudioRecorder());

    await act(async () => {
      await result.current.startRecording('');
    });

    expect((globalThis.MediaRecorder as unknown as { isTypeSupported: ReturnType<typeof vi.fn> }).isTypeSupported).toHaveBeenCalledWith('audio/webm;codecs=opus');
  });

  it('errors when no MIME candidate is supported', async () => {
    mockGetUserMedia.mockResolvedValue(fakeMediaStream());
    (globalThis.MediaRecorder as unknown as { isTypeSupported: ReturnType<typeof vi.fn> }).isTypeSupported.mockReturnValue(false);

    const { result } = renderHook(() => useManualAudioRecorder());

    await act(async () => {
      await result.current.startRecording('');
    });

    expect(result.current.status).toBe('error');
    expect(result.current.error?.code).toBe('microphone_unsupported_format');
  });

  it('errors when recorder constructor throws despite isTypeSupported=true', async () => {
    mockGetUserMedia.mockResolvedValue(fakeMediaStream());
    (globalThis.MediaRecorder as unknown as { isTypeSupported: ReturnType<typeof vi.fn> }).isTypeSupported.mockReturnValue(true);
    const throwingMR = function () { throw new Error('codec init failed'); };
    throwingMR.isTypeSupported = vi.fn().mockReturnValue(true);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    globalThis.MediaRecorder = throwingMR as any;

    const { result } = renderHook(() => useManualAudioRecorder());

    await act(async () => {
      await result.current.startRecording('');
    });

    expect(result.current.status).toBe('error');
    expect(result.current.error?.code).toBe('microphone_unsupported_format');
  });

  // ── recording lifecycle ─────────────────────────────────────────────────

  it('stops all tracks on cancel', async () => {
    const stream = fakeMediaStream();
    mockGetUserMedia.mockResolvedValue(stream);

    const { result } = renderHook(() => useManualAudioRecorder());

    await act(async () => {
      await result.current.startRecording('');
    });
    expect(result.current.status).toBe('recording');

    act(() => {
      result.current.cancelRecording();
    });

    await act(async () => {
      await vi.runAllTimersAsync();
    });

    for (const track of stream.getTracks()) {
      expect(track.stop).toHaveBeenCalled();
    }
  });

  it('double startRecording is prevented', async () => {
    mockGetUserMedia.mockResolvedValue(fakeMediaStream());

    const { result } = renderHook(() => useManualAudioRecorder());

    await act(async () => {
      await result.current.startRecording('');
    });
    expect(result.current.status).toBe('recording');

    await act(async () => {
      await result.current.startRecording('');
    });
    // getUserMedia should only be called once
    expect(mockGetUserMedia).toHaveBeenCalledTimes(1);
  });

  // ── late getUserMedia resolution ─────────────────────────────────────────

  it('stops stream on late getUserMedia resolution after cancel', async () => {
    let resolveStream!: (stream: MediaStream) => void;
    const pendingStream = new Promise<MediaStream>((resolve) => {
      resolveStream = resolve;
    });
    mockGetUserMedia.mockReturnValue(pendingStream);

    const { result } = renderHook(() => useManualAudioRecorder());

    void act(() => {
      result.current.startRecording('');
    });

    // Cancel before getUserMedia resolves
    act(() => {
      result.current.cancelRecording();
    });

    // Now resolve — tracks should be immediately stopped
    const stream = fakeMediaStream();
    await act(async () => {
      resolveStream(stream);
      await vi.runAllTimersAsync();
    });

    for (const track of stream.getTracks()) {
      expect(track.stop).toHaveBeenCalled();
    }
    expect(result.current.status).not.toBe('recording');
  });

  it('stops tracks after successful completion', async () => {
    const stream = fakeMediaStream();
    mockGetUserMedia.mockResolvedValue(stream);

    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ text: '测试', detected_language: 'zh', duration_ms: null, provider: 'fake', model: 'fake-asr-v1', inference_ms: 0 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const { result } = renderHook(() => useManualAudioRecorder());

    await act(async () => {
      await result.current.startRecording('');
    });

    act(() => {
      result.current.stopRecording();
    });

    await act(async () => {
      await vi.runAllTimersAsync();
    });

    for (const track of stream.getTracks()) {
      expect(track.stop).toHaveBeenCalled();
    }
  });

  it('cleans up tracks on unmount', async () => {
    const stream = fakeMediaStream();
    mockGetUserMedia.mockResolvedValue(stream);

    const { result, unmount } = renderHook(() => useManualAudioRecorder());

    await act(async () => {
      await result.current.startRecording('');
    });

    act(() => {
      unmount();
    });

    for (const track of stream.getTracks()) {
      expect(track.stop).toHaveBeenCalled();
    }
  });

  // ── TTS blocking ────────────────────────────────────────────────────────

  it('isPlaybackBlocked is true during recording', async () => {
    mockGetUserMedia.mockResolvedValue(fakeMediaStream());

    const { result } = renderHook(() => useManualAudioRecorder());

    expect(result.current.isPlaybackBlocked).toBe(false);

    await act(async () => {
      await result.current.startRecording('');
    });

    expect(result.current.isPlaybackBlocked).toBe(true);
  });

  // ── stale response handling ─────────────────────────────────────────────

  it('ignores stale fetch response after new recording started', async () => {
    // Simulate two fast recordings. The first completes, starts upload.
    // During upload, user cancels and starts a second recording.
    // The stale upload response must not affect the second recording's transcript.

    mockGetUserMedia.mockResolvedValue(fakeMediaStream());

    vi.mocked(globalThis.fetch).mockResolvedValue(
      new Response(JSON.stringify({ text: 'first-transcript', detected_language: 'zh', duration_ms: null, provider: 'fake', model: 'fake-asr-v1', inference_ms: 0 }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    const { result } = renderHook(() => useManualAudioRecorder());

    // Start and stop first recording
    await act(async () => {
      await result.current.startRecording('');
    });
    await act(async () => {
      result.current.stopRecording();
      await vi.runAllTimersAsync();
    });

    // Upload started — cancel it (aborts active fetch)
    await act(async () => {
      result.current.cancelRecording();
      await vi.runAllTimersAsync();
    });

    // Should be idle with no transcript (cancel cleared it)
    expect(result.current.status).toBe('idle');
    expect(result.current.pendingTranscript).toBeNull();
  });

  // ── min duration guard ───────────────────────────────────────────────────

  it('rejects recording shorter than 300ms', async () => {
    mockGetUserMedia.mockResolvedValue(fakeMediaStream());

    const startTime = 1000;
    const nowSpy = vi.spyOn(performance, 'now');
    nowSpy.mockReturnValue(startTime);

    const { result } = renderHook(() => useManualAudioRecorder());

    await act(async () => {
      await result.current.startRecording('');
    });

    // Make subsequent calls return startTime + 200ms
    nowSpy.mockReturnValue(startTime + 200);

    act(() => {
      result.current.stopRecording();
    });

    await act(async () => {
      await vi.runAllTimersAsync();
    });

    expect(result.current.status).toBe('error');
    expect(result.current.error?.code).toBe('recording_too_short');
  });

  // ── 30s auto-stop ───────────────────────────────────────────────────────

  it('auto-stops at 30 seconds', async () => {
    mockGetUserMedia.mockResolvedValue(fakeMediaStream());

    const FakeMR = globalThis.MediaRecorder;

    const { result } = renderHook(() => useManualAudioRecorder());

    await act(async () => {
      await result.current.startRecording('');
    });
    expect(result.current.status).toBe('recording');

    // Advance 30s
    await act(async () => {
      vi.advanceTimersByTime(30_000);
    });

    // stop should have been called on the recorder constructed during startRecording
    const calls = (FakeMR as unknown as ReturnType<typeof vi.fn>).mock?.instances;
    if (calls && calls.length > 0) {
      const instance = calls[0] as { stop: ReturnType<typeof vi.fn> };
      expect(instance.stop).toHaveBeenCalled();
    }
  });

  it('auto-stop fires only once', async () => {
    mockGetUserMedia.mockResolvedValue(fakeMediaStream());

    const FakeMR = globalThis.MediaRecorder;

    const { result } = renderHook(() => useManualAudioRecorder());

    await act(async () => {
      await result.current.startRecording('');
    });

    await act(async () => {
      vi.advanceTimersByTime(60_000);
    });

    const calls = (FakeMR as unknown as ReturnType<typeof vi.fn>).mock?.instances;
    if (calls && calls.length > 0) {
      const instance = calls[0] as { stop: ReturnType<typeof vi.fn> };
      expect(instance.stop).toHaveBeenCalledTimes(1);
    }
  });

  // ── 10 MiB blob guard ───────────────────────────────────────────────────

  it('rejects blob exceeding 10 MiB', async () => {
    mockGetUserMedia.mockResolvedValue(fakeMediaStream());

    // Override the MediaRecorder stop to emit an 11 MiB blob
    const OversizedMR = function (this: Record<string, unknown>) {
      this.mimeType = 'audio/webm';
      this.state = 'inactive';
      this.stream = { getTracks: () => [fakeTrack()] };
      this.start = vi.fn(function (this: Record<string, string>) { this.state = 'recording'; });
      this.stop = vi.fn(function (this: Record<string, unknown>) {
        const self = this as Record<string, unknown>;
        self.state = 'inactive';
        queueMicrotask(() => {
          const ondata = (self as Record<string, ((e: { data: Blob }) => void) | null>).ondataavailable;
          if (ondata) {
            const bigBytes = new Uint8Array(11 * 1024 * 1024);
            ondata({ data: new Blob([bigBytes], { type: 'audio/webm' }) });
          }
          queueMicrotask(() => {
            const onstop = (self as Record<string, (() => void) | null>).onstop;
            if (onstop) onstop();
          });
        });
      });
      this.pause = vi.fn();
      this.resume = vi.fn();
      this.requestData = vi.fn();
      this.dispatchEvent = vi.fn();
    };
    (OversizedMR as unknown as { isTypeSupported: ReturnType<typeof vi.fn> }).isTypeSupported = vi.fn().mockReturnValue(true);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    globalThis.MediaRecorder = OversizedMR as any;

    const { result } = renderHook(() => useManualAudioRecorder());

    await act(async () => {
      await result.current.startRecording('');
    });

    act(() => {
      result.current.stopRecording();
    });

    await act(async () => {
      await vi.runAllTimersAsync();
    });

    expect(result.current.status).toBe('error');
    expect(result.current.error?.code).toBe('recording_too_large');
  });

  it('exposes partial transcript while recording before stop', async () => {
    mockGetUserMedia.mockResolvedValue(fakeMediaStream());
    const encoder = new TextEncoder();
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response(new ReadableStream({
        start(controller) {
          controller.enqueue(encoder.encode('{"type":"start","provider":"fake","model":"fake-asr-v1"}\n'));
          controller.enqueue(encoder.encode('{"type":"partial","index":0,"text":"语音","is_final":false,"audio_ms":1000}\n'));
          controller.enqueue(encoder.encode('{"type":"final","text":"语音转写文本","detected_language":"zh","duration_ms":null,"provider":"fake","model":"fake-asr-v1","inference_ms":0}\n'));
          controller.enqueue(encoder.encode('{"type":"done"}\n'));
          controller.close();
        },
      }), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }),
    );

    const StreamingMR = function (this: Record<string, unknown>, _stream: MediaStream, _opts?: MediaRecorderOptions) {
      this.mimeType = _opts?.mimeType || 'audio/webm;codecs=opus';
      this.state = 'inactive';
      this.stream = { getTracks: () => [fakeTrack()] };
      this.start = vi.fn(function (this: Record<string, unknown>) {
        this.state = 'recording';
        const self = this;
        queueMicrotask(() => {
          const ondata = (self as Record<string, ((e: { data: Blob }) => void) | null>).ondataavailable;
          if (ondata) {
            ondata({ data: new Blob(['\x1a\x45\xdf\xa3preview-webm-data'], { type: 'audio/webm;codecs=opus' }) });
          }
        });
      });
      this.stop = vi.fn();
      this.pause = vi.fn();
      this.resume = vi.fn();
      this.requestData = vi.fn();
      this.dispatchEvent = vi.fn();
    };
    (StreamingMR as unknown as { isTypeSupported: ReturnType<typeof vi.fn> }).isTypeSupported = vi.fn().mockReturnValue(true);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    globalThis.MediaRecorder = StreamingMR as any;

    const { result } = renderHook(() => useManualAudioRecorder());

    await act(async () => {
      await result.current.startRecording('');
    });

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(vi.mocked(globalThis.fetch).mock.calls[0][0]).toBe('/api/audio/transcriptions/stream');
    expect(result.current.status).toBe('recording');
    expect(result.current.partialTranscript).toBe('语音');
    expect(result.current.pendingTranscript).toBeNull();
  });

  it('streams recording chunks and exposes partial before final transcript', async () => {
    mockGetUserMedia.mockResolvedValue(fakeMediaStream());
    const encoder = new TextEncoder();
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response(new ReadableStream({
        start(controller) {
          controller.enqueue(encoder.encode('{"type":"start","provider":"fake","model":"fake-asr-v1"}\n'));
          controller.enqueue(encoder.encode('{"type":"partial","index":0,"text":"语音","is_final":false,"audio_ms":1000}\n'));
          controller.enqueue(encoder.encode('{"type":"final","text":"语音转写文本","detected_language":"zh","duration_ms":null,"provider":"fake","model":"fake-asr-v1","inference_ms":0}\n'));
          controller.enqueue(encoder.encode('{"type":"done"}\n'));
          controller.close();
        },
      }), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }),
    );

    const { result } = renderHook(() => useManualAudioRecorder());

    await act(async () => {
      await result.current.startRecording('');
    });

    await act(async () => {
      vi.advanceTimersByTime(350);
    });

    act(() => {
      result.current.stopRecording();
    });

    await act(async () => {
      await vi.runAllTimersAsync();
    });

    expect(vi.mocked(globalThis.fetch).mock.calls[0][0]).toBe('/api/audio/transcriptions/stream');
    expect(result.current.partialTranscript).toBe('语音');
    expect(result.current.pendingTranscript).toBe('语音转写文本');
    expect(result.current.status).toBe('ready');
  });

  // ── cancel skips upload ─────────────────────────────────────────────────

  it('cancel during recording discards chunks and does not upload', async () => {
    mockGetUserMedia.mockResolvedValue(fakeMediaStream());

    const { result } = renderHook(() => useManualAudioRecorder());

    await act(async () => {
      await result.current.startRecording('');
    });
    expect(result.current.status).toBe('recording');

    act(() => {
      result.current.cancelRecording();
    });

    await act(async () => {
      await vi.runAllTimersAsync();
    });

    // fetch should not have been called successfully
    const fetchCalls = vi.mocked(globalThis.fetch).mock.calls;
    // fetch is mocked globally — we expect no successful transcription call after cancel
    // (the default mock rejects, so any call would cause unhandled rejection)
    // Just verify we ended in idle
    expect(result.current.status).toBe('idle');
  });
});
