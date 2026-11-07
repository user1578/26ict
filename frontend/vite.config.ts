import { fileURLToPath, URL } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// 开发代理：浏览器只请求同源 /api/...，由本机 Vite 代理在服务端注入 X-Tool-Key。
// 密钥只从启动进程的环境变量读取，绝不放 VITE_ 变量，避免打进浏览器包。
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = process.env.TRAVELGUARD_API_BASE ?? env.TRAVELGUARD_API_BASE ?? 'http://127.0.0.1:8000'
  const toolKey =
    process.env.TRAVELGUARD_TOOL_KEY ?? env.TRAVELGUARD_TOOL_KEY ?? process.env.TRAVELGUARD_TOOL_API_KEY ?? ''

  return {
    plugins: [react()],
    server: {
      // 允许从仓库根目录 data/ 静态导入（C 侧数据三件套的规范位置在仓库根）
      fs: { allow: [fileURLToPath(new URL('..', import.meta.url))] },
      proxy: {
        '/api': {
          target,
          changeOrigin: true,
          headers: toolKey ? { 'X-Tool-Key': toolKey } : {},
        },
      },
    },
  }
})
