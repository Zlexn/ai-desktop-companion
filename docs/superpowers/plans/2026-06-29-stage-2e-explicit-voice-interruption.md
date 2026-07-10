# Stage 2E Explicit Voice Interruption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user explicitly interrupt current assistant TTS synthesis/playback by clicking `开始录音`, stopping audio work and starting the existing recorder/VAD/ASR flow.

**Architecture:** Keep the interruption entirely in the frontend voice orchestration layer. Reuse `audioController.reset()` as the single audio cleanup path, then start the existing `useManualAudioRecorder` recorder; do not add background listening, streaming, backend endpoints, database changes, memory, or emotion behavior.

**Tech Stack:** React, TypeScript, Vite, Vitest, Testing Library, existing `useAudioPlaybackController`, `useManualAudioRecorder`, `useVadAutoStop`, and fake ASR/TTS test infrastructure.

---

## File structure

### Modify

- `frontend/src/App.tsx`
  - Allow recorder start while audio synthesis/playback is busy.
  - Treat `voiceTurnStatus === 'synthesizing_or_playing'` as explicitly interruptible.
  - Keep `voiceTurnStatus === 'sending_chat'` blocked.
  - Reuse existing generation guard so stale TTS completion cannot update state after interruption.

- `frontend/src/App.test.tsx`
  - Replace the old “blocks recording while assistant audio is busy” assertion with explicit-interruption behavior.
  - Add coverage for send-and-speak TTS interruption and stale completion.

- `docs/stage2e-explicit-voice-interruption.md`
  - Evidence file after validation.

- `README.md`
  - Update only after validation passes.

- `CLAUDE.md`
  - Update only after validation passes.

- `docs/stage2-voice-architecture.md`
  - Add implementation addendum only after validation passes.

### Do not modify

- Backend runtime code.
- Database schema.
- ASR/TTS provider interfaces.
- Stage 3 memory files.
- Stage 4 emotion files.

---

## Task 1: Make assistant-message synthesis explicitly interruptible

**Files:**
- Modify: `frontend/src/App.test.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Update the existing failing test expectation**

In `frontend/src/App.test.tsx`, replace the existing test named:

```ts
it('blocks recording while assistant audio is busy', async () => {
```

with this test:

```ts
it('allows recording to explicitly interrupt assistant audio synthesis', async () => {
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
    },
  });

  let resolveSpeech: (response: Response) => void = () => undefined;
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '' }]))
    .mockResolvedValueOnce(jsonResponse([
      { id: 'a1', session_id: 's1', role: 'assistant', content: '可播放回复', created_at: '1', metadata: {} },
    ]))
    .mockReturnValueOnce(new Promise<Response>((resolve) => { resolveSpeech = resolve; }));

  render(<App />);
  await user.click(await screen.findByRole('button', { name: '播放' }));

  const recordButton = await screen.findByRole('button', { name: '开始录音' });
  expect(recordButton).toBeEnabled();

  await user.click(recordButton);

  expect(await screen.findByRole('button', { name: '停止录音' })).toBeInTheDocument();
  expect(screen.getByText('正在监听语音结束')).toBeInTheDocument();

  resolveSpeech(wavResponse());
  await waitFor(() => expect(screen.queryByText('生成中…')).not.toBeInTheDocument());
});
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```powershell
Push-Location frontend
npm test -- --run src/App.test.tsx -t "allows recording to explicitly interrupt assistant audio synthesis"
Pop-Location
```

Expected: FAIL because `开始录音` is still disabled while `audioController.isAudioBusy` is true.

- [ ] **Step 3: Implement the minimal recorder-disabled change**

In `frontend/src/App.tsx`, add these derived booleans before the `return`:

```ts
  const isVoiceTurnSendingChat = voiceTurnStatus === 'sending_chat';
  const isVoiceTurnSynthesizingOrPlaying = voiceTurnStatus === 'synthesizing_or_playing';
  const recorderDisabled =
    !activeSessionId ||
    isVoiceTurnSendingChat ||
    (loading && !isVoiceTurnSynthesizingOrPlaying);
```

