# Server Dashboard

A Flask-based server management dashboard — live system stats, Docker container controls, and AdGuard Home monitoring.

## Features
- Real-time CPU, RAM, disk, and network stats
- Start / stop / restart Docker containers
- AdGuard Home DNS monitoring
- Token-based auth for sensitive actions (shutdown/restart)

## Requirements
- Python 3.9+
- Docker installed and running
- AdGuard Home (optional, only needed if using that monitoring feature)

## Installation

1. Clone the repo:
   ```bash
   git clone https://github.com/Server-Cracker/Server-Dashboard.git
   cd Server-Dashboard
   ```

2. Create and activate a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Set your dashboard token (copy the example and edit it):
   ```bash
   cp .env.example .env
   nano .env   # or use sed to set your own token
   ```
   Replace `changeme_to_a_long_random_string` with a real random token. This is required to shut down or restart services from the dashboard UI.

5. Run the dashboard:
   ```bash
   export $(cat .env | xargs)
   python3 app.py
   ```
   By default it runs on `http://0.0.0.0:5050`. Open `http://<server-ip>:5050` in a browser.

6. In the dashboard UI, paste the same token from `.env` into the "Dashboard token" field so restart/shutdown actions are authorized.

## Run as a systemd service (recommended for always-on servers)

```bash
sudo cp server-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable server-dashboard
sudo systemctl start server-dashboard
```

Check status and logs:
```bash
sudo systemctl status server-dashboard
journalctl -u server-dashboard -f
```

**Note:** the service file loads secrets from `/home/server/Server-Dashboard/.env` via `EnvironmentFile=`. Make sure that file exists on the server before starting the service, and that it is never committed to Git (it's already in `.gitignore`).

## Security notes
- Never commit `.env` — it holds your real dashboard token.
- Change the default example token before deploying.
- Consider putting this behind a reverse proxy (e.g. Caddy/Nginx) with HTTPS if exposing it beyond your LAN.
