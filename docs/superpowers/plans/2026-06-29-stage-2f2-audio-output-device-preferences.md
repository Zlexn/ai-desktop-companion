# Stage 2F-2 Audio Output Device Preferences Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add browser-local microphone/output-device preference persistence and route assistant TTS playback to the selected audio output device when the browser supports it.

**Architecture:** Keep this entirely in the frontend. Add a small localStorage preference helper, extend the existing input-device hook, add a new output-device hook, pass the selected output device into the existing playback controller, and render output controls beside the existing microphone controls. Unsupported or failing device APIs must fall back to system defaults without breaking text chat, ASR, TTS, VAD, interruption, or session cleanup.

**Tech Stack:** React, TypeScript, Vite, Vitest, Testing Library, Playwright, browser `localStorage`, `navigator.mediaDevices.enumerateDevices`, optional `navigator.mediaDevices.selectAudioOutput`, optional `HTMLMediaElement.setSinkId`.

---

## Scope guard

Implement only `docs/superpowers/specs/2026-06-29-stage-2f2-audio-output-device-preferences-design.md`.

Do not implement streaming ASR/TTS, long-term memory, emotion state, backend APIs, database schema changes, wake word, background listening, or telemetry.

Because the current session has not received explicit authorization to create git commits, every task ends with a **checkpoint** instead of a commit. If the user explicitly authorizes commits later, commit after each task using the message shown in that task.

## File structure

Create:

- `frontend/src/audioDevicePreferences.ts`
  - Owns all browser-local audio device preference reads/writes.
  - Stores only opaque device IDs.
  - Tolerates missing `window`, unavailable `localStorage`, malformed JSON, and storage exceptions.

- `frontend/src/audioDevicePreferences.test.ts`
  - Unit tests for preference read/write/clear behavior and storage failure paths.

- `frontend/src/hooks/useAudioOutputDevices.ts`
  - React hook for output-device support detection, enumeration, explicit speaker selection, local preference persistence, and stale device reset.

- `frontend/src/hooks/useAudioOutputDevices.test.ts`
  - Unit tests for unsupported mode, enumeration, selectAudioOutput, preference persistence, stale reset, and failure handling.

Modify:

- `frontend/src/hooks/useAudioInputDevices.ts`
  - Initialize from saved input preference.
  - Persist input preference changes.
  - Reset stale saved input device to default after successful enumeration.

- `frontend/src/hooks/useAudioInputDevices.test.ts`
  - Add preference persistence tests to existing input-device coverage.

- `frontend/src/hooks/useAudioPlaybackController.ts`
  - Accept `{ audioOutputDeviceId?: string }` options.
  - Apply `setSinkId` before playback when supported.
  - Preserve current playback states, Blob URL reuse, interruption, stop/reset, pause/resume/replay behavior.

- `frontend/src/components/MessageList.test.tsx`
  - Add controller-level tests through the existing `MessageList` harness for `setSinkId` success, unsupported fallback, and rejection error.

- `frontend/src/App.tsx`
  - Instantiate `useAudioOutputDevices`.
  - Pass `audioOutputDeviceId` into `useAudioPlaybackController`.
  - Pass `audioOutputDevices` into `ChatLayout`.

- `frontend/src/components/ChatLayout.tsx`
  - Add `audioOutputDevices` prop and pass it into `VoiceRecorder`.

- `frontend/src/components/VoiceRecorder.tsx`
  - Render output-device controls next to existing microphone controls.
  - Keep controls disabled during recording or playback-blocking recorder states.

- `frontend/src/App.test.tsx`
  - Add app-level UI tests for output-device controls and selected output routing.

- `frontend/e2e/voice-turn.spec.ts`
  - Add fake output-device support to the existing half-duplex voice-turn test and assert output selection does not add duplicate chat/TTS requests.

- `frontend/src/styles.css`
  - Add or adjust classes for output device controls while matching current compact voice-recorder style.

- `docs/stage2f2-audio-output-device-preferences.md`
  - Evidence document with validation commands and results.

- `CLAUDE.md`
  - Update Stage 2 status after implementation and verification only.

- `README.md`
  - Update only if browser-support notes are needed after implementation.

---

## Task 1: Add local audio device preference helper

**Files:**
- Create: `frontend/src/audioDevicePreferences.ts`
- Create: `frontend/src/audioDevicePreferences.test.ts`

- [ ] **Step 1: Write failing tests for preference storage**

