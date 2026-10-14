#!/usr/bin/env bash
# Первый запуск Codespace: зависимости, база, данные ТГМУ, демо-входы.
set -euo pipefail
pip install --quiet -r requirements.txt
python manage.py migrate --noinput
python manage.py load_initial_data
python manage.py setup_demo
