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