Create `frontend/src/audioDevicePreferences.test.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  AUDIO_DEVICE_PREFERENCES_KEY,
  clearAudioDevicePreference,
  loadAudioDevicePreferences,
  saveAudioDevicePreference,
} from './audioDevicePreferences';

describe('audioDevicePreferences', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it('returns defaults when no preferences are stored', () => {
    expect(loadAudioDevicePreferences()).toEqual({ inputDeviceId: '', outputDeviceId: '' });
  });

  it('loads valid stored preferences', () => {
    localStorage.setItem(AUDIO_DEVICE_PREFERENCES_KEY, JSON.stringify({
      inputDeviceId: 'usb-mic',
      outputDeviceId: 'usb-speaker',
    }));

    expect(loadAudioDevicePreferences()).toEqual({ inputDeviceId: 'usb-mic', outputDeviceId: 'usb-speaker' });
  });

  it('ignores malformed JSON and falls back to defaults', () => {
    localStorage.setItem(AUDIO_DEVICE_PREFERENCES_KEY, '{broken');

    expect(loadAudioDevicePreferences()).toEqual({ inputDeviceId: '', outputDeviceId: '' });
  });

  it('ignores non-string preference fields', () => {
    localStorage.setItem(AUDIO_DEVICE_PREFERENCES_KEY, JSON.stringify({
      inputDeviceId: 123,
      outputDeviceId: null,
    }));

    expect(loadAudioDevicePreferences()).toEqual({ inputDeviceId: '', outputDeviceId: '' });
  });

  it('saves one device preference without overwriting the other', () => {
    saveAudioDevicePreference('inputDeviceId', 'usb-mic');
    saveAudioDevicePreference('outputDeviceId', 'usb-speaker');

    expect(JSON.parse(localStorage.getItem(AUDIO_DEVICE_PREFERENCES_KEY) ?? '{}')).toEqual({
      inputDeviceId: 'usb-mic',
      outputDeviceId: 'usb-speaker',
    });
  });

  it('clears one preference while preserving the other', () => {
    localStorage.setItem(AUDIO_DEVICE_PREFERENCES_KEY, JSON.stringify({
      inputDeviceId: 'usb-mic',
      outputDeviceId: 'usb-speaker',
    }));

    clearAudioDevicePreference('inputDeviceId');

    expect(loadAudioDevicePreferences()).toEqual({ inputDeviceId: '', outputDeviceId: 'usb-speaker' });
  });

  it('treats localStorage read failures as defaults', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage blocked');
    });

    expect(loadAudioDevicePreferences()).toEqual({ inputDeviceId: '', outputDeviceId: '' });
  });

  it('does not throw when localStorage write fails', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota exceeded');
    });

    expect(() => saveAudioDevicePreference('outputDeviceId', 'usb-speaker')).not.toThrow();
  });
});
```

- [ ] **Step 2: Run the new tests and verify they fail because the helper does not exist**

Run:

```text
cd frontend
npm test -- --run src/audioDevicePreferences.test.ts
```

Expected result:

```text
FAIL  src/audioDevicePreferences.test.ts
Error: Failed to resolve import "./audioDevicePreferences"
```

- [ ] **Step 3: Implement the preference helper**

Create `frontend/src/audioDevicePreferences.ts`:

```ts
export const AUDIO_DEVICE_PREFERENCES_KEY = 'ai-desktop-companion.audio-device-preferences.v1';

export interface AudioDevicePreferences {
  inputDeviceId: string;
  outputDeviceId: string;
}

type AudioDevicePreferenceKey = keyof AudioDevicePreferences;

const DEFAULT_PREFERENCES: AudioDevicePreferences = {
  inputDeviceId: '',
  outputDeviceId: '',
};

function getStorage(): Storage | null {
  try {
    if (typeof window === 'undefined') return null;
    return window.localStorage ?? null;
  } catch {
    return null;
  }
}

function normalizePreferences(value: unknown): AudioDevicePreferences {
  if (!value || typeof value !== 'object') return { ...DEFAULT_PREFERENCES };
  const candidate = value as Partial<Record<AudioDevicePreferenceKey, unknown>>;
  return {
    inputDeviceId: typeof candidate.inputDeviceId === 'string' ? candidate.inputDeviceId : '',
    outputDeviceId: typeof candidate.outputDeviceId === 'string' ? candidate.outputDeviceId : '',
  };
}

export function loadAudioDevicePreferences(): AudioDevicePreferences {
  const storage = getStorage();
  if (!storage) return { ...DEFAULT_PREFERENCES };

  try {
    const raw = storage.getItem(AUDIO_DEVICE_PREFERENCES_KEY);
    if (!raw) return { ...DEFAULT_PREFERENCES };
    return normalizePreferences(JSON.parse(raw));
  } catch {
    return { ...DEFAULT_PREFERENCES };
  }
}

export function saveAudioDevicePreference(key: AudioDevicePreferenceKey, deviceId: string): void {
  const storage = getStorage();
  if (!storage) return;

  try {
    const preferences = loadAudioDevicePreferences();
    preferences[key] = deviceId;
    storage.setItem(AUDIO_DEVICE_PREFERENCES_KEY, JSON.stringify(preferences));
  } catch {
    // Local preferences are optional; system defaults remain usable.
  }
}

export function clearAudioDevicePreference(key: AudioDevicePreferenceKey): void {
  saveAudioDevicePreference(key, '');
}
```

- [ ] **Step 4: Run the helper tests and verify they pass**

Run:

