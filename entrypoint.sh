#!/bin/bash
set -e

# Если передан аргумент "cron", настраиваем планировщик
if [ "$1" = "cron" ]; then
    CRON_SCHEDULE="${CRON_SCHEDULE:-0 8 * * *}"
    echo "Setting up cron job: $CRON_SCHEDULE"

    # Экспортируем все переменные окружения в файл для cron
    printenv | grep -v "no_proxy" > /etc/environment

    # Создаём cron-задание
    echo "$CRON_SCHEDULE cd /app && /usr/local/bin/python main.py >> /var/log/medium_digest.log 2>&1" > /etc/cron.d/medium-digest
    chmod 0644 /etc/cron.d/medium-digest
    crontab /etc/cron.d/medium-digest

    # Создаём лог-файл
    touch /var/log/medium_digest.log

    echo "Cron job configured. Schedule: $CRON_SCHEDULE"
    echo "Logs: /var/log/medium_digest.log"

    # Запускаем cron в foreground и следим за логом
    cron
    exec tail -f /var/log/medium_digest.log
fi

# Иначе выполняем переданную команду (по умолчанию: python main.py)
exec "$@"
