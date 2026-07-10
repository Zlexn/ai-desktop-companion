# Stage 2D VAD Auto-stop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Stage 2D VAD auto-stop so recording can stop automatically after user speech ends, while preserving explicit start, manual stop, cancel, re-record, and the existing ASR/chat/TTS flow.

**Architecture:** Keep `MediaRecorder` as the only source of uploaded ASR audio. Add a project-owned browser VAD adapter around `@ricky0123/vad-web`/Silero ONNX, then coordinate it from a small `useVadAutoStop` hook that only starts while the existing recorder is in `recording`. Default tests use fake VAD; real model loading is validated by an opt-in smoke.

**Tech Stack:** React, TypeScript, Vite, Vitest, Playwright, `@ricky0123/vad-web`, ONNX Runtime Web assets, existing FastAPI ASR/TTS backend.

---

## File structure

### Create

- `frontend/scripts/copy-vad-assets.mjs`
  - Copies local `node_modules` VAD/ONNX browser assets into Vite-served `frontend/public/vendor/...` directories.
  - Keeps binary/model assets generated locally rather than committed.
- `frontend/src/voiceActivity/types.ts`
  - Project-owned VAD interfaces and status types.
- `frontend/src/voiceActivity/createSileroVad.ts`
  - Real Silero/ONNX VAD adapter using `@ricky0123/vad-web`.
- `frontend/src/voiceActivity/ricky-vad-web.d.ts`
  - Minimal local module declaration so TypeScript is not coupled to undocumented package internals.
- `frontend/src/hooks/useVadAutoStop.ts`
  - Starts/stops VAD according to recorder state and calls existing `stopRecording()` once on speech end.
- `frontend/src/hooks/useVadAutoStop.test.ts`
  - Fast fake-VAD unit tests; no real ONNX model loading.
- `frontend/.claude-real-vad-ui-smoke.mjs`
  - Opt-in browser smoke for real VAD asset loading and auto-stop behavior.
- `scripts/smoke_real_vad_ui.ps1`
  - Starts backend/frontend with VAD enabled and runs the real VAD smoke.
- `scripts/smoke_real_vad_ui.cmd`
  - Windows wrapper.
- `docs/stage2d-vad-auto-stop.md`
  - Evidence record after implementation and validation.

### Modify

- `frontend/package.json`
  - Add `@ricky0123/vad-web` dependency and `prepare:vad-assets` script.
- `frontend/package-lock.json`
  - Updated by `npm install`.
- `.gitignore`
  - Ignore generated VAD/ONNX assets under `frontend/public/vendor/vad/` and `frontend/public/vendor/onnxruntime/`.
- `frontend/src/App.tsx`
  - Wire `useVadAutoStop` to the existing recorder and pass VAD status to layout.
- `frontend/src/components/ChatLayout.tsx`
  - Accept and pass VAD status message to `VoiceRecorder`.
- `frontend/src/components/VoiceRecorder.tsx`
  - Display VAD status while preserving manual stop/cancel controls.
- `frontend/src/App.test.tsx`
  - Add component coverage for VAD status and VAD-generated auto-stop using fake VAD where needed.
- `README.md`
  - Update only after validation passes.
- `CLAUDE.md`
  - Update only after validation passes.

### Do not modify unless a directly related defect is found

- Backend ASR routes/services.
- Chat persistence.
- TTS provider interfaces.
- Database schema.
- Stage 3 memory or Stage 4 emotion files.

---

## Task 1: Add dependency and local asset copy script

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `.gitignore`
- Create: `frontend/scripts/copy-vad-assets.mjs`

- [ ] **Step 1: Install the VAD package**

Run:

```powershell
Push-Location frontend
npm install @ricky0123/vad-web
Pop-Location
```

Expected:

```text
added ... packages
```

`frontend/package.json` should include `@ricky0123/vad-web` under `dependencies`, and `frontend/package-lock.json` should update.

- [ ] **Step 2: Add the asset copy script**

Create `frontend/scripts/copy-vad-assets.mjs`:

```js
import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

const root = process.cwd();
const vadSource = path.join(root, 'node_modules', '@ricky0123', 'vad-web', 'dist');
const ortSource = path.join(root, 'node_modules', 'onnxruntime-web', 'dist');
const vadTarget = path.join(root, 'public', 'vendor', 'vad');
const ortTarget = path.join(root, 'public', 'vendor', 'onnxruntime');

const assetExtensions = new Set(['.onnx', '.wasm', '.mjs', '.js', '.data']);

async function assertDirectory(dir, label) {
  const stat = await fs.stat(dir).catch(() => null);
  if (!stat?.isDirectory()) {
    throw new Error(`${label} directory not found: ${dir}. Run npm install first.`);
  }
}

async function copyMatchingFiles(sourceDir, targetDir) {
  await fs.mkdir(targetDir, { recursive: true });
  const entries = await fs.readdir(sourceDir, { withFileTypes: true });
  const copied = [];

  for (const entry of entries) {
    const sourcePath = path.join(sourceDir, entry.name);
    const targetPath = path.join(targetDir, entry.name);
    if (entry.isDirectory()) {
      const nested = await copyMatchingFiles(sourcePath, targetPath);
      copied.push(...nested);
      continue;
    }
    if (!entry.isFile()) continue;
    if (!assetExtensions.has(path.extname(entry.name))) continue;
    await fs.copyFile(sourcePath, targetPath);
    copied.push(path.relative(root, targetPath));
  }

  return copied;
}

await assertDirectory(vadSource, '@ricky0123/vad-web dist');
await assertDirectory(ortSource, 'onnxruntime-web dist');

const copied = [
  ...(await copyMatchingFiles(vadSource, vadTarget)),
  ...(await copyMatchingFiles(ortSource, ortTarget)),
];

if (copied.length === 0) {
  throw new Error('No VAD/ONNX assets were copied. Check installed package layout.');
}

console.log(`Copied ${copied.length} VAD/ONNX asset files:`);
for (const file of copied.sort()) {
  console.log(`- ${file}`);
}
```

