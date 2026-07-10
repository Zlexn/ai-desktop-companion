import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';

const originalFetch = globalThis.fetch;
const originalCreateObjectUrl = URL.createObjectURL;
const originalRevokeObjectUrl = URL.revokeObjectURL;
const originalPlay = HTMLMediaElement.prototype.play;
const originalPause = HTMLMediaElement.prototype.pause;
const originalSetSinkId = HTMLMediaElement.prototype.setSinkId;

let latestVadSpeechEnd: (() => void) | null = null;
let latestVadStop: ReturnType<typeof vi.fn> | null = null;

vi.mock('./voiceActivity/createSileroVad', () => ({
  createSileroVad: vi.fn(async ({ onSpeechEnd }: { onSpeechEnd: () => void }) => {
    latestVadSpeechEnd = onSpeechEnd;
    latestVadStop = vi.fn().mockResolvedValue(undefined);
    return {
      start: vi.fn().mockResolvedValue(undefined),
      stop: latestVadStop,
    };
  }),
}));

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function wavResponse(): Response {
  return new Response(new Uint8Array([82, 73, 70, 70, 0, 0, 0, 0, 87, 65, 86, 69]), {
    status: 200,
    headers: {
      'Content-Type': 'audio/wav',
      'X-TTS-Provider': 'fake',
      'X-TTS-Model': 'fake-tone-v1',
    },
  });
}

function speechStreamResponse(): Response {
  const bytes = new TextEncoder().encode('RIFF....WAVE');
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  const body = [
    JSON.stringify({ type: 'start', provider: 'fake', model: 'fake-tone-v1' }),
    JSON.stringify({
      type: 'segment',
      index: 0,
      audio_base64: btoa(binary),
      media_type: 'audio/wav',
      duration_ms: 100,
      sample_rate: 16000,
    }),
    JSON.stringify({ type: 'done', segment_count: 1 }),
    '',
  ].join('\n');
  return new Response(body, { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } });
}

function transcriptionStreamResponse(text: string, partial = '语音'): Response {
  const body = [
    JSON.stringify({ type: 'start', provider: 'fake', model: 'fake-asr-v1' }),
    JSON.stringify({ type: 'partial', index: 0, text: partial, is_final: false, audio_ms: 1000 }),
    JSON.stringify({ type: 'final', text, detected_language: 'zh', duration_ms: 1000, provider: 'fake-asr', model: 'fake', inference_ms: 1 }),
    JSON.stringify({ type: 'done' }),
    '',
  ].join('\n');
  return new Response(body, { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } });
}

function mockFetchTranscription(text: string) {
  vi.mocked(fetch).mockResolvedValueOnce(transcriptionStreamResponse(text));
}

