# Stage 2F-pre Audio Input Device Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. In this Claude Code session, do not create git commits unless the user explicitly asks; treat commit steps as review checkpoints only.

**Goal:** Add a browser-side microphone input device selector that enumerates audio input devices, lets the user choose a preferred microphone, and passes that selection to recording without breaking existing Stage 2D/2E voice flows.

**Architecture:** Add a focused `useAudioInputDevices` hook for device enumeration and selection state. Extend `useManualAudioRecorder` with an optional selected input device ID and pass it to `getUserMedia` as an ideal `deviceId` constraint. Render the selector in `VoiceRecorder`, keeping enumeration failure non-blocking and avoiding backend/database changes.

**Tech Stack:** React, TypeScript, Vite, Vitest, Testing Library, existing `useManualAudioRecorder`, `VoiceRecorder`, `ChatLayout`, and fake media test infrastructure.

---

## File structure

### Create

- `frontend/src/hooks/useAudioInputDevices.ts`
  - Owns browser audio input enumeration, selected device state, refresh, fallback labels, and optional `devicechange` listener.

- `frontend/src/hooks/useAudioInputDevices.test.ts`
  - Tests unsupported enumeration, successful enumeration, fallback labels, refresh, devicechange, missing selected device reset, and enumeration failure.

- `docs/stage2f-audio-device-management.md`
  - Evidence file after validation passes.

### Modify

- `frontend/src/hooks/useManualAudioRecorder.ts`
  - Accept optional `{ audioInputDeviceId?: string }` and include `deviceId: { ideal }` in audio constraints when selected.

- `frontend/src/App.tsx`
  - Instantiate `useAudioInputDevices()` and pass selected device into `useManualAudioRecorder`.
  - Pass device-management state to `ChatLayout`.

- `frontend/src/components/ChatLayout.tsx`
  - Accept and forward device-management props to `VoiceRecorder`.

- `frontend/src/components/VoiceRecorder.tsx`
  - Render microphone selector, refresh button, and non-blocking status/error text.
  - Disable selector/refresh during active recorder states.

- `frontend/src/App.test.tsx`
  - Add integration coverage that selected microphone ID reaches `getUserMedia` constraints and selector disables while recording.
  - Preserve existing 2D/2E tests.

- `frontend/e2e/voice-recorder.spec.ts`
  - Extend smoke to assert selector is visible and page load still does not call `getUserMedia`.

- `README.md`, `CLAUDE.md`, `docs/stage2-voice-architecture.md`
  - Update only after validation passes.

### Do not modify

- Backend runtime code.
- Database schema.
- ASR/TTS provider interfaces.
- Stage 3 memory files.
- Stage 4 emotion files.
- Output/speaker device code.

---

## Task 1: Add the audio input device hook

**Files:**
- Create: `frontend/src/hooks/useAudioInputDevices.test.ts`
- Create: `frontend/src/hooks/useAudioInputDevices.ts`

- [ ] **Step 1: Write failing hook tests**

Create `frontend/src/hooks/useAudioInputDevices.test.ts`:

```ts
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
  });

  afterEach(() => {
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: originalMediaDevices,
    });
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
});
```

- [ ] **Step 2: Run hook tests and verify RED**

Run:

```powershell
Push-Location frontend
npm test -- --run src/hooks/useAudioInputDevices.test.ts
Pop-Location
```

Expected: FAIL because `./useAudioInputDevices` does not exist.

- [ ] **Step 3: Implement the hook**

Create `frontend/src/hooks/useAudioInputDevices.ts`:

```ts
import { useCallback, useEffect, useRef, useState } from 'react';

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
  const [selectedDeviceId, setSelectedDeviceId] = useState('');
  const [status, setStatus] = useState<AudioInputDeviceStatus>('idle');
  const [error, setError] = useState<string | null>(null);
  const selectedDeviceIdRef = useRef(selectedDeviceId);
  const generationRef = useRef(0);

  selectedDeviceIdRef.current = selectedDeviceId;

  const refreshDevices = useCallback(async () => {
    const mediaDevices = navigator.mediaDevices;
    if (!mediaDevices?.enumerateDevices) {
      setDevices([]);
      setSelectedDeviceId('');
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
        setSelectedDeviceId('');
      }
      setStatus('ready');
    } catch {
      if (generationRef.current !== generation) return;
      setDevices([]);
      setSelectedDeviceId('');
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
```