Then replace the `recorderDisabled={...}` prop in `ChatLayout` with:

```tsx
      recorderDisabled={recorderDisabled}
```

Do not include `audioController.isAudioBusy` in `recorderDisabled`.

- [ ] **Step 4: Run the focused test and verify it passes**

Run:

```powershell
Push-Location frontend
npm test -- --run src/App.test.tsx -t "allows recording to explicitly interrupt assistant audio synthesis"
Pop-Location
```

Expected: PASS.

- [ ] **Step 5: Run App tests to catch immediate regressions**

Run:

```powershell
Push-Location frontend
npm test -- --run src/App.test.tsx
Pop-Location
```

Expected: PASS or only failures that directly describe the new intended interruption behavior.

---

## Task 2: Make send-and-speak TTS explicitly interruptible

**Files:**
- Modify: `frontend/src/App.test.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Add a failing test for interrupting send-and-speak TTS**

Add this test near the other voice-turn tests in `frontend/src/App.test.tsx`:

```ts
it('starts a new recording when user interrupts send-and-speak TTS', async () => {
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
    },
  });

  let resolveSpeech: (response: Response) => void = () => undefined;
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '' }]))
    .mockResolvedValueOnce(jsonResponse([]))
    .mockResolvedValueOnce(jsonResponse({ text: '第一轮语音', detected_language: 'zh', duration_ms: 1000, provider: 'fake-asr', model: 'fake', inference_ms: 1 }))
    .mockResolvedValueOnce(jsonResponse({ reply: '第一轮回复', metadata: { provider: 'fake', model: 'test' } }))
    .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '3' }]))
    .mockResolvedValueOnce(jsonResponse([
      { id: 'u1', session_id: 's1', role: 'user', content: '第一轮语音', created_at: '1', metadata: {} },
      { id: 'a1', session_id: 's1', role: 'assistant', content: '第一轮回复', created_at: '2', metadata: {} },
    ]))
    .mockReturnValueOnce(new Promise<Response>((resolve) => { resolveSpeech = resolve; }));

  render(<App />);
  await user.click(await screen.findByRole('button', { name: '开始录音' }));
  await new Promise((resolve) => setTimeout(resolve, 350));
  await user.click(await screen.findByRole('button', { name: '停止录音' }));
  await user.click(await screen.findByRole('button', { name: '发送并朗读' }));

  const interruptButton = await screen.findByRole('button', { name: '开始录音' });
  expect(interruptButton).toBeEnabled();

  await user.click(interruptButton);

  expect(await screen.findByRole('button', { name: '停止录音' })).toBeInTheDocument();
  expect(screen.getByText('正在监听语音结束')).toBeInTheDocument();

  resolveSpeech(wavResponse());
  await waitFor(() => expect(screen.queryByText('文字回复已生成，但语音合成或播放失败。可稍后重试播放。')).not.toBeInTheDocument());
});
```

- [ ] **Step 2: Run the focused test and verify it fails if Task 1 is insufficient**

Run:

```powershell
Push-Location frontend
npm test -- --run src/App.test.tsx -t "starts a new recording when user interrupts send-and-speak TTS"
Pop-Location
```

Expected before implementation: FAIL because `handleStartRecording()` does not yet clear voice-turn generation/status for interrupted `synthesizing_or_playing`, or because loading still blocks the button.

- [ ] **Step 3: Update `handleStartRecording()` to treat TTS as interruptible**

In `frontend/src/App.tsx`, replace `handleStartRecording` with:

```ts
  const handleStartRecording = useCallback(async () => {
    if (voiceTurnStatus === 'sending_chat') return;

    if (voiceTurnStatus === 'synthesizing_or_playing') {
      voiceTurnGenerationRef.current += 1;
      voiceTurnInFlightRef.current = false;
      setVoiceTurnStatus('idle');
      setVoiceTurnError(null);
      setLoading(false);
    }

    audioController.reset();
    await recorder.startRecording('');
  }, [audioController, recorder, voiceTurnStatus]);
