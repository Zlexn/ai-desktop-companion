import { expect, test, type APIRequestContext } from '@playwright/test';

const fakeDeepSeekPort = process.env.E2E_FAKE_DEEPSEEK_PORT ?? '18101';
const fakeDeepSeekUrl = `http://127.0.0.1:${fakeDeepSeekPort}`;

interface FakeProviderState {
  request_count: number;
  requests: Array<{
    messages: Array<{ role: string; content: string }>;
  }>;
}

interface EmotionStateResponse {
  vector: Record<string, number>;
}

async function getFakeProviderState(request: APIRequestContext): Promise<FakeProviderState> {
  const response = await request.get(`${fakeDeepSeekUrl}/__test__/state`);
  expect(response.ok()).toBe(true);
  return response.json();
}

test('LLM-assisted emotion analysis requires consent, applies safely, and stops after revoke', async ({ page, request }) => {
  const consoleErrors: string[] = [];
  const serverErrors: string[] = [];
  page.on('console', (message) => { if (message.type() === 'error') consoleErrors.push(message.text()); });
  page.on('pageerror', (error) => consoleErrors.push(error.message));
  page.on('response', (response) => { if (response.status() >= 500) serverErrors.push(`${response.status()} ${response.url()}`); });

  const reset = await request.post(`${fakeDeepSeekUrl}/__test__/reset`);
  expect(reset.ok()).toBe(true);

  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'LLM 辅助情感分析' })).toBeVisible();
  await expect(page.getByText(/当前授权状态：unknown/)).toBeVisible();
  await expect(page.getByText(/部署配置尚未开启/)).toHaveCount(0);
  await expect(page.getByText(/暂无远程分析记录/)).toBeVisible();

  await page.getByRole('button', { name: '新建会话' }).click();
  await page.getByLabel('输入消息').fill('今天只是普通的一天。');
  await page.getByRole('button', { name: '发送' }).click();
  await expect(page.locator('.message-list').getByText(/我听见了：今天只是普通的一天。/)).toBeVisible();
  await expect.poll(async () => (await getFakeProviderState(request)).request_count).toBe(0);

  await page.getByRole('button', { name: '授权远程分析' }).click();
  await expect(page.getByRole('button', { name: '确认授权并允许发送' })).toBeVisible();
  await page.getByRole('button', { name: '确认授权并允许发送' }).click();
  await expect(page.getByText(/当前授权状态：granted/)).toBeVisible();

  await page.getByLabel('输入消息').fill('我今天很难受 token=e2e-analysis-secret');
  await page.getByRole('button', { name: '发送' }).click();
  await expect.poll(async () => {
    const response = await request.get('/api/emotion/analysis/audits');
    expect(response.ok()).toBe(true);
    return (await response.json()).length;
  }).toBe(1);

  const providerState = await getFakeProviderState(request);
  expect(providerState.request_count).toBe(1);
  expect(JSON.stringify(providerState)).not.toContain('e2e-analysis-secret');
  const analysisPayload = JSON.parse(providerState.requests[0].messages[1].content);
  expect(analysisPayload.recent_messages.length).toBeLessThanOrEqual(6);
  expect(analysisPayload.memories.length).toBeLessThanOrEqual(3);
  expect(analysisPayload.input_characters).toBeLessThanOrEqual(8000);
  expect(analysisPayload.redaction_count).toBeGreaterThanOrEqual(1);

  const appliedStateResponse = await request.get('/api/emotion/state');
  const appliedState = await appliedStateResponse.json() as EmotionStateResponse;
  expect(Object.values(appliedState.vector).every((value) => value >= 0 && value <= 1)).toBe(true);
  const events = await (await request.get('/api/emotion/events')).json();
  expect(events.some((event: { engine: string }) => event.engine === 'llm_assisted')).toBe(true);

  await page.getByRole('button', { name: '刷新分析记录' }).click();
  await expect(page.getByText(/已应用受本地约束的分析建议/)).toBeVisible();

  await page.getByRole('button', { name: '撤回远程分析授权' }).click();
  await expect(page.getByText(/当前授权状态：revoked/)).toBeVisible();
  const beforeRevokeConcern = appliedState.vector.concern;
  await page.getByLabel('输入消息').fill('我需要帮助 token=e2e-post-revoke-secret');
  await page.getByRole('button', { name: '发送' }).click();
  await expect.poll(async () => {
    const response = await request.get('/api/emotion/state');
    const state = await response.json() as EmotionStateResponse;
    return state.vector.concern;
  }).toBeGreaterThan(beforeRevokeConcern);

  expect((await getFakeProviderState(request)).request_count).toBe(1);
  const audits = await (await request.get('/api/emotion/analysis/audits')).json();
  expect(audits).toHaveLength(1);
  expect(serverErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
});

test('emotion state is global, persistent, disableable, and resettable', async ({ page, request }) => {
  const resetResponse = await request.post('/api/emotion/reset');
  expect(resetResponse.ok()).toBe(true);
  const baseline = await resetResponse.json() as { version: number };
  const consoleErrors: string[] = [];
  const serverErrors: string[] = [];
  page.on('console', (message) => { if (message.type() === 'error') consoleErrors.push(message.text()); });
  page.on('pageerror', (error) => consoleErrors.push(error.message));
  page.on('response', (response) => { if (response.status() >= 500) serverErrors.push(`${response.status()} ${response.url()}`); });

  await page.goto('/');
  await expect(page.getByRole('heading', { name: '情感表达状态' })).toBeVisible();
  await expect(page.getByText(/信任倾向.*0\.40/)).toBeVisible();

  await page.getByRole('button', { name: '新建会话' }).click();
  await page.getByLabel('输入消息').fill('谢谢你认真听我说。');
  await page.getByRole('button', { name: '发送' }).click();
  await expect(page.getByText(/信任倾向.*0\.43/)).toBeVisible();

  await page.getByRole('button', { name: '新建会话' }).click();
  await expect(page.getByText(/信任倾向.*0\.43/)).toBeVisible();
  await page.reload();
  await expect(page.getByText(/信任倾向.*0\.43/)).toBeVisible();

  const toggle = page.getByLabel('启用情感表达状态');
  await toggle.click();
  await expect(toggle).not.toBeChecked();
  await expect(page.getByText(new RegExp(`版本 ${baseline.version + 2}`))).toBeVisible();
  await page.getByLabel('输入消息').fill('你真蠢，闭嘴。');
  await page.getByRole('button', { name: '发送' }).click();
  await expect(page.getByText(new RegExp(`版本 ${baseline.version + 2}`))).toBeVisible();

  await toggle.click();
  await expect(toggle).toBeChecked();
  await page.getByRole('button', { name: '重置状态' }).click();
  await page.getByRole('button', { name: '确认重置' }).click();
  await expect(page.getByText(/信任倾向.*0\.40/)).toBeVisible();
  await expect(page.getByText(/用户手动重置/).first()).toBeVisible();

  expect(serverErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
});
