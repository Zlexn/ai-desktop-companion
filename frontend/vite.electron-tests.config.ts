import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    include: ['electron/**/*.test.ts', 'src/desktop/electronSetup.test.ts'],
    exclude: ['node_modules/**', 'dist/**'],
  },
});
