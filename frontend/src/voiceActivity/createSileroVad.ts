import type { CreateVoiceActivityDetector } from './types';

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

declare global {
  interface Window {
    vad?: {
      MicVAD: {
        new: (options: MicVadOptions) => Promise<MicVadInstance>;
      };
    };
  }
}

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

function loadScriptOnce(id: string, src: string): Promise<void> {
  const existing = document.getElementById(id) as HTMLScriptElement | null;
  if (existing?.dataset.loaded === 'true') return Promise.resolve();
  if (existing?.dataset.loading === 'true') {
    return new Promise((resolve, reject) => {
      existing.addEventListener('load', () => resolve(), { once: true });
      existing.addEventListener('error', () => reject(new Error(`Failed to load ${src}`)), { once: true });
    });
  }

  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.id = id;
    script.src = src;
    script.async = true;
    script.dataset.loading = 'true';
    script.addEventListener('load', () => {
      script.dataset.loading = 'false';
      script.dataset.loaded = 'true';
      resolve();
    }, { once: true });
    script.addEventListener('error', () => reject(new Error(`Failed to load ${src}`)), { once: true });
    document.head.appendChild(script);
  });
}

async function loadVadBundle(): Promise<NonNullable<Window['vad']>> {
  await loadScriptOnce(
    'ai-desktop-companion-onnxruntime',
    envString('VITE_VAD_ONNX_SCRIPT_PATH', '/vendor/onnxruntime/ort.js'),
  );
  await loadScriptOnce(
    'ai-desktop-companion-vad-web',
    envString('VITE_VAD_BUNDLE_SCRIPT_PATH', '/vendor/vad/bundle.min.js'),
  );

  if (!window.vad?.MicVAD) {
    throw new Error('VAD bundle loaded but window.vad.MicVAD is unavailable.');
  }
  return window.vad;
}

export const createSileroVad: CreateVoiceActivityDetector = async ({
  onSpeechStart,
  onSpeechEnd,
  onError,
}) => {
  const vadBundle = await loadVadBundle();

  const vad = await vadBundle.MicVAD.new({
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
