/// <reference types="vitest" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// 开发期 /api 代理（09 轮本机联调开启，target 后端 8000）：
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: true } } },
  build: {
    sourcemap: false,
    chunkSizeWarningLimit: 1500,
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: false,
    css: false,
  },
});