- [ ] **Step 4: Run hook tests and verify GREEN**

Run:

```powershell
Push-Location frontend
npm test -- --run src/hooks/useAudioInputDevices.test.ts
Pop-Location
```

Expected: PASS — 6 tests pass.

---

## Task 2: Pass selected microphone to `getUserMedia`

**Files:**
- Modify: `frontend/src/hooks/useManualAudioRecorder.ts`
- Modify: `frontend/src/App.test.tsx`

- [ ] **Step 1: Add a failing App-level recorder constraint test**

Add this test near the existing recorder tests in `frontend/src/App.test.tsx`:

```ts
it('passes selected microphone device as an ideal getUserMedia constraint', async () => {
  const user = userEvent.setup();
  class FakeMediaRecorder {
    static isTypeSupported() { return true; }
    state = 'inactive';
    mimeType = 'audio/webm';
    ondataavailable: ((event: BlobEvent) => void) | null = null;
    onstop: (() => void) | null = null;
    onerror: (() => void) | null = null;
    start() { this.state = 'recording'; }
    stop() {
      this.state = 'inactive';
      this.ondataavailable?.({ data: new Blob(['voice'], { type: 'audio/webm' }) } as BlobEvent);
      this.onstop?.();
    }
  }
  vi.stubGlobal('MediaRecorder', FakeMediaRecorder);

  const getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [{ stop: vi.fn(), addEventListener: vi.fn() }] });
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      getUserMedia,
      enumerateDevices: vi.fn().mockResolvedValue([
        { deviceId: 'default', groupId: 'g1', kind: 'audioinput', label: 'Default Mic', toJSON: () => ({}) },
        { deviceId: 'usb-mic', groupId: 'g2', kind: 'audioinput', label: 'USB Mic', toJSON: () => ({}) },
      ]),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    },
  });

  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '' }]))
    .mockResolvedValueOnce(jsonResponse([]));

  render(<App />);
  await screen.findByRole('button', { name: '开始录音' });
  await user.selectOptions(await screen.findByLabelText('麦克风'), 'usb-mic');
  await user.click(screen.getByRole('button', { name: '开始录音' }));

  expect(getUserMedia).toHaveBeenCalledWith({
    audio: {
      echoCancellation: { ideal: true },
      noiseSuppression: { ideal: true },
      autoGainControl: { ideal: true },
      deviceId: { ideal: 'usb-mic' },
    },
  });
});
```

- [ ] **Step 2: Run focused test and verify RED**

Run:

```powershell
Push-Location frontend
npm test -- --run src/App.test.tsx -t "passes selected microphone device as an ideal getUserMedia constraint"
Pop-Location
```

Expected: FAIL because the selector does not exist and `useManualAudioRecorder` does not accept a device option.

- [ ] **Step 3: Extend recorder options and constraints**

In `frontend/src/hooks/useManualAudioRecorder.ts`, add this interface after `UseManualAudioRecorderResult`:

```ts
interface UseManualAudioRecorderOptions {
  audioInputDeviceId?: string;
}
```

Change the function signature:

```ts
export function useManualAudioRecorder(options: UseManualAudioRecorderOptions = {}): UseManualAudioRecorderResult {
```

Replace the existing `getUserMedia` call block with:

```ts
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
```

Update the `startRecording` dependency array to include `options.audioInputDeviceId`:

```ts
  }, [status, options.audioInputDeviceId, fullCleanup, resetToIdle, stopAllTracks, clearTimers, stopRecording, uploadBlob]);
```

- [ ] **Step 4: Wire hook state through `App.tsx`**

In `frontend/src/App.tsx`, add import:

```ts
import { useAudioInputDevices } from './hooks/useAudioInputDevices';
```

Replace:

```ts
  const recorder = useManualAudioRecorder();
```

with:

```ts
  const audioInputDevices = useAudioInputDevices();
  const recorder = useManualAudioRecorder({ audioInputDeviceId: audioInputDevices.selectedDeviceId });
```

