#!/usr/bin/env bash
# Каждый запуск Codespace: поднять сервер в фоне на порту 8000.
nohup python manage.py runserver 0.0.0.0:8000 > /tmp/kanon.log 2>&1 &
echo "«Канон» запущен на порту 8000. Логины и пароль: cat .demo-logins.txt"
