export type VadRuntimeStatus =
  | 'disabled'
  | 'loading'
  | 'listening'
  | 'speech_detected'
  | 'speech_ended'
  | 'unavailable';

export interface VoiceActivityDetector {
  start(): Promise<void>;
  stop(): Promise<void>;
}

export interface CreateVoiceActivityDetectorOptions {
  onSpeechStart(): void;
  onSpeechEnd(): void;
  onError(error: unknown): void;
}

export type CreateVoiceActivityDetector = (
  options: CreateVoiceActivityDetectorOptions,
) => Promise<VoiceActivityDetector>;