Add a prop to `ChatLayout`:

```tsx
      audioInputDevices={audioInputDevices}
```

- [ ] **Step 5: Run focused test**

Run:

```powershell
Push-Location frontend
npm test -- --run src/App.test.tsx -t "passes selected microphone device as an ideal getUserMedia constraint"
Pop-Location
```

Expected: still FAIL until `ChatLayout` and `VoiceRecorder` render the selector in Task 3.

---

## Task 3: Render microphone selector in the recorder UI

**Files:**
- Modify: `frontend/src/components/ChatLayout.tsx`
- Modify: `frontend/src/components/VoiceRecorder.tsx`
- Modify: `frontend/src/App.test.tsx`

- [ ] **Step 1: Add UI assertions to the existing test**

In the test added in Task 2, keep these assertions before `selectOptions`:

```ts
expect(await screen.findByLabelText('麦克风')).toBeInTheDocument();
expect(screen.getByRole('button', { name: '刷新设备' })).toBeInTheDocument();
expect(screen.getByRole('option', { name: '系统默认麦克风' })).toBeInTheDocument();
expect(screen.getByRole('option', { name: 'USB Mic' })).toBeInTheDocument();
```

- [ ] **Step 2: Update `ChatLayout` types and forwarding**

In `frontend/src/components/ChatLayout.tsx`, add type import:

```ts
import type { UseAudioInputDevicesResult } from '../hooks/useAudioInputDevices';
```

Add prop to `ChatLayoutProps`:

```ts
  audioInputDevices: UseAudioInputDevicesResult;
```

Destructure it:

```ts
  audioInputDevices,
```

Pass it to `VoiceRecorder`:

```tsx
<VoiceRecorder
  recorder={recorder}
  disabled={recorderDisabled}
  vadStatusMessage={vadStatusMessage}
  hintMessage={recorderHintMessage}
  audioInputDevices={audioInputDevices}
/>
```

- [ ] **Step 3: Update `VoiceRecorder` props and UI**

In `frontend/src/components/VoiceRecorder.tsx`, add type import:

```ts
import type { UseAudioInputDevicesResult } from '../hooks/useAudioInputDevices';
```

Update props:

```ts
interface VoiceRecorderProps {
  recorder: UseManualAudioRecorderResult;
  disabled: boolean;
  vadStatusMessage?: string | null;
  hintMessage?: string | null;
  audioInputDevices: UseAudioInputDevicesResult;
}
```

Update function signature:

```ts
export function VoiceRecorder({ recorder, disabled, vadStatusMessage, hintMessage, audioInputDevices }: VoiceRecorderProps) {
```

Add this derived value after `const { status, elapsedMs, error } = recorder;`:

```ts
  const deviceControlsDisabled = disabled || recorder.isPlaybackBlocked;
```

Render this block near the top of the root `<div>`, after the hint:

```tsx
      <div className="voice-recorder__devices">
        <label>
          麦克风
          <select
            aria-label="麦克风"
            value={audioInputDevices.selectedDeviceId}
            disabled={deviceControlsDisabled}
            onChange={(event) => audioInputDevices.setSelectedDeviceId(event.target.value)}
          >
            <option value="">系统默认麦克风</option>
            {audioInputDevices.devices.map((device) => (
              <option key={device.deviceId} value={device.deviceId}>
                {device.label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          aria-label="刷新设备"
          disabled={deviceControlsDisabled || audioInputDevices.status === 'loading'}
          onClick={() => { void audioInputDevices.refreshDevices(); }}
        >
          刷新设备
        </button>
        {audioInputDevices.status === 'loading' ? <span>正在读取麦克风设备</span> : null}
        {audioInputDevices.status === 'unsupported' || audioInputDevices.status === 'error' ? (
          <span className="voice-recorder__device-error">{audioInputDevices.error}</span>
        ) : null}
      </div>
```

- [ ] **Step 4: Run focused test and verify GREEN**

Run:

```powershell
Push-Location frontend
npm test -- --run src/App.test.tsx -t "passes selected microphone device as an ideal getUserMedia constraint"
Pop-Location
```

