import { expect, test, type Page } from '@playwright/test';
import type { MessageExpressionResponse } from '../src/api/types';

type ExpressionResponse = MessageExpressionResponse;

async function mockPreviewTestMedia(page: Page): Promise<void> {
  await page.addInitScript(() => {
    HTMLMediaElement.prototype.play = async () => undefined;
    HTMLMediaElement.prototype.pause = () => undefined;
  });
}

async function createExpressionMessage(page: Page): Promise<string> {
  let assistantMessageId: string | null = null;
  page.on('response', async (response) => {
    const url = new URL(response.url());
    if (
      response.request().method() === 'POST' &&
      /^\/api\/sessions\/[^/]+\/messages$/.test(url.pathname)
    ) {
      const body = await response.json() as { assistant_message_id?: unknown };
      if (typeof body.assistant_message_id === 'string') {
        assistantMessageId = body.assistant_message_id;
      }
    }
  });

  await page.goto('/');
  await expect(page.getByRole('button', { name: '新建会话' })).toBeEnabled();
  await page.getByRole('button', { name: '新建会话' }).click();
  const messageInput = page.getByLabel('输入消息');
  await expect(messageInput).toBeEnabled();
  await messageInput.fill('请用稳定的表现回复我。');
  await expect(messageInput).toHaveValue('请用稳定的表现回复我。');
  const sendButton = page.getByRole('button', { name: '发送' });
  await expect(sendButton).toBeEnabled();
  await sendButton.click();
  await expect(
    page.locator('.message-list').getByText(/我听见了：请用稳定的表现回复我。/),
  ).toBeVisible();
  await expect.poll(() => assistantMessageId).not.toBeNull();
  if (assistantMessageId === null) throw new Error('assistant message response was not observed');
  return assistantMessageId;
}