```text
cd frontend
npm test -- --run src/audioDevicePreferences.test.ts
```

Expected result:

```text
PASS  src/audioDevicePreferences.test.ts
```

- [ ] **Step 5: Checkpoint**

Run:

```text
git status --short
```

Expected changed files include:

```text
?? frontend/src/audioDevicePreferences.ts
?? frontend/src/audioDevicePreferences.test.ts
```

If commit authorization is active, commit with:

```text
git add frontend/src/audioDevicePreferences.ts frontend/src/audioDevicePreferences.test.ts
git commit -m "feat: add audio device preferences helper"
```

---

## Task 2: Persist microphone input-device preference

**Files:**
- Modify: `frontend/src/hooks/useAudioInputDevices.ts`
- Modify: `frontend/src/hooks/useAudioInputDevices.test.ts`

- [ ] **Step 1: Add failing input preference tests**

Append these tests inside the existing `describe('useAudioInputDevices', () => { ... })` block in `frontend/src/hooks/useAudioInputDevices.test.ts`:

```ts
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
```

Also add `localStorage.clear();` to the existing `beforeEach` and `afterEach` blocks:

```ts
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
```

- [ ] **Step 2: Run input-device tests and verify the new tests fail**

Run:

```text
cd frontend
npm test -- --run src/hooks/useAudioInputDevices.test.ts
```

Expected result:

```text
FAIL  src/hooks/useAudioInputDevices.test.ts
```

The failure should show that `selectedDeviceId` stays `''` and localStorage is not updated.

- [ ] **Step 3: Implement preference persistence in the input hook**

Modify `frontend/src/hooks/useAudioInputDevices.ts`.

Add imports:

```ts
import {
  clearAudioDevicePreference,
  loadAudioDevicePreferences,
  saveAudioDevicePreference,
} from '../audioDevicePreferences';
```

Replace the selected-device state initialization and setter exposure with this pattern:

```ts
  const [selectedDeviceId, setSelectedDeviceIdState] = useState(() => loadAudioDevicePreferences().inputDeviceId);
```

Add this callback after `selectedDeviceIdRef.current = selectedDeviceId;`:

```ts
  const setSelectedDeviceId = useCallback((deviceId: string) => {
    setSelectedDeviceIdState(deviceId);
    saveAudioDevicePreference('inputDeviceId', deviceId);
  }, []);
```

Then replace existing internal calls to `setSelectedDeviceId('')` with:

```ts
setSelectedDeviceIdState('');
clearAudioDevicePreference('inputDeviceId');
```

In the successful enumeration block, use the current ref and clear stale saved IDs:

```ts
      setDevices(nextDevices);
      if (selectedDeviceIdRef.current && !nextDevices.some((device) => device.deviceId === selectedDeviceIdRef.current)) {
        setSelectedDeviceIdState('');
        clearAudioDevicePreference('inputDeviceId');
      }
      setStatus('ready');
```

In unsupported and error paths, keep the current behavior of resetting the state to default and clear the saved input preference:

```ts
      setDevices([]);
      setSelectedDeviceIdState('');
      clearAudioDevicePreference('inputDeviceId');
```

Return the new `setSelectedDeviceId` callback from the hook.

- [ ] **Step 4: Run input-device tests and verify they pass**

Run:

```text
cd frontend
npm test -- --run src/hooks/useAudioInputDevices.test.ts
```

Expected result:

```text
PASS  src/hooks/useAudioInputDevices.test.ts
```

- [ ] **Step 5: Checkpoint**

Run:

```text
git status --short
```

Expected changed files include:

```text
 M frontend/src/hooks/useAudioInputDevices.ts
 M frontend/src/hooks/useAudioInputDevices.test.ts
```

If commit authorization is active, commit with:

```text
git add frontend/src/hooks/useAudioInputDevices.ts frontend/src/hooks/useAudioInputDevices.test.ts
git commit -m "feat: persist microphone device preference"
```

---

## Task 3: Add audio output-device hook

**Files:**
- Create: `frontend/src/hooks/useAudioOutputDevices.ts`
- Create: `frontend/src/hooks/useAudioOutputDevices.test.ts`

- [ ] **Step 1: Write failing tests for output-device hook**

Create `frontend/src/hooks/useAudioOutputDevices.test.ts`:

```ts
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
```

- [ ] **Step 2: Run output hook tests and verify they fail because the hook does not exist**

Run:

```text
cd frontend
npm test -- --run src/hooks/useAudioOutputDevices.test.ts
```

Expected result:

```text
FAIL  src/hooks/useAudioOutputDevices.test.ts
Error: Failed to resolve import "./useAudioOutputDevices"
```

- [ ] **Step 3: Implement the output-device hook**

Create `frontend/src/hooks/useAudioOutputDevices.ts`:

```ts
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
```

- [ ] **Step 4: Run output hook tests and verify they pass**

Run:

```text
cd frontend
npm test -- --run src/hooks/useAudioOutputDevices.test.ts
```

