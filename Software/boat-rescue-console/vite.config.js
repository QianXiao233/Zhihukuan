import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  root: 'dashboard',
  plugins: [react()],
  server: {
    watch: {
      /**
       * 忽略编辑器/工具链写入时产生的临时文件。
       *
       * 背景：某些编辑工具会在项目根目录写 `.Project.md.<pid>.<uuid>.tmpdir/`
       * 之类的临时目录，写完立即删除。Vite 的文件监视器恰好在这瞬间去 watch
       * 它，就会抛 `EBUSY: resource busy or locked`，而且这个错误会让整个
       * dev server（含 Node 串口服务）一起退出。
       *
       * 这里显式忽略临时文件，避免被工具的写入动作误杀。
       */
      ignored: [
        '**/*.tmp',
        '**/*.tmpdir/**',
        '**/.*.tmpdir/**',
        '**/*.swp',
        '**/*~',
      ],
    },
  },
});

