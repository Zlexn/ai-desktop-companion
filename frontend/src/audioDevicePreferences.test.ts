import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  AUDIO_DEVICE_PREFERENCES_KEY,
  clearAudioDevicePreference,
  loadAudioDevicePreferences,
  saveAudioDevicePreference,
} from './audioDevicePreferences';

describe('audioDevicePreferences', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it('returns defaults when no preferences are stored', () => {
    expect(loadAudioDevicePreferences()).toEqual({ inputDeviceId: '', outputDeviceId: '' });
  });

  it('loads valid stored preferences', () => {
    localStorage.setItem(AUDIO_DEVICE_PREFERENCES_KEY, JSON.stringify({
      inputDeviceId: 'usb-mic',
      outputDeviceId: 'usb-speaker',
    }));

    expect(loadAudioDevicePreferences()).toEqual({ inputDeviceId: 'usb-mic', outputDeviceId: 'usb-speaker' });
  });

  it('ignores malformed JSON and falls back to defaults', () => {
    localStorage.setItem(AUDIO_DEVICE_PREFERENCES_KEY, '{broken');

    expect(loadAudioDevicePreferences()).toEqual({ inputDeviceId: '', outputDeviceId: '' });
  });

  it('ignores non-string preference fields', () => {
    localStorage.setItem(AUDIO_DEVICE_PREFERENCES_KEY, JSON.stringify({
      inputDeviceId: 123,
      outputDeviceId: null,
    }));

    expect(loadAudioDevicePreferences()).toEqual({ inputDeviceId: '', outputDeviceId: '' });
  });

  it('saves one device preference without overwriting the other', () => {
    saveAudioDevicePreference('inputDeviceId', 'usb-mic');
    saveAudioDevicePreference('outputDeviceId', 'usb-speaker');

    expect(JSON.parse(localStorage.getItem(AUDIO_DEVICE_PREFERENCES_KEY) ?? '{}')).toEqual({
      inputDeviceId: 'usb-mic',
      outputDeviceId: 'usb-speaker',
    });
  });

  it('clears one preference while preserving the other', () => {
    localStorage.setItem(AUDIO_DEVICE_PREFERENCES_KEY, JSON.stringify({
      inputDeviceId: 'usb-mic',
      outputDeviceId: 'usb-speaker',
    }));

    clearAudioDevicePreference('inputDeviceId');

    expect(loadAudioDevicePreferences()).toEqual({ inputDeviceId: '', outputDeviceId: 'usb-speaker' });
  });

  it('treats localStorage read failures as defaults', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage blocked');
    });

    expect(loadAudioDevicePreferences()).toEqual({ inputDeviceId: '', outputDeviceId: '' });
  });

  it('does not throw when localStorage write fails', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota exceeded');
    });

    expect(() => saveAudioDevicePreference('outputDeviceId', 'usb-speaker')).not.toThrow();
  });
});