```

This keeps interruption explicit and uses the existing generation guard to make the old `handleSendAndSpeakTranscript()` promise stale.

- [ ] **Step 4: Run the focused test and verify it passes**

Run:

```powershell
Push-Location frontend
npm test -- --run src/App.test.tsx -t "starts a new recording when user interrupts send-and-speak TTS"
Pop-Location
```

Expected: PASS.

---

## Task 3: Preserve the `sending_chat` blocker

**Files:**
- Modify: `frontend/src/App.test.tsx`

- [ ] **Step 1: Add a failing test that recording stays blocked while chat send is in flight**

Add this test near the voice-turn tests in `frontend/src/App.test.tsx`:

```ts
it('keeps recording blocked while voice turn chat send is in flight', async () => {
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
    },
  });

  let resolveChat: (response: Response) => void = () => undefined;
  vi.mocked(fetch)
    .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '' }]))
    .mockResolvedValueOnce(jsonResponse([]))
    .mockResolvedValueOnce(jsonResponse({ text: '语音转写文本', detected_language: 'zh', duration_ms: 1000, provider: 'fake-asr', model: 'fake', inference_ms: 1 }))
    .mockReturnValueOnce(new Promise<Response>((resolve) => { resolveChat = resolve; }));

  render(<App />);
  await user.click(await screen.findByRole('button', { name: '开始录音' }));
  await new Promise((resolve) => setTimeout(resolve, 350));
  await user.click(await screen.findByRole('button', { name: '停止录音' }));
  await user.click(await screen.findByRole('button', { name: '发送并朗读' }));

  expect(await screen.findByRole('button', { name: '开始录音' })).toBeDisabled();

  resolveChat(jsonResponse({ reply: '回复', metadata: { provider: 'fake', model: 'test' } }));
});
```

- [ ] **Step 2: Run the focused test**

Run:

```powershell
Push-Location frontend
npm test -- --run src/App.test.tsx -t "keeps recording blocked while voice turn chat send is in flight"
Pop-Location
```

Expected: PASS if Task 1/2 preserved the `sending_chat` blocker. If it fails, fix `recorderDisabled` to include `voiceTurnStatus === 'sending_chat'` and re-run.

---

## Task 4: Add optional interruption hint text

**Files:**
- Modify: `frontend/src/components/VoiceRecorder.tsx`
- Modify: `frontend/src/components/ChatLayout.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.test.tsx`

- [ ] **Step 1: Add a failing test for the hint**

Add this assertion to the Task 1 test after finding the enabled record button:

```ts
expect(screen.getByText('点击开始录音会停止当前朗读')).toBeInTheDocument();
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```powershell
Push-Location frontend
npm test -- --run src/App.test.tsx -t "allows recording to explicitly interrupt assistant audio synthesis"
Pop-Location
```

Expected: FAIL because no hint is shown yet.

- [ ] **Step 3: Pass an interruption hint through `ChatLayout`**

In `frontend/src/components/ChatLayout.tsx`, add this prop to `ChatLayoutProps`:

```ts
  recorderHintMessage: string | null;
```

Destructure it from props:

```ts
  recorderHintMessage,
```

Pass it to `VoiceRecorder`:

```tsx
<VoiceRecorder
  recorder={recorder}
  disabled={recorderDisabled}
  vadStatusMessage={vadStatusMessage}
  hintMessage={recorderHintMessage}
/>
```

- [ ] **Step 4: Display the hint in `VoiceRecorder`**

In `frontend/src/components/VoiceRecorder.tsx`, update props:

```ts
interface VoiceRecorderProps {
  recorder: UseManualAudioRecorderResult;
  disabled: boolean;
  vadStatusMessage?: string | null;
  hintMessage?: string | null;
}
```

