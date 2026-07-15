import { expect, test } from '@playwright/test';

test('creates a manual memory and keeps text chat usable', async ({ page }) => {
  const consoleErrors: string[] = [];
  const serverErrors: string[] = [];
  const originalContent = '用户偏好中文回复。';
  const updatedContent = '用户偏好简洁的中文回复。';

  page.on('console', (message) => {
    if (message.type() === 'error') {
      const location = message.location();
      consoleErrors.push(`${message.text()} (${location.url}:${location.lineNumber}:${location.columnNumber})`);
    }
  });
  page.on('pageerror', (error) => {
    consoleErrors.push(error.message);
  });
  page.on('response', (response) => {
    if (response.status() >= 500) {
      serverErrors.push(`${response.status()} ${response.url()}`);
    }
  });

  await page.goto('/');
  await expect(page.getByRole('heading', { name: '长期记忆' })).toBeVisible();
  await expect(page.getByText(/聊天记录不会自动变成长期记忆/)).toBeVisible();

  await page.getByLabel('记忆内容').fill(originalContent);
  await page.getByLabel('记忆类型').selectOption('preference');
  await page.getByRole('button', { name: '保存记忆' }).click();
  await expect(page.getByText(originalContent)).toBeVisible();

  await page.getByRole('button', { name: '编辑记忆' }).click();
  await page.getByLabel('编辑记忆内容').fill(updatedContent);
  await page.getByLabel('编辑重要度').fill('5');
  await page.getByLabel('编辑可信度').fill('0.8');
  await page.getByRole('button', { name: '保存修改' }).click();
  await expect(page.getByText(updatedContent)).toBeVisible();

  await page.getByRole('button', { name: '编辑记忆' }).click();
  await page.getByLabel('编辑记忆内容').fill('不会保存的草稿');
  await page.getByRole('button', { name: '取消编辑' }).click();
  await expect(page.getByText(updatedContent)).toBeVisible();

  await page.getByRole('button', { name: '编辑记忆' }).click();
  await page.getByLabel('编辑记忆内容').fill('   ');
  await expect(page.getByRole('button', { name: '保存修改' })).toBeDisabled();
  await page.getByLabel('编辑记忆内容').fill('数字无效时也不能保存');
  await page.getByLabel('编辑重要度').fill('');
  await expect(page.getByRole('button', { name: '保存修改' })).toBeDisabled();
  await page.getByRole('button', { name: '取消编辑' }).click();

  await page.getByRole('button', { name: '新建会话' }).click();
  await expect(page.getByRole('heading', { name: '新会话' })).toBeVisible();
  await page.getByLabel('输入消息').fill('你好');
  await page.getByRole('button', { name: '发送' }).click();

  await expect(page.getByText('你好', { exact: true })).toBeVisible();
  await expect(page.locator('.message-list').getByText(/我听见了：你好/)).toBeVisible();

  await page.reload();
  await expect(page.getByText(updatedContent)).toBeVisible();
  await expect(page.getByText(originalContent)).toHaveCount(0);

  expect(serverErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
});

test('suggests and confirms a memory candidate from chat', async ({ page }) => {
  const consoleErrors: string[] = [];
  const serverErrors: string[] = [];

  page.on('console', (message) => {
    if (message.type() === 'error') {
      const location = message.location();
      consoleErrors.push(`${message.text()} (${location.url}:${location.lineNumber}:${location.columnNumber})`);
    }
  });
  page.on('pageerror', (error) => {
    consoleErrors.push(error.message);
  });
  page.on('response', (response) => {
    if (response.status() >= 500) {
      serverErrors.push(`${response.status()} ${response.url()}`);
    }
  });

  await page.goto('/');
  await page.getByRole('button', { name: '新建会话' }).click();
  await expect(page.getByRole('heading', { name: '新会话' })).toBeVisible();
  await page.getByLabel('输入消息').fill('我喜欢红茶。');
  await page.getByRole('button', { name: '发送' }).click();

  await expect(page.getByText('用户喜欢红茶。')).toBeVisible();
  await expect(page.getByRole('heading', { name: '待确认记忆' })).toBeVisible();
  await page.getByRole('button', { name: '保存为长期记忆' }).click();

  await expect(page.getByRole('heading', { name: '长期记忆' })).toBeVisible();
  await expect(page.getByText('用户喜欢红茶。')).toBeVisible();

  await page.reload();
  await expect(page.getByText('用户喜欢红茶。')).toBeVisible();

  expect(serverErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
});
