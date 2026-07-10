import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createStreamingAudioScheduler } from '../audio/streamingAudioScheduler';
import { useAudioPlaybackController } from './useAudioPlaybackController';

vi.mock('../audio/streamingAudioScheduler', () => ({
  createStreamingAudioScheduler: vi.fn(),
}));

const originalFetch = globalThis.fetch;
const originalCreateObjectUrl = URL.createObjectURL;
const originalRevokeObjectUrl = URL.revokeObjectURL;
const originalPlay = HTMLMediaElement.prototype.play;
const originalPause = HTMLMediaElement.prototype.pause;

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

function baseScheduler() {
  return {
    isSupported: vi.fn(() => true),
    enqueue: vi.fn(async () => ({
      scheduledStartTime: 1,
      scheduledEndTime: 1.1,
      decodedDurationMs: 100,
      queueDepth: 1,
      underrunMs: 0,
    })),
    waitForIdle: vi.fn(async () => undefined),
    pause: vi.fn(async () => undefined),
    resume: vi.fn(async () => undefined),
    stop: vi.fn(),
    dispose: vi.fn(async () => undefined),
  };
}

type MockScheduler = ReturnType<typeof baseScheduler>;

function makeScheduler(overrides: Partial<MockScheduler> = {}): MockScheduler {
  return { ...baseScheduler(), ...overrides };
}

function StreamingHarness({ outputDeviceId = '' }: { outputDeviceId?: string }) {
  const audioController = useAudioPlaybackController({ audioOutputDeviceId: outputDeviceId });
  const state = audioController.stateFor('a1');
  return (
    <>
      <div data-testid="state">{state.state}</div>
      <button type="button" onClick={() => { void audioController.play('a1', '第一句。第二句。', { streaming: true }); }}>
        stream play
      </button>
      <button type="button" onClick={() => audioController.stop('a1')}>
        stop stream
      </button>
      <button type="button" onClick={() => audioController.pause('a1')}>
        pause stream
      </button>
      <button type="button" onClick={() => { void audioController.resume('a1'); }}>
        resume stream
      </button>
    </>
  );
}

