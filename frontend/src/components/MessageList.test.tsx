import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Message } from '../api/types';
import { useAudioPlaybackController } from '../hooks/useAudioPlaybackController';
import { MessageList } from './MessageList';

const originalFetch = globalThis.fetch;
const originalCreateObjectUrl = URL.createObjectURL;
const originalRevokeObjectUrl = URL.revokeObjectURL;
const originalPlay = HTMLMediaElement.prototype.play;
const originalPause = HTMLMediaElement.prototype.pause;
const originalSetSinkId = HTMLMediaElement.prototype.setSinkId;

const messages: Message[] = [
  { id: 'u1', session_id: 's1', role: 'user', content: '你好', created_at: '', metadata: {} },
  { id: 'a1', session_id: 's1', role: 'assistant', content: '我听见了：你好', created_at: '', metadata: {} },
  { id: 'a2', session_id: 's1', role: 'assistant', content: '第二条回复', created_at: '', metadata: {} },
];

function wavResponse(status = 200): Response {
  return new Response(new Uint8Array([82, 73, 70, 70, 0, 0, 0, 0, 87, 65, 86, 69]), {
    status,
    headers: {
      'Content-Type': 'audio/wav',
      'X-TTS-Provider': 'fake',
      'X-TTS-Model': 'fake-tone-v1',
      'X-Audio-Duration-Ms': '240',
      'X-Audio-Sample-Rate': '16000',
    },
  });
}

function errorResponse(message: string): Response {
  return new Response(JSON.stringify({ error: { message } }), { status: 502, headers: { 'Content-Type': 'application/json' } });
}

function segmentLine(index: number, label: string): string {
  const bytes = new TextEncoder().encode(`RIFF....WAVE${label}`);
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return JSON.stringify({
    type: 'segment',
    index,
    audio_base64: btoa(binary),
    media_type: 'audio/wav',
    duration_ms: 100,
    sample_rate: 16000,
  }) + '\n';
}

function Harness({ items = messages }: { items?: Message[] }) {
  const audioController = useAudioPlaybackController();
  return <MessageList messages={items} audioController={audioController} playbackBlocked={false} />;
}

function OutputHarness({ outputDeviceId }: { outputDeviceId: string }) {
  const audioController = useAudioPlaybackController({ audioOutputDeviceId: outputDeviceId });
  return <MessageList messages={messages} audioController={audioController} playbackBlocked={false} />;
}

