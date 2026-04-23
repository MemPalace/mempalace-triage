const path = require('node:path');

const root = __dirname;
const logsDir = path.join(root, 'logs');

module.exports = {
  apps: [
    {
      name: 'mempalace-server-dev',
      cwd: path.join(root, 'server'),
      script: 'bun',
      args: '--watch src/index.ts',
      interpreter: 'none',
      instances: 1,
      exec_mode: 'fork',
      autorestart: true,
      watch: false,
      kill_timeout: 10000,
      env: {
        NODE_ENV: 'development',
        PORT: '7800',
        POLLER_ENABLED: 'true',
      },
      out_file: path.join(logsDir, 'server-dev-out.log'),
      error_file: path.join(logsDir, 'server-dev-err.log'),
      merge_logs: true,
      time: true,
    },
    {
      name: 'mempalace-dashboard-dev',
      cwd: path.join(root, 'dashboard'),
      script: 'bun',
      args: 'run start -- --host 0.0.0.0 --port 4200',
      interpreter: 'none',
      instances: 1,
      exec_mode: 'fork',
      autorestart: true,
      watch: false,
      env: {
        NODE_ENV: 'development',
      },
      out_file: path.join(logsDir, 'dashboard-dev-out.log'),
      error_file: path.join(logsDir, 'dashboard-dev-err.log'),
      merge_logs: true,
      time: true,
    },
  ],
};