test('message-bound expression preview follows playback and survives session reload', async ({ page, request }) => {
  await page.addInitScript(() => {
    const endedListeners: EventListenerOrEventListenerObject[] = [];
    const originalAddEventListener = HTMLMediaElement.prototype.addEventListener;
    HTMLMediaElement.prototype.addEventListener = function addEventListener(
      type: string,
      listener: EventListenerOrEventListenerObject,
      options?: boolean | AddEventListenerOptions,
    ) {
      if (type === 'ended') endedListeners.push(listener);
      originalAddEventListener.call(this, type, listener, options);
    };
    class FakeMediaRecorder {
      static isTypeSupported() { return true; }
      state = 'inactive';
      mimeType = 'audio/webm';
      ondataavailable: ((event: BlobEvent) => void) | null = null;
      onstop: (() => void) | null = null;
      onerror: (() => void) | null = null;
      start() { this.state = 'recording'; }
      stop() {
        this.state = 'inactive';
        this.ondataavailable?.({ data: new Blob(['voice'], { type: 'audio/webm' }) } as BlobEvent);
        this.onstop?.();
      }
    }
    Object.defineProperty(window, 'MediaRecorder', { value: FakeMediaRecorder });
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: async () => ({ getTracks: () => [{ stop() {}, addEventListener() {} }] }),
        enumerateDevices: async () => [],
        addEventListener() {},
        removeEventListener() {},
      },
    });
    Object.assign(window, { __stage4eEndedListeners: endedListeners });
    HTMLMediaElement.prototype.play = async () => undefined;
    HTMLMediaElement.prototype.pause = () => undefined;
  });
  const expressionGets: string[] = [];
  page.on('request', (browserRequest) => {
    const url = new URL(browserRequest.url());
    if (browserRequest.method() === 'GET' && /^\/api\/messages\/[^/]+\/expression$/.test(url.pathname)) {
      expressionGets.push(url.pathname);
    }
  });

  const assistantMessageId = await createExpressionMessage(page);
  const expressionPath = `/api/messages/${assistantMessageId}/expression`;
  await expect.poll(() => expressionGets.filter((path) => path === expressionPath).length).toBe(1);
  await expect(page.getByRole('region', { name: '角色表现预览' })).toContainText('准备就绪');

  const first = await request.get(expressionPath);
  const second = await request.get(expressionPath);
  expect(first.ok()).toBe(true);
  expect(second.ok()).toBe(true);
  const firstBody = await first.json() as ExpressionResponse;
  const secondBody = await second.json() as ExpressionResponse;
  expect(secondBody).toEqual(firstBody);
  expect(Object.keys(firstBody).sort()).toEqual([
    'assistant_message_id',
    'delivery',
    'intensity',
    'rate',
    'schema_version',
    'source',
  ]);

  const message = page.getByRole('article').filter({ hasText: '我听见了：请用稳定的表现回复我。' });
  await message.getByRole('button', { name: '播放' }).click();
  await expect(page.getByRole('region', { name: '角色表现预览' })).toContainText('正在说话');
  await message.getByRole('button', { name: '暂停' }).click();
  await expect(page.getByRole('region', { name: '角色表现预览' })).toContainText('已暂停');
  await message.getByRole('button', { name: '继续' }).click();
  await expect(page.getByRole('region', { name: '角色表现预览' })).toContainText('正在说话');
  const oldEndedListener = await page.evaluate(() => {
    const listeners = (window as typeof window & {
      __stage4eEndedListeners?: EventListenerOrEventListenerObject[];
    }).__stage4eEndedListeners ?? [];
    return listeners.length - 1;
  });
  await message.getByRole('button', { name: '停止' }).click();
  await message.getByRole('button', { name: '重播' }).click();
  await expect(page.getByRole('region', { name: '角色表现预览' })).toContainText('正在说话');
  await page.evaluate((listenerIndex) => {
    const listeners = (window as typeof window & {
      __stage4eEndedListeners?: EventListenerOrEventListenerObject[];
    }).__stage4eEndedListeners ?? [];
    const listener = listeners[listenerIndex];
    if (typeof listener === 'function') listener.call(new Audio(), new Event('ended'));
    else listener?.handleEvent(new Event('ended'));
  }, oldEndedListener);
  await expect(page.getByRole('region', { name: '角色表现预览' })).toContainText('正在说话');
  await page.getByRole('button', { name: '开始录音' }).click();
  await expect(page.getByRole('region', { name: '角色表现预览' })).not.toContainText(/正在说话|已暂停/);
  await page.evaluate((listenerIndex) => {
    const listeners = (window as typeof window & {
      __stage4eEndedListeners?: EventListenerOrEventListenerObject[];
    }).__stage4eEndedListeners ?? [];
    const listener = listeners[listenerIndex];
    if (typeof listener === 'function') listener.call(new Audio(), new Event('ended'));
    else listener?.handleEvent(new Event('ended'));
  }, oldEndedListener);
  await expect(page.getByRole('region', { name: '角色表现预览' })).not.toContainText(/正在说话|已暂停/);
  await page.getByRole('button', { name: '取消录音' }).click();

  await page.getByRole('button', { name: '新建会话' }).click();
  await expect(page.getByRole('region', { name: '角色表现预览' })).toContainText('等待消息');
  await page.getByRole('button', { name: '新会话' }).first().click();
  await expect(page.getByRole('region', { name: '角色表现预览' })).not.toContainText('正在说话');
  await page.reload();
  const afterReload = await request.get(expressionPath);
  expect(await afterReload.json()).toEqual(firstBody);
});

test('local neutral fallback is not cached and replay recovers persisted expression', async ({ page }) => {
  await mockPreviewTestMedia(page);
  let expressionAttempts = 0;
  await page.route('**/api/messages/*/expression', async (route) => {
    expressionAttempts += 1;
    if (expressionAttempts === 1) {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: { message: 'forced expression failure' } }),
      });
      return;
    }
    await route.continue();
  });

  await createExpressionMessage(page);
  const preview = page.getByRole('region', { name: '角色表现预览' });
  await expect(preview).toContainText('中性表达');
  await expect(page.getByRole('article').filter({ hasText: '我听见了' })).toBeVisible();

  const message = page.getByRole('article').filter({ hasText: '我听见了：请用稳定的表现回复我。' });
  await message.getByRole('button', { name: '播放' }).click();
  await expect.poll(() => expressionAttempts).toBe(2);
  await expect(preview).toContainText('正在说话');
  await message.getByRole('button', { name: '停止' }).click();
});
