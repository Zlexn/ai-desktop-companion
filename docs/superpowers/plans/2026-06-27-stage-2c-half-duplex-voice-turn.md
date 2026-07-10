# Stage 2C-1 Half-Duplex Voice Turn Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first fake-provider half-duplex voice turn: pending ASR transcript -> explicit `发送并朗读` -> existing text chat -> stable matching assistant reply -> existing TTS playback.

**Architecture:** Keep orchestration in the React frontend and reuse the existing backend APIs. Add a small frontend helper for stable post-send assistant-message matching, expose global audio busy state from the playback controller, and thread a new explicit voice-send action through `App`, `ChatLayout`, and `MessageInput`. Do not add a backend `/voice-turns` endpoint and do not change message persistence semantics.

**Tech Stack:** React + TypeScript + Vite, Vitest + Testing Library, Playwright, existing FastAPI backend tests with fake ASR/TTS/LLM providers.

---

## File structure

### Create

- `frontend/src/voiceTurn.ts`
  - Pure helper for selecting the assistant message produced by the current voice-turn send.
  - No React, no network calls, no audio calls.
- `frontend/src/voiceTurn.test.ts`
  - Focused unit tests for stable post-send matching and stale/no-match cases.

### Modify

- `frontend/src/hooks/useAudioPlaybackController.ts`
  - Add global `isAudioBusy`.
  - Change `play()` to return `Promise<boolean>` so a caller can detect TTS/playback failure after chat succeeds.
  - Keep existing callers compatible; ignored boolean return is safe.
- `frontend/src/components/VoiceRecorder.tsx`
  - Apply `disabled` to retry recording from error state as well as idle state.
- `frontend/src/components/MessageInput.tsx`
  - Add explicit `发送并朗读` action for pending transcript.
  - Accept voice-turn busy/error props.
- `frontend/src/components/ChatLayout.tsx`
  - Thread new voice-turn props.
  - Disable recorder while global audio busy or voice-turn send is active.
- `frontend/src/App.tsx`
  - Add active-session ref to ignore stale async results.
  - Add voice-turn status/error state.
  - Add `handleSendAndSpeakTranscript()` that sends pending transcript, refreshes messages, selects the matching assistant, and invokes TTS.
- `frontend/src/App.test.tsx`
  - Add integration tests for `发送并朗读`, stable assistant selection, duplicate click prevention, and TTS failure behavior.
- `frontend/src/components/MessageList.test.tsx`
  - Add/adjust tests for `isAudioBusy` and `play()` boolean return.
- `frontend/e2e/voice-turn.spec.ts`
  - Add fake-provider browser coverage for the full 2C-1 flow, using controlled browser mocks instead of real microphone/model calls.
- `README.md`
  - Update only after validation with exact 2C-1 fake-provider status.
- `CLAUDE.md`
  - Update only after validation. If real-provider smoke is deferred, record 2C-1 fake baseline separately and keep full 2C incomplete.

### Do not modify unless a test reveals an existing bug

- `backend/app/api/routes/audio.py`
- `backend/app/api/routes/chat.py`
- `backend/app/services/chat_service.py`
- `backend/app/services/asr_service.py`
- `backend/app/services/tts_service.py`

---

## Task 1: Add stable voice-turn assistant matching helper

**Files:**
- Create: `frontend/src/voiceTurn.ts`
- Create: `frontend/src/voiceTurn.test.ts`

- [ ] **Step 1: Write failing tests for assistant matching**

Create `frontend/src/voiceTurn.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import type { Message } from './api/types';
import { findAssistantReplyForVoiceTurn } from './voiceTurn';

function message(overrides: Partial<Message>): Message {
  return {
    id: overrides.id ?? 'm',
    session_id: overrides.session_id ?? 's1',
    role: overrides.role ?? 'user',
    content: overrides.content ?? '',
    created_at: overrides.created_at ?? '',
    metadata: overrides.metadata ?? {},
  };
}

describe('findAssistantReplyForVoiceTurn', () => {
  it('selects the new assistant message directly after the new transcript user message', () => {
    const before = [
      message({ id: 'u1', role: 'user', content: '旧消息' }),
      message({ id: 'a1', role: 'assistant', content: '旧回复' }),
    ];
    const after = [
      ...before,
      message({ id: 'u2', role: 'user', content: '语音转写文本' }),
      message({ id: 'a2', role: 'assistant', content: '新的助手回复' }),
    ];

    expect(findAssistantReplyForVoiceTurn({ before, after, transcript: '语音转写文本', sessionId: 's1' }))
      .toEqual(after[3]);
  });

  it('returns null when the active session changed', () => {
    const before = [message({ id: 'u1', session_id: 's1', role: 'user', content: '旧消息' })];
    const after = [
      ...before,
      message({ id: 'u2', session_id: 's2', role: 'user', content: '语音转写文本' }),
      message({ id: 'a2', session_id: 's2', role: 'assistant', content: '错误会话回复' }),
    ];

    expect(findAssistantReplyForVoiceTurn({ before, after, transcript: '语音转写文本', sessionId: 's1' }))
      .toBeNull();
  });

  it('returns null instead of using a blind newest-assistant heuristic', () => {
    const before = [message({ id: 'u1', role: 'user', content: '旧消息' })];
    const after = [
      ...before,
      message({ id: 'a2', role: 'assistant', content: '无对应用户消息的新回复' }),
    ];

    expect(findAssistantReplyForVoiceTurn({ before, after, transcript: '语音转写文本', sessionId: 's1' }))
      .toBeNull();
  });

  it('chooses the assistant after the matching new user transcript when multiple new messages exist', () => {
    const before = [message({ id: 'u1', role: 'user', content: '旧消息' })];
    const after = [
      ...before,
      message({ id: 'u2', role: 'user', content: '其他输入' }),
      message({ id: 'a2', role: 'assistant', content: '其他回复' }),
      message({ id: 'u3', role: 'user', content: '语音转写文本' }),
      message({ id: 'a3', role: 'assistant', content: '语音回合回复' }),
    ];

    expect(findAssistantReplyForVoiceTurn({ before, after, transcript: '语音转写文本', sessionId: 's1' }))
      .toEqual(after[4]);
  });
});
```

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```powershell
Push-Location frontend
npm test -- --run src/voiceTurn.test.ts
Pop-Location
```