Expected result:

```text
PASS  src/hooks/useAudioOutputDevices.test.ts
```

- [ ] **Step 5: Checkpoint**

Run:

```text
git status --short
```

Expected changed files include:

```text
?? frontend/src/hooks/useAudioOutputDevices.ts
?? frontend/src/hooks/useAudioOutputDevices.test.ts
```

If commit authorization is active, commit with:

```text
git add frontend/src/hooks/useAudioOutputDevices.ts frontend/src/hooks/useAudioOutputDevices.test.ts
git commit -m "feat: add audio output device hook"
```

---

## Task 4: Route playback through selected output device

**Files:**
- Modify: `frontend/src/hooks/useAudioPlaybackController.ts`
- Modify: `frontend/src/components/MessageList.test.tsx`

- [ ] **Step 1: Add failing playback routing tests**

Modify `frontend/src/components/MessageList.test.tsx`.

Add this constant near the existing original prototype constants:

```ts
const originalSetSinkId = HTMLMediaElement.prototype.setSinkId;
```

Add this restoration logic to `afterEach` after restoring `pause`:

```ts
    if (originalSetSinkId) {
      Object.defineProperty(HTMLMediaElement.prototype, 'setSinkId', {
        configurable: true,
        value: originalSetSinkId,
      });
    } else {
      delete (HTMLMediaElement.prototype as Partial<HTMLMediaElement>).setSinkId;
    }
```

Add this test harness after the existing `Harness` function:

```tsx
function OutputHarness({ outputDeviceId }: { outputDeviceId: string }) {
  const audioController = useAudioPlaybackController({ audioOutputDeviceId: outputDeviceId });
  return <MessageList messages={messages} audioController={audioController} playbackBlocked={false} />;
}
```

Append these tests inside `describe('MessageList audio controls', () => { ... })`:

```ts
  it('applies the selected output device before playback when setSinkId is supported', async () => {
    const user = userEvent.setup();
    const setSinkId = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(HTMLMediaElement.prototype, 'setSinkId', {
      configurable: true,
      value: setSinkId,
    });
    vi.mocked(fetch).mockResolvedValueOnce(wavResponse());

    render(<OutputHarness outputDeviceId="usb-speaker" />);
    await user.click(screen.getAllByRole('button', { name: '播放' })[0]);

    await waitFor(() => expect(setSinkId).toHaveBeenCalledWith('usb-speaker'));
    expect(setSinkId.mock.invocationCallOrder[0]).toBeLessThan(playMock.mock.invocationCallOrder[0]);
  });

  it('uses default output when output device id is empty', async () => {
    const user = userEvent.setup();
    const setSinkId = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(HTMLMediaElement.prototype, 'setSinkId', {
      configurable: true,
      value: setSinkId,
    });
    vi.mocked(fetch).mockResolvedValueOnce(wavResponse());

    render(<OutputHarness outputDeviceId="" />);
    await user.click(screen.getAllByRole('button', { name: '播放' })[0]);

    await waitFor(() => expect(setSinkId).toHaveBeenCalledWith(''));
    expect(playMock).toHaveBeenCalledTimes(1);
  });

  it('continues playback through browser default when setSinkId is unsupported', async () => {
    const user = userEvent.setup();
    delete (HTMLMediaElement.prototype as Partial<HTMLMediaElement>).setSinkId;
    vi.mocked(fetch).mockResolvedValueOnce(wavResponse());

    render(<OutputHarness outputDeviceId="usb-speaker" />);
    await user.click(screen.getAllByRole('button', { name: '播放' })[0]);

    await waitFor(() => expect(playMock).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole('button', { name: '暂停' })).toBeInTheDocument();
  });

  it('reports output routing errors without losing the assistant message', async () => {
    const user = userEvent.setup();
    const setSinkId = vi.fn().mockRejectedValue(new DOMException('missing output', 'NotFoundError'));
    Object.defineProperty(HTMLMediaElement.prototype, 'setSinkId', {
      configurable: true,
      value: setSinkId,
    });
    vi.mocked(fetch).mockResolvedValueOnce(wavResponse());

    render(<OutputHarness outputDeviceId="missing-speaker" />);
    await user.click(screen.getAllByRole('button', { name: '播放' })[0]);

    expect(await screen.findByText('无法切换到选择的输出设备，请改用系统默认输出后重试。')).toBeInTheDocument();
    expect(screen.getAllByText('我听见了：你好').length).toBeGreaterThan(0);
  });
```

- [ ] **Step 2: Run message-list tests and verify new tests fail**

Run:

```text
cd frontend
npm test -- --run src/components/MessageList.test.tsx
```

Expected result:

```text
FAIL  src/components/MessageList.test.tsx
```

The failure should show that `useAudioPlaybackController` does not accept options or `setSinkId` is not called.

- [ ] **Step 3: Implement output routing in playback controller**

Modify `frontend/src/hooks/useAudioPlaybackController.ts`.

