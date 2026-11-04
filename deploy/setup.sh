#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu VM (Oracle Cloud Always Free). Run as the default `ubuntu` user:
#   curl -fsSL https://raw.githubusercontent.com/doric2000/job-radar/main/deploy/setup.sh | bash
# Then put the secrets in ~/.config/job-radar.env and start the timer (the script prints how).
set -euo pipefail
sudo apt-get update -qq
sudo apt-get install -y -qq git python3-venv python3-pip >/dev/null
sudo timedatectl set-timezone Asia/Jerusalem || true

[ -d "$HOME/job-radar/.git" ] || git clone -q https://github.com/doric2000/job-radar.git "$HOME/job-radar"
cd "$HOME/job-radar"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
mkdir -p "$HOME/job-radar-state" "$HOME/.config"
cp requirements.txt "$HOME/job-radar-state/requirements.installed"

ENV="$HOME/.config/job-radar.env"
if [ ! -f "$ENV" ]; then
  cat > "$ENV" <<'EOF'
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
# optional: fine-grained GitHub token (repository doric2000/job-radar, Contents: read and write)
GH_PUSH_TOKEN=
EOF
fi
chmod 600 "$ENV"

sudo tee /etc/systemd/system/job-radar.service >/dev/null <<EOF
[Unit]
Description=Job Radar scan
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=$USER
ExecStart=/bin/bash $HOME/job-radar/deploy/run.sh
TimeoutStartSec=12min
EOF

sudo tee /etc/systemd/system/job-radar.timer >/dev/null <<'EOF'
[Unit]
Description=Job Radar scan every 5 minutes

[Timer]
OnCalendar=*:1/5
AccuracySec=10s

[Install]
WantedBy=timers.target
EOF
sudo systemctl daemon-reload

cat <<EOF

Installed. Next:
  1. nano ~/.config/job-radar.env     (fill in the Telegram values; save with Ctrl+O, Enter, Ctrl+X)
  2. bash ~/job-radar/deploy/run.sh   (one scan now, to check it works)
  3. sudo systemctl enable --now job-radar.timer
Logs: journalctl -u job-radar -n 50
EOF
