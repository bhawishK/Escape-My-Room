import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', ws: true },
      '/assets': { target: 'http://127.0.0.1:8000' },
    },
  },
  // ONNX Runtime's bundle needs module features in the depth worker; workers start as modules anyway.
  worker: { format: 'es' },
});
