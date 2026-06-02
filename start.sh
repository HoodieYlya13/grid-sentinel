#!/bin/bash

redis-server --daemonize yes

cd /app/django_control_plane

python manage.py migrate

export CONTROL_PLANE_URL="http://127.0.0.1:7860"

(
  sleep 5
  python /app/mock_agent/mock_agent.py grid-worker-01 &
  python /app/mock_agent/mock_agent.py grid-worker-02 &
) &

python manage.py runserver 0.0.0.0:7860
