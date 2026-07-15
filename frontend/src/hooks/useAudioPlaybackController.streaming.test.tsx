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

function StreamingHarness({
  outputDeviceId = '',
  onRunActivated,
  onRunDeactivated,
  onSpeakingEvent,
}: {
  outputDeviceId?: string;
  onRunActivated?: (run: { assistantMessageId: string; playbackRunId: number }) => boolean;
  onRunDeactivated?: (run: { assistantMessageId: string; playbackRunId: number }) => void;
  onSpeakingEvent?: (event: {
    type: 'speaking';
    assistantMessageId: string;
    playbackRunId: number;
    phase: 'started' | 'paused' | 'resumed' | 'stopped' | 'interrupted' | 'failed';
  }) => void;
}) {
  const audioController = useAudioPlaybackController({
    audioOutputDeviceId: outputDeviceId,
    onRunActivated,
    onRunDeactivated,
    onSpeakingEvent,
  });
  const state = audioController.stateFor('a1');
  return (
    <>
      <div data-testid="state">{state.state}</div>
      <button type="button" onClick={() => { void audioController.play('a1'); }}>
        normal play
      </button>
      <button type="button" onClick={() => { void audioController.replay('a1'); }}>
        replay audio
      </button>
      <button type="button" onClick={() => { void audioController.play('a1', { streaming: true }); }}>
        stream play
      </button>
      <button type="button" onClick={() => { void audioController.play('a1', { streaming: true }); }}>
        restart stream
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
    vi.clearAllMocks();
    globalThis.fetch = vi.fn();
    URL.createObjectURL = vi.fn(() => 'blob:fallback-segment');
    URL.revokeObjectURL = vi.fn();
    HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined);
    vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(vi.fn());
  });

  afterEach(() => {
    cleanup();
    vi.mocked(createStreamingAudioScheduler).mockReset();
    globalThis.fetch = originalFetch;
    URL.createObjectURL = originalCreateObjectUrl;
    URL.revokeObjectURL = originalRevokeObjectUrl;
    HTMLMediaElement.prototype.play = originalPlay;
    HTMLMediaElement.prototype.pause = originalPause;
    vi.restoreAllMocks();
  });

  it('activates a playback run synchronously before requesting speech', async () => {
    const user = userEvent.setup();
    const order: string[] = [];
    const onRunActivated = vi.fn(() => {
      order.push('activated');
      return true;
    });
    vi.mocked(createStreamingAudioScheduler).mockReturnValueOnce(
      makeScheduler({ isSupported: vi.fn(() => false) }),
    );
    vi.mocked(fetch).mockImplementationOnce(async () => {
      order.push('fetch');
      throw new Error('stop after ordering assertion');
    });

    render(<StreamingHarness onRunActivated={onRunActivated} />);
    await user.click(screen.getByRole('button', { name: 'stream play' }));

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    expect(order.slice(0, 2)).toEqual(['activated', 'fetch']);
    expect(onRunActivated).toHaveBeenCalledWith({
      assistantMessageId: 'a1',
      playbackRunId: 1,
    });
  });

  it('does not start asynchronous work when run activation is refused', async () => {
    const user = userEvent.setup();
    const onRunActivated = vi.fn(() => false);

    render(<StreamingHarness onRunActivated={onRunActivated} />);
    await user.click(screen.getByRole('button', { name: 'stream play' }));

    expect(fetch).not.toHaveBeenCalled();
    expect(createStreamingAudioScheduler).not.toHaveBeenCalled();
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
  });

  it('emits one lifecycle for start pause resume and explicit stop', async () => {
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
    const events: string[] = [];
    const deactivated = vi.fn();

    render(
      <StreamingHarness
        onSpeakingEvent={(event) => events.push(`${event.playbackRunId}:${event.phase}`)}
        onRunDeactivated={deactivated}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'stream play' }));
    await waitFor(() => expect(events).toContain('1:started'));

    await user.click(screen.getByRole('button', { name: 'pause stream' }));
    await waitFor(() => expect(events).toContain('1:paused'));
    await user.click(screen.getByRole('button', { name: 'resume stream' }));
    await waitFor(() => expect(events).toContain('1:resumed'));
    await user.click(screen.getByRole('button', { name: 'stop stream' }));

    expect(events).toEqual(['1:started', '1:paused', '1:resumed', '1:stopped']);
    expect(deactivated).toHaveBeenCalledTimes(1);
    expect(streamController).not.toBeNull();
  });

  it('reports pre-start failure without a started event', async () => {
    const user = userEvent.setup();
    vi.mocked(createStreamingAudioScheduler).mockReturnValueOnce(
      makeScheduler({ isSupported: vi.fn(() => false) }),
    );
    vi.mocked(fetch).mockRejectedValueOnce(new Error('speech unavailable'));
    const events: string[] = [];
    const deactivated = vi.fn();

    render(
      <StreamingHarness
        onSpeakingEvent={(event) => events.push(event.phase)}
        onRunDeactivated={deactivated}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'stream play' }));

    await waitFor(() => expect(events).toContain('failed'));
    expect(events).toEqual(['failed']);
    expect(deactivated).toHaveBeenCalledTimes(1);
  });

  it('ignores completion from an old same-message run after restart', async () => {
    const user = userEvent.setup();
    let resolveOldEnqueue!: (value: ReturnType<MockScheduler['enqueue']> extends Promise<infer T> ? T : never) => void;
    const oldScheduler = makeScheduler({
      enqueue: vi.fn(() => new Promise((resolve) => { resolveOldEnqueue = resolve; })),
    });
    const newScheduler = makeScheduler();
    vi.mocked(createStreamingAudioScheduler)
      .mockReturnValueOnce(oldScheduler)
      .mockReturnValueOnce(newScheduler);
    const encoder = new TextEncoder();
    vi.mocked(fetch)
      .mockResolvedValueOnce(new Response(new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(encoder.encode('{"type":"start","provider":"fake","model":"fake-tone-v1"}\n'));
          controller.enqueue(encoder.encode(segmentLine(0, 'old')));
        },
      }), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }))
      .mockResolvedValueOnce(new Response(new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(encoder.encode('{"type":"start","provider":"fake","model":"fake-tone-v1"}\n'));
          controller.enqueue(encoder.encode(segmentLine(0, 'new')));
        },
      }), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));
    const events: string[] = [];

    render(<StreamingHarness onSpeakingEvent={(event) => events.push(`${event.playbackRunId}:${event.phase}`)} />);
    await user.click(screen.getByRole('button', { name: 'stream play' }));
    await waitFor(() => expect(oldScheduler.enqueue).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole('button', { name: 'stop stream' }));
    await user.click(screen.getByRole('button', { name: 'restart stream' }));
    await waitFor(() => expect(newScheduler.enqueue).toHaveBeenCalledTimes(1));
    expect(events).toContain('2:started');

    resolveOldEnqueue({
      scheduledStartTime: 1,
      scheduledEndTime: 1.1,
      decodedDurationMs: 100,
      queueDepth: 1,
      underrunMs: 0,
    });
    await Promise.resolve();

    expect(events.filter((event) => event === '2:started')).toHaveLength(1);
    expect(newScheduler.stop).not.toHaveBeenCalled();
    expect(screen.getByTestId('state')).toHaveTextContent('playing');
  });

  it('creates a new run when replaying cached non-streaming audio', async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockResolvedValueOnce(new Response(new Uint8Array([82, 73, 70, 70]), {
      status: 200,
      headers: { 'Content-Type': 'audio/wav' },
    }));
    const activated: number[] = [];
    const events: string[] = [];

    render(
      <StreamingHarness
        onRunActivated={(run) => { activated.push(run.playbackRunId); return true; }}
        onSpeakingEvent={(event) => events.push(`${event.playbackRunId}:${event.phase}`)}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'normal play' }));
    await waitFor(() => expect(events).toContain('1:started'));
    await user.click(screen.getByRole('button', { name: 'stop stream' }));
    await user.click(screen.getByRole('button', { name: 'replay audio' }));
    await waitFor(() => expect(events).toContain('2:started'));

    expect(activated).toEqual([1, 2]);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('cleans HTML streaming segment URLs on natural completion', async () => {
    const user = userEvent.setup();
    const scheduler = makeScheduler({ isSupported: vi.fn(() => false) });
    vi.mocked(createStreamingAudioScheduler).mockReturnValueOnce(scheduler);
    const encoder = new TextEncoder();
    vi.mocked(fetch).mockResolvedValueOnce(new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('{"type":"start","provider":"fake","model":"fake-tone-v1"}\n'));
        controller.enqueue(encoder.encode(segmentLine(0, 'only')));
        controller.enqueue(encoder.encode('{"type":"done","segment_count":1}\n'));
        controller.close();
      },
    }), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));

    const addEventSpy = vi.spyOn(HTMLMediaElement.prototype, 'addEventListener');
    render(<StreamingHarness />);
    await user.click(screen.getByRole('button', { name: 'stream play' }));
    await waitFor(() => expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1));
    const ended = [...addEventSpy.mock.calls]
      .reverse()
      .find(([type]) => type === 'ended')?.[1] as EventListener | undefined;
    expect(ended).toBeDefined();
    ended?.call(new Audio(), new Event('ended'));

    await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:fallback-segment'));
    expect(screen.getByTestId('state')).toHaveTextContent('idle');
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

  it('keeps HTML streaming fallback paused when later segments arrive', async () => {
    const user = userEvent.setup();
    const scheduler = makeScheduler({ isSupported: vi.fn(() => false) });
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
    const events: string[] = [];

    render(<StreamingHarness onSpeakingEvent={(event) => events.push(event.phase)} />);
    await user.click(screen.getByRole('button', { name: 'stream play' }));
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('playing'));
    await user.click(screen.getByRole('button', { name: 'pause stream' }));
    expect(screen.getByTestId('state')).toHaveTextContent('paused');

    if (!streamController) throw new Error('stream controller missing');
    (streamController as ReadableStreamDefaultController<Uint8Array>).enqueue(
      encoder.encode(segmentLine(1, 'second')),
    );

    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId('state')).toHaveTextContent('paused');
    expect(events).not.toContain('resumed');
  });

  it('ignores a superseded resume completion after a later pause command', async () => {
    const user = userEvent.setup();
    let resolveResume!: (value: undefined) => void;
    const scheduler = makeScheduler({
      resume: vi.fn(() => new Promise<undefined>((resolve) => { resolveResume = resolve; })),
    });
    vi.mocked(createStreamingAudioScheduler).mockReturnValueOnce(scheduler);
    const encoder = new TextEncoder();
    vi.mocked(fetch).mockResolvedValueOnce(new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('{"type":"start","provider":"fake","model":"fake-tone-v1"}\n'));
        controller.enqueue(encoder.encode(segmentLine(0, 'first')));
      },
    }), { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } }));
    const events: string[] = [];

    render(<StreamingHarness onSpeakingEvent={(event) => events.push(event.phase)} />);
    await user.click(screen.getByRole('button', { name: 'stream play' }));
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('playing'));
    await user.click(screen.getByRole('button', { name: 'pause stream' }));
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('paused'));

    await user.click(screen.getByRole('button', { name: 'resume stream' }));
    await user.click(screen.getByRole('button', { name: 'pause stream' }));
    resolveResume(undefined);

    await Promise.resolve();
    expect(screen.getByTestId('state')).toHaveTextContent('paused');
    expect(events.at(-1)).toBe('paused');
  });

  it('ignores a pause rejection from a scheduler replaced by HTML fallback', async () => {
    const user = userEvent.setup();
    let rejectPause!: (reason: unknown) => void;
    const scheduler = makeScheduler({
      enqueue: vi.fn()
        .mockResolvedValueOnce({ scheduledStartTime: 1, scheduledEndTime: 1.1, decodedDurationMs: 100, queueDepth: 1, underrunMs: 0 })
        .mockRejectedValueOnce(new Error('decode failed')),
      pause: vi.fn(() => new Promise<undefined>((_resolve, reject) => { rejectPause = reject; })),
    });
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
    const events: string[] = [];
    const deactivated = vi.fn();

    render(
      <StreamingHarness
        onSpeakingEvent={(event) => events.push(event.phase)}
        onRunDeactivated={deactivated}
      />,
    );
    await user.click(screen.getByRole('button', { name: 'stream play' }));
    await waitFor(() => expect(scheduler.enqueue).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole('button', { name: 'pause stream' }));
    if (!streamController) throw new Error('stream controller missing');
    (streamController as ReadableStreamDefaultController<Uint8Array>).enqueue(
      encoder.encode(segmentLine(1, 'fallback')),
    );
    await waitFor(() => expect(HTMLMediaElement.prototype.play).toHaveBeenCalledTimes(1));

    rejectPause(new Error('old scheduler pause failed'));
    await Promise.resolve();

    expect(events).not.toContain('failed');
    expect(deactivated).not.toHaveBeenCalled();
    expect(screen.getByTestId('state')).toHaveTextContent('playing');
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
          <button type="button" onClick={() => { void audioController.play('a1', { streaming: true }); }}>
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
