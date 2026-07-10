import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createStreamingAudioScheduler } from './streamingAudioScheduler';

interface FakeSource {
  buffer: FakeAudioBuffer | null;
  connected: boolean;
  onended: (() => void) | null;
  start: ReturnType<typeof vi.fn<(when?: number) => void>>;
  stop: ReturnType<typeof vi.fn<() => void>>;
  connect: ReturnType<typeof vi.fn<(destination: unknown) => void>>;
  end: () => void;
}

interface FakeAudioBuffer {
  duration: number;
}

class FakeAudioContext {
  static instances: FakeAudioContext[] = [];

  currentTime = 10;
  destination = { kind: 'destination' };
  state: AudioContextState = 'running';
  decodedBuffers: FakeAudioBuffer[] = [];
  sources: FakeSource[] = [];
  sinkIds: string[] = [];
  closed = false;

  constructor(_options?: AudioContextOptions) {
    FakeAudioContext.instances.push(this);
  }

  decodeAudioData = vi.fn(async (_data: ArrayBuffer): Promise<AudioBuffer> => {
    const next = this.decodedBuffers.shift() ?? { duration: 0.1 };
    return next as AudioBuffer;
  });

  createBufferSource = vi.fn((): AudioBufferSourceNode => {
    const source: FakeSource = {
      buffer: null,
      connected: false,
      onended: null,
      start: vi.fn(),
      stop: vi.fn(),
      connect: vi.fn(() => {
        source.connected = true;
      }),
      end: () => {
        source.onended?.();
      },
    };
    this.sources.push(source);
    return source as unknown as AudioBufferSourceNode;
  });

  resume = vi.fn(async () => {
    this.state = 'running';
  });

  suspend = vi.fn(async () => {
    this.state = 'suspended';
  });

  close = vi.fn(async () => {
    this.closed = true;
    this.state = 'closed';
  });

  setSinkId = vi.fn(async (sinkId: string) => {
    this.sinkIds.push(sinkId);
  });
}

async function waitForMicrotask(): Promise<void> {
  await Promise.resolve();
}

