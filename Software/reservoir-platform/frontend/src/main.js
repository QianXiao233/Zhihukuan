import { createApp, h } from 'vue'
import { ConfigProvider } from 'ant-design-vue'
import 'ant-design-vue/dist/reset.css'
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'
import App from './App.vue'
import router from './router/index.js'
import { initPreferences } from './composables/usePreferences.js'
import './index.css'
import './mobile.css'

// antd 中文语言包
dayjs.locale('zh-cn')

// 应用用户保存的字号偏好
initPreferences()

const app = createApp({
  render: () =>
    h(
      ConfigProvider,
      {
        locale: zhCN,
        // 政务海洋风格：政务蓝主色 + 系统字体栈
        theme: {
          token: {
            colorPrimary: '#1667d6',
            colorInfo: '#12a8c4',
            colorLink: '#12a8c4',
            borderRadius: 10,
            fontFamily:
              '-apple-system, "PingFang SC", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif',
          },
        },
      },
      { default: () => h(App) },
    ),
})

app.use(router)
app.mount('#app')
