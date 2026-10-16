#!/usr/bin/env bash
# Обновление программы до последней версии из GitHub. Запускать от root.
set -euo pipefail
cd /srv/kanon/app
/srv/kanon/app/deploy/backup.sh                     # сначала резервная копия
sudo -u kanon git pull --ff-only
sudo -u kanon .venv/bin/pip install -q -r requirements.txt -c requirements.lock
set -a; . /etc/kanon/kanon.env; set +a
sudo -E -u kanon .venv/bin/python manage.py migrate --noinput
sudo -E -u kanon .venv/bin/python manage.py load_initial_data
sudo -E -u kanon .venv/bin/python manage.py collectstatic --noinput -v0
sudo -E -u kanon .venv/bin/python manage.py check --deploy --fail-level WARNING
systemctl restart kanon
sleep 2
curl -fsS -H "X-Forwarded-Proto: https" -H "Host: ${KANON_ALLOWED_HOSTS%%,*}" http://127.0.0.1:8001/health/ && echo " — программа работает"
