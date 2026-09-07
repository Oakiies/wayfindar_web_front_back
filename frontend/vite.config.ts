import fs from 'node:fs';
import path from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import basicSsl from '@vitejs/plugin-basic-ssl';

const enableHttps = process.env.VITE_DEV_HTTPS === '1';
const backendProxyTarget = String(process.env.VITE_BACKEND_TARGET ?? 'http://127.0.0.1:5000').trim();

function resolveHttpsConfig() {
  const certDir = path.resolve(__dirname, 'certs');
  const keyPath = path.join(certDir, 'dev.key');
  const certPath = path.join(certDir, 'dev.crt');

  if (!fs.existsSync(keyPath) || !fs.existsSync(certPath)) {
    console.warn(
      '[vite] VITE_DEV_HTTPS=1 but certs/dev.key or certs/dev.crt is missing. Falling back to generated self-signed cert.'
    );
    return undefined;
  }

  return {
    key: fs.readFileSync(keyPath),
    cert: fs.readFileSync(certPath),
  };
}

const manualHttpsConfig = enableHttps ? resolveHttpsConfig() : undefined;
const useBasicSslFallback = enableHttps && !manualHttpsConfig;

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), ...(useBasicSslFallback ? [basicSsl()] : [])],
  server: {
    host: true,
    https: enableHttps ? (manualHttpsConfig ?? {}) : undefined,
    proxy: {
      '/api': {
        target: backendProxyTarget,
        changeOrigin: true,
        secure: false,
      },
      '/uploads': {
        target: backendProxyTarget,
        changeOrigin: true,
        secure: false,
      },
    },
  },
});
