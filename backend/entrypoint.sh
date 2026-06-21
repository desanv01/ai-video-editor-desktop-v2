#!/bin/sh
set -eu

mkdir -p \
  /data/videos \
  /data/uploads \
  /data/uploads/staging/native-imports/manifests \
  /data/uploads/orphaned-imports \
  /data/temp \
  /data/logs \
  /data/config \
  /data/backups \
  /data/proxies \
  /data/models

alembic -c /app/alembic.ini upgrade head

exec uvicorn main:app --host 0.0.0.0 --port 8000
