import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig, devices } from '@playwright/test';
import { resolvePythonCommand } from './playwrightPython';
import { resolveE2EDatabase } from './playwrightDatabase';

const backendPort = Number(process.env.E2E_BACKEND_PORT ?? 18100);
const frontendPort = Number(process.env.E2E_FRONTEND_PORT ?? 15173);
const fakeDeepSeekPort = Number(process.env.E2E_FAKE_DEEPSEEK_PORT ?? 18101);
process.env.E2E_FAKE_DEEPSEEK_PORT = String(fakeDeepSeekPort);
const frontendDir = fileURLToPath(new URL('.', import.meta.url));
const defaultDatabasePath = resolve(frontendDir, 'test-results', `e2e-${process.pid}.db`);
const database = resolveE2EDatabase({
  databaseUrl: process.env.E2E_DATABASE_URL,
  databasePath: process.env.E2E_DATABASE_PATH,
  defaultDatabasePath,
});
const databasePath = database.databasePath;
const databaseUrl = database.databaseUrl;
process.env.E2E_DATABASE_PATH = databasePath;
const backendUrl = `http://127.0.0.1:${backendPort}`;
const frontendUrl = `http://127.0.0.1:${frontendPort}`;
const localVenvPython = resolve(frontendDir, '..', '.venv', 'Scripts', 'python.exe');
const pythonCommand = resolvePythonCommand({
  explicitPython: process.env.E2E_PYTHON,
  localVenvPython,
  localVenvExists: existsSync(localVenvPython),
});

export default defineConfig({
  testDir: './e2e',
  globalTeardown: './playwright.global-teardown.ts',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: frontendUrl,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'msedge',
      use: { ...devices['Desktop Edge'], channel: 'msedge' },
    },
  ],
  webServer: [
    {
      command: `${pythonCommand} -m uvicorn scripts.fake_deepseek_emotion_server:app --app-dir .. --host 127.0.0.1 --port ${fakeDeepSeekPort} --no-access-log`,
      url: `http://127.0.0.1:${fakeDeepSeekPort}/__test__/state`,
      reuseExistingServer: false,
      timeout: 20_000,
    },
    {
      command: `${pythonCommand} -m uvicorn app.main:app --app-dir ..\\backend --host 127.0.0.1 --port ${backendPort} --no-access-log`,
      url: `${backendUrl}/health`,
      reuseExistingServer: false,
      timeout: 20_000,
      env: {
        APP_ENV: 'test',
        DATABASE_URL: databaseUrl,
        LLM_PROVIDER: 'fake',
        LLM_MODEL: 'test-model',
        FAKE_PROVIDER_MODE: 'ok',
        TTS_PROVIDER: 'fake',
        TTS_FAKE_MODE: 'ok',
        TTS_DEFAULT_VOICE: 'fake-default',
        EMOTION_ANALYSIS_ENABLED: 'true',
        EMOTION_ANALYSIS_PROVIDER: 'deepseek',
        EMOTION_ANALYSIS_MODEL: 'stage4c-e2e-model',
        EMOTION_ANALYSIS_MAX_RETRIES: '0',
        DEEPSEEK_API_KEY: 'stage4c-e2e-token',
        DEEPSEEK_BASE_URL: `http://127.0.0.1:${fakeDeepSeekPort}`,
      },
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${frontendPort} --mode test`,
      url: frontendUrl,
      reuseExistingServer: false,
      timeout: 20_000,
      env: {
        BACKEND_PROXY_TARGET: backendUrl,
        VITE_ENABLE_MEMORY_LOAD_IN_TEST: '1',
        VITE_ENABLE_EMOTION_LOAD_IN_TEST: '1',
      },
    },
  ],
});