describe('useAudioPlaybackController streaming Web Audio integration', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn();
    URL.createObjectURL = vi.fn(() => 'blob:fallback-segment');
    URL.revokeObjectURL = vi.fn();
    HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined);
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(vi.fn());
  });

  afterEach(() => {
    cleanup();
    globalThis.fetch = originalFetch;
    URL.createObjectURL = originalCreateObjectUrl;
    URL.revokeObjectURL = originalRevokeObjectUrl;
    HTMLMediaElement.prototype.play = originalPlay;
    HTMLMediaElement.prototype.pause = originalPause;
    vi.restoreAllMocks();
  });

  it('uses the Web Audio scheduler for streaming TTS segments when supported', async () => {
    const user = userEvent.setup();
    const scheduler = makeScheduler();
    vi.mocked(createStreamingAudioScheduler).mockReturnValueOnce(scheduler);
    const encoder = new TextEncoder();
    vi.mocked(fetch).mockResolvedValueOnce(new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('{"type":"start","provider":"fake","model":"fake-tone-v1"}\n'));
        controller.enqueue(encoder.encode(segmentLine(0, 'first')));
        controller.enqueue(encoder.encode(segmentLine(1, 'second')));
        controller.enqueue(encoder.encode('{"type":"done","segment_count":2}\n'));
        controller.close();
      },
    }), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));

    render(<StreamingHarness />);
    await user.click(screen.getByRole('button', { name: 'stream play' }));

    await waitFor(() => expect(scheduler.enqueue).toHaveBeenCalledTimes(2));
    expect(createStreamingAudioScheduler).toHaveBeenCalledWith({ audioOutputDeviceId: '' });
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    expect(screen.getByTestId('state')).toHaveTextContent(/playing|ready/);
  });

  it('pauses and resumes the Web Audio scheduler for active streaming playback', async () => {
    const user = userEvent.setup();
    const scheduler = makeScheduler();
    vi.mocked(createStreamingAudioScheduler).mockReturnValueOnce(scheduler);
    const encoder = new TextEncoder();
    let streamController: ReadableStreamDefaultController<Uint8Array> | null = null;
    vi.mocked(fetch).mockResolvedValueOnce(new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        streamController = controller;
        controller.enqueue(encoder.encode('{"type":"start","provider":"fake","model":"fake-tone-v1"}\n'));
        controller.enqueue(encoder.encode(segmentLine(0, 'first')));
      },
    }), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));

    render(<StreamingHarness />);
    await user.click(screen.getByRole('button', { name: 'stream play' }));
    await waitFor(() => expect(scheduler.enqueue).toHaveBeenCalledTimes(1));
    vi.mocked(HTMLMediaElement.prototype.pause).mockClear();
    vi.mocked(HTMLMediaElement.prototype.play).mockClear();

    await user.click(screen.getByRole('button', { name: 'pause stream' }));
    expect(scheduler.pause).toHaveBeenCalledTimes(1);
    expect(HTMLMediaElement.prototype.pause).not.toHaveBeenCalled();
    expect(screen.getByTestId('state')).toHaveTextContent('paused');

    const getStreamController = (): ReadableStreamDefaultController<Uint8Array> => {
      if (!streamController) throw new Error('stream controller missing');
      return streamController;
    };
    getStreamController().enqueue(encoder.encode(segmentLine(1, 'second')));
    await waitFor(() => expect(scheduler.enqueue).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId('state')).toHaveTextContent('paused');

    await user.click(screen.getByRole('button', { name: 'resume stream' }));
    expect(scheduler.resume).toHaveBeenCalledTimes(1);
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
    expect(screen.getByTestId('state')).toHaveTextContent('playing');
  });

  it('passes the selected output device to the Web Audio scheduler', async () => {
    const user = userEvent.setup();
    const scheduler = makeScheduler();
    vi.mocked(createStreamingAudioScheduler).mockReturnValueOnce(scheduler);
    const encoder = new TextEncoder();
    vi.mocked(fetch).mockResolvedValueOnce(new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('{"type":"start","provider":"fake","model":"fake-tone-v1"}\n'));
        controller.enqueue(encoder.encode(segmentLine(0, 'first')));
        controller.enqueue(encoder.encode('{"type":"done","segment_count":1}\n'));
        controller.close();
      },
    }), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));

    render(<StreamingHarness outputDeviceId="speaker-1" />);
    await user.click(screen.getByRole('button', { name: 'stream play' }));

    await waitFor(() => expect(createStreamingAudioScheduler).toHaveBeenCalledWith({ audioOutputDeviceId: 'speaker-1' }));
  });

  it('falls back to HTMLAudio segment playback when the scheduler is unsupported', async () => {
    const user = userEvent.setup();
    const scheduler = makeScheduler({ isSupported: vi.fn(() => false) });
    vi.mocked(createStreamingAudioScheduler).mockReturnValueOnce(scheduler);
    const encoder = new TextEncoder();
    vi.mocked(fetch).mockResolvedValueOnce(new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('{"type":"start","provider":"fake","model":"fake-tone-v1"}\n'));
        controller.enqueue(encoder.encode(segmentLine(0, 'first')));
        controller.enqueue(encoder.encode('{"type":"done","segment_count":1}\n'));
        controller.close();
      },
    }), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));

    render(<StreamingHarness />);
    await user.click(screen.getByRole('button', { name: 'stream play' }));

    await waitFor(() => expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1));
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    expect(scheduler.enqueue).not.toHaveBeenCalled();
  });

  it('stops the scheduler and aborts the stream when streaming playback is stopped', async () => {
    const user = userEvent.setup();
    const scheduler = makeScheduler();
    vi.mocked(createStreamingAudioScheduler).mockReturnValueOnce(scheduler);
    let capturedSignal: AbortSignal | undefined;
    let streamController: ReadableStreamDefaultController<Uint8Array> | null = null;
    const encoder = new TextEncoder();
    vi.mocked(fetch).mockImplementationOnce((_input, init) => {
      capturedSignal = init?.signal as AbortSignal;
      return Promise.resolve(new Response(new ReadableStream<Uint8Array>({
        start(controller) {
          streamController = controller;
        },
      }), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));
    });

    render(<StreamingHarness />);
    await user.click(screen.getByRole('button', { name: 'stream play' }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    const getStreamController = (): ReadableStreamDefaultController<Uint8Array> => {
      if (!streamController) throw new Error('stream controller missing');
      return streamController;
    };
    getStreamController().enqueue(encoder.encode('{"type":"start","provider":"fake","model":"fake-tone-v1"}\n'));
    getStreamController().enqueue(encoder.encode(segmentLine(0, 'first')));
    await waitFor(() => expect(scheduler.enqueue).toHaveBeenCalledTimes(1));

    await user.click(screen.getByRole('button', { name: 'stop stream' }));

    expect(capturedSignal?.aborted).toBe(true);
    expect(scheduler.stop).toHaveBeenCalledTimes(1);
  });

  it('falls back to HTMLAudio playback when Web Audio enqueue fails', async () => {
    const user = userEvent.setup();
    const scheduler = makeScheduler({
      enqueue: vi.fn(async () => {
        throw new Error('decode failed');
      }),
    });
    vi.mocked(createStreamingAudioScheduler).mockReturnValueOnce(scheduler);
    const encoder = new TextEncoder();
    vi.mocked(fetch).mockResolvedValueOnce(new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('{"type":"start","provider":"fake","model":"fake-tone-v1"}\n'));
        controller.enqueue(encoder.encode(segmentLine(0, 'first')));
        controller.enqueue(encoder.encode('{"type":"done","segment_count":1}\n'));
        controller.close();
      },
    }), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));

    render(<StreamingHarness />);
    await user.click(screen.getByRole('button', { name: 'stream play' }));

    await waitFor(() => expect(scheduler.enqueue).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1));
    expect(scheduler.stop).toHaveBeenCalledTimes(1);
    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
  });

  it('starts HTMLAudio fallback when a later Web Audio segment fails after prior scheduled playback', async () => {
    const user = userEvent.setup();
    const scheduler = makeScheduler({
      enqueue: vi.fn()
        .mockResolvedValueOnce({ scheduledStartTime: 1, scheduledEndTime: 1.1, decodedDurationMs: 100, queueDepth: 1, underrunMs: 0 })
        .mockRejectedValueOnce(new Error('decode failed')),
    });
    vi.mocked(createStreamingAudioScheduler).mockReturnValueOnce(scheduler);
    const encoder = new TextEncoder();
    vi.mocked(fetch).mockResolvedValueOnce(new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('{"type":"start","provider":"fake","model":"fake-tone-v1"}\n'));
        controller.enqueue(encoder.encode(segmentLine(0, 'first')));
        controller.enqueue(encoder.encode(segmentLine(1, 'second')));
        controller.enqueue(encoder.encode('{"type":"done","segment_count":2}\n'));
        controller.close();
      },
    }), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));

    render(<StreamingHarness />);
    await user.click(screen.getByRole('button', { name: 'stream play' }));

    await waitFor(() => expect(scheduler.enqueue).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1));
    expect(scheduler.stop).toHaveBeenCalledTimes(1);
  });

  it('uses HTMLAudio fallback for selected output devices when Web Audio sink routing is unsupported', async () => {
    const user = userEvent.setup();
    const scheduler = makeScheduler({ isSupported: vi.fn(() => false) });
    vi.mocked(createStreamingAudioScheduler).mockReturnValueOnce(scheduler);
    const encoder = new TextEncoder();
    vi.mocked(fetch).mockResolvedValueOnce(new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('{"type":"start","provider":"fake","model":"fake-tone-v1"}\n'));
        controller.enqueue(encoder.encode(segmentLine(0, 'first')));
        controller.enqueue(encoder.encode('{"type":"done","segment_count":1}\n'));
        controller.close();
      },
    }), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));

    render(<StreamingHarness outputDeviceId="speaker-1" />);
    await user.click(screen.getByRole('button', { name: 'stream play' }));

    await waitFor(() => expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1));
    expect(scheduler.enqueue).not.toHaveBeenCalled();
  });

  it('disposes the scheduler when the controller resets', async () => {
    const user = userEvent.setup();
    const scheduler = makeScheduler();
    vi.mocked(createStreamingAudioScheduler).mockReturnValueOnce(scheduler);
    const encoder = new TextEncoder();
    vi.mocked(fetch).mockResolvedValueOnce(new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('{"type":"start","provider":"fake","model":"fake-tone-v1"}\n'));
        controller.enqueue(encoder.encode(segmentLine(0, 'first')));
        controller.enqueue(encoder.encode('{"type":"done","segment_count":1}\n'));
        controller.close();
      },
    }), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));

    function ResetHarness() {
      const audioController = useAudioPlaybackController();
      return (
        <>
          <button type="button" onClick={() => { void audioController.play('a1', '第一句。', { streaming: true }); }}>
            stream play
          </button>
          <button type="button" onClick={() => audioController.reset()}>
            reset audio
          </button>
        </>
      );
    }

    render(<ResetHarness />);
    await user.click(screen.getByRole('button', { name: 'stream play' }));
    await waitFor(() => expect(scheduler.enqueue).toHaveBeenCalledTimes(1));

    await user.click(screen.getByRole('button', { name: 'reset audio' }));

    expect(scheduler.dispose).toHaveBeenCalledTimes(1);
  });
});
