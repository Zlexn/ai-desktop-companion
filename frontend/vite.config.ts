import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

const backendProxyTarget = process.env.BACKEND_PROXY_TARGET || 'http://127.0.0.1:8000';

const longProxyTimeoutMs = Number(process.env.BACKEND_PROXY_TIMEOUT_MS || 300_000);

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: backendProxyTarget,
        changeOrigin: true,
        timeout: longProxyTimeoutMs,
        proxyTimeout: longProxyTimeoutMs,
      },
      '/health': {
        target: backendProxyTarget,
        changeOrigin: true,
        timeout: longProxyTimeoutMs,
        proxyTimeout: longProxyTimeoutMs,
      },
    },
  },
  test: {
    environment: 'jsdom',
    exclude: ['e2e/**', 'node_modules/**', 'dist/**', '.claude-*.test.mjs'],
    setupFiles: './src/testSetup.ts',
  },
});