Add an options interface and output error helper after the existing interfaces:

```ts
interface UseAudioPlaybackControllerOptions {
  audioOutputDeviceId?: string;
}

const OUTPUT_DEVICE_ERROR_MESSAGE = '无法切换到选择的输出设备，请改用系统默认输出后重试。';
```

Add this helper before the hook:

```ts
async function applySinkId(audio: HTMLAudioElement, audioOutputDeviceId: string): Promise<void> {
  const setSinkId = audio.setSinkId;
  if (typeof setSinkId !== 'function') return;
  await setSinkId.call(audio, audioOutputDeviceId);
}
```

Change the hook signature:

```ts
export function useAudioPlaybackController(options: UseAudioPlaybackControllerOptions = {}) {
```

Add a ref after `urlsRef`:

```ts
  const audioOutputDeviceIdRef = useRef(options.audioOutputDeviceId ?? '');
  audioOutputDeviceIdRef.current = options.audioOutputDeviceId ?? '';
```

Change `playExisting` so it applies the sink before `audio.play()`:

```ts
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
```

No other playback behavior should change.

- [ ] **Step 4: Run message-list tests and verify they pass**

Run:

```text
cd frontend
npm test -- --run src/components/MessageList.test.tsx
```

Expected result:

```text
PASS  src/components/MessageList.test.tsx
```

- [ ] **Step 5: Checkpoint**

Run:

```text
git status --short
```

Expected changed files include:

```text
 M frontend/src/hooks/useAudioPlaybackController.ts
 M frontend/src/components/MessageList.test.tsx
```

If commit authorization is active, commit with:

```text
git add frontend/src/hooks/useAudioPlaybackController.ts frontend/src/components/MessageList.test.tsx
git commit -m "feat: route speech playback to selected output"
```

---

## Task 5: Render output-device controls in the app

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/ChatLayout.tsx`
- Modify: `frontend/src/components/VoiceRecorder.tsx`
- Modify: `frontend/src/App.test.tsx`
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Add failing app-level output-device UI tests**

Modify `frontend/src/App.test.tsx`.

Add this original prototype constant near existing constants:

```ts
const originalSetSinkId = HTMLMediaElement.prototype.setSinkId;
```

Add this restoration logic to `afterEach`:

```ts
    if (originalSetSinkId) {
      Object.defineProperty(HTMLMediaElement.prototype, 'setSinkId', {
        configurable: true,
        value: originalSetSinkId,
      });
    } else {
      delete (HTMLMediaElement.prototype as Partial<HTMLMediaElement>).setSinkId;
    }
```

Append these tests inside `describe('App', () => { ... })`:

```ts
  it('renders output device controls without requesting microphone permission', async () => {
    const getUserMedia = vi.fn();
    Object.defineProperty(HTMLMediaElement.prototype, 'setSinkId', {
      configurable: true,
      value: vi.fn().mockResolvedValue(undefined),
    });
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia,
        enumerateDevices: vi.fn().mockResolvedValue([
          { deviceId: 'speaker-1', groupId: 'g1', kind: 'audiooutput', label: 'USB Speaker', toJSON: () => ({}) },
        ]),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      },
    });

    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '' }]))
      .mockResolvedValueOnce(jsonResponse([]));

    render(<App />);

    expect(await screen.findByLabelText('扬声器/耳机')).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '系统默认输出设备' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'USB Speaker' })).toBeInTheDocument();
    expect(getUserMedia).not.toHaveBeenCalled();
  });

  it('passes selected output device to speech playback', async () => {
    const user = userEvent.setup();
    const setSinkId = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(HTMLMediaElement.prototype, 'setSinkId', {
      configurable: true,
      value: setSinkId,
    });
    HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined);
    URL.createObjectURL = vi.fn(() => 'blob:tts-audio');
    URL.revokeObjectURL = vi.fn();

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        enumerateDevices: vi.fn().mockResolvedValue([
          { deviceId: 'speaker-1', groupId: 'g1', kind: 'audiooutput', label: 'USB Speaker', toJSON: () => ({}) },
        ]),
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      },
    });

    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '' }]))
      .mockResolvedValueOnce(jsonResponse([
        { id: 'a1', session_id: 's1', role: 'assistant', content: '测试朗读', created_at: '', metadata: {} },
      ]))
      .mockResolvedValueOnce(wavResponse());

    render(<App />);
    await user.selectOptions(await screen.findByLabelText('扬声器/耳机'), 'speaker-1');
    await user.click(await screen.findByRole('button', { name: '播放' }));

    await waitFor(() => expect(setSinkId).toHaveBeenCalledWith('speaker-1'));
  });

  it('shows output unsupported message while keeping default playback path available', async () => {
    delete (HTMLMediaElement.prototype as Partial<HTMLMediaElement>).setSinkId;
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        enumerateDevices: vi.fn(),
      },
    });

    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '' }]))
      .mockResolvedValueOnce(jsonResponse([]));

    render(<App />);

    expect(await screen.findByText('当前浏览器不支持单独选择输出设备，将使用系统默认输出。')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '开始录音' })).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run App tests and verify they fail**

