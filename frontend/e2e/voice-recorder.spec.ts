import { expect, test } from '@playwright/test';

test.describe('Voice recorder E2E', () => {
  test('page load does NOT trigger getUserMedia', async ({ page }) => {
    let gumCalled = false;

    await page.addInitScript(() => {
      const origGetUserMedia = navigator.mediaDevices.getUserMedia;
      const patched = async function (this: typeof navigator.mediaDevices, ...args: Parameters<typeof origGetUserMedia>) {
        (window as unknown as Record<string, boolean>)._gum_called = true;
        return origGetUserMedia.apply(this, args);
      };
      Object.defineProperty(navigator.mediaDevices, 'getUserMedia', {
        configurable: true,
        enumerable: true,
        value: patched,
      });
    });

    await page.goto('/');
    await expect(page.getByLabel('麦克风')).toBeVisible();
    await expect(page.getByRole('button', { name: '刷新设备' })).toBeVisible();

    gumCalled = await page.evaluate(() => !!(window as unknown as Record<string, boolean>)._gum_called);
    expect(gumCalled).toBe(false);
  });

  test('recorder button is present and text chat works', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveTitle('AI 桌宠');

    // Recorder button should be visible
    await expect(page.getByRole('button', { name: '开始录音' })).toBeVisible();

    // Text chat works
    await page.getByRole('button', { name: '新建会话' }).click();
    await expect(page.getByRole('heading', { name: '新会话' })).toBeVisible();
    await page.getByLabel('输入消息').fill('并行测试');
    await page.getByRole('button', { name: '发送' }).click();

    await expect(page.getByText('并行测试', { exact: true })).toBeVisible({ timeout: 5000 });
  });

  test('text chat remains fully operational with recorder present', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: '新建会话' }).click();
    await expect(page.getByRole('heading', { name: '新会话' })).toBeVisible();

    await page.getByLabel('输入消息').fill('语音测试');
    await page.getByRole('button', { name: '发送' }).click();

    await expect(page.getByText('语音测试', { exact: true })).toBeVisible({ timeout: 5000 });
    await expect(page.locator('.message-list').getByText(/我听见了/)).toBeVisible({ timeout: 5000 });

    // Assistant playback still works
    await expect(page.getByRole('button', { name: '播放' })).toBeVisible();
  });
});
