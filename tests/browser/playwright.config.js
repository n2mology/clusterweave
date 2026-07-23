const { defineConfig } = require('@playwright/test');
const path = require('path');

module.exports = defineConfig({
  testDir: __dirname,
  timeout: 30_000,
  retries: 0,
  workers: 1,
  use: {
    browserName: 'chromium',
    headless: true,
  },
  webServer: {
    command: 'python3 -m http.server 4173 --bind 127.0.0.1 --directory web/static',
    cwd: path.resolve(__dirname, '../..'),
    url: 'http://127.0.0.1:4173/',
    reuseExistingServer: false,
  },
});