Run:

```text
cd frontend
npm test -- --run src/App.test.tsx
```

Expected result:

```text
FAIL  src/App.test.tsx
```

The failure should show that `扬声器/耳机` is not rendered or the playback controller is not receiving the selected output ID.

- [ ] **Step 3: Wire the output hook through App and ChatLayout**

Modify `frontend/src/App.tsx`:

Add import:

```ts
import { useAudioOutputDevices } from './hooks/useAudioOutputDevices';
```

Instantiate output devices before playback controller:

```ts
  const audioOutputDevices = useAudioOutputDevices();
  const audioController = useAudioPlaybackController({ audioOutputDeviceId: audioOutputDevices.selectedDeviceId });
  const audioInputDevices = useAudioInputDevices();
```

Remove the old no-argument `useAudioPlaybackController()` call.

Pass the new prop into `ChatLayout`:

```tsx
      audioOutputDevices={audioOutputDevices}
```

Modify `frontend/src/components/ChatLayout.tsx`:

Add import:

```ts
import type { UseAudioOutputDevicesResult } from '../hooks/useAudioOutputDevices';
```

Add prop:

```ts
  audioOutputDevices: UseAudioOutputDevicesResult;
```

Destructure it and pass into `VoiceRecorder`:

```tsx
          audioOutputDevices={audioOutputDevices}
```

- [ ] **Step 4: Render output controls in VoiceRecorder**

Modify `frontend/src/components/VoiceRecorder.tsx`.

Add import:

```ts
import type { UseAudioOutputDevicesResult } from '../hooks/useAudioOutputDevices';
```

Add prop:

```ts
  audioOutputDevices: UseAudioOutputDevicesResult;
```

Destructure it:

```ts
export function VoiceRecorder({ recorder, disabled, vadStatusMessage, hintMessage, audioInputDevices, audioOutputDevices }: VoiceRecorderProps) {
```

Add this output controls block after the microphone `.voice-recorder__devices` block:

```tsx
      <div className="voice-recorder__devices">
        <label>
          扬声器/耳机
          <select
            aria-label="扬声器/耳机"
            value={audioOutputDevices.selectedDeviceId}
            disabled={deviceControlsDisabled || audioOutputDevices.status === 'unsupported'}
            onChange={(event) => audioOutputDevices.setSelectedDeviceId(event.target.value)}
          >
            <option value="">系统默认输出设备</option>
            {audioOutputDevices.devices.map((device) => (
              <option key={device.deviceId} value={device.deviceId}>
                {device.label}
              </option>
            ))}
          </select>
        </label>
        {audioOutputDevices.canSelectOutput ? (
          <button
            type="button"
            aria-label="选择输出设备"
            disabled={deviceControlsDisabled || audioOutputDevices.status === 'loading'}
            onClick={() => { void audioOutputDevices.selectOutputDevice(); }}
          >
            选择输出设备
          </button>
        ) : null}
        <button
          type="button"
          aria-label="刷新输出设备"
          disabled={deviceControlsDisabled || audioOutputDevices.status === 'loading' || audioOutputDevices.status === 'unsupported'}
          onClick={() => { void audioOutputDevices.refreshDevices(); }}
        >
          刷新输出设备
        </button>
        {audioOutputDevices.status === 'loading' ? <span>正在读取输出设备</span> : null}
        {audioOutputDevices.status === 'unsupported' || audioOutputDevices.status === 'error' ? (
          <span className="voice-recorder__device-error">{audioOutputDevices.error}</span>
        ) : null}
      </div>
```

- [ ] **Step 5: Adjust styles for two device rows**

Modify `frontend/src/styles.css` around the existing voice-recorder rules:

```css
.voice-recorder {
  align-items: flex-start;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}

.voice-recorder__devices {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.voice-recorder__devices label {
  align-items: center;
  display: flex;
  gap: 0.35rem;
}

.voice-recorder__devices select {
  border: 1px solid #cdbdaa;
  border-radius: 10px;
  color: #2d2520;
  padding: 0.45rem 0.55rem;
}

.voice-recorder__device-error {
  color: #a33f3f;
  font-size: 0.86rem;
}
```

Keep the existing `.voice-recorder__status`, `.voice-recorder__recording`, and `.voice-recorder__error` rules.

- [ ] **Step 6: Run App tests and verify they pass**

Run:

```text
cd frontend
npm test -- --run src/App.test.tsx
```

Expected result:

```text
PASS  src/App.test.tsx
```

- [ ] **Step 7: Checkpoint**

Run:

```text
git status --short
```

Expected changed files include:

```text
 M frontend/src/App.tsx
 M frontend/src/components/ChatLayout.tsx
 M frontend/src/components/VoiceRecorder.tsx
 M frontend/src/App.test.tsx
 M frontend/src/styles.css
```