Expected: PASS.

- [ ] **Step 5: Add disabled-while-recording test**

Add this test near the same area in `frontend/src/App.test.tsx`:

```ts
it('disables microphone device controls while recording', async () => {
  const user = userEvent.setup();
  class FakeMediaRecorder {
    static isTypeSupported() { return true; }
    state = 'inactive';
    mimeType = 'audio/webm';
    ondataavailable: ((event: BlobEvent) => void) | null = null;
    onstop: (() => void) | null = null;
    onerror: (() => void) | null = null;
    start() { this.state = 'recording'; }
    stop() {
      this.state = 'inactive';
      this.ondataavailable?.({ data: new Blob(['voice'], { type: 'audio/webm' }) } as BlobEvent);
      this.onstop?.();
    }
  }
  vi.stubGlobal('MediaRecorder', FakeMediaRecorder);
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: vi.fn(), addEventListener: vi.fn() }] }),
      enumerateDevices: vi.fn().mockResolvedValue([
        { deviceId: 'usb-mic', groupId: 'g1', kind: 'audioinput', label: 'USB Mic', toJSON: () => ({}) },
      ]),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    },
  });

  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '' }]))
    .mockResolvedValueOnce(jsonResponse([]));

  render(<App />);
  await user.click(await screen.findByRole('button', { name: '开始录音' }));

  expect(await screen.findByLabelText('麦克风')).toBeDisabled();
  expect(screen.getByRole('button', { name: '刷新设备' })).toBeDisabled();
});
```

- [ ] **Step 6: Run disabled test and verify PASS**

Run:

```powershell
Push-Location frontend
npm test -- --run src/App.test.tsx -t "disables microphone device controls while recording"
Pop-Location
```

Expected: PASS.

---

## Task 4: Preserve page-load privacy and E2E smoke

**Files:**
- Modify: `frontend/e2e/voice-recorder.spec.ts`

- [ ] **Step 1: Extend E2E page-load test**

In `frontend/e2e/voice-recorder.spec.ts`, update the first test to include selector assertions after `await page.goto('/');`:

```ts
    await expect(page.getByLabel('麦克风')).toBeVisible();
    await expect(page.getByRole('button', { name: '刷新设备' })).toBeVisible();
```

Keep the `gumCalled` assertion:

```ts
    gumCalled = await page.evaluate(() => !!(window as unknown as Record<string, boolean>)._gum_called);
    expect(gumCalled).toBe(false);
```

- [ ] **Step 2: Run E2E and verify PASS**

Run:

```powershell
Push-Location frontend
npm run test:e2e
Pop-Location
```

Expected: PASS — 5 tests pass; page load still does not trigger `getUserMedia`.

---

## Task 5: Run full validation

**Files:**
- Read/validate only.

- [ ] **Step 1: Run new hook tests**

Run:

```powershell
Push-Location frontend
npm test -- --run src/hooks/useAudioInputDevices.test.ts
Pop-Location
```

Expected: PASS — 6 tests.

- [ ] **Step 2: Run App tests**

Run:

```powershell
Push-Location frontend
npm test -- --run src/App.test.tsx
Pop-Location
```

Expected: PASS — existing App tests plus new device-management tests.

- [ ] **Step 3: Run VAD hook regression**

Run:

```powershell
Push-Location frontend
npm test -- --run src/hooks/useVadAutoStop.test.ts
Pop-Location
```

Expected: PASS — 6 tests.

- [ ] **Step 4: Run all frontend unit tests**

Run:

```powershell
Push-Location frontend
npm test -- --run
Pop-Location
```

Expected: PASS.

- [ ] **Step 5: Run typecheck**

Run:

```powershell
Push-Location frontend
npm run typecheck
Pop-Location
```

Expected: PASS.

- [ ] **Step 6: Run build**

Run:

```powershell
Push-Location frontend
npm run build
Pop-Location
```

Expected: PASS.

- [ ] **Step 7: Run fake E2E**

Run:

```powershell
Push-Location frontend
npm run test:e2e
Pop-Location
```

Expected: PASS — 5 tests.

---

## Task 6: Runtime verification