- [ ] **Step 3: Add the npm script**

Edit `frontend/package.json` `scripts` to add `prepare:vad-assets` without changing existing scripts:

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "typecheck": "tsc -b",
    "test": "vitest run",
    "test:watch": "vitest",
    "test:e2e": "playwright test",
    "prepare:vad-assets": "node scripts/copy-vad-assets.mjs"
  }
}
```

- [ ] **Step 4: Ignore generated local VAD assets**

Append these lines to `.gitignore`:

```gitignore
# Generated browser VAD/ONNX assets copied from node_modules for local Vite serving
frontend/public/vendor/vad/
frontend/public/vendor/onnxruntime/
```

- [ ] **Step 5: Run asset copy**

Run:

```powershell
Push-Location frontend
npm run prepare:vad-assets
Pop-Location
```

Expected:

```text
Copied <N> VAD/ONNX asset files:
- public\vendor\...
```

If the command fails because package layout differs, stop and inspect `frontend/node_modules/@ricky0123/vad-web` and `frontend/node_modules/onnxruntime-web`; do not continue to code until the local asset serving path is known.

- [ ] **Step 6: Commit checkpoint only if explicitly authorized**

If commits are authorized, run:

```powershell
git add .gitignore frontend/package.json frontend/package-lock.json frontend/scripts/copy-vad-assets.mjs
git commit -m "build: add browser vad assets setup"
```

If commits are not authorized, skip this step.

---

## Task 2: Define VAD interfaces and real adapter

**Files:**
- Create: `frontend/src/voiceActivity/types.ts`
- Create: `frontend/src/voiceActivity/ricky-vad-web.d.ts`
- Create: `frontend/src/voiceActivity/createSileroVad.ts`

- [ ] **Step 1: Create project VAD types**

Create `frontend/src/voiceActivity/types.ts`:

```ts
export type VadRuntimeStatus =
  | 'disabled'
  | 'loading'
  | 'listening'
  | 'speech_detected'
  | 'speech_ended'
  | 'unavailable';

export interface VoiceActivityDetector {
  start(): Promise<void>;
  stop(): Promise<void>;
}

export interface CreateVoiceActivityDetectorOptions {
  onSpeechStart(): void;
  onSpeechEnd(): void;
  onError(error: unknown): void;
}

export type CreateVoiceActivityDetector = (
  options: CreateVoiceActivityDetectorOptions,
) => Promise<VoiceActivityDetector>;
```

- [ ] **Step 2: Declare the third-party module boundary**

Create `frontend/src/voiceActivity/ricky-vad-web.d.ts`:

```ts
declare module '@ricky0123/vad-web' {
  interface MicVadOptions {
    onSpeechStart?: () => void;
    onSpeechEnd?: (audio: Float32Array) => void;
    onVADMisfire?: () => void;
    onnxWASMBasePath?: string;
    baseAssetPath?: string;
    positiveSpeechThreshold?: number;
    negativeSpeechThreshold?: number;
    redemptionFrames?: number;
    minSpeechFrames?: number;
  }

  interface MicVadInstance {
    start: () => void | Promise<void>;
    pause?: () => void | Promise<void>;
    destroy?: () => void | Promise<void>;
  }

  export const MicVAD: {
    new: (options: MicVadOptions) => Promise<MicVadInstance>;
  };
}
```

- [ ] **Step 3: Write the real adapter**

Create `frontend/src/voiceActivity/createSileroVad.ts`:

```ts
import type { CreateVoiceActivityDetector } from './types';

function envString(name: string, fallback: string): string {
  const value = import.meta.env[name];
  return typeof value === 'string' && value.trim() ? value : fallback;
}