describe('createStreamingAudioScheduler', () => {
  const originalAudioContext = globalThis.AudioContext;

  beforeEach(() => {
    FakeAudioContext.instances = [];
    Object.defineProperty(globalThis, 'AudioContext', {
      configurable: true,
      value: FakeAudioContext,
    });
  });

  afterEach(() => {
    if (originalAudioContext) {
      Object.defineProperty(globalThis, 'AudioContext', {
        configurable: true,
        value: originalAudioContext,
      });
    } else {
      delete (globalThis as Partial<typeof globalThis>).AudioContext;
    }
    vi.restoreAllMocks();
  });

  it('schedules adjacent decoded segments on the AudioContext timeline', async () => {
    const scheduler = createStreamingAudioScheduler({ initialLookaheadSeconds: 0.02 });
    const context = FakeAudioContext.instances[0];
    context.decodedBuffers.push({ duration: 0.12 }, { duration: 0.2 });

    const first = await scheduler.enqueue({
      audioBytes: new Uint8Array([82, 73, 70, 70, 87, 65, 86, 69]),
      mediaType: 'audio/wav',
      durationMs: 120,
      sampleRate: 24000,
    });
    const second = await scheduler.enqueue({
      audioBytes: new Uint8Array([82, 73, 70, 70, 87, 65, 86, 69]),
      mediaType: 'audio/wav',
      durationMs: 200,
      sampleRate: 24000,
    });

    expect(context.decodeAudioData).toHaveBeenCalledTimes(2);
    expect(context.sources).toHaveLength(2);
    expect(context.sources[0].connect).toHaveBeenCalledWith(context.destination);
    expect(context.sources[0].start).toHaveBeenCalledWith(10.02);
    expect(context.sources[1].start.mock.calls[0][0]).toBeCloseTo(10.14, 5);
    expect(first.queueDepth).toBe(1);
    expect(second.queueDepth).toBe(2);
    expect(second.scheduledStartTime).toBeCloseTo(first.scheduledStartTime + 0.12, 5);
  });

  it('stops all scheduled sources and resolves idle waiters', async () => {
    const scheduler = createStreamingAudioScheduler({ initialLookaheadSeconds: 0 });
    const context = FakeAudioContext.instances[0];
    context.decodedBuffers.push({ duration: 0.5 }, { duration: 0.5 });

    await scheduler.enqueue({ audioBytes: new Uint8Array([1]), mediaType: 'audio/wav', durationMs: 500, sampleRate: 24000 });
    await scheduler.enqueue({ audioBytes: new Uint8Array([2]), mediaType: 'audio/wav', durationMs: 500, sampleRate: 24000 });
    const idle = scheduler.waitForIdle();

    scheduler.stop();

    await expect(idle).resolves.toBeUndefined();
    expect(context.sources[0].stop).toHaveBeenCalledTimes(1);
    expect(context.sources[1].stop).toHaveBeenCalledTimes(1);
  });

  it('applies selected output sink when AudioContext setSinkId is available', async () => {
    const scheduler = createStreamingAudioScheduler({ audioOutputDeviceId: 'speaker-1' });
    const context = FakeAudioContext.instances[0];
    context.decodedBuffers.push({ duration: 0.1 });

    await scheduler.enqueue({ audioBytes: new Uint8Array([1]), mediaType: 'audio/wav', durationMs: 100, sampleRate: 24000 });

    expect(context.setSinkId).toHaveBeenCalledWith('speaker-1');
  });

  it('reports unsupported for selected output when AudioContext setSinkId is unavailable', () => {
    const scheduler = createStreamingAudioScheduler({ audioOutputDeviceId: 'speaker-1' });
    const context = FakeAudioContext.instances[0];
    Object.defineProperty(context, 'setSinkId', { configurable: true, value: undefined });

    expect(scheduler.isSupported()).toBe(false);
  });

  it('does not schedule audio if stopped while selected output sink is being applied', async () => {
    const scheduler = createStreamingAudioScheduler({ audioOutputDeviceId: 'speaker-1', initialLookaheadSeconds: 0 });
    const context = FakeAudioContext.instances[0];
    let resolveSink: (() => void) | null = null;
    context.setSinkId.mockImplementationOnce(async () => new Promise<void>((resolve) => {
      resolveSink = resolve;
    }));

    const enqueue = scheduler.enqueue({ audioBytes: new Uint8Array([1]), mediaType: 'audio/wav', durationMs: 100, sampleRate: 24000 });
    await waitForMicrotask();
    scheduler.stop();
    const completeSink = resolveSink as (() => void) | null;
    if (!completeSink) throw new Error('sink promise was not captured');
    completeSink();

    await expect(enqueue).rejects.toThrow('语音播放已停止。');
    expect(context.decodeAudioData).not.toHaveBeenCalled();
    expect(context.sources).toHaveLength(0);
  });

  it('does not schedule audio if stopped while a segment is decoding', async () => {
    const scheduler = createStreamingAudioScheduler({ initialLookaheadSeconds: 0 });
    const context = FakeAudioContext.instances[0];
    let resolveDecode: ((buffer: AudioBuffer) => void) | null = null;
    context.decodeAudioData.mockImplementationOnce(() => new Promise<AudioBuffer>((resolve) => {
      resolveDecode = resolve;
    }));

    const enqueue = scheduler.enqueue({ audioBytes: new Uint8Array([1]), mediaType: 'audio/wav', durationMs: 100, sampleRate: 24000 });
    await waitForMicrotask();
    scheduler.stop();
    const completeDecode = resolveDecode as ((buffer: AudioBuffer) => void) | null;
    if (!completeDecode) throw new Error('decode promise was not captured');
    completeDecode({ duration: 0.1 } as AudioBuffer);

    await expect(enqueue).rejects.toThrow('语音播放已停止。');
    expect(context.sources).toHaveLength(0);
  });

  it('reports unsupported when AudioContext is unavailable', () => {
    delete (globalThis as Partial<typeof globalThis>).AudioContext;

    const scheduler = createStreamingAudioScheduler();

    expect(scheduler.isSupported()).toBe(false);
  });

  it('pauses and resumes the AudioContext', async () => {
    const scheduler = createStreamingAudioScheduler();
    const context = FakeAudioContext.instances[0];

    await scheduler.pause();
    await scheduler.resume();

    expect(context.suspend).toHaveBeenCalledTimes(1);
    expect(context.resume).toHaveBeenCalledTimes(1);
  });

  it('does not auto-resume an intentionally paused AudioContext when more segments are enqueued', async () => {
    const scheduler = createStreamingAudioScheduler({ initialLookaheadSeconds: 0 });
    const context = FakeAudioContext.instances[0];
    context.decodedBuffers.push({ duration: 0.1 });

    await scheduler.pause();
    await scheduler.enqueue({ audioBytes: new Uint8Array([1]), mediaType: 'audio/wav', durationMs: 100, sampleRate: 24000 });

    expect(context.suspend).toHaveBeenCalledTimes(1);
    expect(context.resume).not.toHaveBeenCalled();
    expect(context.sources[0].start).toHaveBeenCalledTimes(1);
  });

  it('closes the AudioContext on dispose', async () => {
    const scheduler = createStreamingAudioScheduler();
    const context = FakeAudioContext.instances[0];
    context.decodedBuffers.push({ duration: 0.1 });

    await scheduler.enqueue({ audioBytes: new Uint8Array([1]), mediaType: 'audio/wav', durationMs: 100, sampleRate: 24000 });
    await scheduler.dispose();

    expect(context.close).toHaveBeenCalledTimes(1);
  });
});
