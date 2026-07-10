import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { UseAudioInputDevicesResult } from '../hooks/useAudioInputDevices';
import type { UseAudioOutputDevicesResult } from '../hooks/useAudioOutputDevices';
import type { UseManualAudioRecorderResult } from '../hooks/useManualAudioRecorder';
import { VoiceRecorder } from './VoiceRecorder';

function recorder(overrides: Partial<UseManualAudioRecorderResult> = {}): UseManualAudioRecorderResult {
  return {
    status: 'recording',
    elapsedMs: 1000,
    partialTranscript: null,
    pendingTranscript: null,
    error: null,
    isPlaybackBlocked: true,
    startRecording: vi.fn(),
    stopRecording: vi.fn(),
    cancelRecording: vi.fn(),
    clearResult: vi.fn(),
    ...overrides,
  };
}

const audioInputDevices: UseAudioInputDevicesResult = {
  devices: [],
  selectedDeviceId: '',
  setSelectedDeviceId: vi.fn(),
  refreshDevices: vi.fn().mockResolvedValue(undefined),
  status: 'ready',
  error: null,
};

const audioOutputDevices: UseAudioOutputDevicesResult = {
  devices: [],
  selectedDeviceId: '',
  setSelectedDeviceId: vi.fn(),
  refreshDevices: vi.fn().mockResolvedValue(undefined),
  selectOutputDevice: vi.fn().mockResolvedValue(undefined),
  status: 'ready',
  error: null,
  canSelectOutput: false,
};

describe('VoiceRecorder', () => {
  it('shows partial transcript as a non-final realtime preview', () => {
    render(
      <VoiceRecorder
        recorder={recorder({ partialTranscript: '语音' })}
        disabled={false}
        audioInputDevices={audioInputDevices}
        audioOutputDevices={audioOutputDevices}
      />,
    );

    expect(screen.getByText('实时转写预览：语音')).toBeInTheDocument();
  });
});
