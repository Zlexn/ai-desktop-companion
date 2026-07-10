import { useEffect, useMemo, useRef, useState } from 'react';
import type { RecordingStatus } from './useManualAudioRecorder';
import { createSileroVad } from '../voiceActivity/createSileroVad';
import type { CreateVoiceActivityDetector, VadRuntimeStatus, VoiceActivityDetector } from '../voiceActivity/types';

interface UseVadAutoStopOptions {
  enabled: boolean;
  recordingStatus: RecordingStatus;
  stopRecording: () => void;
  createDetector?: CreateVoiceActivityDetector;
}

interface UseVadAutoStopResult {
  runtimeStatus: VadRuntimeStatus;
  message: string | null;
}

function messageForStatus(status: VadRuntimeStatus): string | null {
  switch (status) {
    case 'loading':
      return '正在加载语音端点检测';
    case 'listening':
      return '正在监听语音结束';
    case 'speech_detected':
      return '检测到语音，正在等待结束';
    case 'speech_ended':
      return '检测到语音结束，正在停止录音';
    case 'unavailable':
      return '语音端点检测不可用，请手动停止';
    case 'disabled':
    default:
      return null;
  }
}

export function useVadAutoStop({
  enabled,
  recordingStatus,
  stopRecording,
  createDetector = createSileroVad,
}: UseVadAutoStopOptions): UseVadAutoStopResult {
  const [runtimeStatus, setRuntimeStatus] = useState<VadRuntimeStatus>('disabled');
  const generationRef = useRef(0);
  const detectorRef = useRef<VoiceActivityDetector | null>(null);
  const stopRequestedRef = useRef(false);
  const stopRecordingRef = useRef(stopRecording);

  stopRecordingRef.current = stopRecording;

  useEffect(() => {
    if (!enabled || recordingStatus !== 'recording') {
      generationRef.current += 1;
      stopRequestedRef.current = false;
      const detector = detectorRef.current;
      detectorRef.current = null;
      if (detector) void detector.stop();
      setRuntimeStatus('disabled');
      return;
    }

    generationRef.current += 1;
    const generation = generationRef.current;
    stopRequestedRef.current = false;
    let disposed = false;

    setRuntimeStatus('loading');

    void (async () => {
      try {
        const detector = await createDetector({
          onSpeechStart: () => {
            if (disposed || generationRef.current !== generation) return;
            setRuntimeStatus('speech_detected');
          },
          onSpeechEnd: () => {
            if (disposed || generationRef.current !== generation) return;
            if (stopRequestedRef.current) return;
            stopRequestedRef.current = true;
            setRuntimeStatus('speech_ended');
            stopRecordingRef.current();
          },
          onError: () => {
            if (disposed || generationRef.current !== generation) return;
            setRuntimeStatus('unavailable');
          },
        });

        if (disposed || generationRef.current !== generation) {
          await detector.stop();
          return;
        }

        detectorRef.current = detector;
        await detector.start();

        if (!disposed && generationRef.current === generation) {
          setRuntimeStatus('listening');
        }
      } catch {
        if (!disposed && generationRef.current === generation) {
          detectorRef.current = null;
          setRuntimeStatus('unavailable');
        }
      }
    })();

    return () => {
      disposed = true;
      generationRef.current += 1;
      stopRequestedRef.current = false;
      const detector = detectorRef.current;
      detectorRef.current = null;
      if (detector) void detector.stop();
    };
  }, [enabled, recordingStatus, createDetector]);

  const message = useMemo(() => messageForStatus(runtimeStatus), [runtimeStatus]);
  return { runtimeStatus, message };
}