If commit authorization is active, commit with:

```text
git add frontend/src/App.tsx frontend/src/components/ChatLayout.tsx frontend/src/components/VoiceRecorder.tsx frontend/src/App.test.tsx frontend/src/styles.css
git commit -m "feat: add audio output device controls"
```

---

## Task 6: Extend fake browser voice-turn E2E coverage

**Files:**
- Modify: `frontend/e2e/voice-turn.spec.ts`

- [ ] **Step 1: Add output-device support to the E2E browser mock**

Modify the `page.addInitScript` block in `frontend/e2e/voice-turn.spec.ts`.

Replace the current `navigator.mediaDevices` mock with:

```ts
    const fakeDevices = [
      { deviceId: 'usb-mic', groupId: 'g-mic', kind: 'audioinput', label: 'USB Mic', toJSON: () => ({}) },
      { deviceId: 'usb-speaker', groupId: 'g-speaker', kind: 'audiooutput', label: 'USB Speaker', toJSON: () => ({}) },
    ];

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: async () => ({ getTracks: () => [{ stop() {}, addEventListener() {} }] }),
        enumerateDevices: async () => fakeDevices,
        selectAudioOutput: async () => fakeDevices[1],
        addEventListener() {},
        removeEventListener() {},
      },
    });

    HTMLMediaElement.prototype.setSinkId = async function setSinkId(sinkId: string) {
      (window as typeof window & { __lastSinkId?: string }).__lastSinkId = sinkId;
    };
```

Keep the existing fake `MediaRecorder`, `play`, and `pause` mocks.

- [ ] **Step 2: Add E2E assertions for output selection**

After the assertion that the start recording button is visible, add:

```ts
  await expect(page.getByLabel('扬声器/耳机')).toBeVisible();
  await expect(page.getByRole('option', { name: 'USB Speaker' })).toBeVisible();
  await page.getByLabel('扬声器/耳机').selectOption('usb-speaker');
```

After the existing request-count assertions, add:

```ts
  await expect.poll(async () => page.evaluate(() => (window as typeof window & { __lastSinkId?: string }).__lastSinkId)).toBe('usb-speaker');
```

- [ ] **Step 3: Run the single E2E test**

Run:

```text
cd frontend
npm run test:e2e -- voice-turn.spec.ts
```

Expected result:

```text
1 passed
```

- [ ] **Step 4: Checkpoint**

Run:

```text
git status --short
```

Expected changed files include:

```text
 M frontend/e2e/voice-turn.spec.ts
```

If commit authorization is active, commit with:

```text
git add frontend/e2e/voice-turn.spec.ts
git commit -m "test: cover output device selection in voice turn"
```

---

## Task 7: Run full frontend validation

**Files:**
- No code changes expected.

- [ ] **Step 1: Run all frontend unit tests**

Run:

```text
cd frontend
npm test -- --run
```

Expected result:

```text
PASS
```

The exact test count may increase from the current baseline because this plan adds new unit tests.

- [ ] **Step 2: Run typecheck**

Run:

```text
cd frontend
npm run typecheck
```

Expected result:

```text
No TypeScript errors
```

- [ ] **Step 3: Run production build**

Run:

```text
cd frontend
npm run build
```

Expected result:

```text
built in
```

The command must exit with code 0.

- [ ] **Step 4: Run E2E suite**

Run:

```text
cd frontend
npm run test:e2e
```

Expected result:

```text
passed
```

The exact count may remain 5 or increase if additional E2E tests are added.

- [ ] **Step 5: Record command outputs for documentation**

Capture the pass/fail result and test counts for:

```text
npm test -- --run
npm run typecheck
npm run build
npm run test:e2e
```

These values are required for the evidence document in Task 8.

---

## Task 8: Document evidence and update stage status

**Files:**
- Create: `docs/stage2f2-audio-output-device-preferences.md`
- Modify: `CLAUDE.md`
- Modify: `README.md` only if browser support notes are added

- [ ] **Step 1: Write evidence document**

Create `docs/stage2f2-audio-output-device-preferences.md` with this structure, replacing the validation result lines with the actual outputs from Task 7:

