import { expect, test } from '@playwright/test';

test('fake half-duplex voice turn sends transcript and requests TTS playback', async ({ page }) => {
  const consoleErrors: string[] = [];
  const speechRequests: Array<{ pathname: string; body: unknown }> = [];
  const chatPostRequests: string[] = [];
  let assistantMessageId: string | null = null;
  let firstAudioPlayAt: number | null = null;
  let streamFinishedAt: number | null = null;

  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('pageerror', (error) => {
    consoleErrors.push(error.message);
  });
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (/^\/api\/messages\/[^/]+\/speech\/stream$/.test(url.pathname)) {
      speechRequests.push({ pathname: url.pathname, body: request.postDataJSON() });
    }
    if (request.method() === 'POST' && /^\/api\/sessions\/[^/]+\/messages$/.test(url.pathname)) {
      chatPostRequests.push(request.url());
    }
  });

  page.on('response', async (response) => {
    const url = new URL(response.url());
    if (response.request().method() === 'POST' && /^\/api\/sessions\/[^/]+\/messages$/.test(url.pathname)) {
      const body = await response.json() as { assistant_message_id?: unknown };
      if (typeof body.assistant_message_id === 'string') assistantMessageId = body.assistant_message_id;
    }
  });

  page.on('requestfinished', (request) => {
    const url = new URL(request.url());
    if (/^\/api\/messages\/[^/]+\/speech\/stream$/.test(url.pathname) && streamFinishedAt === null) {
      streamFinishedAt = Date.now();
    }
  });

  await page.exposeFunction('__recordAudioPlay', () => {
    if (firstAudioPlayAt === null) firstAudioPlayAt = Date.now();
  });

  await page.addInitScript(() => {
    class FakeMediaRecorder {
      static isTypeSupported() { return true; }
      state = 'inactive';
      mimeType = 'audio/webm';
      ondataavailable: ((event: BlobEvent) => void) | null = null;
      onstop: (() => void) | null = null;
      onerror: (() => void) | null = null;

      start() {
        this.state = 'recording';
      }

      stop() {
        this.state = 'inactive';
        this.ondataavailable?.({ data: new Blob(['voice'], { type: 'audio/webm' }) } as BlobEvent);
        this.onstop?.();
      }
    }

    Object.defineProperty(window, 'MediaRecorder', { value: FakeMediaRecorder });
    const fakeDevices = [
      { deviceId: 'usb-mic', groupId: 'g-mic', kind: 'audioinput', label: 'USB Mic', toJSON: () => ({}) },
      { deviceId: 'usb-speaker', groupId: 'g-speaker', kind: 'audiooutput', label: 'USB Speaker', toJSON: () => ({}) },
    ];

    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: async () => ({ getTracks: () => [{ stop() {}, addEventListener() {} }] }),
        enumerateDevices: async () => fakeDevices,
        selectAudioOutput: async () => fakeDevices[1],
        addEventListener() {},
        removeEventListener() {},
      },
    });

    HTMLMediaElement.prototype.setSinkId = async function setSinkId(sinkId: string) {
      (window as typeof window & { __lastSinkId?: string }).__lastSinkId = sinkId;
    };

    HTMLMediaElement.prototype.play = async () => {
      await (window as typeof window & { __recordAudioPlay?: () => Promise<void> }).__recordAudioPlay?.();
    };
    HTMLMediaElement.prototype.pause = () => undefined;
  });

  await page.route('**/api/audio/transcriptions/stream', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/x-ndjson',
      body: [
        JSON.stringify({ type: 'start', provider: 'fake-asr', model: 'fake-asr-v1' }),
        JSON.stringify({
          type: 'final',
          text: '语音转写文本',
          detected_language: 'zh',
          duration_ms: 1000,
          provider: 'fake-asr',
          model: 'fake-asr-v1',
          inference_ms: 1,
        }),
        JSON.stringify({ type: 'done' }),
        '',
      ].join('\n'),
    });
  });

  await page.goto('/');
  await expect(page).toHaveTitle('AI 桌宠');
  await page.getByRole('button', { name: '新建会话' }).click();
  await expect(page.getByRole('button', { name: '开始录音' })).toBeVisible();
  await expect(page.getByLabel('扬声器/耳机')).toBeVisible();
  await expect(page.getByLabel('扬声器/耳机')).toContainText('USB Speaker');
  await page.getByLabel('扬声器/耳机').selectOption('usb-speaker');

  await page.getByRole('button', { name: '开始录音' }).click();
  await page.waitForTimeout(350);
  await page.getByRole('button', { name: '停止录音' }).click();
  await expect(page.getByText(/转写待确认/)).toBeVisible();

  await page.getByRole('button', { name: '发送并朗读' }).click();

  await expect(page.locator('.message-list').getByText(/我听见了/)).toBeVisible({ timeout: 5000 });
  await expect.poll(() => speechRequests.length).toBe(1);
  await expect.poll(() => assistantMessageId).not.toBeNull();
  expect(speechRequests[0].pathname).toBe(`/api/messages/${assistantMessageId}/speech/stream`);
  expect(speechRequests[0].body).toEqual({});
  expect(JSON.stringify(speechRequests[0].body)).not.toMatch(/text|delivery|intensity|style|ssml|provider_options/);
  expect(chatPostRequests).toHaveLength(1);
  await expect.poll(() => firstAudioPlayAt).not.toBeNull();
  await expect.poll(() => streamFinishedAt).not.toBeNull();
  expect(firstAudioPlayAt as number).toBeLessThanOrEqual((streamFinishedAt as number) + 1000);
  await expect.poll(async () => page.evaluate(() => (window as typeof window & { __lastSinkId?: string }).__lastSinkId)).toBe('usb-speaker');
  await expect(page.getByText('语音转写文本', { exact: true })).toHaveCount(1);
  await expect(page.locator('.message-list').getByText(/我听见了：语音转写文本/)).toHaveCount(1);
  expect(consoleErrors).toEqual([]);
});
