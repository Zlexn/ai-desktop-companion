import { resolve } from 'node:path';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';
import {
  DESKTOP_CSP_NONCE,
  DESKTOP_DEV_HOST,
  DESKTOP_DEV_ORIGIN,
  DESKTOP_DEV_PORT,
} from './dev-origin.mjs';

const backendProxyTarget = process.env.BACKEND_PROXY_TARGET || 'http://127.0.0.1:8000';

const longProxyTimeoutMs = Number(process.env.BACKEND_PROXY_TIMEOUT_MS || 300_000);

export default defineConfig({
  plugins: [react()],
  html: { cspNonce: DESKTOP_CSP_NONCE },
  build: {
    rollupOptions: {
      input: {
        chat: resolve(import.meta.dirname, 'index.html'),
        pet: resolve(import.meta.dirname, 'pet.html'),
      },
    },
  },
  server: {
    host: DESKTOP_DEV_HOST,
    port: DESKTOP_DEV_PORT,
    strictPort: true,
    origin: DESKTOP_DEV_ORIGIN,
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