Expected: FAIL because `./voiceTurn` does not exist.

- [ ] **Step 3: Implement the helper**

Create `frontend/src/voiceTurn.ts`:

```ts
import type { Message } from './api/types';

interface FindAssistantReplyArgs {
  before: Message[];
  after: Message[];
  transcript: string;
  sessionId: string;
}

export function findAssistantReplyForVoiceTurn({ before, after, transcript, sessionId }: FindAssistantReplyArgs): Message | null {
  const cleanTranscript = transcript.trim();
  if (!cleanTranscript) return null;

  const beforeIds = new Set(before.map((item) => item.id));
  const isNewInSession = (message: Message) => message.session_id === sessionId && !beforeIds.has(message.id);

  const userIndex = after.findIndex(
    (item) => isNewInSession(item) && item.role === 'user' && item.content.trim() === cleanTranscript,
  );
  if (userIndex < 0) return null;

  for (const item of after.slice(userIndex + 1)) {
    if (!isNewInSession(item)) continue;
    if (item.role === 'assistant') return item;
    if (item.role === 'user') return null;
  }

  return null;
}
```

- [ ] **Step 4: Run helper tests and verify they pass**

Run:

```powershell
Push-Location frontend
npm test -- --run src/voiceTurn.test.ts
Pop-Location
```

Expected: PASS.

- [ ] **Step 5: Commit checkpoint only if commits are authorized**

If the user explicitly authorized commits, run:

```powershell
git add frontend/src/voiceTurn.ts frontend/src/voiceTurn.test.ts
git commit -m "test: add voice turn assistant matching helper"
```

If commits are not authorized, skip this step and continue with uncommitted changes.

---

## Task 2: Expose global audio busy state and TTS play success result

**Files:**
- Modify: `frontend/src/hooks/useAudioPlaybackController.ts`
- Modify: `frontend/src/components/MessageList.test.tsx`

- [ ] **Step 1: Add failing tests for `isAudioBusy` and boolean `play()` result**

Append these tests inside `describe('MessageList audio controls', ...)` in `frontend/src/components/MessageList.test.tsx`:

```ts
  it('exposes global busy state while speech is synthesizing and playing', async () => {
    const user = userEvent.setup();
    let resolveResponse: (response: Response) => void = () => undefined;
    vi.mocked(fetch).mockReturnValueOnce(new Promise<Response>((resolve) => { resolveResponse = resolve; }));

    function BusyHarness() {
      const audioController = useAudioPlaybackController();
      return (
        <>
          <div data-testid="audio-busy">{audioController.isAudioBusy ? 'busy' : 'idle'}</div>
          <MessageList messages={messages} audioController={audioController} playbackBlocked={false} />
        </>
      );
    }

    render(<BusyHarness />);
    expect(screen.getByTestId('audio-busy')).toHaveTextContent('idle');

    await user.click(screen.getAllByRole('button', { name: '播放' })[0]);
    expect(screen.getByTestId('audio-busy')).toHaveTextContent('busy');

    resolveResponse(wavResponse());
    await screen.findByRole('button', { name: '暂停' });
    expect(screen.getByTestId('audio-busy')).toHaveTextContent('busy');

    await user.click(screen.getByRole('button', { name: '停止' }));
    expect(screen.getByTestId('audio-busy')).toHaveTextContent('idle');
  });

  it('returns false when speech synthesis fails', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(errorResponse('语音合成服务暂时不可用，请稍后重试。'));
    let playResult: boolean | null = null;

    function ResultHarness() {
      const audioController = useAudioPlaybackController();
      return (
        <button type="button" onClick={async () => { playResult = await audioController.play('a1', '我听见了：你好'); }}>
          run play
        </button>
      );
    }

    render(<ResultHarness />);
    await userEvent.click(screen.getByRole('button', { name: 'run play' }));

    await waitFor(() => expect(playResult).toBe(false));
  });
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```powershell
Push-Location frontend
npm test -- --run src/components/MessageList.test.tsx
Pop-Location
```

Expected: FAIL because `isAudioBusy` does not exist and `play()` does not return `boolean`.

- [ ] **Step 3: Implement `isAudioBusy` and boolean play result**

Modify `frontend/src/hooks/useAudioPlaybackController.ts`:

1. Change `playExisting` to return `Promise<boolean>`:

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
      await audio.play();
      updateEntry(messageId, { state: 'playing', error: null });
      return true;
    } catch (caught) {
      updateEntry(messageId, { state: 'error', error: errorMessage(caught) });
      setActive(null);
      return false;
    }
  }, [setActive, stopActive, updateEntry]);
```

2. Change `play` to return `Promise<boolean>`:

```ts
  const play = useCallback(async (messageId: string, text: string): Promise<boolean> => {
    const existing = entries[messageId];
    if (existing?.state === 'synthesizing') return false;
    if (existing?.url) {
      return playExisting(messageId, existing.url);
    }

    if (activeMessageIdRef.current && activeMessageIdRef.current !== messageId) {
      stopActive();
    }
    abortControllerRef.current?.abort();
    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    setActive(messageId);
    updateEntry(messageId, { state: 'synthesizing', error: null });

    try {
      const result = await apiClient.synthesizeSpeech(text, { signal: abortController.signal });
      if (abortController.signal.aborted || activeMessageIdRef.current !== messageId) return false;
      revokeUrl(messageId);
      const url = URL.createObjectURL(result.blob);
      urlsRef.current.set(messageId, url);
      updateEntry(messageId, {
        state: 'ready',
        url,
        error: null,
        metadata: {
          provider: result.provider,
          model: result.model,
          durationMs: result.durationMs,
          sampleRate: result.sampleRate,
        },
      });
      return playExisting(messageId, url);
    } catch (caught) {
      if (abortController.signal.aborted) return false;
      updateEntry(messageId, { state: 'error', error: errorMessage(caught) });
      setActive(null);
      return false;
    } finally {
      if (abortControllerRef.current === abortController) {
        abortControllerRef.current = null;
      }
    }
  }, [entries, playExisting, revokeUrl, setActive, stopActive, updateEntry]);
```

