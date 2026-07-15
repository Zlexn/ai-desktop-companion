import { expect, test } from '@playwright/test';

test('completes a proxied two-turn chat and persists after refresh', async ({ page }) => {
  const consoleErrors: string[] = [];
  const apiRequests: string[] = [];
  const speechResponses: string[] = [];
  const speechRequests: Array<{ pathname: string; body: unknown }> = [];
  const serverErrors: string[] = [];
  const notFoundRequests: string[] = [];

  page.on('console', (message) => {
    if (message.type() === 'error') {
      const location = message.location();
      consoleErrors.push(`${message.text()} (${location.url}:${location.lineNumber}:${location.columnNumber})`);
    }
  });
  page.on('pageerror', (error) => {
    consoleErrors.push(error.message);
  });
  page.on('request', (request) => {
    if (new URL(request.url()).pathname.startsWith('/api/')) {
      apiRequests.push(request.url());
    }
    const pathname = new URL(request.url()).pathname;
    if (/^\/api\/messages\/[^/]+\/speech$/.test(pathname)) {
      speechRequests.push({ pathname, body: request.postDataJSON() });
    }
  });
  page.on('response', (response) => {
    if (response.status() === 404) {
      notFoundRequests.push(response.url());
    }
    if (response.status() >= 500) {
      serverErrors.push(`${response.status()} ${response.url()}`);
    }
    if (/^\/api\/messages\/[^/]+\/speech$/.test(new URL(response.url()).pathname)) {
      speechResponses.push(response.headers()['content-type'] ?? '');
    }
  });

  await page.goto('/');

  await expect(page).toHaveTitle('AI 桌宠');
  await expect(page.getByRole('heading', { name: 'AI 桌宠' })).toBeVisible();
  await expect(page.getByRole('button', { name: '新建会话' })).toBeVisible();
  await expect(page.getByText('请选择或新建会话')).toBeVisible();

  await page.getByRole('button', { name: '新建会话' }).click();
  await expect(page.getByRole('heading', { name: '新会话' })).toBeVisible();

  await page.getByLabel('输入消息').fill('第一条消息');
  await page.getByRole('button', { name: '发送' }).click();
  await expect(page.locator('.message-list').getByText('第一条消息', { exact: true })).toBeVisible();
  await expect(page.locator('.message-list').getByText(/我听见了：第一条消息/)).toBeVisible();

  await expect(page.getByRole('button', { name: '播放' })).toBeVisible();
  await page.getByRole('button', { name: '播放' }).click();
  await expect(page.getByRole('button', { name: '停止' })).toBeVisible();
  await expect.poll(() => speechResponses.some((contentType) => contentType.includes('audio/wav'))).toBe(true);
  expect(speechRequests).toHaveLength(1);
  const firstSpeechPath = speechRequests[0].pathname;
  expect(speechRequests[0].body).toEqual({});
  expect(JSON.stringify(speechRequests[0].body)).not.toMatch(/text|delivery|intensity|style|ssml|provider_options/);
  await page.getByRole('button', { name: '停止' }).click();
  await expect(page.getByRole('button', { name: '播放' })).toBeVisible();

  await page.getByLabel('输入消息').fill('第二条消息');
  await page.getByRole('button', { name: '发送' }).click();
  await expect(page.locator('.message-list').getByText('第二条消息', { exact: true })).toBeVisible();
  await expect(page.locator('.message-list').getByText(/我听见了：第二条消息/)).toBeVisible();

  await page.reload();
  await expect(page.getByRole('heading', { name: '新会话' })).toBeVisible();
  await expect(page.locator('.message-list').getByText('第一条消息', { exact: true })).toBeVisible();
  await expect(page.locator('.message-list').getByText(/我听见了：第一条消息/)).toBeVisible();
  await expect(page.locator('.message-list').getByText('第二条消息', { exact: true })).toBeVisible();
  await expect(page.locator('.message-list').getByText(/我听见了：第二条消息/)).toBeVisible();
  await page.getByRole('button', { name: '播放' }).first().click();
  await expect.poll(() => speechRequests.length).toBe(2);
  expect(speechRequests[1].pathname).toBe(firstSpeechPath);

  const deleteButtons = page.getByRole('button', { name: '删除 新会话' });
  await deleteButtons.first().click();
  await expect(page.getByText('还没有会话。')).toBeVisible();
  await expect(page.getByText('请选择或新建会话')).toBeVisible();

  expect(notFoundRequests).toEqual([]);
  expect(serverErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
  expect(speechResponses.some((contentType) => contentType.includes('audio/wav'))).toBe(true);
  expect(apiRequests.length).toBeGreaterThan(0);
  for (const url of apiRequests) {
    expect(url).toContain('127.0.0.1:15173/api/');
  }
});
