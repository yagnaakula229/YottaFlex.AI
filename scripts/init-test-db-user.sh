#!/bin/sh

if [ -z "${YOTTAFLEX_TEST_DB_PASSWORD:-}" ]; then
    echo "YOTTAFLEX_TEST_DB_PASSWORD must be set" >&2
    exit 1
fi

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    --set=ON_ERROR_STOP=1 \
    --set=test_password="$YOTTAFLEX_TEST_DB_PASSWORD" <<'SQL'
CREATE ROLE yottaflex_ci
    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    PASSWORD :'test_password';
SQL

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    --set=ON_ERROR_STOP=1 \
    --command="CREATE DATABASE yottaflex_test OWNER yottaflex_ci"