3. Change `resume` and `replay` to preserve compatibility with the new return type:

```ts
  const resume = useCallback(async (messageId: string): Promise<boolean> => {
    const entry = entries[messageId];
    if (!entry?.url) return false;
    return playExisting(messageId, entry.url);
  }, [entries, playExisting]);

  const replay = useCallback(async (messageId: string, text: string): Promise<boolean> => {
    const entry = entries[messageId];
    if (!entry?.url) {
      return play(messageId, text);
    }
    if (audioRef.current) {
      audioRef.current.currentTime = 0;
    }
    return playExisting(messageId, entry.url);
  }, [entries, play, playExisting]);
```

4. Add `isAudioBusy` before the return:

```ts
  const isAudioBusy = Object.values(entries).some((entry) =>
    entry.state === 'synthesizing' || entry.state === 'playing' || entry.state === 'paused',
  );
```

5. Return it:

```ts
  return { isAudioBusy, pause, play, replay, reset, resume, stateFor, stop };
```

- [ ] **Step 4: Run playback tests and verify they pass**

Run:

```powershell
Push-Location frontend
npm test -- --run src/components/MessageList.test.tsx
Pop-Location
```

Expected: PASS.

- [ ] **Step 5: Commit checkpoint only if commits are authorized**

If authorized:

```powershell
git add frontend/src/hooks/useAudioPlaybackController.ts frontend/src/components/MessageList.test.tsx
git commit -m "feat: expose global audio busy state"
```

Otherwise skip.

---

## Task 3: Add `发送并朗读` UI to pending transcript

**Files:**
- Modify: `frontend/src/components/MessageInput.tsx`

- [ ] **Step 1: Add failing component tests in `App.test.tsx` for visible action**

Append a focused render-level test to `frontend/src/App.test.tsx`. This test will fail until later tasks wire the whole flow, but it defines the UI contract now:

```ts
  it('offers send-and-speak for a pending transcript', async () => {
    const user = userEvent.setup();
    class FakeMediaRecorder {
      static isTypeSupported() { return true; }
      state = 'inactive';
      mimeType = 'audio/webm';
      ondataavailable: ((event: BlobEvent) => void) | null = null;
      onstop: (() => void) | null = null;
      onerror: (() => void) | null = null;
      constructor() {}
      start() { this.state = 'recording'; }
      stop() {
        this.state = 'inactive';
        this.ondataavailable?.({ data: new Blob(['voice'], { type: 'audio/webm' }) } as BlobEvent);
        this.onstop?.();
      }
    }
    vi.stubGlobal('MediaRecorder', FakeMediaRecorder);
    vi.stubGlobal('navigator', {
      mediaDevices: {
        getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: vi.fn(), addEventListener: vi.fn() }] }),
      },
    });

    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '' }]))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse({ text: '语音转写文本', detected_language: 'zh', duration_ms: 1000, provider: 'fake-asr', model: 'fake', inference_ms: 1 }));

    render(<App />);
    await user.click(await screen.findByRole('button', { name: '开始录音' }));
    await user.click(await screen.findByRole('button', { name: '停止录音' }));

    expect(await screen.findByRole('button', { name: '发送并朗读' })).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```powershell
