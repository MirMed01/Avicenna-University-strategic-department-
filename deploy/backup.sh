#!/usr/bin/env bash
# Ежедневная резервная копия: база + загруженные файлы. Хранится 14 дней.
# cron (root): 30 2 * * * /srv/kanon/app/deploy/backup.sh >> /var/log/kanon-backup.log 2>&1
set -euo pipefail
DEST=/var/backups/kanon
STAMP=$(date +%Y-%m-%d_%H%M)
mkdir -p "$DEST"
chmod 700 "$DEST"
sudo -u postgres pg_dump -Fc kanon > "$DEST/kanon-db-$STAMP.dump"
tar -czf "$DEST/kanon-media-$STAMP.tar.gz" -C /srv/kanon media
find "$DEST" -type f -mtime +14 -delete
echo "$(date '+%F %T') резервная копия готова: $STAMP"
# Копию раз в неделю переносить на другой носитель / сервер — копия на том же диске не спасёт при поломке диска.
