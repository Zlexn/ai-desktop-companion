import { useCallback, useEffect, useRef, useState } from 'react';
import {
  clearAudioDevicePreference,
  loadAudioDevicePreferences,
  saveAudioDevicePreference,
} from '../audioDevicePreferences';

export interface AudioOutputDeviceOption {
  deviceId: string;
  label: string;
}

export type AudioOutputDeviceStatus = 'idle' | 'loading' | 'ready' | 'unsupported' | 'error';

export interface UseAudioOutputDevicesResult {
  devices: AudioOutputDeviceOption[];
  selectedDeviceId: string;
  setSelectedDeviceId: (deviceId: string) => void;
  refreshDevices: () => Promise<void>;
  selectOutputDevice: () => Promise<void>;
  status: AudioOutputDeviceStatus;
  error: string | null;
  canSelectOutput: boolean;
}

const UNSUPPORTED_MESSAGE = '当前浏览器不支持单独选择输出设备，将使用系统默认输出。';
const ENUMERATION_ERROR_MESSAGE = '无法读取输出设备，请使用系统默认输出。';
const SELECTION_ERROR_MESSAGE = '未选择输出设备，将继续使用系统默认输出。';

function supportsSetSinkId(): boolean {
  return typeof HTMLMediaElement !== 'undefined' && typeof HTMLMediaElement.prototype.setSinkId === 'function';
}

function toAudioOutputOptions(devices: MediaDeviceInfo[]): AudioOutputDeviceOption[] {
  return devices
    .filter((device) => device.kind === 'audiooutput')
    .map((device, index) => ({
      deviceId: device.deviceId,
      label: device.label.trim() || `输出设备 ${index + 1}`,
    }));
}

export function useAudioOutputDevices(): UseAudioOutputDevicesResult {
  const [devices, setDevices] = useState<AudioOutputDeviceOption[]>([]);
  const [selectedDeviceId, setSelectedDeviceIdState] = useState(() => loadAudioDevicePreferences().outputDeviceId);
  const [status, setStatus] = useState<AudioOutputDeviceStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const selectedDeviceIdRef = useRef(selectedDeviceId);
  const generationRef = useRef(0);

  selectedDeviceIdRef.current = selectedDeviceId;

  const setSelectedDeviceId = useCallback((deviceId: string) => {
    setSelectedDeviceIdState(deviceId);
    saveAudioDevicePreference('outputDeviceId', deviceId);
  }, []);

  const refreshDevices = useCallback(async () => {
    if (!supportsSetSinkId()) {
      setDevices([]);
      setSelectedDeviceIdState('');
      clearAudioDevicePreference('outputDeviceId');
      setStatus('unsupported');
      setError(UNSUPPORTED_MESSAGE);
      return;
    }

    const mediaDevices = navigator.mediaDevices;
    if (!mediaDevices?.enumerateDevices) {
      setDevices([]);
      setSelectedDeviceIdState('');
      clearAudioDevicePreference('outputDeviceId');
      setStatus('unsupported');
      setError(UNSUPPORTED_MESSAGE);
      return;
    }

    generationRef.current += 1;
    const generation = generationRef.current;
    setStatus('loading');
    setError(null);

    try {
      const nextDevices = toAudioOutputOptions(await mediaDevices.enumerateDevices());
      if (generationRef.current !== generation) return;

      setDevices(nextDevices);
      if (selectedDeviceIdRef.current && !nextDevices.some((device) => device.deviceId === selectedDeviceIdRef.current)) {
        setSelectedDeviceIdState('');
        clearAudioDevicePreference('outputDeviceId');
      }
      setStatus('ready');
    } catch {
      if (generationRef.current !== generation) return;
      setDevices([]);
      setStatus('error');
      setError(ENUMERATION_ERROR_MESSAGE);
    }
  }, []);

  const selectOutputDevice = useCallback(async () => {
    if (!supportsSetSinkId()) {
      setStatus('unsupported');
      setError(UNSUPPORTED_MESSAGE);
      return;
    }

    const mediaDevices = navigator.mediaDevices as MediaDevices & {
      selectAudioOutput?: () => Promise<MediaDeviceInfo>;
    };

    if (!mediaDevices?.selectAudioOutput) {
      setError(UNSUPPORTED_MESSAGE);
      return;
    }

    try {
      const device = await mediaDevices.selectAudioOutput();
      setSelectedDeviceId(device.deviceId);
      await refreshDevices();
    } catch {
      setError(SELECTION_ERROR_MESSAGE);
    }
  }, [refreshDevices, setSelectedDeviceId]);

  useEffect(() => {
    void refreshDevices();
  }, [refreshDevices]);

  useEffect(() => {
    const mediaDevices = navigator.mediaDevices;
    if (!mediaDevices?.addEventListener || !mediaDevices?.removeEventListener) return;

    const handleDeviceChange = () => {
      void refreshDevices();
    };
    mediaDevices.addEventListener('devicechange', handleDeviceChange);
    return () => mediaDevices.removeEventListener('devicechange', handleDeviceChange);
  }, [refreshDevices]);

  return {
    devices,
    selectedDeviceId,
    setSelectedDeviceId,
    refreshDevices,
    selectOutputDevice,
    status,
    error,
    canSelectOutput: supportsSetSinkId() && typeof (navigator.mediaDevices as MediaDevices & { selectAudioOutput?: unknown } | undefined)?.selectAudioOutput === 'function',
  };
}
