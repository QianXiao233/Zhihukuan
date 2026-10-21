import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

/**
 * 后端地址：必须与 reservoir-platform/backend/src/main/resources/application.yml 的 server.port 一致。
 * 三处代理共用这一个常量，避免像之前那样三个 target 各写一个端口、改一处漏两处。
 * 需要临时指向别的机器时，用环境变量覆盖即可：
 *   VITE_BACKEND_ORIGIN=http://192.168.2.7:8085 npm run dev
 */
const BACKEND_ORIGIN = process.env.VITE_BACKEND_ORIGIN || 'http://127.0.0.1:8085'

export default defineConfig({
  plugins: [vue()],
  build: {
    // three 与 antd 体积较大，单独分包，避免主 chunk 过大
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        manualChunks: {
          three: ['three'],
          antd: ['ant-design-vue', '@ant-design/icons-vue'],
          vue: ['vue'],
        },
      },
    },
  },
  server: {
    host: true,
    port: 5173,
    proxy: {
      // 问答与平台接口（后端为 Spring Boot，融合后同进程承载）
      '/api': {
        target: BACKEND_ORIGIN,
        changeOrigin: true,
        ws: false,
      },
      // 登录 / 注册 / 令牌校验
      '/auth': {
        target: BACKEND_ORIGIN,
        changeOrigin: true,
      },
      // 健康检查
      '/health': {
        target: BACKEND_ORIGIN,
        changeOrigin: true,
      },
    },
  },
})
