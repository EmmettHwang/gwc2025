module.exports = {
  apps: [
    {
      name: 'bhhs-backend',
      script: 'python3',
      args: '-m uvicorn main:app --host 0.0.0.0 --port 8000',
      cwd: '/usr/minilms/backend',
      env: {
        PYTHONUNBUFFERED: '1'
      },
      watch: false,
      instances: 1,
      exec_mode: 'fork',
      max_restarts: 5,
      restart_delay: 2000
    }
  ]
}