describe('MessageList audio controls', () => {
  let playMock: ReturnType<typeof vi.fn<() => Promise<void>>>;
  let pauseMock: ReturnType<typeof vi.fn<() => void>>;

  beforeEach(() => {
    globalThis.fetch = vi.fn();
    URL.createObjectURL = vi.fn(() => 'blob:tts-audio');
    URL.revokeObjectURL = vi.fn();
    playMock = vi.fn().mockResolvedValue(undefined);
    pauseMock = vi.fn();
    HTMLMediaElement.prototype.play = playMock;
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(pauseMock);
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
    vi.restoreAllMocks();
  });

  it('shows playback controls only for assistant messages and does not autoplay', () => {
    render(<Harness />);

    expect(screen.getByText('你好')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: '播放' })).toHaveLength(2);
    expect(fetch).not.toHaveBeenCalled();
    expect(playMock).not.toHaveBeenCalled();
  });

  it('binds historical playback and retry to the persisted assistant ID', async () => {
    const user = userEvent.setup();
    vi.mocked(fetch)
      .mockResolvedValueOnce(errorResponse('暂时失败'))
      .mockResolvedValueOnce(wavResponse());
    render(<Harness />);

    await user.click(screen.getAllByRole('button', { name: '播放' })[0]);
    expect(await screen.findByText('暂时失败')).toBeInTheDocument();
    expect(screen.getAllByText('我听见了：你好').length).toBeGreaterThan(0);
    await user.click(screen.getAllByRole('button', { name: '播放' })[0]);

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    for (const [url, init] of vi.mocked(fetch).mock.calls) {
      expect(url).toBe('/api/messages/a1/speech');
      expect(String(init?.body)).not.toContain('text');
      expect(String(init?.body)).not.toContain('我听见了：你好');
    }
  });

  it('synthesizes once, creates a Blob URL, and enters playback state', async () => {
    const user = userEvent.setup();
    let resolveResponse: (response: Response) => void = () => undefined;
    vi.mocked(fetch).mockReturnValueOnce(new Promise<Response>((resolve) => { resolveResponse = resolve; }));
    render(<Harness />);

    const firstPlay = screen.getAllByRole('button', { name: '播放' })[0];
    await user.click(firstPlay);

    expect(screen.getByRole('button', { name: '生成中…' })).toBeDisabled();
    resolveResponse(wavResponse());
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(playMock).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole('button', { name: '暂停' })).toBeInTheDocument();
  });

  it('does not create duplicate requests during rapid repeated clicks', async () => {
    const user = userEvent.setup();
    let resolveResponse: (response: Response) => void = () => undefined;
    vi.mocked(fetch).mockReturnValueOnce(new Promise<Response>((resolve) => { resolveResponse = resolve; }));
    render(<Harness />);

    const firstPlay = screen.getAllByRole('button', { name: '播放' })[0];
    await Promise.all([user.click(firstPlay), user.click(firstPlay)]);
    resolveResponse(wavResponse());

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  });

  it('converts play rejection into a visible error', async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockResolvedValueOnce(wavResponse());
    playMock.mockRejectedValueOnce(new Error('浏览器拒绝播放'));
    render(<Harness />);

    await user.click(screen.getAllByRole('button', { name: '播放' })[0]);

    expect(await screen.findByText('浏览器拒绝播放')).toBeInTheDocument();
  });

  it('pauses, resumes, stops, and replays existing audio', async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockResolvedValueOnce(wavResponse());
    render(<Harness />);

    await user.click(screen.getAllByRole('button', { name: '播放' })[0]);
    await user.click(await screen.findByRole('button', { name: '暂停' }));
    expect(pauseMock).toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: '继续' }));
    await waitFor(() => expect(playMock).toHaveBeenCalledTimes(2));
    await user.click(screen.getByRole('button', { name: '停止' }));
    expect(pauseMock).toHaveBeenCalledTimes(2);
    await user.click(screen.getByRole('button', { name: '重播' }));
    await waitFor(() => expect(playMock).toHaveBeenCalledTimes(3));
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('stops the current message before playing another one', async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockResolvedValueOnce(wavResponse()).mockResolvedValueOnce(wavResponse());
    render(<Harness />);

    await user.click(screen.getAllByRole('button', { name: '播放' })[0]);
    await screen.findByRole('button', { name: '暂停' });
    await user.click(screen.getAllByRole('button', { name: '播放' })[0]);

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(pauseMock).toHaveBeenCalled();
  });

  it('aborts an old request and prevents stale state after unmount', async () => {
    const user = userEvent.setup();
    let capturedSignal: AbortSignal | undefined;
    vi.mocked(fetch).mockImplementationOnce((_input, init) => {
      capturedSignal = init?.signal as AbortSignal;
      return new Promise<Response>(() => undefined);
    });
    const { unmount } = render(<Harness />);

    await user.click(screen.getAllByRole('button', { name: '播放' })[0]);
    unmount();

    await waitFor(() => expect(capturedSignal?.aborted).toBe(true));
  });

  it('revokes Blob URLs on unmount', async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockResolvedValueOnce(wavResponse());
    const { unmount } = render(<Harness />);

    await user.click(screen.getAllByRole('button', { name: '播放' })[0]);
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalled());
    unmount();

    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:tts-audio');
  });

  it('keeps text messages visible when TTS fails', async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockResolvedValueOnce(errorResponse('语音合成服务暂时不可用，请稍后重试。'));
    render(<Harness />);

    await user.click(screen.getAllByRole('button', { name: '播放' })[0]);

    expect(await screen.findByText('语音合成服务暂时不可用，请稍后重试。')).toBeInTheDocument();
    expect(screen.getAllByText('我听见了：你好').length).toBeGreaterThan(0);
    expect(screen.getAllByText('第二条回复').length).toBeGreaterThan(0);
  });

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
        <button type="button" onClick={async () => { playResult = await audioController.play('a1'); }}>
          run play
        </button>
      );
    }

    render(<ResultHarness />);
    await userEvent.click(screen.getByRole('button', { name: 'run play' }));

    await waitFor(() => expect(playResult).toBe(false));
  });

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

  it('starts streamed playback after the first segment before stream completion', async () => {
    const user = userEvent.setup();
    let streamController: ReadableStreamDefaultController<Uint8Array> | null = null;
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        streamController = controller;
      },
    });
    vi.mocked(fetch).mockResolvedValueOnce(new Response(stream, {
      status: 200,
      headers: { 'Content-Type': 'application/x-ndjson' },
    }));

    function StreamingHarness() {
      const audioController = useAudioPlaybackController();
      return (
        <button
          type="button"
          onClick={() => {
            void audioController.play('a1', { streaming: true });
          }}
        >
          stream play
        </button>
      );
    }

    render(<StreamingHarness />);
    await user.click(screen.getByRole('button', { name: 'stream play' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/messages/a1/speech/stream', expect.any(Object)));

    const getStreamController = (): ReadableStreamDefaultController<Uint8Array> => {
      if (!streamController) throw new Error('stream controller was not initialized');
      return streamController;
    };

    getStreamController().enqueue(encoder.encode('{"type":"start","provider":"fake","model":"fake-tone-v1"}\n'));
    getStreamController().enqueue(encoder.encode(segmentLine(0, 'first')));

    await waitFor(() => expect(playMock).toHaveBeenCalledTimes(1));
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);

    getStreamController().enqueue(encoder.encode('{"type":"done","segment_count":1}\n'));
    getStreamController().close();
  });

  it('aborts streamed playback and revokes segment URLs when stopped', async () => {
    const user = userEvent.setup();
    let capturedSignal: AbortSignal | undefined;
    let streamController: ReadableStreamDefaultController<Uint8Array> | null = null;
    const encoder = new TextEncoder();
    URL.createObjectURL = vi.fn(() => 'blob:stream-segment');
    vi.mocked(fetch).mockImplementationOnce((_input, init) => {
      capturedSignal = init?.signal as AbortSignal;
      return Promise.resolve(new Response(new ReadableStream<Uint8Array>({
        start(controller) {
          streamController = controller;
        },
      }), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));
    });

    function StreamingHarness() {
      const audioController = useAudioPlaybackController();
      return (
        <>
          <button type="button" onClick={() => { void audioController.play('a1', { streaming: true }); }}>
            stream play
          </button>
          <button type="button" onClick={() => audioController.stop('a1')}>
            stop stream
          </button>
        </>
      );
    }

    render(<StreamingHarness />);
    await user.click(screen.getByRole('button', { name: 'stream play' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/messages/a1/speech/stream', expect.any(Object)));

    const getStreamController = (): ReadableStreamDefaultController<Uint8Array> => {
      if (!streamController) throw new Error('stream controller was not initialized');
      return streamController;
    };
    getStreamController().enqueue(encoder.encode('{"type":"start","provider":"fake","model":"fake-tone-v1"}\n'));
    getStreamController().enqueue(encoder.encode(segmentLine(0, 'first')));
    await waitFor(() => expect(playMock).toHaveBeenCalledTimes(1));

    await user.click(screen.getByRole('button', { name: 'stop stream' }));

    expect(capturedSignal?.aborted).toBe(true);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:stream-segment');
  });

  it('aborts a streamed speech request when first segment playback fails', async () => {
    const user = userEvent.setup();
    let capturedSignal: AbortSignal | undefined;
    const encoder = new TextEncoder();
    URL.createObjectURL = vi.fn(() => 'blob:failed-stream-segment');
    playMock.mockRejectedValueOnce(new DOMException('blocked', 'NotAllowedError'));
    vi.mocked(fetch).mockImplementationOnce((_input, init) => {
      capturedSignal = init?.signal as AbortSignal;
      return Promise.resolve(new Response(new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(encoder.encode('{"type":"start","provider":"fake","model":"fake-tone-v1"}\n'));
          controller.enqueue(encoder.encode(segmentLine(0, 'first')));
        },
      }), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));
    });

    function StreamingHarness() {
      const audioController = useAudioPlaybackController();
      return (
        <button type="button" onClick={() => { void audioController.play('a1', { streaming: true }); }}>
          stream play
        </button>
      );
    }

    render(<StreamingHarness />);
    await user.click(screen.getByRole('button', { name: 'stream play' }));

    await waitFor(() => expect(playMock).toHaveBeenCalledTimes(1));
    expect(capturedSignal?.aborted).toBe(true);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:failed-stream-segment');
  });
});
