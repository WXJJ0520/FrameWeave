import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 开发时统一经本地后端访问素材与接口；生产构建由同一个后端托管。
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:8765' } },
});