Update the function signature:

```ts
export function VoiceRecorder({ recorder, disabled, vadStatusMessage, hintMessage }: VoiceRecorderProps) {
```

Inside the root `<div>`, render the hint when present:

```tsx
{hintMessage ? <span className="voice-recorder__hint">{hintMessage}</span> : null}
```

Place it before the idle button so the user sees it before clicking.

- [ ] **Step 5: Provide the hint from `App.tsx`**

In `frontend/src/App.tsx`, add this derived value before `return`:

```ts
  const recorderHintMessage = audioController.isAudioBusy || isVoiceTurnSynthesizingOrPlaying
    ? '点击开始录音会停止当前朗读'
    : null;
```

Pass it to `ChatLayout`:

```tsx
      recorderHintMessage={recorderHintMessage}
```

- [ ] **Step 6: Run the focused test and verify it passes**

Run:

```powershell
Push-Location frontend
npm test -- --run src/App.test.tsx -t "allows recording to explicitly interrupt assistant audio synthesis"
Pop-Location
```

Expected: PASS.

---

## Task 5: Run full frontend validation

**Files:**
- Read/validate only.

- [ ] **Step 1: Run VAD hook tests**

Run:

```powershell
Push-Location frontend
npm test -- --run src/hooks/useVadAutoStop.test.ts
Pop-Location
```

Expected: PASS — 6 tests.

- [ ] **Step 2: Run all frontend unit tests**

Run:

```powershell
Push-Location frontend
npm test -- --run
Pop-Location
```

Expected: PASS — all frontend tests pass. The exact count may be higher than 71 after new 2E tests.

- [ ] **Step 3: Run typecheck**

Run:

```powershell
Push-Location frontend
npm run typecheck
Pop-Location
```

Expected: PASS.

- [ ] **Step 4: Run build**

Run:

```powershell
Push-Location frontend
npm run build
Pop-Location
```

Expected: PASS.

- [ ] **Step 5: Run fake E2E if time permits**

Run:

```powershell
Push-Location frontend
npm run test:e2e
Pop-Location
```

Expected: PASS. If existing E2E setup fails for an environmental reason unrelated to 2E, record the exact failure and do not claim E2E PASS.

---

## Task 6: Record Stage 2E evidence and status

**Files:**
- Create: `docs/stage2e-explicit-voice-interruption.md`
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `docs/stage2-voice-architecture.md`

- [ ] **Step 1: Write the evidence document**

Create `docs/stage2e-explicit-voice-interruption.md`:

```markdown
# Stage 2E Explicit Voice Interruption Evidence

Status: COMPLETED on 2026-06-29 if and only if all validation rows below are PASS.

## Scope

Stage 2E adds explicit voice interruption: clicking `开始录音` while assistant audio is synthesizing or playing stops/aborts current audio work and starts the existing recorder/VAD/ASR flow.

It does not add background listening, wake word detection, automatic spoken barge-in, streaming ASR/TTS, long-term memory, or emotion behavior.

## Validation

| Command | Result |
|---|---|
| `npm test -- --run src/hooks/useVadAutoStop.test.ts` | PASS — VAD lifecycle regression passed |
| `npm test -- --run` | PASS — frontend unit tests passed |
| `npm run typecheck` | PASS |
| `npm run build` | PASS |
| `npm run test:e2e` | PASS or SKIPPED with reason recorded here |

## Behavior verified

- `开始录音` is enabled during assistant-message TTS synthesis/playback.
- Clicking `开始录音` stops/aborts current assistant audio work.
- `开始录音` is enabled during send-and-speak TTS synthesis/playback.
- Interrupted send-and-speak stale TTS completion does not show a false voice-turn error.
- Recording remains blocked while chat send is still in flight.
- Stage 2D VAD auto-stop/manual stop behavior remains unchanged.
- Text chat remains usable.

## Evidence notes

No raw audio, private transcript, API key, or generated speech artifact is committed by this document.
```

