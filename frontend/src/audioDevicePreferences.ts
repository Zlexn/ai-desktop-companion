export const AUDIO_DEVICE_PREFERENCES_KEY = 'ai-desktop-companion.audio-device-preferences.v1';

export interface AudioDevicePreferences {
  inputDeviceId: string;
  outputDeviceId: string;
}

type AudioDevicePreferenceKey = keyof AudioDevicePreferences;

const DEFAULT_PREFERENCES: AudioDevicePreferences = {
  inputDeviceId: '',
  outputDeviceId: '',
};

function getStorage(): Storage | null {
  try {
    if (typeof window === 'undefined') return null;
    return window.localStorage ?? null;
  } catch {
    return null;
  }
}

function normalizePreferences(value: unknown): AudioDevicePreferences {
  if (!value || typeof value !== 'object') return { ...DEFAULT_PREFERENCES };
  const candidate = value as Partial<Record<AudioDevicePreferenceKey, unknown>>;
  return {
    inputDeviceId: typeof candidate.inputDeviceId === 'string' ? candidate.inputDeviceId : '',
    outputDeviceId: typeof candidate.outputDeviceId === 'string' ? candidate.outputDeviceId : '',
  };
}

export function loadAudioDevicePreferences(): AudioDevicePreferences {
  const storage = getStorage();
  if (!storage) return { ...DEFAULT_PREFERENCES };

  try {
    const raw = storage.getItem(AUDIO_DEVICE_PREFERENCES_KEY);
    if (!raw) return { ...DEFAULT_PREFERENCES };
    return normalizePreferences(JSON.parse(raw));
  } catch {
    return { ...DEFAULT_PREFERENCES };
  }
}

export function saveAudioDevicePreference(key: AudioDevicePreferenceKey, deviceId: string): void {
  const storage = getStorage();
  if (!storage) return;

  try {
    const preferences = loadAudioDevicePreferences();
    preferences[key] = deviceId;
    storage.setItem(AUDIO_DEVICE_PREFERENCES_KEY, JSON.stringify(preferences));
  } catch {
    // Local preferences are optional; system defaults remain usable.
  }
}

export function clearAudioDevicePreference(key: AudioDevicePreferenceKey): void {
  saveAudioDevicePreference(key, '');
}
