import { useCallback, useEffect, useRef, useState } from 'react';
import {
  clearAudioDevicePreference,
  loadAudioDevicePreferences,
  saveAudioDevicePreference,
} from '../audioDevicePreferences';

export interface AudioInputDeviceOption {
  deviceId: string;
  label: string;
}

export type AudioInputDeviceStatus = 'idle' | 'loading' | 'ready' | 'unsupported' | 'error';

export interface UseAudioInputDevicesResult {
  devices: AudioInputDeviceOption[];
  selectedDeviceId: string;
  setSelectedDeviceId: (deviceId: string) => void;
  refreshDevices: () => Promise<void>;
  status: AudioInputDeviceStatus;
  error: string | null;
}

const UNSUPPORTED_MESSAGE = '当前浏览器不支持麦克风设备列表';
const ENUMERATION_ERROR_MESSAGE = '无法读取麦克风设备，请使用系统默认麦克风';

function toAudioInputOptions(devices: MediaDeviceInfo[]): AudioInputDeviceOption[] {
  return devices
    .filter((device) => device.kind === 'audioinput')
    .map((device, index) => ({
      deviceId: device.deviceId,
      label: device.label.trim() || `麦克风 ${index + 1}`,
    }));
}

export function useAudioInputDevices(): UseAudioInputDevicesResult {
  const [devices, setDevices] = useState<AudioInputDeviceOption[]>([]);
  const [selectedDeviceId, setSelectedDeviceIdState] = useState(() => loadAudioDevicePreferences().inputDeviceId);
  const [status, setStatus] = useState<AudioInputDeviceStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const selectedDeviceIdRef = useRef(selectedDeviceId);
  const generationRef = useRef(0);

  selectedDeviceIdRef.current = selectedDeviceId;

  const setSelectedDeviceId = useCallback((deviceId: string) => {
    setSelectedDeviceIdState(deviceId);
    saveAudioDevicePreference('inputDeviceId', deviceId);
  }, []);

  const refreshDevices = useCallback(async () => {
    const mediaDevices = navigator.mediaDevices;
    if (!mediaDevices?.enumerateDevices) {
      setDevices([]);
      setSelectedDeviceIdState('');
      clearAudioDevicePreference('inputDeviceId');
      setStatus('unsupported');
      setError(UNSUPPORTED_MESSAGE);
      return;
    }

    generationRef.current += 1;
    const generation = generationRef.current;
    setStatus('loading');
    setError(null);

    try {
      const nextDevices = toAudioInputOptions(await mediaDevices.enumerateDevices());
      if (generationRef.current !== generation) return;

      setDevices(nextDevices);
      if (selectedDeviceIdRef.current && !nextDevices.some((device) => device.deviceId === selectedDeviceIdRef.current)) {
        setSelectedDeviceIdState('');
        clearAudioDevicePreference('inputDeviceId');
      }
      setStatus('ready');
    } catch {
      if (generationRef.current !== generation) return;
      setDevices([]);
      setSelectedDeviceIdState('');
      clearAudioDevicePreference('inputDeviceId');
      setStatus('error');
      setError(ENUMERATION_ERROR_MESSAGE);
    }
  }, []);

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
    status,
    error,
  };
}
