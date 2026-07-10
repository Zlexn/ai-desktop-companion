import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useAudioInputDevices } from './useAudioInputDevices';

const originalMediaDevices = navigator.mediaDevices;

interface FakeMediaDevices {
  enumerateDevices?: ReturnType<typeof vi.fn>;
  addEventListener?: ReturnType<typeof vi.fn>;
  removeEventListener?: ReturnType<typeof vi.fn>;
}

function setMediaDevices(value: FakeMediaDevices | undefined) {
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value,
  });
}

function audioInput(deviceId: string, label: string): MediaDeviceInfo {
  return {
    deviceId,
    groupId: `group-${deviceId}`,
    kind: 'audioinput',
    label,
    toJSON: () => ({}),
  } as MediaDeviceInfo;
}

function videoInput(deviceId: string): MediaDeviceInfo {
  return {
    deviceId,
    groupId: `group-${deviceId}`,
    kind: 'videoinput',
    label: 'camera',
    toJSON: () => ({}),
  } as MediaDeviceInfo;
}

describe('useAudioInputDevices', () => {
  beforeEach(() => {
    vi.useRealTimers();
    localStorage.clear();
  });

  afterEach(() => {
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: originalMediaDevices,
    });
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('reports unsupported when enumerateDevices is unavailable', async () => {
    setMediaDevices(undefined);

    const { result } = renderHook(() => useAudioInputDevices());

    await waitFor(() => expect(result.current.status).toBe('unsupported'));
    expect(result.current.devices).toEqual([]);
    expect(result.current.error).toBe('当前浏览器不支持麦克风设备列表');
    expect(result.current.selectedDeviceId).toBe('');
  });

  it('lists only audio input devices and uses fallback labels for hidden labels', async () => {
    setMediaDevices({
      enumerateDevices: vi.fn().mockResolvedValue([
        audioInput('default', 'Built-in Microphone'),
        audioInput('usb', ''),
        videoInput('camera'),
      ]),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    });

    const { result } = renderHook(() => useAudioInputDevices());

    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.devices).toEqual([
      { deviceId: 'default', label: 'Built-in Microphone' },
      { deviceId: 'usb', label: '麦克风 2' },
    ]);
  });

  it('refreshes devices on demand', async () => {
    const enumerateDevices = vi.fn()
      .mockResolvedValueOnce([audioInput('one', 'Mic One')])
      .mockResolvedValueOnce([audioInput('two', 'Mic Two')]);
    setMediaDevices({ enumerateDevices, addEventListener: vi.fn(), removeEventListener: vi.fn() });

    const { result } = renderHook(() => useAudioInputDevices());
    await waitFor(() => expect(result.current.devices).toEqual([{ deviceId: 'one', label: 'Mic One' }]));

    await act(async () => {
      await result.current.refreshDevices();
    });

    expect(result.current.devices).toEqual([{ deviceId: 'two', label: 'Mic Two' }]);
    expect(enumerateDevices).toHaveBeenCalledTimes(2);
  });

  it('refreshes after devicechange when the browser supports the event', async () => {
    let deviceChangeHandler: (() => void) | undefined;
    const enumerateDevices = vi.fn()
      .mockResolvedValueOnce([audioInput('one', 'Mic One')])
      .mockResolvedValueOnce([audioInput('two', 'Mic Two')]);
    const addEventListener = vi.fn((event: string, handler: EventListener) => {
      if (event === 'devicechange') deviceChangeHandler = handler as () => void;
    });
    const removeEventListener = vi.fn();
    setMediaDevices({ enumerateDevices, addEventListener, removeEventListener });

    const { result, unmount } = renderHook(() => useAudioInputDevices());
    await waitFor(() => expect(result.current.devices).toEqual([{ deviceId: 'one', label: 'Mic One' }]));

    await act(async () => {
      deviceChangeHandler?.();
    });

    await waitFor(() => expect(result.current.devices).toEqual([{ deviceId: 'two', label: 'Mic Two' }]));
    unmount();
    expect(removeEventListener).toHaveBeenCalledWith('devicechange', expect.any(Function));
  });

  it('resets selected device to default when selected device disappears', async () => {
    const enumerateDevices = vi.fn()
      .mockResolvedValueOnce([audioInput('usb', 'USB Mic')])
      .mockResolvedValueOnce([audioInput('other', 'Other Mic')]);
    setMediaDevices({ enumerateDevices, addEventListener: vi.fn(), removeEventListener: vi.fn() });

    const { result } = renderHook(() => useAudioInputDevices());
    await waitFor(() => expect(result.current.devices).toEqual([{ deviceId: 'usb', label: 'USB Mic' }]));

    act(() => {
      result.current.setSelectedDeviceId('usb');
    });
    expect(result.current.selectedDeviceId).toBe('usb');

    await act(async () => {
      await result.current.refreshDevices();
    });

    expect(result.current.devices).toEqual([{ deviceId: 'other', label: 'Other Mic' }]);
    expect(result.current.selectedDeviceId).toBe('');
  });

  it('keeps recording path recoverable when enumeration fails', async () => {
    setMediaDevices({
      enumerateDevices: vi.fn().mockRejectedValue(new Error('blocked')),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    });

    const { result } = renderHook(() => useAudioInputDevices());

    await waitFor(() => expect(result.current.status).toBe('error'));
    expect(result.current.devices).toEqual([]);
    expect(result.current.error).toBe('无法读取麦克风设备，请使用系统默认麦克风');
    expect(result.current.selectedDeviceId).toBe('');
  });

  it('initializes selected microphone from saved preference', async () => {
    localStorage.setItem('ai-desktop-companion.audio-device-preferences.v1', JSON.stringify({
      inputDeviceId: 'usb-mic',
      outputDeviceId: '',
    }));
    setMediaDevices({
      enumerateDevices: vi.fn().mockResolvedValue([
        audioInput('default', 'Default Mic'),
        audioInput('usb-mic', 'USB Mic'),
      ]),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    });

    const { result } = renderHook(() => useAudioInputDevices());

    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.selectedDeviceId).toBe('usb-mic');
  });

  it('persists selected microphone changes', async () => {
    setMediaDevices({
      enumerateDevices: vi.fn().mockResolvedValue([audioInput('usb-mic', 'USB Mic')]),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    });

    const { result } = renderHook(() => useAudioInputDevices());
    await waitFor(() => expect(result.current.status).toBe('ready'));

    act(() => {
      result.current.setSelectedDeviceId('usb-mic');
    });

    expect(JSON.parse(localStorage.getItem('ai-desktop-companion.audio-device-preferences.v1') ?? '{}')).toMatchObject({
      inputDeviceId: 'usb-mic',
    });
  });

  it('clears stale saved microphone preference after successful enumeration', async () => {
    localStorage.setItem('ai-desktop-companion.audio-device-preferences.v1', JSON.stringify({
      inputDeviceId: 'missing-mic',
      outputDeviceId: 'speaker-1',
    }));
    setMediaDevices({
      enumerateDevices: vi.fn().mockResolvedValue([audioInput('usb-mic', 'USB Mic')]),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    });

    const { result } = renderHook(() => useAudioInputDevices());

    await waitFor(() => expect(result.current.status).toBe('ready'));
    expect(result.current.selectedDeviceId).toBe('');
    expect(JSON.parse(localStorage.getItem('ai-desktop-companion.audio-device-preferences.v1') ?? '{}')).toEqual({
      inputDeviceId: '',
      outputDeviceId: 'speaker-1',
    });
  });
});