**Files:**
- Optional temporary script: `frontend/.claude-verify-audio-input-devices.mjs` (delete after use)
- Read/validate app runtime.

- [ ] **Step 1: Launch backend**

Run from repo root in a background terminal:

```powershell
$env:APP_ENV='test'
$env:DATABASE_URL='sqlite:///./test-results/verify-audio-devices.db'
$env:LLM_PROVIDER='fake'
$env:LLM_MODEL='test-model'
$env:FAKE_PROVIDER_MODE='ok'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 18102 --no-access-log
```

Expected: backend responds at `http://127.0.0.1:18102/health`.

- [ ] **Step 2: Launch frontend**

Run from repo root in a background terminal:

```powershell
Push-Location frontend
$env:BACKEND_PROXY_TARGET='http://127.0.0.1:18102'
npm run dev -- --host 127.0.0.1 --port 15175 --mode test
Pop-Location
```

Expected: frontend responds at `http://127.0.0.1:15175`.

- [ ] **Step 3: Drive browser UI**

Using Playwright or Chrome DevTools Protocol, verify:

1. Page shows `麦克风` selector and `刷新设备` button.
2. Page load does not call `getUserMedia`.
3. Selecting a fake USB microphone and clicking `开始录音` calls `getUserMedia` with `deviceId: { ideal: 'usb-mic' }`.
4. Recording reaches `停止录音` without console errors.

Expected runtime observation JSON:

```json
{
  "selectorVisible": true,
  "refreshVisible": true,
  "getUserMediaCallsBeforeRecord": 0,
  "selectedDeviceId": "usb-mic",
  "usedIdealDeviceId": true,
  "recordingStarted": true,
  "consoleErrors": []
}
```

Delete any temporary verification script after capturing output.

---

## Task 7: Record evidence and update status

**Files:**
- Create: `docs/stage2f-audio-device-management.md`
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `docs/stage2-voice-architecture.md`

- [ ] **Step 1: Write evidence document**

Create `docs/stage2f-audio-device-management.md`:

```markdown
# Stage 2F-pre Audio Input Device Management Evidence

Status: COMPLETED on 2026-06-29 if and only if all validation rows below are PASS.

## Scope

This slice adds browser-side microphone input device management: the UI shows a microphone selector, lets the user choose system default or an enumerated audio input device, lets the user refresh devices, and passes the selected device as an ideal `getUserMedia` constraint when recording starts.

It does not add speaker/output device selection, persistent device preferences, streaming ASR/TTS, background listening, long-term memory, or emotion behavior.

## Validation

| Command | Result |
|---|---|
| `npm test -- --run src/hooks/useAudioInputDevices.test.ts` | PASS |
| `npm test -- --run src/App.test.tsx` | PASS |
| `npm test -- --run src/hooks/useVadAutoStop.test.ts` | PASS |
| `npm test -- --run` | PASS |
| `npm run typecheck` | PASS |
| `npm run build` | PASS |
| `npm run test:e2e` | PASS |

## Runtime verification

Record the runtime observation JSON from Task 6 here.

## Behavior verified

- The UI shows `系统默认麦克风` and enumerated microphone options.
- Empty browser device labels fall back to safe labels such as `麦克风 1`.
- The user can refresh the microphone list.
- Selected device ID is passed as `deviceId: { ideal: selectedDeviceId }`.
- Page load does not request microphone permission.
- Enumeration failure does not block recording or text chat.
- Existing VAD, voice interruption, and fake voice-turn tests remain passing.

## Evidence notes

No raw audio, private transcript, API key, generated speech artifact, or persistent device ID is committed by this document.
```

If any validation command fails, set `Status: NOT COMPLETED` and do not update `CLAUDE.md` as completed.

- [ ] **Step 2: Update README only after PASS**

If validation passed, update README current status and implemented scope to include `Stage 2F-pre audio input device management`.

Add a section:

