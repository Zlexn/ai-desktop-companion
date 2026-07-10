export interface StreamingAudioSegment {
  audioBytes: Uint8Array;
  mediaType: 'audio/wav';
  durationMs: number;
  sampleRate: number;
}

export interface StreamingAudioScheduleResult {
  scheduledStartTime: number;
  scheduledEndTime: number;
  decodedDurationMs: number;
  queueDepth: number;
  underrunMs: number;
}

export interface StreamingAudioScheduler {
  isSupported: () => boolean;
  enqueue: (segment: StreamingAudioSegment) => Promise<StreamingAudioScheduleResult>;
  waitForIdle: () => Promise<void>;
  pause: () => Promise<void>;
  resume: () => Promise<void>;
  stop: () => void;
  dispose: () => Promise<void>;
}

interface StreamingAudioSchedulerOptions {
  audioOutputDeviceId?: string;
  initialLookaheadSeconds?: number;
}

type AudioContextConstructor = new (options?: AudioContextOptions) => AudioContext;
type SinkCapableAudioContext = AudioContext & { setSinkId?: (sinkId: string) => Promise<void> };

const DEFAULT_LOOKAHEAD_SECONDS = 0.03;

function audioContextConstructor(): AudioContextConstructor | null {
  const maybeGlobal = globalThis as typeof globalThis & { webkitAudioContext?: AudioContextConstructor };
  return globalThis.AudioContext ?? maybeGlobal.webkitAudioContext ?? null;
}

function copyToArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return copy.buffer;
}

function resolveIdle(waiters: Array<() => void>): void {
  while (waiters.length > 0) {
    const resolve = waiters.shift();
    resolve?.();
  }
}

export function createStreamingAudioScheduler(options: StreamingAudioSchedulerOptions = {}): StreamingAudioScheduler {
  const ContextCtor = audioContextConstructor();
  const lookaheadSeconds = options.initialLookaheadSeconds ?? DEFAULT_LOOKAHEAD_SECONDS;
  let context: AudioContext | null = ContextCtor ? new ContextCtor({ latencyHint: 'interactive' }) : null;
  let sinkApplied = false;
  let nextStartTime = 0;
  let hasScheduled = false;
  let generation = 0;
  let intentionallyPaused = false;
  const activeSources = new Set<AudioBufferSourceNode>();
  const idleWaiters: Array<() => void> = [];

  function isSupported(): boolean {
    if (!ContextCtor || !context || typeof context.decodeAudioData !== 'function' || typeof context.createBufferSource !== 'function') {
      return false;
    }
    const selectedSink = options.audioOutputDeviceId ?? '';
    if (selectedSink && typeof (context as SinkCapableAudioContext).setSinkId !== 'function') {
      return false;
    }
    return true;
  }

  async function ensureContext(): Promise<AudioContext> {
    if (!ContextCtor) throw new Error('当前浏览器不支持低间隙 Web Audio 播放。');
    if (!context || context.state === 'closed') {
      context = new ContextCtor({ latencyHint: 'interactive' });
      sinkApplied = false;
    }
    if (context.state === 'suspended' && !intentionallyPaused) {
      await context.resume();
    }
    const selectedSink = options.audioOutputDeviceId ?? '';
    const sinkContext = context as SinkCapableAudioContext;
    if (selectedSink && !sinkApplied && typeof sinkContext.setSinkId === 'function') {
      await sinkContext.setSinkId(selectedSink);
      sinkApplied = true;
    }
    return context;
  }

  function notifyIdleIfNeeded(): void {
    if (activeSources.size === 0) {
      resolveIdle(idleWaiters);
    }
  }

  async function enqueue(segment: StreamingAudioSegment): Promise<StreamingAudioScheduleResult> {
    if (segment.mediaType !== 'audio/wav') {
      throw new Error('低间隙播放仅支持 WAV 语音片段。');
    }
    const enqueueGeneration = generation;
    const audioContext = await ensureContext();
    if (enqueueGeneration !== generation) {
      throw new Error('语音播放已停止。');
    }
    const decoded = await audioContext.decodeAudioData(copyToArrayBuffer(segment.audioBytes));
    if (enqueueGeneration !== generation) {
      throw new Error('语音播放已停止。');
    }
    const source = audioContext.createBufferSource();
    source.buffer = decoded;
    source.connect(audioContext.destination);

    const now = audioContext.currentTime;
    const underrunMs = hasScheduled && nextStartTime < now ? Math.round((now - nextStartTime) * 1000) : 0;
    if (!hasScheduled || nextStartTime < now) {
      nextStartTime = now + lookaheadSeconds;
    }

    const scheduledStartTime = nextStartTime;
    const decodedDurationSeconds = decoded.duration;
    const scheduledEndTime = scheduledStartTime + decodedDurationSeconds;

    activeSources.add(source);
    source.onended = () => {
      activeSources.delete(source);
      notifyIdleIfNeeded();
    };
    source.start(scheduledStartTime);
    hasScheduled = true;
    nextStartTime = scheduledEndTime;

    return {
      scheduledStartTime,
      scheduledEndTime,
      decodedDurationMs: Math.round(decodedDurationSeconds * 1000),
      queueDepth: activeSources.size,
      underrunMs,
    };
  }

  async function pause(): Promise<void> {
    intentionallyPaused = true;
    if (context && context.state === 'running') {
      await context.suspend();
    }
  }

  async function resume(): Promise<void> {
    intentionallyPaused = false;
    if (context && context.state === 'suspended') {
      await context.resume();
    }
  }

  function stop(): void {
    generation += 1;
    for (const source of Array.from(activeSources)) {
      try {
        source.stop();
      } catch {
        // Stopping an already-ended source is harmless for this controller.
      }
      activeSources.delete(source);
    }
    nextStartTime = 0;
    hasScheduled = false;
    intentionallyPaused = false;
    notifyIdleIfNeeded();
  }

  function waitForIdle(): Promise<void> {
    if (activeSources.size === 0) return Promise.resolve();
    return new Promise((resolve) => {
      idleWaiters.push(resolve);
    });
  }

  async function dispose(): Promise<void> {
    stop();
    if (context && context.state !== 'closed') {
      await context.close();
    }
    context = null;
    sinkApplied = false;
  }

  return { dispose, enqueue, isSupported, pause, resume, stop, waitForIdle };
}