function envNumber(name: string): number | undefined {
  const value = import.meta.env[name];
  if (typeof value !== 'string' || !value.trim()) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

export const createSileroVad: CreateVoiceActivityDetector = async ({
  onSpeechStart,
  onSpeechEnd,
  onError,
}) => {
  const { MicVAD } = await import('@ricky0123/vad-web');

  const vad = await MicVAD.new({
    onSpeechStart,
    onSpeechEnd: () => onSpeechEnd(),
    onVADMisfire: () => undefined,
    onnxWASMBasePath: envString('VITE_VAD_ONNX_WASM_BASE_PATH', '/vendor/onnxruntime/'),
    baseAssetPath: envString('VITE_VAD_BASE_ASSET_PATH', '/vendor/vad/'),
    positiveSpeechThreshold: envNumber('VITE_VAD_POSITIVE_SPEECH_THRESHOLD'),
    negativeSpeechThreshold: envNumber('VITE_VAD_NEGATIVE_SPEECH_THRESHOLD'),
    redemptionFrames: envNumber('VITE_VAD_REDEMPTION_FRAMES'),
    minSpeechFrames: envNumber('VITE_VAD_MIN_SPEECH_FRAMES'),
  });

  return {
    async start() {
      try {
        await vad.start();
      } catch (error) {
        onError(error);
        throw error;
      }
    },
    async stop() {
      const maybePause = vad.pause?.();
      if (maybePause instanceof Promise) await maybePause;
      const maybeDestroy = vad.destroy?.();
      if (maybeDestroy instanceof Promise) await maybeDestroy;
    },
  };
};
```

- [ ] **Step 4: Run typecheck for the new types**

Run:

```powershell
Push-Location frontend
npm run typecheck
Pop-Location
```

Expected: typecheck may fail if later tasks are not implemented yet only if imports are referenced. At this point these new standalone files should not introduce type errors.

- [ ] **Step 5: Commit checkpoint only if explicitly authorized**

If commits are authorized, run:

```powershell
git add frontend/src/voiceActivity/types.ts frontend/src/voiceActivity/ricky-vad-web.d.ts frontend/src/voiceActivity/createSileroVad.ts
git commit -m "feat: add browser vad adapter boundary"
```

If commits are not authorized, skip this step.

---

## Task 3: Add the VAD auto-stop hook with fake tests

**Files:**
- Create: `frontend/src/hooks/useVadAutoStop.ts`
- Create: `frontend/src/hooks/useVadAutoStop.test.ts`

- [ ] **Step 1: Write failing tests for lifecycle and safety**

Create `frontend/src/hooks/useVadAutoStop.test.ts`:

```ts
import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useVadAutoStop } from './useVadAutoStop';
import type { CreateVoiceActivityDetector, CreateVoiceActivityDetectorOptions, VoiceActivityDetector } from '../voiceActivity/types';

