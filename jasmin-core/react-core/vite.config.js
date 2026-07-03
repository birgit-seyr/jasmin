import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [
    react(),
  ],
  define: {
    global: 'globalThis',
    'process.env': {},
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      // New domain-first layout (see docs/frontend-structure-proposal.md):
      '@app': path.resolve(__dirname, './src/app'),
      '@shared': path.resolve(__dirname, './src/shared'),
      '@features': path.resolve(__dirname, './src/features'),
      '@hooks': path.resolve(__dirname, './src/shared/hooks'),
      '@routing': path.resolve(__dirname, './src/app/routing'),
      buffer: 'buffer/',
    }
  },
  server: {
    port: 3000,
    host: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
        ws: true,
        configure: (proxy, options) => {
          proxy.on('proxyReq', (proxyReq, req, res) => {
            const host = req.headers.host || 'localhost:3000';
            const parts = host.split('.');
            
            // Check if we have a subdomain (e.g., solawi.localhost:3000)
            if (parts.length >= 2 && parts[0] !== 'localhost') {
              const subdomain = parts[0];
              const backendHost = `${subdomain}.localhost:8000`;
              
              // Update the host header to point to correct backend
              proxyReq.setHeader('host', backendHost);
              
              console.log(`🔄 [Proxy] ${host} → ${backendHost}${req.url}`);
            } else {
              // Default to localhost:8000
              proxyReq.setHeader('host', 'localhost:8000');
            }
          });
          
          proxy.on('error', (err, req, res) => {
            console.error('❌ Proxy error:', err.message);
          });
        },
      },
      '/media': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
        configure: (proxy, options) => {
          proxy.on('proxyReq', (proxyReq, req, res) => {
            const host = req.headers.host || 'localhost:3000';
            const parts = host.split('.');
            if (parts.length >= 2 && parts[0] !== 'localhost') {
              const subdomain = parts[0];
              proxyReq.setHeader('host', `${subdomain}.localhost:8000`);
            }
          });
        },
      },
      '/static': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
        configure: (proxy, options) => {
          proxy.on('proxyReq', (proxyReq, req, res) => {
            const host = req.headers.host || 'localhost:3000';
            const parts = host.split('.');
            if (parts.length >= 2 && parts[0] !== 'localhost') {
              const subdomain = parts[0];
              proxyReq.setHeader('host', `${subdomain}.localhost:8000`);
            }
          });
        },
      },
    },
  },
  build: {
    minify: 'terser',
    terserOptions: {
      compress: {
        drop_console: true,
        drop_debugger: true,
      },
    },
    rollupOptions: {
      output: {
        // Function form is required under Vite 5/6 — the historical
        // object form silently produced an empty ``vendor`` chunk
        // (the chunk file emitted, but React + React-DOM ended up
        // inlined into the main app chunk instead of split out).
        // The function form matches against module IDs as Rollup
        // walks the dep graph and reliably co-locates packages into
        // the named chunk regardless of how callers import them.
        //
        // ``buffer`` deliberately NOT in any named chunk: main.jsx
        // imports it eagerly to polyfill ``globalThis.Buffer`` (used
        // by @react-pdf/renderer's image loader). Co-bundling it with
        // @react-pdf would force the entire 1.5 MB PDF chunk to load
        // on app boot. Letting Rollup place it on its own keeps the
        // heavy ``pdf`` chunk lazy until a PDF-using page is visited.
        manualChunks(id) {
          if (id.includes('node_modules/@react-pdf/')) return 'pdf';
          if (id.includes('node_modules/react-router')) return 'router';
          if (
            id.includes('node_modules/axios/') ||
            id.includes('node_modules/@tanstack/react-query')
          ) {
            return 'api';
          }
          // Ant Design + its underlying rc-* primitives + the CSS-in-JS
          // runtime, ALL into one chunk. Without this, ant-design's
          // shared internals (``rc-table``, ``rc-virtual-list``,
          // ``rc-select``, ``@ant-design/cssinjs``, ...) get duplicated
          // into every page chunk that imports an antd component.
          // Co-locating them means each lazy page pulls the antd chunk
          // once and reuses it.
          if (
            id.includes('node_modules/antd/') ||
            id.includes('node_modules/@ant-design/') ||
            id.includes('node_modules/rc-')
          ) {
            return 'antd';
          }
          // Match ``react`` + ``react-dom`` but NOT ``react-router``,
          // ``react-i18next``, ``react-pdf``, etc — those are their
          // own chunks or merge into the main bundle. The trailing
          // slash matters: ``node_modules/react/`` excludes
          // ``node_modules/react-anything-else/``.
          if (
            id.includes('node_modules/react/') ||
            id.includes('node_modules/react-dom/')
          ) {
            return 'vendor';
          }
        },
      },
    },
  }
})