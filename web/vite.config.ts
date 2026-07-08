import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/book-assets': 'http://127.0.0.1:7860',
      '/covers': 'http://127.0.0.1:7860',
    },
  },
  test: {
    environment: 'jsdom',
    exclude: ['node_modules/**', 'dist/**', 'e2e/**', 'test-results/**', 'playwright-report/**'],
    setupFiles: './src/test/setup.ts',
  },
});
