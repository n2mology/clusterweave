const { defineConfig } = require('@playwright/test');
const fs = require('fs');
const os = require('os');
const path = require('path');

const emptyBaseURL = 'http://127.0.0.1:4174';
const lifecycleBaseURL = 'http://127.0.0.1:4175';
const statePrefix = path.join(os.tmpdir(), 'clusterweave-playwright-real-server-');
const emptyStateDir = fs.mkdtempSync(statePrefix);
const lifecycleStateDir = fs.mkdtempSync(statePrefix);
const adminStateDir = fs.mkdtempSync(statePrefix);
const stateDirs = [emptyStateDir, lifecycleStateDir, adminStateDir];

process.once('exit', () => {
  for (const stateDir of stateDirs) {
    if (stateDir.startsWith(statePrefix)) {
      fs.rmSync(stateDir, { recursive: true, force: true });
    }
  }
});

function realServer(stateDir, port, fixture = '') {
  const baseURL = `http://127.0.0.1:${port}`;
  return {
    command: 'python3 -B tests/browser/real-server/run_server.py',
    cwd: path.resolve(__dirname, '../..'),
    env: {
      CLUSTERWEAVE_REAL_SERVER_DATA_DIR: stateDir,
      CLUSTERWEAVE_REAL_SERVER_PORT: String(port),
      CLUSTERWEAVE_REAL_SERVER_FIXTURE: fixture,
    },
    url: `${baseURL}/api/system/status`,
    reuseExistingServer: false,
    timeout: 30_000,
  };
}

module.exports = defineConfig({
  testDir: path.join(__dirname, 'real-server'),
  testMatch: ['idle_public.spec.js', 'job_lifecycle.spec.js', 'admin_access.spec.js'],
  timeout: 30_000,
  retries: 0,
  workers: 1,
  use: {
    baseURL: emptyBaseURL,
    browserName: 'chromium',
    headless: true,
  },
  webServer: [
    realServer(emptyStateDir, 4174),
    realServer(lifecycleStateDir, 4175, 'lifecycle'),
    realServer(adminStateDir, 4176, 'admin'),
  ],
});