describe('App', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn();
    latestVadSpeechEnd = null;
    latestVadStop = null;
  });

  afterEach(() => {
    cleanup();
    globalThis.fetch = originalFetch;
    URL.createObjectURL = originalCreateObjectUrl;
    URL.revokeObjectURL = originalRevokeObjectUrl;
    HTMLMediaElement.prototype.play = originalPlay;
    HTMLMediaElement.prototype.pause = originalPause;
    if (originalSetSinkId) {
      Object.defineProperty(HTMLMediaElement.prototype, 'setSinkId', {
        configurable: true,
        value: originalSetSinkId,
      });
    } else {
      delete (HTMLMediaElement.prototype as Partial<HTMLMediaElement>).setSinkId;
    }
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it('creates a session and sends a message', async () => {
    const user = userEvent.setup();
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse({ id: 's1', title: '新会话', created_at: '', updated_at: '' }, 201))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse({ reply: '我听见了：你好。', metadata: { provider: 'fake', model: 'test' } }))
      .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '' }]))
      .mockResolvedValueOnce(jsonResponse([
        { id: 'm1', session_id: 's1', role: 'user', content: '你好', created_at: '', metadata: {} },
        { id: 'm2', session_id: 's1', role: 'assistant', content: '我听见了：你好。', created_at: '', metadata: {} },
      ]));

    render(<App />);
    await user.click(await screen.findByRole('button', { name: '新建会话' }));
    await user.type(await screen.findByLabelText('输入消息'), '你好');
    await user.click(screen.getByRole('button', { name: '发送' }));

    await waitFor(() => expect(screen.getByText('我听见了：你好。')).toBeInTheDocument());
  });

  it('shows understandable backend errors', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ error: { message: '模型服务暂时不可用，请稍后重试。' } }, 502),
    );

    render(<App />);

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('模型服务暂时不可用，请稍后重试。'));
  });

  it('loads existing memories on startup', async () => {
    vi.stubEnv('VITE_ENABLE_MEMORY_LOAD_IN_TEST', '1');
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse([
        {
          id: 'mem-existing',
          content: '用户正在构建本地 AI 桌宠。',
          memory_type: 'long_term_goal',
          source: 'manual',
          source_session_id: null,
          importance: 5,
          confidence: 1,
          status: 'active',
          created_at: '2026-07-06T00:00:00Z',
          updated_at: '2026-07-06T00:00:00Z',
          metadata: {},
        },
      ]))
      .mockResolvedValueOnce(jsonResponse([]));

    render(<App />);

    expect(await screen.findByText('用户正在构建本地 AI 桌宠。')).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input) === '/api/memories')).toBe(true);
  });

  it('loads pending memory candidates on startup when memory loading is enabled', async () => {
    vi.stubEnv('VITE_ENABLE_MEMORY_LOAD_IN_TEST', '1');
    const candidate = {
      id: 'c1',
      content: '用户喜欢红茶。',
      memory_type: 'preference',
      source: 'candidate',
      source_session_id: 's1',
      importance: 3,
      confidence: 0.7,
      status: 'pending',
      created_at: '2026-07-06T00:00:00Z',
      updated_at: '2026-07-06T00:00:00Z',
      metadata: {},
    };
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse([candidate]));

    render(<App />);

    expect(await screen.findByText('用户喜欢红茶。')).toBeInTheDocument();
    expect(screen.getByText('待确认记忆')).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input) === '/api/memories?status_filter=pending')).toBe(true);
  });

  it('confirms a pending memory candidate and moves it into active memories', async () => {
    vi.stubEnv('VITE_ENABLE_MEMORY_LOAD_IN_TEST', '1');
    const candidate = {
      id: 'c1',
      content: '用户喜欢红茶。',
      memory_type: 'preference',
      source: 'candidate',
      source_session_id: 's1',
      importance: 3,
      confidence: 0.7,
      status: 'pending',
      created_at: '2026-07-06T00:00:00Z',
      updated_at: '2026-07-06T00:00:00Z',
      metadata: {},
    };
    const confirmed = { ...candidate, status: 'active', metadata: { confirmed_at: '2026-07-06T00:00:01Z' } };
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse([candidate]))
      .mockResolvedValueOnce(jsonResponse({ memory: confirmed, conflicts: [] }));

    const user = userEvent.setup();
    render(<App />);
    await screen.findByText('用户喜欢红茶。');
    await user.click(screen.getByRole('button', { name: '保存为长期记忆' }));

    expect(fetch).toHaveBeenCalledWith('/api/memories/c1/confirm', expect.objectContaining({ method: 'POST' }));
    await waitFor(() => expect(screen.queryByText('暂无长期记忆。')).not.toBeInTheDocument());
  });

  it('shows memory panel and creates a manual memory without blocking chat setup', async () => {
    const user = userEvent.setup();
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse({
        memory: {
          id: 'mem-1',
          content: '用户偏好中文回复。',
          memory_type: 'preference',
          source: 'manual',
          source_session_id: null,
          importance: 3,
          confidence: 1,
          status: 'active',
          created_at: '2026-07-06T00:00:00Z',
          updated_at: '2026-07-06T00:00:00Z',
          metadata: {},
        },
        conflicts: [],
      }, 201));

    render(<App />);

    expect(await screen.findByText('长期记忆')).toBeInTheDocument();
    expect(screen.getByText(/聊天记录不会自动变成长期记忆/)).toBeInTheDocument();
    await user.type(screen.getByLabelText('记忆内容'), '用户偏好中文回复。');
    await user.click(screen.getByRole('button', { name: '保存记忆' }));

    await waitFor(() => expect(screen.getByText('用户偏好中文回复。')).toBeInTheDocument());
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input) === '/api/memories')).toBe(true);
  });

  it('offers send-and-speak for a pending transcript', async () => {
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

    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '' }]))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(transcriptionStreamResponse('语音转写文本'));

    render(<App />);
    await user.click(await screen.findByRole('button', { name: '开始录音' }));
    await new Promise((resolve) => setTimeout(resolve, 350));
    await user.click(await screen.findByRole('button', { name: '停止录音' }));

    expect(await screen.findByRole('button', { name: '发送并朗读' })).toBeInTheDocument();
  });

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
    expect(await screen.findByLabelText('麦克风')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '刷新设备' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: '系统默认麦克风' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'USB Mic' })).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText('麦克风'), 'usb-mic');
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

  it('shows VAD auto-stop status while recording when VAD is active', async () => {
    vi.stubEnv('VITE_ENABLE_FAKE_VAD_IN_TEST', '1');
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

    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '' }]))
      .mockResolvedValueOnce(jsonResponse([]));

    render(<App />);
    await user.click(await screen.findByRole('button', { name: '开始录音' }));

    expect(await screen.findByText('正在监听语音结束')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '停止录音' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '取消录音' })).toBeInTheDocument();
  });

  it('VAD speech end auto-stops recording and produces pending transcript', async () => {
    vi.stubEnv('VITE_ENABLE_FAKE_VAD_IN_TEST', '1');
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

    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '' }]))
      .mockResolvedValueOnce(jsonResponse([]));
    mockFetchTranscription('这是 VAD 自动停止后的转写。');

    render(<App />);
    await user.click(await screen.findByRole('button', { name: '开始录音' }));
    expect(await screen.findByText('正在监听语音结束')).toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 350));

    act(() => {
      latestVadSpeechEnd?.();
    });

    expect(await screen.findByText('转写待确认：这是 VAD 自动停止后的转写。')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '发送并朗读' })).toBeInTheDocument();
  });

  it('manual stop cleans up VAD and prevents duplicate auto-stop', async () => {
    vi.stubEnv('VITE_ENABLE_FAKE_VAD_IN_TEST', '1');
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

    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '' }]))
      .mockResolvedValueOnce(jsonResponse([]));
    mockFetchTranscription('手动停止优先。');

    render(<App />);
    await user.click(await screen.findByRole('button', { name: '开始录音' }));
    await new Promise((resolve) => setTimeout(resolve, 350));
    await user.click(await screen.findByRole('button', { name: '停止录音' }));

    await screen.findByText('转写待确认：手动停止优先。');
    expect(latestVadStop).toHaveBeenCalled();

    act(() => {
      latestVadSpeechEnd?.();
    });

    expect(screen.getByText('转写待确认：手动停止优先。')).toBeInTheDocument();
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(3);
  });

  it('cancel recording stops VAD and does not upload after later speech end', async () => {
    vi.stubEnv('VITE_ENABLE_FAKE_VAD_IN_TEST', '1');
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

    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '' }]))
      .mockResolvedValueOnce(jsonResponse([]));

    render(<App />);
    await user.click(await screen.findByRole('button', { name: '开始录音' }));
    await user.click(await screen.findByRole('button', { name: '取消录音' }));

    expect(latestVadStop).toHaveBeenCalled();

    act(() => {
      latestVadSpeechEnd?.();
    });

    expect(screen.getByRole('button', { name: '开始录音' })).toBeInTheDocument();
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(2);
  });

  it('sends a pending transcript and auto-plays the matching assistant reply', async () => {
    const user = userEvent.setup();
    URL.createObjectURL = vi.fn(() => 'blob:tts-audio');
    URL.revokeObjectURL = vi.fn();
    const playMock = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);

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

    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '' }]))
      .mockResolvedValueOnce(jsonResponse([
        { id: 'old-u', session_id: 's1', role: 'user', content: '旧消息', created_at: '1', metadata: {} },
        { id: 'old-a', session_id: 's1', role: 'assistant', content: '旧回复', created_at: '2', metadata: {} },
      ]))
      .mockResolvedValueOnce(transcriptionStreamResponse('语音转写文本'))
      .mockResolvedValueOnce(jsonResponse({ reply: '语音回合回复', metadata: { provider: 'fake', model: 'test' } }))
      .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '3' }]))
      .mockResolvedValueOnce(jsonResponse([
        { id: 'old-u', session_id: 's1', role: 'user', content: '旧消息', created_at: '1', metadata: {} },
        { id: 'old-a', session_id: 's1', role: 'assistant', content: '旧回复', created_at: '2', metadata: {} },
        { id: 'new-u', session_id: 's1', role: 'user', content: '语音转写文本', created_at: '3', metadata: {} },
        { id: 'new-a', session_id: 's1', role: 'assistant', content: '语音回合回复', created_at: '4', metadata: {} },
      ]))
      .mockResolvedValueOnce(speechStreamResponse());

    render(<App />);
    await user.click(await screen.findByRole('button', { name: '开始录音' }));
    await new Promise((resolve) => setTimeout(resolve, 350));
    await user.click(await screen.findByRole('button', { name: '停止录音' }));
    await user.click(await screen.findByRole('button', { name: '发送并朗读' }));

    await waitFor(() => expect(screen.getByText('语音回合回复')).toBeInTheDocument());
    await waitFor(() => expect(playMock).toHaveBeenCalledTimes(1));
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input) === '/api/audio/speech/stream')).toBe(true);
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input) === '/api/audio/speech')).toBe(false);
  });

  it('allows recording to explicitly interrupt assistant audio synthesis', async () => {
    vi.stubEnv('VITE_ENABLE_FAKE_VAD_IN_TEST', '1');
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
    expect(screen.getByText('点击开始录音会停止当前朗读')).toBeInTheDocument();

    await user.click(recordButton);

    expect(await screen.findByRole('button', { name: '停止录音' })).toBeInTheDocument();
    expect(screen.getByText('正在监听语音结束')).toBeInTheDocument();

    resolveSpeech(wavResponse());
    await waitFor(() => expect(screen.queryByText('生成中…')).not.toBeInTheDocument());
  });

  it('clears pending transcript when switching sessions', async () => {
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

    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse([
        { id: 's1', title: '会话一', created_at: '', updated_at: '2' },
        { id: 's2', title: '会话二', created_at: '', updated_at: '1' },
      ]))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(transcriptionStreamResponse('语音转写文本'))
      .mockResolvedValueOnce(jsonResponse([]));

    render(<App />);
    await user.click(await screen.findByRole('button', { name: '开始录音' }));
    await new Promise((resolve) => setTimeout(resolve, 350));
    await user.click(await screen.findByRole('button', { name: '停止录音' }));
    expect(await screen.findByText('转写待确认：语音转写文本')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '会话二' }));
    await waitFor(() => expect(screen.queryByText('转写待确认：语音转写文本')).not.toBeInTheDocument());
  });

  it('keeps text reply visible when voice-turn TTS fails', async () => {
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

    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '' }]))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(transcriptionStreamResponse('语音转写文本'))
      .mockResolvedValueOnce(jsonResponse({ reply: '文字回复已经生成', metadata: { provider: 'fake', model: 'test' } }))
      .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '3' }]))
      .mockResolvedValueOnce(jsonResponse([
        { id: 'u1', session_id: 's1', role: 'user', content: '语音转写文本', created_at: '1', metadata: {} },
        { id: 'a1', session_id: 's1', role: 'assistant', content: '文字回复已经生成', created_at: '2', metadata: {} },
      ]))
      .mockResolvedValueOnce(jsonResponse({ error: { message: '语音合成服务暂时不可用，请稍后重试。' } }, 502));

    render(<App />);
    await user.click(await screen.findByRole('button', { name: '开始录音' }));
    await new Promise((resolve) => setTimeout(resolve, 350));
    await user.click(await screen.findByRole('button', { name: '停止录音' }));
    await user.click(await screen.findByRole('button', { name: '发送并朗读' }));

    expect(await screen.findByText('文字回复已经生成')).toBeInTheDocument();
    expect(await screen.findByText('文字回复已生成，但语音合成或播放失败。可稍后重试播放。')).toBeInTheDocument();
  });

  it('starts a new recording when user interrupts send-and-speak TTS', async () => {
    vi.stubEnv('VITE_ENABLE_FAKE_VAD_IN_TEST', '1');
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
      .mockResolvedValueOnce(transcriptionStreamResponse('第一轮语音'))
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
      .mockResolvedValueOnce(transcriptionStreamResponse('语音转写文本'))
      .mockReturnValueOnce(new Promise<Response>((resolve) => { resolveChat = resolve; }));

    render(<App />);
    await user.click(await screen.findByRole('button', { name: '开始录音' }));
    await new Promise((resolve) => setTimeout(resolve, 350));
    await user.click(await screen.findByRole('button', { name: '停止录音' }));
    await user.click(await screen.findByRole('button', { name: '发送并朗读' }));

    expect(await screen.findByRole('button', { name: '发送并朗读' })).toHaveTextContent('发送并朗读中…');
    expect(screen.queryByRole('button', { name: '开始录音' })).not.toBeInTheDocument();

    resolveChat(jsonResponse({ reply: '回复', metadata: { provider: 'fake', model: 'test' } }));
  });

  it('does not duplicate voice-turn chat sends on repeated clicks', async () => {
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
      .mockResolvedValueOnce(transcriptionStreamResponse('语音转写文本'))
      .mockReturnValueOnce(new Promise<Response>((resolve) => { resolveChat = resolve; }))
      .mockResolvedValueOnce(jsonResponse([{ id: 's1', title: '新会话', created_at: '', updated_at: '3' }]))
      .mockResolvedValueOnce(jsonResponse([
        { id: 'u1', session_id: 's1', role: 'user', content: '语音转写文本', created_at: '1', metadata: {} },
        { id: 'a1', session_id: 's1', role: 'assistant', content: '回复', created_at: '2', metadata: {} },
      ]))
      .mockResolvedValueOnce(wavResponse());

    render(<App />);
    await user.click(await screen.findByRole('button', { name: '开始录音' }));
    await new Promise((resolve) => setTimeout(resolve, 350));
    await user.click(await screen.findByRole('button', { name: '停止录音' }));
    const button = await screen.findByRole('button', { name: '发送并朗读' });

    await Promise.all([user.click(button), user.click(button)]);
    resolveChat(jsonResponse({ reply: '回复', metadata: { provider: 'fake', model: 'test' } }));

    await waitFor(() => {
      const chatCalls = vi.mocked(fetch).mock.calls.filter(([input, init]) =>
        String(input) === '/api/sessions/s1/messages' && init?.method === 'POST',
      );
      expect(chatCalls).toHaveLength(1);
    });
  });

  it('ignores stale voice-turn results after switching sessions before refresh completes', async () => {
    const user = userEvent.setup();
    URL.createObjectURL = vi.fn(() => 'blob:tts-audio');
    URL.revokeObjectURL = vi.fn();

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

    let resolveSessionsAfterSend: (response: Response) => void = () => undefined;
    let resolveMessagesAfterSend: (response: Response) => void = () => undefined;
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse([
        { id: 's1', title: '会话一', created_at: '', updated_at: '2' },
        { id: 's2', title: '会话二', created_at: '', updated_at: '1' },
      ]))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(transcriptionStreamResponse('语音转写文本'))
      .mockResolvedValueOnce(jsonResponse({ reply: '旧会话回复', metadata: { provider: 'fake', model: 'test' } }))
      .mockReturnValueOnce(new Promise<Response>((resolve) => { resolveSessionsAfterSend = resolve; }))
      .mockReturnValueOnce(new Promise<Response>((resolve) => { resolveMessagesAfterSend = resolve; }))
      .mockResolvedValueOnce(jsonResponse([
        { id: 's2-u1', session_id: 's2', role: 'user', content: '会话二消息', created_at: '1', metadata: {} },
      ]));

    render(<App />);
    await user.click(await screen.findByRole('button', { name: '开始录音' }));
    await new Promise((resolve) => setTimeout(resolve, 350));
    await user.click(await screen.findByRole('button', { name: '停止录音' }));
    await user.click(await screen.findByRole('button', { name: '发送并朗读' }));
    await user.click(screen.getByRole('button', { name: '会话二' }));

    resolveSessionsAfterSend(jsonResponse([
      { id: 's1', title: '会话一', created_at: '', updated_at: '3' },
      { id: 's2', title: '会话二', created_at: '', updated_at: '1' },
    ]));
    resolveMessagesAfterSend(jsonResponse([
      { id: 'u1', session_id: 's1', role: 'user', content: '语音转写文本', created_at: '1', metadata: {} },
      { id: 'a1', session_id: 's1', role: 'assistant', content: '旧会话回复', created_at: '2', metadata: {} },
    ]));

    await waitFor(() => expect(screen.getByRole('heading', { name: '会话二' })).toBeInTheDocument());
    expect(screen.queryByText('旧会话回复')).not.toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input) === '/api/audio/speech')).toBe(false);
  });

  it('ignores stale voice-turn results after switching away and back to the same session', async () => {
    const user = userEvent.setup();
    URL.createObjectURL = vi.fn(() => 'blob:tts-audio');
    URL.revokeObjectURL = vi.fn();

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

    let resolveSessionsAfterSend: (response: Response) => void = () => undefined;
    let resolveMessagesAfterSend: (response: Response) => void = () => undefined;
    vi.mocked(fetch)
      .mockResolvedValueOnce(jsonResponse([
        { id: 's1', title: '会话一', created_at: '', updated_at: '2' },
        { id: 's2', title: '会话二', created_at: '', updated_at: '1' },
      ]))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(transcriptionStreamResponse('语音转写文本'))
      .mockResolvedValueOnce(jsonResponse({ reply: '旧会话回复', metadata: { provider: 'fake', model: 'test' } }))
      .mockReturnValueOnce(new Promise<Response>((resolve) => { resolveSessionsAfterSend = resolve; }))
      .mockReturnValueOnce(new Promise<Response>((resolve) => { resolveMessagesAfterSend = resolve; }))
      .mockResolvedValueOnce(jsonResponse([{ id: 's2-u1', session_id: 's2', role: 'user', content: '会话二消息', created_at: '1', metadata: {} }]))
      .mockResolvedValueOnce(jsonResponse([]));

    render(<App />);
    await user.click(await screen.findByRole('button', { name: '开始录音' }));
    await new Promise((resolve) => setTimeout(resolve, 350));
    await user.click(await screen.findByRole('button', { name: '停止录音' }));
    await user.click(await screen.findByRole('button', { name: '发送并朗读' }));
    await user.click(screen.getByRole('button', { name: '会话二' }));
    await user.click(screen.getByRole('button', { name: '会话一' }));

    resolveSessionsAfterSend(jsonResponse([
      { id: 's1', title: '会话一', created_at: '', updated_at: '3' },
      { id: 's2', title: '会话二', created_at: '', updated_at: '1' },
    ]));
    resolveMessagesAfterSend(jsonResponse([
      { id: 'u1', session_id: 's1', role: 'user', content: '语音转写文本', created_at: '1', metadata: {} },
      { id: 'a1', session_id: 's1', role: 'assistant', content: '旧会话回复', created_at: '2', metadata: {} },
    ]));

    await waitFor(() => expect(screen.getByRole('heading', { name: '会话一' })).toBeInTheDocument());
    expect(screen.queryByText('旧会话回复')).not.toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input) === '/api/audio/speech')).toBe(false);
  });

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
});
