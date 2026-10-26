import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', ws: true },
      '/assets': { target: 'http://127.0.0.1:8000' },
    },
  },
  // Pages: the shared room with connecting, room photos, the room splat spike (#92), and the
  // headless page Python renders room views with (#98).
  build: {
    rolldownOptions: {
      input: { main: 'index.html', photos: 'photos.html', splat: 'splat.html', render: 'render.html' },
    },
  },
  // ONNX Runtime's bundle needs module features in the depth worker; workers start as modules anyway.
  worker: { format: 'es' },
});