Push-Location frontend
npm test -- --run src/App.test.tsx -t "offers send-and-speak"
Pop-Location
```

Expected: FAIL because no `发送并朗读` button exists.

- [ ] **Step 3: Modify `MessageInput` props and pending UI**

Modify the interface in `frontend/src/components/MessageInput.tsx`:

```ts
interface MessageInputProps {
  disabled: boolean;
  onSend: (content: string) => Promise<void>;
  /** ASR transcript pending user action — null means no pending transcript. */
  pendingTranscript: string | null;
  /** Called when the user discards the pending transcript without applying it. */
  onClearPendingTranscript: () => void;
  onSendAndSpeakTranscript: (transcript: string) => Promise<void>;
  voiceTurnBusy: boolean;
  voiceTurnError: string | null;
}
```

Change the function signature:

```ts
export function MessageInput({
  disabled,
  onSend,
  pendingTranscript,
  onClearPendingTranscript,
  onSendAndSpeakTranscript,
  voiceTurnBusy,
  voiceTurnError,
}: MessageInputProps) {
```

Add this handler below `applyDiscard()`:

```ts
  async function applySendAndSpeak(transcript: string) {
    await onSendAndSpeakTranscript(transcript);
  }
```

Add the new button inside `.message-input__pending-actions` after `追加` and before `丢弃`:

```tsx
            <button
              type="button"
              aria-label="发送并朗读"
              disabled={disabled || voiceTurnBusy}
              onClick={() => void applySendAndSpeak(pendingTranscript)}
            >
              {voiceTurnBusy ? '发送并朗读中…' : '发送并朗读'}
            </button>
```

Add a voice-turn error display after the pending transcript block and before the form:

```tsx
      {voiceTurnError ? (
        <div className="message-input__voice-error" role="alert">
          {voiceTurnError}
        </div>
      ) : null}
```

- [ ] **Step 4: Thread temporary bridge props through `ChatLayout` so compilation reaches App wiring**

Modify `frontend/src/components/ChatLayout.tsx` props:

```ts
  onSendAndSpeakTranscript: (transcript: string) => Promise<void>;
  voiceTurnBusy: boolean;
  voiceTurnError: string | null;
```

Destructure them in the component parameter and pass them to `MessageInput`:

```tsx
          onSendAndSpeakTranscript={onSendAndSpeakTranscript}
          voiceTurnBusy={voiceTurnBusy}
          voiceTurnError={voiceTurnError}
```

- [ ] **Step 5: Add temporary App no-op wiring to make the UI test pass**

In `frontend/src/App.tsx`, pass temporary bridge values to `ChatLayout`:

```tsx
      onSendAndSpeakTranscript={async () => undefined}
      voiceTurnBusy={false}
      voiceTurnError={null}
```

These are intentionally replaced by Task 4.

- [ ] **Step 6: Run the focused UI test**

Run:

```powershell
Push-Location frontend
npm test -- --run src/App.test.tsx -t "offers send-and-speak"
Pop-Location
```

Expected: PASS.

- [ ] **Step 7: Commit checkpoint only if commits are authorized**

If authorized:

```powershell
git add frontend/src/components/MessageInput.tsx frontend/src/components/ChatLayout.tsx frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "feat: add voice transcript send-and-speak action"
```

Otherwise skip.

---

## Task 4: Implement voice-turn orchestration in `App`

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.test.tsx`
- Use: `frontend/src/voiceTurn.ts`

- [ ] **Step 1: Add failing integration test for full fake voice turn**

Append to `frontend/src/App.test.tsx`:

```ts
  it('sends a pending transcript and auto-plays the matching assistant reply', async () => {
    const user = userEvent.setup();
    URL.createObjectURL = vi.fn(() => 'blob:tts-audio');
    const playMock = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);

    class FakeMediaRecorder {
      static isTypeSupported() { return true; }
      state = 'inactive';
      mimeType = 'audio/webm';
      ondataavailable: ((event: BlobEvent) => void) | null = null;
      onstop: (() => void) | null = null;
      constructor() {}
      start() { this.state = 'recording'; }
      stop() {
        this.state = 'inactive';
        this.ondataavailable?.({ data: new Blob(['voice'], { type: 'audio/webm' }) } as BlobEvent);
        this.onstop?.();
      }
    }
    vi.stubGlobal('MediaRecorder', FakeMediaRecorder);
    vi.stubGlobal('navigator', {
      mediaDevices: {
        getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: vi.fn(), addEventListener: vi.fn() }] }),
      },
    });

    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '' }]))
      .mockResolvedValueOnce(jsonResponse([
        { id: 'old-u', session_id: 's1', role: 'user', content: '旧消息', created_at: '1', metadata: {} },
        { id: 'old-a', session_id: 's1', role: 'assistant', content: '旧回复', created_at: '2', metadata: {} },
      ]))
      .mockResolvedValueOnce(jsonResponse({ text: '语音转写文本', detected_language: 'zh', duration_ms: 1000, provider: 'fake-asr', model: 'fake', inference_ms: 1 }))
      .mockResolvedValueOnce(jsonResponse({ reply: '语音回合回复', metadata: { provider: 'fake', model: 'test' } }))
      .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '3' }]))
      .mockResolvedValueOnce(jsonResponse([
        { id: 'old-u', session_id: 's1', role: 'user', content: '旧消息', created_at: '1', metadata: {} },
        { id: 'old-a', session_id: 's1', role: 'assistant', content: '旧回复', created_at: '2', metadata: {} },
        { id: 'new-u', session_id: 's1', role: 'user', content: '语音转写文本', created_at: '3', metadata: {} },
        { id: 'new-a', session_id: 's1', role: 'assistant', content: '语音回合回复', created_at: '4', metadata: {} },
      ]))
      .mockResolvedValueOnce(new Response(new Uint8Array([82, 73, 70, 70, 0, 0, 0, 0, 87, 65, 86, 69]), {
        status: 200,
        headers: {
          'Content-Type': 'audio/wav',
          'X-TTS-Provider': 'fake',
          'X-TTS-Model': 'fake-tone-v1',
        },
      }));

    render(<App />);
    await user.click(await screen.findByRole('button', { name: '开始录音' }));
    await user.click(await screen.findByRole('button', { name: '停止录音' }));
    await user.click(await screen.findByRole('button', { name: '发送并朗读' }));

    await waitFor(() => expect(screen.getByText('语音回合回复')).toBeInTheDocument());
    await waitFor(() => expect(playMock).toHaveBeenCalledTimes(1));
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input) === '/api/audio/speech')).toBe(true);
  });
```

- [ ] **Step 2: Run the integration test and verify it fails**

Run:

```powershell
Push-Location frontend
npm test -- --run src/App.test.tsx -t "sends a pending transcript"
Pop-Location
```

Expected: FAIL because App still uses the temporary no-op handler.

- [ ] **Step 3: Implement App voice-turn state and handler**

Modify imports in `frontend/src/App.tsx`:

```ts
import { useCallback, useEffect, useRef, useState } from 'react';
import { findAssistantReplyForVoiceTurn } from './voiceTurn';
```

Add state and ref after existing state:

```ts
  const [voiceTurnStatus, setVoiceTurnStatus] = useState<'idle' | 'sending_chat' | 'synthesizing_or_playing' | 'error'>('idle');
  const [voiceTurnError, setVoiceTurnError] = useState<string | null>(null);
  const activeSessionIdRef = useRef<string | null>(activeSessionId);
```

Add an effect after the existing session load effects:

```ts
  useEffect(() => {
    activeSessionIdRef.current = activeSessionId;
  }, [activeSessionId]);
```

Update `resetVoiceState()`:

```ts
  function resetVoiceState() {
    recorder.cancelRecording();
    setPendingTranscript(null);
    setVoiceTurnStatus('idle');
    setVoiceTurnError(null);
  }
```

Add the handler below `handleSendMessage`:

```ts
  async function handleSendAndSpeakTranscript(transcript: string) {
    const sessionId = activeSessionId;
    const cleanTranscript = transcript.trim();
    if (!sessionId || !cleanTranscript) return;
    if (voiceTurnStatus === 'sending_chat' || voiceTurnStatus === 'synthesizing_or_playing') return;

    const beforeMessages = messages;
    setLoading(true);
    setError(null);
    setVoiceTurnError(null);
    setVoiceTurnStatus('sending_chat');

    try {
      await apiClient.sendMessage(sessionId, cleanTranscript);
      const [updatedSessions, updatedMessages] = await Promise.all([
        apiClient.listSessions(),
        apiClient.listMessages(sessionId),
      ]);

      if (activeSessionIdRef.current !== sessionId) return;

      setSessions(updatedSessions);
      setMessages(updatedMessages);
      setPendingTranscript(null);
      recorder.clearResult();

      const assistantMessage = findAssistantReplyForVoiceTurn({
        before: beforeMessages,
        after: updatedMessages,
        transcript: cleanTranscript,
        sessionId,
      });

      if (!assistantMessage) {
        setVoiceTurnStatus('error');
        setVoiceTurnError('文字回复已生成，但没有找到对应的语音回复，请使用消息上的播放按钮。');
        return;
      }

      setVoiceTurnStatus('synthesizing_or_playing');
      const played = await audioController.play(assistantMessage.id, assistantMessage.content);
      if (activeSessionIdRef.current !== sessionId) return;

      if (!played) {
        setVoiceTurnStatus('error');
        setVoiceTurnError('文字回复已生成，但语音合成或播放失败。可稍后重试播放。');
        return;
      }

      setVoiceTurnStatus('idle');
    } catch (caught) {
      if (activeSessionIdRef.current !== sessionId) return;
      setVoiceTurnStatus('error');
      setError(errorMessage(caught));
    } finally {
      if (activeSessionIdRef.current === sessionId) {
        setLoading(false);
      }
    }
  }
```

Replace temporary `ChatLayout` props:

```tsx
      onSendAndSpeakTranscript={handleSendAndSpeakTranscript}
      voiceTurnBusy={voiceTurnStatus === 'sending_chat' || voiceTurnStatus === 'synthesizing_or_playing'}
      voiceTurnError={voiceTurnError}
```

- [ ] **Step 4: Run the integration test and verify it passes**

Run:

```powershell
Push-Location frontend
npm test -- --run src/App.test.tsx -t "sends a pending transcript"
Pop-Location
```

Expected: PASS.

- [ ] **Step 5: Run all App tests**

Run:

```powershell
Push-Location frontend
npm test -- --run src/App.test.tsx
Pop-Location
```

Expected: PASS.

- [ ] **Step 6: Commit checkpoint only if commits are authorized**

If authorized:

```powershell
git add frontend/src/App.tsx frontend/src/App.test.tsx frontend/src/voiceTurn.ts
git commit -m "feat: orchestrate fake half-duplex voice turns"
```

Otherwise skip.

---

## Task 5: Enforce half-duplex recorder disable and stale session cleanup

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/ChatLayout.tsx`
- Modify: `frontend/src/components/VoiceRecorder.tsx`
- Modify: `frontend/src/App.test.tsx`

- [ ] **Step 1: Add failing test for audio busy blocking recording retry/start**

Append to `frontend/src/App.test.tsx`:

```ts
  it('blocks recording while assistant audio is busy', async () => {
    const user = userEvent.setup();
    let resolveSpeech: (response: Response) => void = () => undefined;
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockReturnValue(new Promise<void>(() => undefined));
    URL.createObjectURL = vi.fn(() => 'blob:tts-audio');

    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '' }]))
      .mockResolvedValueOnce(jsonResponse([
        { id: 'a1', session_id: 's1', role: 'assistant', content: '可播放回复', created_at: '1', metadata: {} },
      ]))
      .mockReturnValueOnce(new Promise<Response>((resolve) => { resolveSpeech = resolve; }));

    render(<App />);
    await user.click(await screen.findByRole('button', { name: '播放' }));
    expect(screen.getByRole('button', { name: '开始录音' })).toBeDisabled();

    resolveSpeech(new Response(new Uint8Array([82, 73, 70, 70, 0, 0, 0, 0, 87, 65, 86, 69]), {
      status: 200,
      headers: { 'Content-Type': 'audio/wav' },
    }));
    await waitFor(() => expect(screen.getByRole('button', { name: '开始录音' })).toBeDisabled());
  });