```markdown
### Stage 2F-pre audio input device management

The browser UI now includes a microphone selector with `系统默认麦克风`, enumerated audio input devices, and a refresh control. A selected microphone is passed to `getUserMedia` as an ideal device constraint when recording starts. Device enumeration failure remains non-blocking and page load does not request microphone permission.

Verification result on 2026-06-29: **PASS** — hook tests, App tests, VAD regression, full frontend unit tests, typecheck, build, Playwright E2E, and runtime UI verification passed. Evidence is recorded in `docs/stage2f-audio-device-management.md`.
```

- [ ] **Step 3: Update CLAUDE.md only after PASS**

If validation passed, update `CLAUDE.md`:

- Header: add `2F-pre Audio Input Device Management COMPLETED`.
- Stage 2 table: add `2F-pre Audio Input Device Management：COMPLETED；2F Streaming/Performance：NOT STARTED`.
- Completed abilities: add:

```markdown
- 子任务 2F-pre：Audio input device management 已完成（2026-06-29；浏览器 UI 提供 `系统默认麦克风`、枚举麦克风选项和刷新设备；选择的麦克风以 `deviceId: { ideal }` 传给 `getUserMedia`；设备枚举失败不阻塞录音或文字聊天；页面加载不请求麦克风权限；证据记录于 `docs/stage2f-audio-device-management.md`）。未实现输出设备选择、设备偏好持久化、后台监听、流式 ASR/TTS、长期记忆或情感系统。
```

- Stage 2 unimplemented list: replace `音频设备管理。` with narrower remaining items if needed, such as output device selection and streaming ASR/TTS.

- [ ] **Step 4: Add architecture addendum**

Append to `docs/stage2-voice-architecture.md`:

```markdown
## 21. Stage 2F-pre implementation addendum — audio input device management — 2026-06-29

Implemented boundary:

- Browser UI shows a microphone input selector and refresh control.
- Device enumeration uses `navigator.mediaDevices.enumerateDevices()` without requesting microphone permission on page load.
- Selected audio input device is passed to recording as `deviceId: { ideal: selectedDeviceId }`.
- Enumeration failure is non-blocking and falls back to system default microphone.
- Device IDs remain frontend session state only; they are not sent to the backend or persisted.
- No output device selection, streaming, memory, or emotion behavior is introduced.

Evidence is recorded in `docs/stage2f-audio-device-management.md`.
```

- [ ] **Step 5: Check working tree for secrets/artifacts**

Run:

```powershell
git status --short
```

Expected:

- No `.env` files.
- No raw audio files.
- No generated private speech artifacts.
- No API keys or tokens.

---

## Task 8: Final report

**Files:**
- Read: `docs/stage2f-audio-device-management.md`
- Read: `CLAUDE.md`
- Read: `README.md`

- [ ] **Step 1: Confirm final status consistency**

Run:

```powershell
Select-String -Path docs\stage2f-audio-device-management.md -Pattern "Status:|PASS|NOT COMPLETED"
Select-String -Path CLAUDE.md -Pattern "2F-pre|音频设备管理|阶段 2 尚未实现"
Select-String -Path README.md -Pattern "2F-pre|audio input device|未实现范围"
```

Expected for completion: all files agree that the input-device management slice is completed. If validation failed, all files must agree that it is not completed.

- [ ] **Step 2: Produce required task-end report**

Use this exact format:

```text
完成内容：
修改文件：
验证命令与结果：
未完成或受限部分：
是否改变当前阶段：否/是（附验收证据）
下一项建议任务：
```

For PASS, next suggested task is Stage 2F streaming/performance optimization, starting with a measurement-only latency baseline before adding streaming. For FAIL, next suggested task is the smallest fix for the classified failure.

---

## Self-review

- Spec coverage: Tasks cover enumeration, fallback labels, selection, refresh, devicechange, `deviceId: { ideal }`, non-blocking errors, no page-load permission request, validation, runtime verification, and docs.
- Placeholder scan: No TODO/TBD placeholders are present. Failure branches specify exact status handling.
- Type consistency: `AudioInputDeviceOption`, `UseAudioInputDevicesResult`, `audioInputDeviceId`, `selectedDeviceId`, and `refreshDevices` are used consistently.
- Scope check: No backend endpoint, output device selection, persistence, streaming, memory, emotion, or schema change is included.
- TDD check: Each behavior change starts with a failing/updated test before production code changes.
