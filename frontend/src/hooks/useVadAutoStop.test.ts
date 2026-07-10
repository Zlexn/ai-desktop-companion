import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useVadAutoStop } from './useVadAutoStop';
import type { CreateVoiceActivityDetector, CreateVoiceActivityDetectorOptions, VoiceActivityDetector } from '../voiceActivity/types';
import type { RecordingStatus } from './useManualAudioRecorder';

function createFakeVadFactory() {
  const controls: {
    options?: CreateVoiceActivityDetectorOptions;
    detector?: VoiceActivityDetector;
    start: ReturnType<typeof vi.fn<() => Promise<void>>>;
    stop: ReturnType<typeof vi.fn<() => Promise<void>>>;
  } = {
    start: vi.fn<() => Promise<void>>().mockResolvedValue(undefined),
    stop: vi.fn<() => Promise<void>>().mockResolvedValue(undefined),
  };

  const createDetector: CreateVoiceActivityDetector = vi.fn(async (options) => {
    const detector: VoiceActivityDetector = {
      start: controls.start,
      stop: controls.stop,
    };
    controls.options = options;
    controls.detector = detector;
    return detector;
  });

  return { createDetector, controls };
}

describe('useVadAutoStop', () => {
  it('does not create VAD while idle', () => {
    const { createDetector } = createFakeVadFactory();

    renderHook(() => useVadAutoStop({
      enabled: true,
      recordingStatus: 'idle',
      stopRecording: vi.fn(),
      createDetector,
    }));

    expect(createDetector).not.toHaveBeenCalled();
  });

  it('starts VAD when recording begins', async () => {
    const { createDetector, controls } = createFakeVadFactory();
    const { rerender, result } = renderHook(
      ({ status }) => useVadAutoStop({
        enabled: true,
        recordingStatus: status,
        stopRecording: vi.fn(),
        createDetector,
      }),
      { initialProps: { status: 'idle' as RecordingStatus } },
    );

    rerender({ status: 'recording' });
    await act(async () => {});

    expect(createDetector).toHaveBeenCalledTimes(1);
    expect(controls.start).toHaveBeenCalledTimes(1);
    expect(result.current.runtimeStatus).toBe('listening');
  });

  it('calls stopRecording once when VAD reports speech end', async () => {
    const { createDetector, controls } = createFakeVadFactory();
    const stopRecording = vi.fn();

    renderHook(() => useVadAutoStop({
      enabled: true,
      recordingStatus: 'recording',
      stopRecording,
      createDetector,
    }));
    await act(async () => {});

    act(() => {
      controls.options?.onSpeechEnd();
      controls.options?.onSpeechEnd();
    });

    expect(stopRecording).toHaveBeenCalledTimes(1);
  });

  it('stops VAD when recording leaves recording state', async () => {
    const { createDetector, controls } = createFakeVadFactory();
    const { rerender } = renderHook(
      ({ status }) => useVadAutoStop({
        enabled: true,
        recordingStatus: status,
        stopRecording: vi.fn(),
        createDetector,
      }),
      { initialProps: { status: 'recording' as RecordingStatus } },
    );
    await act(async () => {});

    rerender({ status: 'stopping' });
    await act(async () => {});

    expect(controls.stop).toHaveBeenCalledTimes(1);
  });

  it('does not call stopRecording after manual stop cleaned up VAD', async () => {
    const { createDetector, controls } = createFakeVadFactory();
    const stopRecording = vi.fn();
    const { rerender } = renderHook(
      ({ status }) => useVadAutoStop({
        enabled: true,
        recordingStatus: status,
        stopRecording,
        createDetector,
      }),
      { initialProps: { status: 'recording' as RecordingStatus } },
    );
    await act(async () => {});

    rerender({ status: 'stopping' });
    await act(async () => {});

    act(() => {
      controls.options?.onSpeechEnd();
    });

    expect(stopRecording).not.toHaveBeenCalled();
  });

  it('reports recoverable unavailable state when VAD creation fails', async () => {
    const createDetector: CreateVoiceActivityDetector = vi.fn(async () => {
      throw new Error('model missing');
    });

    const { result } = renderHook(() => useVadAutoStop({
      enabled: true,
      recordingStatus: 'recording',
      stopRecording: vi.fn(),
      createDetector,
    }));
    await act(async () => {});

    expect(result.current.runtimeStatus).toBe('unavailable');
    expect(result.current.message).toBe('语音端点检测不可用，请手动停止');
  });
});