```

- [ ] **Step 2: Add failing test for session switch cleanup**

Append to `frontend/src/App.test.tsx`:

```ts
  it('clears pending transcript when switching sessions', async () => {
    const user = userEvent.setup();
    class FakeMediaRecorder {
      static isTypeSupported() { return true; }
      state = 'inactive';
      mimeType = 'audio/webm';
      ondataavailable: ((event: BlobEvent) => void) | null = null;
      onstop: (() => void) | null = null;
      start() { this.state = 'recording'; }
      stop() {
        this.state = 'inactive';
        this.ondataavailable?.({ data: new Blob(['voice'], { type: 'audio/webm' }) } as BlobEvent);
        this.onstop?.();
      }
    }
    vi.stubGlobal('MediaRecorder', FakeMediaRecorder);
    vi.stubGlobal('navigator', {
      mediaDevices: {
        getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: vi.fn(), addEventListener: vi.fn() }] }),
      },
    });

    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse([
        { id: 's1', title: '会话一', created_at: '', updated_at: '2' },
        { id: 's2', title: '会话二', created_at: '', updated_at: '1' },
      ]))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse({ text: '语音转写文本', detected_language: 'zh', duration_ms: 1000, provider: 'fake-asr', model: 'fake', inference_ms: 1 }))
      .mockResolvedValueOnce(jsonResponse([]));

    render(<App />);
    await user.click(await screen.findByRole('button', { name: '开始录音' }));
    await user.click(await screen.findByRole('button', { name: '停止录音' }));
    expect(await screen.findByText('转写待确认：语音转写文本')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '会话二' }));
    await waitFor(() => expect(screen.queryByText('转写待确认：语音转写文本')).not.toBeInTheDocument());
  });