```md
# Stage 2F-2 Audio Output Device Selection and Device Preference Persistence Evidence

Status: COMPLETED on 2026-06-29.

## Scope

This slice adds browser-local audio device preference persistence and output-device selection for assistant TTS playback.

It persists only opaque browser device IDs in localStorage. It does not persist raw audio, device labels, transcripts, messages, or provider secrets.

It does not implement streaming ASR, streaming TTS, backend storage, long-term memory, or emotion behavior.

## Implemented behavior

- Microphone selection is restored from browser-local preference when the saved device still exists.
- Stale microphone preference resets to system default after successful enumeration.
- Assistant speech playback can use a selected output device in browsers that support `HTMLMediaElement.setSinkId`.
- Output selection falls back to system default when unsupported.
- Stale output preference resets to system default after successful enumeration.
- Output-device selection failure does not break text chat, ASR, TTS synthesis, or default playback retry.

## Validation

| Command | Result |
|---|---|
| `npm test -- --run src/audioDevicePreferences.test.ts` | PASS — fill in exact count |
| `npm test -- --run src/hooks/useAudioInputDevices.test.ts` | PASS — fill in exact count |
| `npm test -- --run src/hooks/useAudioOutputDevices.test.ts` | PASS — fill in exact count |
| `npm test -- --run src/components/MessageList.test.tsx` | PASS — fill in exact count |
| `npm test -- --run src/App.test.tsx` | PASS — fill in exact count |
| `npm run test:e2e -- voice-turn.spec.ts` | PASS — fill in exact count |
| `npm test -- --run` | PASS — fill in exact count |
| `npm run typecheck` | PASS |
| `npm run build` | PASS |
| `npm run test:e2e` | PASS — fill in exact count |

## Browser support note

Output-device selection depends on browser support for `HTMLMediaElement.setSinkId`. When unsupported, the UI reports that the system default output device will be used. The app keeps text chat, recording, ASR, and TTS playback through the default output available.

## Phase boundary

This remains Stage 2 voice-device management. Streaming ASR/TTS, long-term memory, and emotion state remain unimplemented.
```

- [ ] **Step 2: Replace evidence placeholders with actual validation results**

Before saving the final evidence doc, replace every `fill in exact count` phrase with the actual result text from Task 7 and targeted tests.

Example final rows:

```md
| `npm test -- --run src/audioDevicePreferences.test.ts` | PASS — 8 passed |
| `npm run test:e2e` | PASS — 5 passed |
```

- [ ] **Step 3: Update CLAUDE.md stage status only after validation passes**

Modify `CLAUDE.md`:

1. In the top current-stage line, add `2F-2 Audio Output Device Selection and Device Preference Persistence COMPLETED` after `2F-1 Streaming/Performance Measurement Baseline COMPLETED`.
2. In the Stage 2 status table, add the same completed milestone.
3. In the Stage 2 completed abilities list, add a concise bullet:

```md
- 子任务 2F-2：Audio output device selection and device preference persistence 已完成（2026-06-29；浏览器 UI 支持系统默认输出设备和可枚举/授权的扬声器或耳机选择；麦克风与输出设备偏好仅以浏览器 opaque deviceId 存入 localStorage；设备缺失、枚举失败或 `setSinkId` 不支持时回退到系统默认；文字聊天、录音、ASR、TTS 播放、VAD、显式打断和会话切换回归保持 PASS；证据记录于 `docs/stage2f2-audio-output-device-preferences.md`）。未实现流式 ASR/TTS、长期记忆或情感系统。
```

4. In `阶段 2 尚未实现`, remove `输出设备选择和设备偏好持久化。` and leave `流式识别与流式合成。`.

- [ ] **Step 4: Update README only if needed**

If the UI has a user-facing browser support caveat, add a short note to README voice instructions:

```md
- 扬声器/耳机选择依赖浏览器支持 `HTMLMediaElement.setSinkId`。不支持时应用会使用系统默认输出设备，文字聊天和语音播放仍可继续使用。
```

If README already has a suitable browser-support note or no user-facing voice-device section, do not modify README.

- [ ] **Step 5: Run documentation sanity check**

Run:

```text
git diff -- docs/stage2f2-audio-output-device-preferences.md CLAUDE.md README.md
```

Expected result:

- Evidence doc includes actual validation results.
- `CLAUDE.md` says 2F-2 is completed only if all validation passed.
- No text claims streaming, memory, or emotion is implemented.

- [ ] **Step 6: Final checkpoint**

Run:

```text
git status --short
```

Expected changed files include all code, tests, and docs from this plan.

If commit authorization is active, commit remaining documentation with:

```text
git add docs/stage2f2-audio-output-device-preferences.md CLAUDE.md README.md
git commit -m "docs: record audio device preference evidence"
```

---

## Self-review notes

Spec coverage:

- Local preference helper: Task 1.
- Microphone preference persistence and stale reset: Task 2.
- Output-device hook, unsupported fallback, `selectAudioOutput`, enumeration: Task 3.
- Playback controller `setSinkId` integration and error handling: Task 4.
- UI integration: Task 5.
- Fake-provider E2E voice-turn regression: Task 6.
- Full validation commands: Task 7.
- Evidence doc and `CLAUDE.md` status update: Task 8.

Placeholder scan:

- The plan intentionally uses explicit code snippets, paths, commands, and expected results.
- The evidence-document template contains replacement instructions for measured test counts; Task 8 Step 2 requires replacing them before completion.

Type consistency:

- `AudioDevicePreferences`, `UseAudioOutputDevicesResult`, `audioOutputDeviceId`, `setSelectedDeviceId`, `refreshDevices`, and `selectOutputDevice` are named consistently across tasks.
- `useAudioPlaybackController({ audioOutputDeviceId })` is used consistently in tests and `App.tsx`.
