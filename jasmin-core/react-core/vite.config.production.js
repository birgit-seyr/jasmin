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
    host: '0.0.0.0',
    strictPort: true,
  },
  build: {
    outDir: 'dist',
    sourcemap: false, // No source maps in production
    minify: 'terser',
    terserOptions: {
      compress: {
        drop_console: true,    // Remove console.* calls
        drop_debugger: true,   // Remove debugger statements
        pure_funcs: ['console.log', 'console.info', 'console.debug', 'console.trace']
      },
      mangle: {
        safari10: true
      }
    },
    rollupOptions: {
      output: {
        // Function form is required under Vite 5/6 — the historical
        // object form silently produces an empty ``vendor-react``
        // chunk (the chunk file emits, but React + React-DOM end up
        // inlined into the main app chunk instead of split out).
        // See the matching function-form impl in vite.config.js.
        // Note ``antd`` + ``rc-*`` get their own chunk to dedupe
        // shared ant-design internals across lazy page chunks.
        manualChunks(id) {
          if (id.includes('node_modules/@react-pdf/')) return 'vendor-pdf';
          if (id.includes('node_modules/react-router')) return 'vendor-router';
          if (
            id.includes('node_modules/axios/') ||
            id.includes('node_modules/@tanstack/react-query')
          ) {
            return 'vendor-api';
          }
          if (
            id.includes('node_modules/antd/') ||
            id.includes('node_modules/@ant-design/') ||
            id.includes('node_modules/rc-')
          ) {
            return 'vendor-antd';
          }
          // Match ``react`` + ``react-dom`` but NOT ``react-router``,
          // ``react-i18next``, ``react-pdf``, etc.
          if (
            id.includes('node_modules/react/') ||
            id.includes('node_modules/react-dom/')
          ) {
            return 'vendor-react';
          }
        },
        chunkFileNames: 'assets/js/[name]-[hash].js',
        entryFileNames: 'assets/js/[name]-[hash].js',
        assetFileNames: 'assets/[ext]/[name]-[hash].[ext]'
      }
    },
    // PDF rendering (@react-pdf/renderer) is genuinely large and lives in its
    // own lazy chunk; the main bundle is also above 1MB. Both are acceptable
    // for an authenticated-staff SPA. Raise threshold to silence cosmetic warning.
    chunkSizeWarningLimit: 1800,
    cssCodeSplit: true,
    assetsInlineLimit: 4096, // 4kb - inline small assets as base64
  },
  // Optimizations
  optimizeDeps: {
    include: ['react', 'react-dom', 'react-router-dom']
  }
})