If any validation command fails, set `Status: NOT COMPLETED` and do not update `CLAUDE.md` as completed.

- [ ] **Step 2: Update README only after PASS**

If validation passed, update README current status to include `2E explicit voice interruption，已完成`, remove 2E from the unimplemented list, and add a short section:

```markdown
### Stage 2E explicit voice interruption

Stage 2E adds explicit voice interruption: when assistant audio is synthesizing or playing, clicking `开始录音` stops/aborts the current audio and starts the existing recorder/VAD/ASR flow. This is not background listening or automatic spoken barge-in.

Verification result on 2026-06-29: **PASS** — frontend unit tests, VAD regression, typecheck, build, and documented E2E status passed. Evidence is recorded in `docs/stage2e-explicit-voice-interruption.md`.
```

- [ ] **Step 3: Update CLAUDE.md only after PASS**

If validation passed, update `CLAUDE.md`:

- Header: add `2E Explicit Voice Interruption COMPLETED`.
- Stage 2 table: change `2E—2F：NOT STARTED` to `2E Explicit Voice Interruption：COMPLETED；2F：NOT STARTED`.
- Completed abilities: add this bullet:

```markdown
- 子任务 2E：Explicit voice interruption 已完成（2026-06-29；用户可在 assistant 音频合成或播放中点击 `开始录音`，系统会停止/取消当前音频并启动现有录音/VAD/ASR 路径；`sending_chat` 期间仍阻止录音；stale TTS completion 不会重启播放或污染 voice-turn 状态；证据记录于 `docs/stage2e-explicit-voice-interruption.md`）。未实现后台监听、自动 spoken barge-in、流式 ASR/TTS、长期记忆或情感系统。
```

- Unimplemented list: remove `打断与轮次控制。`, keep audio device management and streaming ASR/TTS.

- [ ] **Step 4: Add architecture addendum**

Append to `docs/stage2-voice-architecture.md`:

```markdown
## 20. Milestone 2E implementation addendum — 2026-06-29

Implemented 2E boundary:

- Explicit user click on `开始录音` can interrupt assistant audio synthesis/playback.
- Interruption reuses `audioController.reset()` and the existing recorder/VAD/ASR path.
- Recording remains blocked while chat send is in flight.
- No background listening, automatic spoken barge-in, streaming, memory, or emotion behavior is introduced.

Evidence is recorded in `docs/stage2e-explicit-voice-interruption.md`.
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

## Task 7: Final report

**Files:**
- Read: `docs/stage2e-explicit-voice-interruption.md`
- Read: `CLAUDE.md`
- Read: `README.md`

- [ ] **Step 1: Confirm final status consistency**

Run:

```powershell
Select-String -Path docs\stage2e-explicit-voice-interruption.md -Pattern "Status:|PASS|NOT COMPLETED"
Select-String -Path CLAUDE.md -Pattern "2E|阶段 2 尚未实现"
Select-String -Path README.md -Pattern "2E|explicit voice interruption|未实现范围"
```

Expected for completion: all files agree that 2E is completed. If validation failed, all files must agree that 2E is not completed.

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

For PASS, next suggested task is Stage 2F streaming/performance optimization or a narrow audio device management slice, depending on project priority. For FAIL, next suggested task is the smallest fix for the classified failure.

---

## Self-review

- Spec coverage: Tasks cover explicit interruption during assistant-message synthesis, send-and-speak TTS interruption, `sending_chat` blocker, stale TTS protection, optional UI hint, validation, and docs.
- Placeholder scan: No TODO/TBD placeholders are present. Failure branches specify exact status handling.
- Type consistency: Uses existing `voiceTurnStatus`, `audioController.reset()`, `recorder.startRecording('')`, `recorderDisabled`, and existing test helpers.
- Scope check: No backend endpoint, background listening, streaming, memory, emotion, or schema change is included.
- TDD check: Each behavior change starts with a failing/updated test before production code changes.
