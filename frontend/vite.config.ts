import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from "path"

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
        // While the Python backend is still booting (loading AI models), the
        // proxy target refuses connections. Respond with a consistent, retryable
        // 503 instead of letting the socket reset — the reset surfaces to the
        // browser inconsistently (sometimes a 500), which the frontend can't
        // reliably retry. The api.ts fetcher retries on any 5xx.
        configure: (proxy: any) => {
          proxy.on('error', (_err: any, _req: any, res: any) => {
            if (res && typeof res.writeHead === 'function' && !res.headersSent) {
              res.writeHead(503, { 'Content-Type': 'application/json' });
              res.end(JSON.stringify({ detail: 'Backend starting up' }));
            }
          });
        },
      }
    }
  }
})