```

- [ ] **Step 3: Run the new tests and verify they fail if behavior is missing**

Run:

```powershell
Push-Location frontend
npm test -- --run src/App.test.tsx -t "blocks recording|clears pending transcript"
Pop-Location
```

Expected: FAIL for audio busy blocking until wiring is added. Session cleanup may already pass; keep the test either way as regression coverage.

- [ ] **Step 4: Wire audio busy into recorder disabled state**

Modify `frontend/src/App.tsx` `ChatLayout` props:

```tsx
      playbackBlocked={recorder.isPlaybackBlocked}
      recorderDisabled={loading || !activeSessionId || audioController.isAudioBusy || voiceTurnStatus === 'sending_chat' || voiceTurnStatus === 'synthesizing_or_playing'}
```

Modify `frontend/src/components/ChatLayout.tsx` props:

```ts
  recorderDisabled: boolean;
```

Destructure it and replace the `VoiceRecorder` call:

```tsx
        <VoiceRecorder recorder={recorder} disabled={recorderDisabled} />
```

- [ ] **Step 5: Disable retry button in `VoiceRecorder`**

Modify `frontend/src/components/VoiceRecorder.tsx` error button:

```tsx
          <button type="button" aria-label="重试录音" disabled={disabled} onClick={() => recorder.startRecording('')}>
            重试
          </button>
```

- [ ] **Step 6: Run the focused tests**

Run:

```powershell
Push-Location frontend
npm test -- --run src/App.test.tsx -t "blocks recording|clears pending transcript"
Pop-Location
```

Expected: PASS.

- [ ] **Step 7: Commit checkpoint only if commits are authorized**

If authorized:

```powershell
git add frontend/src/App.tsx frontend/src/components/ChatLayout.tsx frontend/src/components/VoiceRecorder.tsx frontend/src/App.test.tsx
git commit -m "test: cover half-duplex recorder blocking"
```

Otherwise skip.

---

## Task 6: Add TTS failure and duplicate-click coverage for voice turns

**Files:**
- Modify: `frontend/src/App.test.tsx`
- Modify if needed: `frontend/src/App.tsx`

- [ ] **Step 1: Add failing test for TTS failure after chat success**

Append to `frontend/src/App.test.tsx`:

```ts
  it('keeps text reply visible when voice-turn TTS fails', async () => {
    const user = userEvent.setup();
    class FakeMediaRecorder {
      static isTypeSupported() { return true; }
      state = 'inactive';
      mimeType = 'audio/webm';
      ondataavailable: ((event: BlobEvent) => void) | null = null;
      onstop: (() => void) | null = null;
      start() { this.state = 'recording'; }
      stop() {
        this.state = 'inactive';
        this.ondataavailable?.({ data: new Blob(['voice'], { type: 'audio/webm' }) } as BlobEvent);
        this.onstop?.();
      }
    }
    vi.stubGlobal('MediaRecorder', FakeMediaRecorder);
    vi.stubGlobal('navigator', {
      mediaDevices: {
        getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: vi.fn(), addEventListener: vi.fn() }] }),
      },
    });

    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '' }]))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse({ text: '语音转写文本', detected_language: 'zh', duration_ms: 1000, provider: 'fake-asr', model: 'fake', inference_ms: 1 }))
      .mockResolvedValueOnce(jsonResponse({ reply: '文字回复已经生成', metadata: { provider: 'fake', model: 'test' } }))
      .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '3' }]))
      .mockResolvedValueOnce(jsonResponse([
        { id: 'u1', session_id: 's1', role: 'user', content: '语音转写文本', created_at: '1', metadata: {} },
        { id: 'a1', session_id: 's1', role: 'assistant', content: '文字回复已经生成', created_at: '2', metadata: {} },
      ]))
      .mockResolvedValueOnce(jsonResponse({ error: { message: '语音合成服务暂时不可用，请稍后重试。' } }, 502));

    render(<App />);
    await user.click(await screen.findByRole('button', { name: '开始录音' }));
    await user.click(await screen.findByRole('button', { name: '停止录音' }));
    await user.click(await screen.findByRole('button', { name: '发送并朗读' }));

    expect(await screen.findByText('文字回复已经生成')).toBeInTheDocument();
    expect(await screen.findByText('文字回复已生成，但语音合成或播放失败。可稍后重试播放。')).toBeInTheDocument();
  });
```

- [ ] **Step 2: Add failing test for duplicate send-and-speak clicks**

Append to `frontend/src/App.test.tsx`:

```ts
  it('does not duplicate voice-turn chat sends on repeated clicks', async () => {
    const user = userEvent.setup();
    class FakeMediaRecorder {
      static isTypeSupported() { return true; }
      state = 'inactive';
      mimeType = 'audio/webm';
      ondataavailable: ((event: BlobEvent) => void) | null = null;
      onstop: (() => void) | null = null;
      start() { this.state = 'recording'; }
      stop() {
        this.state = 'inactive';
        this.ondataavailable?.({ data: new Blob(['voice'], { type: 'audio/webm' }) } as BlobEvent);
        this.onstop?.();
      }
    }
    vi.stubGlobal('MediaRecorder', FakeMediaRecorder);
    vi.stubGlobal('navigator', {
      mediaDevices: {
        getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: vi.fn(), addEventListener: vi.fn() }] }),
      },
    });

    let resolveChat: (response: Response) => void = () => undefined;
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '' }]))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse({ text: '语音转写文本', detected_language: 'zh', duration_ms: 1000, provider: 'fake-asr', model: 'fake', inference_ms: 1 }))
      .mockReturnValueOnce(new Promise<Response>((resolve) => { resolveChat = resolve; }))
      .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '3' }]))
      .mockResolvedValueOnce(jsonResponse([
        { id: 'u1', session_id: 's1', role: 'user', content: '语音转写文本', created_at: '1', metadata: {} },
        { id: 'a1', session_id: 's1', role: 'assistant', content: '回复', created_at: '2', metadata: {} },
      ]));

    render(<App />);
    await user.click(await screen.findByRole('button', { name: '开始录音' }));
    await user.click(await screen.findByRole('button', { name: '停止录音' }));
    const button = await screen.findByRole('button', { name: '发送并朗读' });

    await Promise.all([user.click(button), user.click(button)]);
    resolveChat(jsonResponse({ reply: '回复', metadata: { provider: 'fake', model: 'test' } }));

    await waitFor(() => {
      const chatCalls = vi.mocked(fetch).mock.calls.filter(([input]) => String(input).includes('/messages') && String(input).includes('/api/sessions/s1'));
      expect(chatCalls).toHaveLength(2); // initial listMessages + exactly one POST send
    });
  });
