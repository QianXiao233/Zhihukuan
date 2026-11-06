import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

/**
 * 后端地址：必须与 reservoir-platform/backend/src/main/resources/application.yml 的 server.port 一致。
 * 三处代理共用这一个常量，避免像之前那样三个 target 各写一个端口、改一处漏两处。
 * 需要临时指向别的机器时，用环境变量覆盖即可：
 *   VITE_BACKEND_ORIGIN=http://192.168.2.7:8085 npm run dev
 */
const BACKEND_ORIGIN = process.env.VITE_BACKEND_ORIGIN || 'http://127.0.0.1:8085'

/**
 * MQTT broker 的 WebSocket 端点，供前端 `mqttUrl()` 的同源反代使用。
 *
 * 生产环境由 Nginx 把 `/mqtt` 反代到 EMQX 的 8083；本地开发没有 Nginx，
 * 就由 Vite 代劳。所以这里默认指向本地 broker 的 ws 监听端口。
 * 换机器时用 VITE_MQTT_WS_ORIGIN 覆盖即可。
 */
const MQTT_WS_ORIGIN = process.env.VITE_MQTT_WS_ORIGIN || 'ws://127.0.0.1:8083'

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
      // MQTT over WebSocket：前端 mqttUrl() 在未显式配置时用同源 /mqtt
      '/mqtt': {
        target: MQTT_WS_ORIGIN,
        ws: true,
        changeOrigin: true,
      },
    },
  },
})