function createFakeVadFactory() {
  const controls: {
    options?: CreateVoiceActivityDetectorOptions;
    detector?: VoiceActivityDetector;
    start: ReturnType<typeof vi.fn>;
    stop: ReturnType<typeof vi.fn>;
  } = {
    start: vi.fn().mockResolvedValue(undefined),
    stop: vi.fn().mockResolvedValue(undefined),
  };

  const createDetector: CreateVoiceActivityDetector = vi.fn(async (options) => {
    controls.options = options;
    controls.detector = {
      start: controls.start,
      stop: controls.stop,
    };
    return controls.detector;
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
      { initialProps: { status: 'idle' as const } },
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
      { initialProps: { status: 'recording' as const } },
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
      { initialProps: { status: 'recording' as const } },
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
Push-Location frontend
npm test -- --run src/hooks/useVadAutoStop.test.ts
Pop-Location
```

Expected: FAIL because `useVadAutoStop.ts` does not exist.

- [ ] **Step 3: Implement the hook**

Create `frontend/src/hooks/useVadAutoStop.ts`:

```ts
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
```

- [ ] **Step 4: Run hook tests**

Run:

```powershell
Push-Location frontend
npm test -- --run src/hooks/useVadAutoStop.test.ts
Pop-Location
```

Expected: PASS.

- [ ] **Step 5: Commit checkpoint only if explicitly authorized**

If commits are authorized, run:

```powershell
git add frontend/src/hooks/useVadAutoStop.ts frontend/src/hooks/useVadAutoStop.test.ts
git commit -m "feat: add vad auto-stop hook"
```

If commits are not authorized, skip this step.

---

## Task 4: Wire VAD auto-stop into the app UI

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/ChatLayout.tsx`
- Modify: `frontend/src/components/VoiceRecorder.tsx`
- Modify: `frontend/src/App.test.tsx`

- [ ] **Step 1: Add a failing UI test for VAD status**

Add this test to `frontend/src/App.test.tsx` near the voice recorder tests:

```ts
it('shows VAD auto-stop status while recording when VAD is active', async () => {
  const user = userEvent.setup();
  mockGetUserMedia.mockResolvedValue(fakeMediaStream());

  render(<App />);

  await user.click(await screen.findByRole('button', { name: '开始录音' }));

  expect(await screen.findByText('正在监听语音结束')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '停止录音' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '取消录音' })).toBeInTheDocument();
});
```

If `App.test.tsx` does not have a fake VAD mock yet, add this mock near the existing module mocks at the top of the file:

```ts
vi.mock('./voiceActivity/createSileroVad', () => ({
  createSileroVad: vi.fn(async ({ onSpeechEnd }: { onSpeechEnd: () => void }) => ({
    start: vi.fn(),
    stop: vi.fn(),
    __triggerSpeechEnd: onSpeechEnd,
  })),
}));
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
Push-Location frontend
npm test -- --run src/App.test.tsx -t "shows VAD auto-stop status"
Pop-Location
```

Expected: FAIL because the UI does not yet expose VAD status.

- [ ] **Step 3: Wire hook in `App.tsx`**

Modify imports in `frontend/src/App.tsx`:

```ts
import { useVadAutoStop } from './hooks/useVadAutoStop';
```

Add after recorder creation:

```ts
const vadAutoStop = useVadAutoStop({
  enabled: import.meta.env.MODE !== 'test' || import.meta.env.VITE_ENABLE_FAKE_VAD_IN_TEST === '1',
  recordingStatus: recorder.status,
  stopRecording: recorder.stopRecording,
});
```

Pass the message into `ChatLayout`:

```tsx
<ChatLayout
  sessions={sessions}
  activeSessionId={activeSessionId}
  messages={messages}
  loading={loading}
  error={error}
  audioController={audioController}
  recorder={recorder}
  pendingTranscript={pendingTranscript}
  playbackBlocked={recorder.isPlaybackBlocked || voiceTurnStatus === 'synthesizing_or_playing'}
  recorderDisabled={loading || !activeSessionId || voiceTurnStatus !== 'idle'}
  onCreateSession={handleCreateSession}
  onSelectSession={handleSelectSession}
  onDeleteSession={handleDeleteSession}
  onSendMessage={handleSendMessage}
  onSendAndSpeakTranscript={handleSendAndSpeakTranscript}
  voiceTurnBusy={voiceTurnStatus === 'sending_chat' || voiceTurnStatus === 'synthesizing_or_playing'}
  voiceTurnError={voiceTurnError}
  onDismissError={() => setError(null)}
  onClearPendingTranscript={handleClearPendingTranscript}
  vadStatusMessage={vadAutoStop.message}
/>
```

If the existing `ChatLayout` props differ, keep all existing props unchanged and add only `vadStatusMessage={vadAutoStop.message}`.

- [ ] **Step 4: Pass VAD message through `ChatLayout`**

Modify `frontend/src/components/ChatLayout.tsx` props:

```ts
interface ChatLayoutProps {
  sessions: Session[];
  activeSessionId: string | null;
  messages: Message[];
  loading: boolean;
  error: string | null;
  audioController: ReturnType<typeof useAudioPlaybackController>;
  recorder: UseManualAudioRecorderResult;
  pendingTranscript: string | null;
  playbackBlocked: boolean;
  recorderDisabled: boolean;
  vadStatusMessage: string | null;
  onCreateSession: () => void;
  onSelectSession: (sessionId: string) => void;
  onDeleteSession: (sessionId: string) => void;
  onSendMessage: (content: string) => Promise<void>;
  onSendAndSpeakTranscript: (transcript: string) => Promise<void>;
  voiceTurnBusy: boolean;
  voiceTurnError: string | null;
  onDismissError: () => void;
  onClearPendingTranscript: () => void;
}
```

Destructure it:

```ts
  vadStatusMessage,
```

Pass it to `VoiceRecorder`:

```tsx
<VoiceRecorder recorder={recorder} disabled={recorderDisabled} vadStatusMessage={vadStatusMessage} />
```

- [ ] **Step 5: Display status in `VoiceRecorder`**

Modify `frontend/src/components/VoiceRecorder.tsx` props:

```ts
interface VoiceRecorderProps {
  recorder: UseManualAudioRecorderResult;
  disabled: boolean;
  vadStatusMessage?: string | null;
}
```

Update function signature:

```ts
export function VoiceRecorder({ recorder, disabled, vadStatusMessage }: VoiceRecorderProps) {
```

Inside the recording block, insert the VAD message after elapsed time and before buttons:

```tsx
{vadStatusMessage ? (
  <span className="voice-recorder__vad-status" aria-label={vadStatusMessage}>
    {vadStatusMessage}
  </span>
) : null}
```

The final recording block should still include both buttons:

```tsx
{status === 'recording' && (
  <div className="voice-recorder__recording">
    <span className="voice-recorder__indicator" aria-hidden="true">🔴</span>
    <span aria-label={`已录音 ${formatElapsed(elapsedMs)}`}>{formatElapsed(elapsedMs)}</span>
    {vadStatusMessage ? (
      <span className="voice-recorder__vad-status" aria-label={vadStatusMessage}>
        {vadStatusMessage}
      </span>
    ) : null}
    <button type="button" aria-label="停止录音" onClick={() => recorder.stopRecording()}>
      停止录音
    </button>
    <button type="button" aria-label="取消录音" onClick={() => recorder.cancelRecording()}>
      取消
    </button>
  </div>
)}
```

- [ ] **Step 6: Run the focused UI test**

Run:

```powershell
Push-Location frontend
$env:VITE_ENABLE_FAKE_VAD_IN_TEST = "1"
npm test -- --run src/App.test.tsx -t "shows VAD auto-stop status"
Remove-Item Env:VITE_ENABLE_FAKE_VAD_IN_TEST
Pop-Location
```

Expected: PASS.

- [ ] **Step 7: Run existing frontend tests**

Run:

```powershell
Push-Location frontend
npm test -- --run
Pop-Location
```

Expected: PASS. If existing App tests now need VAD disabled by default, ensure they run without `VITE_ENABLE_FAKE_VAD_IN_TEST` and pass because VAD is off in test mode by default.

- [ ] **Step 8: Commit checkpoint only if explicitly authorized**

If commits are authorized, run:

```powershell
git add frontend/src/App.tsx frontend/src/components/ChatLayout.tsx frontend/src/components/VoiceRecorder.tsx frontend/src/App.test.tsx
git commit -m "feat: wire vad auto-stop status into recorder ui"
```

If commits are not authorized, skip this step.

---

## Task 5: Add explicit auto-stop behavior tests

**Files:**
- Modify: `frontend/src/App.test.tsx`

- [ ] **Step 1: Add a controllable fake VAD mock**

At the top of `frontend/src/App.test.tsx`, replace any simple VAD mock from Task 4 with this controllable version:

```ts
let latestVadSpeechEnd: (() => void) | null = null;
let latestVadStop: ReturnType<typeof vi.fn> | null = null;

vi.mock('./voiceActivity/createSileroVad', () => ({
  createSileroVad: vi.fn(async ({ onSpeechEnd }: { onSpeechEnd: () => void }) => {
    latestVadSpeechEnd = onSpeechEnd;
    latestVadStop = vi.fn();
    return {
      start: vi.fn(),
      stop: latestVadStop,
    };
  }),
}));
```

In `beforeEach`, reset it:

```ts
latestVadSpeechEnd = null;
latestVadStop = null;
```

- [ ] **Step 2: Add an auto-stop to transcript test**

Add this test to `frontend/src/App.test.tsx`:

```ts
it('VAD speech end auto-stops recording and produces pending transcript', async () => {
  const user = userEvent.setup();
  mockGetUserMedia.mockResolvedValue(fakeMediaStream());
  mockFetchTranscription('这是 VAD 自动停止后的转写。');

  render(<App />);

  await user.click(await screen.findByRole('button', { name: '开始录音' }));
  expect(await screen.findByText('正在监听语音结束')).toBeInTheDocument();

  act(() => {
    latestVadSpeechEnd?.();
  });

  expect(await screen.findByText(/转写待确认：这是 VAD 自动停止后的转写。/)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: '发送并朗读' })).toBeInTheDocument();
});
```

If `mockFetchTranscription` does not exist, add this helper near existing fetch helpers:

```ts
function mockFetchTranscription(text: string) {
  vi.mocked(globalThis.fetch).mockResolvedValueOnce(
    new Response(JSON.stringify({
      text,
      detected_language: 'zh',
      duration_ms: null,
      provider: 'fake',
      model: 'fake-asr-v1',
      inference_ms: 0,
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
}
```

- [ ] **Step 3: Add manual stop precedence test**

Add this test:

```ts
it('manual stop cleans up VAD and prevents duplicate auto-stop', async () => {
  const user = userEvent.setup();
  mockGetUserMedia.mockResolvedValue(fakeMediaStream());
  mockFetchTranscription('手动停止优先。');

  render(<App />);

  await user.click(await screen.findByRole('button', { name: '开始录音' }));
  await user.click(await screen.findByRole('button', { name: '停止录音' }));

  await screen.findByText(/转写待确认：手动停止优先。/);
  expect(latestVadStop).toHaveBeenCalled();

  act(() => {
    latestVadSpeechEnd?.();
  });

  expect(screen.getByText(/转写待确认：手动停止优先。/)).toBeInTheDocument();
  expect(vi.mocked(globalThis.fetch)).toHaveBeenCalledTimes(1);
});
```

- [ ] **Step 4: Add cancel cleanup test**

Add this test:

```ts
it('cancel recording stops VAD and does not upload after later speech end', async () => {
  const user = userEvent.setup();
  mockGetUserMedia.mockResolvedValue(fakeMediaStream());

  render(<App />);

  await user.click(await screen.findByRole('button', { name: '开始录音' }));
  await user.click(await screen.findByRole('button', { name: '取消录音' }));

  expect(latestVadStop).toHaveBeenCalled();

  act(() => {
    latestVadSpeechEnd?.();
  });

  expect(screen.getByRole('button', { name: '开始录音' })).toBeInTheDocument();
  expect(vi.mocked(globalThis.fetch)).not.toHaveBeenCalled();
});
```

- [ ] **Step 5: Run the new tests**

Run:

```powershell
Push-Location frontend
$env:VITE_ENABLE_FAKE_VAD_IN_TEST = "1"
npm test -- --run src/App.test.tsx -t "VAD|manual stop cleans up VAD|cancel recording stops VAD"
Remove-Item Env:VITE_ENABLE_FAKE_VAD_IN_TEST
Pop-Location
```

Expected: PASS.

- [ ] **Step 6: Run all frontend unit tests**

Run:

```powershell
Push-Location frontend
npm test -- --run
Pop-Location
```

Expected: PASS.

- [ ] **Step 7: Commit checkpoint only if explicitly authorized**

If commits are authorized, run:

```powershell
git add frontend/src/App.test.tsx
git commit -m "test: cover vad auto-stop recorder flow"
```

If commits are not authorized, skip this step.

---

## Task 6: Add real VAD UI smoke runner

**Files:**
- Create: `frontend/.claude-real-vad-ui-smoke.mjs`
- Create: `scripts/smoke_real_vad_ui.ps1`
- Create: `scripts/smoke_real_vad_ui.cmd`

- [ ] **Step 1: Create browser smoke driver**

Create `frontend/.claude-real-vad-ui-smoke.mjs`:

```js
import { chromium } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import readline from 'node:readline/promises';

const port = parseInt(process.env.E2E_FRONTEND_PORT ?? '16004', 10);
const frontendUrl = `http://127.0.0.1:${port}`;
const resultsDir = path.resolve('test-results');
const resultPath = path.join(resultsDir, 'real-vad-ui-smoke.json');
const screenshotPath = path.join(resultsDir, 'real-vad-ui-smoke.png');
const headed = process.env.REAL_VAD_HEADLESS !== '1';
const manualConfirm = process.env.REAL_VAD_MANUAL_CONFIRM !== '0';

await fs.mkdir(resultsDir, { recursive: true });

const browser = await chromium.launch({ headless: !headed, channel: 'msedge' });
const page = await browser.newPage();
const consoleErrors = [];

page.on('console', (message) => {
  if (message.type() === 'error') consoleErrors.push(message.text());
});
page.on('pageerror', (error) => consoleErrors.push(error.message));

let failure = null;
let operatorConfirmed = false;

try {
  await page.goto(frontendUrl, { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: '新建会话' }).click();
  await page.getByRole('button', { name: '开始录音' }).click();
  await page.getByText(/正在加载语音端点检测|正在监听语音结束|语音端点检测不可用/).waitFor({ timeout: 30000 });

  if (manualConfirm) {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    const answer = await rl.question('Speak a short phrase, then stay silent. Did VAD auto-stop and show pending transcript or transcribing state? Type y or n: ');
    rl.close();
    operatorConfirmed = answer.trim().toLowerCase() === 'y';
  } else {
    operatorConfirmed = true;
  }
} catch (error) {
  failure = `${error.name}: ${error.message}`;
}

const bodyText = await page.locator('body').innerText().catch(() => '');
await page.screenshot({ path: screenshotPath, fullPage: true }).catch(() => undefined);
await browser.close();

const result = {
  verdict: !failure && operatorConfirmed && consoleErrors.length === 0 ? 'PASS' : 'FAIL',
  failure,
  operatorConfirmed,
  bodyContainsVadStatus: /正在加载语音端点检测|正在监听语音结束|检测到语音结束|语音端点检测不可用/.test(bodyText),
  bodyContainsPendingTranscript: bodyText.includes('转写待确认：'),
  bodyContainsManualStop: bodyText.includes('停止录音'),
  bodyContainsCancel: bodyText.includes('取消'),
  consoleErrorCount: consoleErrors.length,
  consoleErrors,
  screenshotPath,
};

await fs.writeFile(resultPath, `${JSON.stringify(result, null, 2)}\n`, 'utf8');
console.log(JSON.stringify(result, null, 2));
if (result.verdict !== 'PASS') process.exit(1);
```

- [ ] **Step 2: Create PowerShell runner**

Create `scripts/smoke_real_vad_ui.ps1`:

```powershell
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $scriptDir
Push-Location ..

$backendPort = 18004
$frontendPort = 16004

function Stop-PortOwner([int]$port) {
    $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) {
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

function Wait-HttpOk([string]$url, [string]$name, [int]$maxSeconds) {
    for ($i = 1; $i -le $maxSeconds; $i++) {
        Start-Sleep 1
        try {
            $r = Invoke-WebRequest $url -TimeoutSec 2 -UseBasicParsing
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 300) {
                Write-Output "$name ready after ${i}s"
                return
            }
        } catch {}
    }
    throw "$name failed to become ready at $url"
}

try {
    Push-Location frontend
    npm run prepare:vad-assets
    Pop-Location

    foreach ($p in @($backendPort, $frontendPort)) {
        Stop-PortOwner $p
    }
    Start-Sleep 2

    $env:APP_ENV = "test"
    $env:LLM_PROVIDER = "fake"
    $env:ASR_PROVIDER = "fake"
    $env:FAKE_ASR_TEXT = "这是 VAD 自动停止测试转写。"
    $env:TTS_PROVIDER = "fake"
    $env:DATABASE_URL = "sqlite:///./test-results/smoke-real-vad.db"

    $beJob = Start-Job -Name "be-real-vad-smoke" -ScriptBlock {
        Set-Location $using:PWD
        $env:APP_ENV = "test"
        $env:LLM_PROVIDER = "fake"
        $env:ASR_PROVIDER = "fake"
        $env:FAKE_ASR_TEXT = "这是 VAD 自动停止测试转写。"
        $env:TTS_PROVIDER = "fake"
        $env:DATABASE_URL = "sqlite:///./test-results/smoke-real-vad.db"
        & ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port $using:backendPort
    }
    Write-Output "Backend job: $($beJob.Id)"
    Wait-HttpOk "http://127.0.0.1:$backendPort/health" "Backend" 60

    $env:BACKEND_PROXY_TARGET = "http://127.0.0.1:$backendPort"
    $env:VITE_VAD_ONNX_WASM_BASE_PATH = "/vendor/onnxruntime/"
    $env:VITE_VAD_BASE_ASSET_PATH = "/vendor/vad/"
    Push-Location frontend
    $feJob = Start-Job -Name "fe-real-vad-smoke" -ScriptBlock {
        Set-Location $using:PWD
        $env:BACKEND_PROXY_TARGET = "http://127.0.0.1:$using:backendPort"
        $env:VITE_VAD_ONNX_WASM_BASE_PATH = "/vendor/onnxruntime/"
        $env:VITE_VAD_BASE_ASSET_PATH = "/vendor/vad/"
        & node .\node_modules\vite\bin\vite.js --port $using:frontendPort --host 127.0.0.1
    }
    Pop-Location
    Write-Output "Frontend job: $($feJob.Id)"
    Wait-HttpOk "http://127.0.0.1:$frontendPort/" "Frontend" 60

    Push-Location frontend
    $env:E2E_FRONTEND_PORT = "$frontendPort"
    if (-not $env:REAL_VAD_HEADLESS) { $env:REAL_VAD_HEADLESS = "0" }
    if (-not $env:REAL_VAD_MANUAL_CONFIRM) { $env:REAL_VAD_MANUAL_CONFIRM = "1" }
    node .claude-real-vad-ui-smoke.mjs
    $exitCode = $LASTEXITCODE
    Pop-Location

    if ($exitCode -ne 0) {
        throw "Real VAD smoke failed with exit code $exitCode"
    }

    Write-Output "2D real VAD UI smoke PASS. Evidence: frontend/test-results/real-vad-ui-smoke.json"
    exit 0
} finally {
    Get-Job | Where-Object { $_.Name -like "*real-vad-smoke*" } | Stop-Job -ErrorAction SilentlyContinue
    Get-Job | Where-Object { $_.Name -like "*real-vad-smoke*" } | Remove-Job -Force -ErrorAction SilentlyContinue
    Pop-Location
    Pop-Location
}
```

- [ ] **Step 3: Create command wrapper**

Create `scripts/smoke_real_vad_ui.cmd`:

```bat
@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0smoke_real_vad_ui.ps1"
exit /b %ERRORLEVEL%
```

- [ ] **Step 4: Run syntax checks**

Run:

```powershell
Push-Location frontend
node --check .claude-real-vad-ui-smoke.mjs
Pop-Location
$null = [System.Management.Automation.PSParser]::Tokenize((Get-Content scripts/smoke_real_vad_ui.ps1 -Raw), [ref]$null)
```

Expected: no syntax errors.

- [ ] **Step 5: Commit checkpoint only if explicitly authorized**

If commits are authorized, run:

```powershell
git add frontend/.claude-real-vad-ui-smoke.mjs scripts/smoke_real_vad_ui.ps1 scripts/smoke_real_vad_ui.cmd
git commit -m "test: add real vad ui smoke"
```

If commits are not authorized, skip this step.

---

## Task 7: Validate and record Stage 2D evidence

**Files:**
- Create: `docs/stage2d-vad-auto-stop.md`
- Modify: `README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Run automated validation**

Run:

```powershell
Push-Location frontend
npm test -- --run src/hooks/useVadAutoStop.test.ts
npm test -- --run
npm run typecheck
npm run build
Pop-Location
```

Expected:

```text
PASS src/hooks/useVadAutoStop.test.ts
... all frontend tests pass
npm run typecheck exits 0
npm run build exits 0
```

- [ ] **Step 2: Run backend regression if runtime backend files changed**

If no backend files changed, skip this step and record that it was skipped because 2D only changed frontend VAD/docs/scripts.

If any backend runtime file changed, run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -v
```

Expected: PASS.

- [ ] **Step 3: Run real VAD smoke**

Run:

```powershell
.\scripts\smoke_real_vad_ui.ps1
```

Expected:

```text
Backend ready after ...s
Frontend ready after ...s
Speak a short phrase, then stay silent. Did VAD auto-stop and show pending transcript or transcribing state? Type y or n:
2D real VAD UI smoke PASS. Evidence: frontend/test-results/real-vad-ui-smoke.json
```

When prompted, type `y` only if real VAD auto-stop occurred after explicit start. Type `n` if you had to use manual stop or if VAD failed.

- [ ] **Step 4: Read smoke evidence**

Run:

```powershell
Get-Content frontend\test-results\real-vad-ui-smoke.json -Raw
```

Expected success indicators:

```json
{
  "verdict": "PASS",
  "operatorConfirmed": true,
  "consoleErrorCount": 0
}
```

- [ ] **Step 5: Write evidence doc**

Create `docs/stage2d-vad-auto-stop.md`:

```markdown
# Stage 2D VAD Auto-stop Evidence

Status: COMPLETED on 2026-06-28 if and only if the validation table below records PASS for the real VAD smoke.

## Scope

Stage 2D adds VAD auto-stop only after the user explicitly starts recording. It does not add background listening, wake word, voice interruption, streaming ASR/TTS, long-term memory, or emotion behavior.

## Validation

| Command | Result |
|---|---|
| `npm test -- --run src/hooks/useVadAutoStop.test.ts` | PASS — fake VAD lifecycle tests passed |
| `npm test -- --run` | PASS — frontend unit tests passed |
| `npm run typecheck` | PASS |
| `npm run build` | PASS |
| `.\scripts\smoke_real_vad_ui.ps1` | PASS — real Silero/ONNX VAD loaded in browser after explicit start and auto-stopped recording after speech end |

## Behavior verified

- VAD does not start on page load or before `开始录音`.
- VAD starts only during active recording.
- VAD speech-end calls the existing recorder stop path.
- Manual `停止录音` remains available.
- `取消录音` remains available.
- VAD failure is recoverable and does not block manual recording.
- The existing ASR transcript confirmation path remains unchanged.

## Evidence artifacts

- Real VAD smoke JSON: `frontend/test-results/real-vad-ui-smoke.json`.
- Real VAD smoke screenshot: `frontend/test-results/real-vad-ui-smoke.png`.

Generated smoke artifacts are local and are not committed by default.
```

If the real smoke failed, replace the first status line with:

```markdown
Status: NOT COMPLETED.
```

Then set the `.\scripts\smoke_real_vad_ui.ps1` row to the concrete failure classification and do not update `CLAUDE.md` as completed.

- [ ] **Step 6: Update README only for PASS**

If the real VAD smoke passed, update `README.md` top status to include `2D VAD auto-stop，已完成`, remove VAD from the unimplemented list, and add a short section:

```markdown
### Stage 2D VAD auto-stop

Stage 2D adds browser-side Silero/ONNX VAD auto-stop after the user explicitly clicks `开始录音`. Manual stop and cancel remain available, and VAD does not run as background listening.

Verification result on 2026-06-28: **PASS** — fake VAD unit tests, frontend regression, typecheck, build, and opt-in real VAD browser smoke passed. Evidence is recorded in `docs/stage2d-vad-auto-stop.md`.
```

If the real smoke failed, keep README clear that Stage 2D is not completed.

- [ ] **Step 7: Update CLAUDE.md only for PASS**

If the real VAD smoke passed, update `CLAUDE.md`:

- Header: add `2D VAD Auto-stop COMPLETED`.
- Stage 2 table: change `2D—2F：NOT STARTED` to `2D VAD Auto-stop：COMPLETED；2E—2F：NOT STARTED`.
- Completed abilities: add this bullet:

```markdown
- 子任务 2D：VAD auto-stop 已完成（2026-06-28；浏览器端 Silero/ONNX VAD 仅在用户显式点击 `开始录音` 后运行，检测到 speech end 后调用现有录音停止路径；手动停止、取消、重录仍可用；VAD failure 不破坏手动录音；fake VAD 自动化测试与 opt-in real VAD browser smoke 均 PASS；证据记录于 `docs/stage2d-vad-auto-stop.md`）。未实现后台监听、语音打断、流式 ASR/TTS、长期记忆或情感系统。
```

- Unimplemented list: remove `VAD。`, keep interruption/turn control, audio device management, streaming ASR/TTS.

If the real smoke failed, do not mark 2D complete.

- [ ] **Step 8: Check secrets and generated artifacts**

Run:

```powershell
git status --short
```

Expected:

- No `.env` files.
- No raw microphone recordings.
- No generated `.wav`, `.mp3`, `.m4a` files.
- No `frontend/public/vendor/vad/` or `frontend/public/vendor/onnxruntime/` files staged unless the project deliberately decides to vendor model assets.
- `frontend/test-results/` remains ignored.

- [ ] **Step 9: Commit checkpoint only if explicitly authorized**

If commits are authorized, run:

```powershell
git add docs/stage2d-vad-auto-stop.md README.md CLAUDE.md
git commit -m "docs: record stage 2d vad auto-stop"
```

If commits are not authorized, skip this step.

---

## Task 8: Final report

**Files:**
- Read: `docs/stage2d-vad-auto-stop.md`
- Read: `CLAUDE.md`
- Read: `README.md`

- [ ] **Step 1: Confirm final status**

Run:

```powershell
Select-String -Path docs\stage2d-vad-auto-stop.md -Pattern "Status:"
Select-String -Path CLAUDE.md -Pattern "2D"
Select-String -Path README.md -Pattern "Stage 2D|2D"
```

Expected for completion: all three files agree that 2D is completed. If the real smoke failed, all three files must agree that 2D is not completed.

- [ ] **Step 2: Produce required task-end report**

Use this format:

```text
完成内容：
修改文件：
验证命令与结果：
未完成或受限部分：
是否改变当前阶段：否/是（附验收证据）
下一项建议任务：
```

For PASS, next suggested task is Stage 2E voice interruption/turn control. For FAIL, next suggested task is the smallest fix for the classified VAD failure.

---

## Self-review

- Spec coverage: Tasks cover dependency/assets, adapter boundary, fake tests, app wiring, real smoke, evidence docs, README/CLAUDE status, and final report.
- Placeholder scan: No TODO/TBD placeholders are present. Failure branches have explicit text to use.
- Type consistency: `CreateVoiceActivityDetector`, `VoiceActivityDetector`, `VadRuntimeStatus`, and `useVadAutoStop` signatures are defined before later tasks use them.
- Scope check: The plan does not add background listening, interruption, streaming, backend VAD, memory, emotion, or schema changes.
- Testing boundary: Default tests use fake VAD; real Silero/ONNX is isolated to opt-in smoke.