```

- [ ] **Step 3: Run the focused tests**

Run:

```powershell
Push-Location frontend
npm test -- --run src/App.test.tsx -t "TTS fails|duplicate voice-turn"
Pop-Location
```

Expected: PASS if Task 4 handler and Task 2 `play()` boolean are correct. If duplicate test fails, add a ref guard:

```ts
  const voiceTurnInFlightRef = useRef(false);
```

Set it before the async send and clear in `finally`:

```ts
    if (voiceTurnInFlightRef.current) return;
    voiceTurnInFlightRef.current = true;
    try {
      // existing body
    } finally {
      voiceTurnInFlightRef.current = false;
      if (activeSessionIdRef.current === sessionId) {
        setLoading(false);
      }
    }
```

- [ ] **Step 4: Run all App tests**

Run:

```powershell
Push-Location frontend
npm test -- --run src/App.test.tsx
Pop-Location
```

Expected: PASS.

- [ ] **Step 5: Commit checkpoint only if commits are authorized**

If authorized:

```powershell
git add frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "test: cover voice-turn failure and duplicate guards"
```

Otherwise skip.

---

## Task 7: Add Playwright fake 2C-1 full-turn coverage

**Files:**
- Create: `frontend/e2e/voice-turn.spec.ts`
- Modify if needed: `frontend/playwright.config.ts`

- [ ] **Step 1: Create failing E2E spec**

Create `frontend/e2e/voice-turn.spec.ts`:

```ts
import { expect, test } from '@playwright/test';

test('fake half-duplex voice turn sends transcript and requests TTS playback', async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });

  await page.addInitScript(() => {
    class FakeMediaRecorder {
      static isTypeSupported() { return true; }
      state = 'inactive';
      mimeType = 'audio/webm';
      ondataavailable: ((event: BlobEvent) => void) | null = null;
      onstop: (() => void) | null = null;
      start() { this.state = 'recording'; }
      stop() {
        this.state = 'inactive';
        this.ondataavailable?.({ data: new Blob(['voice'], { type: 'audio/webm' }) } as BlobEvent);
        this.onstop?.();
      }
    }

    Object.defineProperty(window, 'MediaRecorder', { value: FakeMediaRecorder });
    Object.defineProperty(navigator, 'mediaDevices', {
      value: {
        getUserMedia: async () => ({ getTracks: () => [{ stop() {}, addEventListener() {} }] }),
      },
      configurable: true,
    });

    HTMLMediaElement.prototype.play = async () => undefined;
    HTMLMediaElement.prototype.pause = () => undefined;
  });

  const speechRequests: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/api/audio/speech')) speechRequests.push(request.url());
  });

  await page.goto('/');
  await page.getByRole('button', { name: '新建会话' }).click();
  await expect(page.getByRole('button', { name: '开始录音' })).toBeVisible();
  await page.getByRole('button', { name: '开始录音' }).click();
  await page.getByRole('button', { name: '停止录音' }).click();
  await expect(page.getByText(/转写待确认/)).toBeVisible();
  await page.getByRole('button', { name: '发送并朗读' }).click();

  await expect(page.getByText(/我听见了/)).toBeVisible();
  await expect.poll(() => speechRequests.length).toBeGreaterThan(0);
  expect(consoleErrors).toEqual([]);
});
```

- [ ] **Step 2: Run the E2E spec and verify current behavior**

Run:

```powershell
Push-Location frontend
npm run test:e2e -- voice-turn.spec.ts
Pop-Location
```

Expected: PASS after prior tasks. If it fails because fake ASR text differs, assert the actual fake ASR text shown by the app and keep the test focused on one user message, one assistant reply, and one TTS request.

- [ ] **Step 3: Commit checkpoint only if commits are authorized**

If authorized:

```powershell
git add frontend/e2e/voice-turn.spec.ts frontend/playwright.config.ts
git commit -m "test: add fake half-duplex voice turn e2e"
```

Otherwise skip.

---

## Task 8: Run full automated validation

**Files:**
- No code changes expected.

- [ ] **Step 1: Run backend regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -v
```

Expected: PASS. Backend should remain unchanged for 2C-1.

- [ ] **Step 2: Run frontend unit tests**

Run:

```powershell
Push-Location frontend
npm test -- --run
Pop-Location
```

Expected: PASS.

- [ ] **Step 3: Run frontend typecheck**

Run:

```powershell
Push-Location frontend
npm run typecheck
Pop-Location
```

Expected: PASS.

- [ ] **Step 4: Run frontend build**

Run:

```powershell
Push-Location frontend
npm run build
Pop-Location
```

Expected: PASS.

- [ ] **Step 5: Run Playwright E2E**

Run:

```powershell
Push-Location frontend
npm run test:e2e
Pop-Location
```

Expected: PASS.

- [ ] **Step 6: Record any failures honestly**

If a command fails, do not mark 2C-1 complete. Capture:

```text
Command:
Result: FAIL
Relevant output:
Next fix:
```

- [ ] **Step 7: Commit checkpoint only if commits are authorized**

If authorized and all validation passes:

```powershell
git add frontend/src frontend/e2e
git commit -m "feat: complete fake half-duplex voice turn"
```

Otherwise skip.

---

## Task 9: Update documentation after validation

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Optional create: `docs/stage2c-half-duplex-voice-turn.md`

- [ ] **Step 1: Update README with user-facing 2C-1 behavior**

Add a short Stage 2 status note in `README.md` after the existing voice status section:

