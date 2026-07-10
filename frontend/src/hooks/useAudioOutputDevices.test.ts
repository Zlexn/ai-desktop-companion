import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useAudioOutputDevices } from './useAudioOutputDevices';

const originalMediaDevices = navigator.mediaDevices;
const originalSetSinkId = HTMLMediaElement.prototype.setSinkId;

interface FakeMediaDevices {
  enumerateDevices?: ReturnType<typeof vi.fn>;
  selectAudioOutput?: ReturnType<typeof vi.fn>;
  addEventListener?: ReturnType<typeof vi.fn>;
  removeEventListener?: ReturnType<typeof vi.fn>;
}

function setMediaDevices(value: FakeMediaDevices | undefined) {
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value,
  });
}

function setSetSinkId(value: ((sinkId: string) => Promise<void>) | undefined) {
  if (value) {
    Object.defineProperty(HTMLMediaElement.prototype, 'setSinkId', {
      configurable: true,
      value,
    });
    return;
  }

  Object.defineProperty(HTMLMediaElement.prototype, 'setSinkId', {
    configurable: true,
    value: undefined,
  });
}

function audioOutput(deviceId: string, label: string): MediaDeviceInfo {
  return {
    deviceId,
    groupId: `group-${deviceId}`,
    kind: 'audiooutput',
    label,
    toJSON: () => ({}),
  } as MediaDeviceInfo;
}

function audioInput(deviceId: string): MediaDeviceInfo {
  return {
    deviceId,
    groupId: `group-${deviceId}`,
    kind: 'audioinput',
    label: 'mic',
    toJSON: () => ({}),
  } as MediaDeviceInfo;
}

describe('useAudioOutputDevices', () => {
  beforeEach(() => {
    localStorage.clear();
    setSetSinkId(vi.fn().mockResolvedValue(undefined));
  });

  afterEach(() => {
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: originalMediaDevices,
    });
    if (originalSetSinkId) {
      Object.defineProperty(HTMLMediaElement.prototype, 'setSinkId', {
        configurable: true,
        value: originalSetSinkId,
      });
    } else {
      delete (HTMLMediaElement.prototype as Partial<HTMLMediaElement>).setSinkId;
    }
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('reports unsupported when setSinkId is unavailable', async () => {
    setSetSinkId(undefined);
    setMediaDevices({ enumerateDevices: vi.fn() });

    const { result } = renderHook(() => useAudioOutputDevices());

    await waitFor(() => expect(result.current.status).toBe('unsupported'));
    expect(result.current.devices).toEqual([]);
    expect(result.current.selectedDeviceId).toBe('');
    expect(result.current.canSelectOutput).toBe(false);
    expect(result.current.error).toBe('当前浏览器不支持单独选择输出设备，将使用系统默认输出。');
  });

  it('lists only audio output devices and uses fallback labels', async () => {
    setMediaDevices({
      enumerateDevices: vi.fn().mockResolvedValue([
        audioOutput('default', 'Default Speaker'),
        audioOutput('usb', ''),
        audioInput('mic'),
      ]),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    });

    const { result } = renderHook(() => useAudioOutputDevices());

    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.devices).toEqual([
      { deviceId: 'default', label: 'Default Speaker' },
      { deviceId: 'usb', label: '输出设备 2' },
    ]);
  });

  it('initializes selected output from saved preference', async () => {
    localStorage.setItem('ai-desktop-companion.audio-device-preferences.v1', JSON.stringify({
      inputDeviceId: '',
      outputDeviceId: 'usb-speaker',
    }));
    setMediaDevices({
      enumerateDevices: vi.fn().mockResolvedValue([
        audioOutput('default', 'Default Speaker'),
        audioOutput('usb-speaker', 'USB Speaker'),
      ]),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    });

    const { result } = renderHook(() => useAudioOutputDevices());

    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.selectedDeviceId).toBe('usb-speaker');
  });

  it('persists selected output changes', async () => {
    setMediaDevices({
      enumerateDevices: vi.fn().mockResolvedValue([audioOutput('usb-speaker', 'USB Speaker')]),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    });

    const { result } = renderHook(() => useAudioOutputDevices());
    await waitFor(() => expect(result.current.status).toBe('ready'));

    act(() => {
      result.current.setSelectedDeviceId('usb-speaker');
    });

    expect(JSON.parse(localStorage.getItem('ai-desktop-companion.audio-device-preferences.v1') ?? '{}')).toMatchObject({
      outputDeviceId: 'usb-speaker',
    });
  });

  it('clears stale saved output preference after successful enumeration', async () => {
    localStorage.setItem('ai-desktop-companion.audio-device-preferences.v1', JSON.stringify({
      inputDeviceId: 'usb-mic',
      outputDeviceId: 'missing-speaker',
    }));
    setMediaDevices({
      enumerateDevices: vi.fn().mockResolvedValue([audioOutput('usb-speaker', 'USB Speaker')]),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    });

    const { result } = renderHook(() => useAudioOutputDevices());

    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.selectedDeviceId).toBe('');
    expect(JSON.parse(localStorage.getItem('ai-desktop-companion.audio-device-preferences.v1') ?? '{}')).toEqual({
      inputDeviceId: 'usb-mic',
      outputDeviceId: '',
    });
  });

  it('uses selectAudioOutput when explicitly requested', async () => {
    const enumerateDevices = vi.fn()
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([audioOutput('chosen-speaker', 'Chosen Speaker')]);
    const selectAudioOutput = vi.fn().mockResolvedValue(audioOutput('chosen-speaker', 'Chosen Speaker'));
    setMediaDevices({
      enumerateDevices,
      selectAudioOutput,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    });

    const { result } = renderHook(() => useAudioOutputDevices());
    await waitFor(() => expect(result.current.status).toBe('ready'));

    await act(async () => {
      await result.current.selectOutputDevice();
    });

    expect(selectAudioOutput).toHaveBeenCalledTimes(1);
    expect(result.current.selectedDeviceId).toBe('chosen-speaker');
    expect(result.current.devices).toEqual([{ deviceId: 'chosen-speaker', label: 'Chosen Speaker' }]);
  });

  it('handles selectAudioOutput rejection without throwing', async () => {
    setMediaDevices({
      enumerateDevices: vi.fn().mockResolvedValue([]),
      selectAudioOutput: vi.fn().mockRejectedValue(new DOMException('cancelled', 'NotAllowedError')),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    });

    const { result } = renderHook(() => useAudioOutputDevices());
    await waitFor(() => expect(result.current.status).toBe('ready'));

    await act(async () => {
      await result.current.selectOutputDevice();
    });

    expect(result.current.selectedDeviceId).toBe('');
    expect(result.current.error).toBe('未选择输出设备，将继续使用系统默认输出。');
  });
});
