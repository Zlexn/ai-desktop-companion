import { defineConfig, devices } from '@playwright/test';

const backendPort = Number(process.env.E2E_BACKEND_PORT ?? 18100);
const frontendPort = Number(process.env.E2E_FRONTEND_PORT ?? 15173);
const databaseUrl = process.env.E2E_DATABASE_URL ?? `sqlite:///./test-results/e2e-${process.pid}.db`;
const backendUrl = `http://127.0.0.1:${backendPort}`;
const frontendUrl = `http://127.0.0.1:${frontendPort}`;

export default defineConfig({
  testDir: './e2e',
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
      command: `..\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --app-dir ..\\backend --host 127.0.0.1 --port ${backendPort} --no-access-log`,
      url: `${backendUrl}/health`,
      reuseExistingServer: false,
      timeout: 20_000,
      env: {
        APP_ENV: 'test',
        DATABASE_URL: databaseUrl,
        LLM_PROVIDER: 'fake',
        LLM_MODEL: 'test-model',
        FAKE_PROVIDER_MODE: 'ok',
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
      },
    },
  ],
});