```md
### Stage 2C-1 fake half-duplex voice turn

The app supports a fake-provider half-duplex voice-turn baseline:

1. Record with the manual microphone UI.
2. Review the ASR transcript.
3. Click `发送并朗读` to send the transcript through the existing text-chat path.
4. The matching assistant reply is synthesized through the existing TTS path and played back.

This baseline keeps confirmation explicit, keeps text chat usable, and does not add VAD, interruption, streaming, long-term memory, or emotion. Real-provider full-turn validation is tracked separately as 2C-2 unless explicitly recorded below.
```

- [ ] **Step 2: Create evidence doc if real smoke is not run in this implementation task**

If real-provider full-turn smoke is deferred, create `docs/stage2c-half-duplex-voice-turn.md`:

```md
# Stage 2C Half-Duplex Voice Turn Evidence

## 2C-1 Fake-provider baseline

Status: COMPLETED only if the validation commands below passed.

Validation:

| Command | Result |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest backend/tests -v` | PASS/FAIL |
| `npm test -- --run` | PASS/FAIL |
| `npm run typecheck` | PASS/FAIL |
| `npm run build` | PASS/FAIL |
| `npm run test:e2e` | PASS/FAIL |

Behavior verified:

- Pending transcript can be sent with `发送并朗读`.
- The app selects the assistant message produced by that send using a stable post-send rule.
- TTS failure after chat success keeps text messages visible.
- Recording and playback/synthesis are mutually exclusive.
- Session switch/create/delete clears stale voice-turn state.

## 2C-2 Real-provider full-turn smoke

Status: NOT COMPLETED unless a real FasterWhisper + real text provider + CosyVoice HTTP browser smoke is recorded here.

Reason if deferred: fake-provider baseline was implemented first to stabilize UX and tests before running heavy local model smoke.
```

Replace `PASS/FAIL` with actual observed results before saving. Do not write PASS unless the command actually passed.

- [ ] **Step 3: Update CLAUDE.md accurately**

If only fake-provider 2C-1 passes and real-provider smoke is deferred, update `CLAUDE.md` with wording like:

```md
- 子任务 2C-1：Fake-provider full half-duplex voice turn baseline 已完成（日期；后端/前端/typecheck/build/E2E 验证结果）。实现前端编排 ASR → 显式 `发送并朗读` → 现有文本对话 → TTS 播放；稳定匹配本轮 assistant message；TTS 失败不丢失文字回复；录音与播放/合成互斥；session 切换清理 stale voice state。真实 FasterWhisper + DeepSeek + CosyVoice HTTP full-turn smoke 尚未完成，完整 2C 仍未关闭。
```

Do not change Stage 3 or Stage 4 status.

- [ ] **Step 4: Run documentation grep checks**

Run:

```powershell
git diff -- README.md CLAUDE.md docs/stage2c-half-duplex-voice-turn.md
```

Expected: diff states exactly what passed and what remains incomplete. It must not claim full 2C completion unless real-provider full-turn smoke passed.

- [ ] **Step 5: Commit documentation only if commits are authorized**

If authorized:

```powershell
git add README.md CLAUDE.md docs/stage2c-half-duplex-voice-turn.md
git commit -m "docs: record fake half-duplex voice turn baseline"
```

Otherwise skip.

---

## Task 10: Optional real-provider 2C-2 smoke planning gate

**Files:**
- No code changes in this task unless the smoke script is explicitly requested.

- [ ] **Step 1: Confirm fake-provider 2C-1 is stable**

Before running heavy local providers, confirm Task 8 passed. If Task 8 did not pass, stop here and fix fake-provider issues first.

- [ ] **Step 2: Prepare real provider environment manually**

Use existing documented local setup. Do not commit `.env`, model paths, private recordings, or secrets.

Expected local configuration categories:

```powershell
$env:ASR_PROVIDER = "faster-whisper"
$env:TTS_PROVIDER = "cosyvoice-http"
$env:LLM_PROVIDER = "deepseek"
```

Also set existing local model path and provider-specific environment variables according to the already recorded 2B-6 and 2B-7 docs.

- [ ] **Step 3: Run one real browser UI smoke**

Manual criteria:

```text
1. Start FastAPI with FasterWhisper ASR and CosyVoice HTTP TTS configured.
2. Start frontend.
3. Record a non-private Chinese test utterance.
4. Confirm transcript appears.
5. Click 发送并朗读.
6. Confirm user and assistant text messages appear.
7. Confirm assistant audio plays or TTS failure is clearly reported without losing text.
8. Record browser console error count.
```

- [ ] **Step 4: Update evidence only after real smoke**

If this smoke passes, update `docs/stage2c-half-duplex-voice-turn.md` and `CLAUDE.md` to record exact commands, providers, observed result, and remaining Stage 2 items. If it fails, record the failure and keep full 2C incomplete.

---

## Self-review

### Spec coverage

- Explicit `发送并朗读`: Tasks 3 and 4.
- Frontend orchestration, no `/voice-turns`: Tasks 4 and 9; no backend tasks added.
- Stable post-send assistant matching: Task 1 and Task 4.
- Global audio busy state: Task 2 and Task 5.
- Session switch/create/delete stale cleanup: Task 5 and Task 9.
- Fake-provider automated validation: Tasks 7 and 8.
- TTS failure preserves text reply: Task 6.
- Stage 3/4 boundary: Task 9 docs wording and no memory/emotion files touched.
- Real full-turn smoke separated as 2C-2: Task 10.

### Red-flag scan

This plan intentionally avoids unfinished markers and vague instructions. Each code-changing task includes concrete code snippets and exact commands.

### Type consistency

- `findAssistantReplyForVoiceTurn()` is defined in Task 1 and imported by `App.tsx` in Task 4.
- `audioController.isAudioBusy` is defined in Task 2 and consumed in Task 5.
- `audioController.play()` returns `Promise<boolean>` in Task 2 and is awaited in Task 4.
- `onSendAndSpeakTranscript`, `voiceTurnBusy`, and `voiceTurnError` are added to `MessageInput` and threaded through `ChatLayout` in Task 3.

### Commit policy note

The writing-plans process prefers frequent commits, but this Claude Code session must not commit unless the user explicitly authorizes commits. Every commit step is therefore conditional.
