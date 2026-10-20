#!/usr/bin/env bash
# Instalacja bota na serwerze z Ubuntu/Debianem (np. Oracle Cloud Free, Mikrus, dowolny VPS).
# Użycie (jako root, w folderze typy-bot z plikiem .env):
#   sudo bash deploy/install.sh
set -euo pipefail

apt-get update -y
apt-get install -y python3 python3-venv rsync
id typybot >/dev/null 2>&1 || useradd --system --create-home typybot

mkdir -p /opt/typy-bot
rsync -a --exclude venv --exclude data ./ /opt/typy-bot/
python3 -m venv /opt/typy-bot/venv
/opt/typy-bot/venv/bin/pip install -q -r /opt/typy-bot/requirements.txt
chown -R typybot:typybot /opt/typy-bot
chmod 600 /opt/typy-bot/.env

cp deploy/typy-bot.service /etc/systemd/system/typy-bot.service
systemctl daemon-reload
systemctl enable --now typy-bot
systemctl --no-pager status typy-bot
echo "Gotowe. Logi: journalctl -u typy-bot -f"
