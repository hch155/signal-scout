#!/bin/bash

# Development server with HTTPS and auto-reload
# Access from your phone at: https://DEV_PHONE_IP:8080

cd "$(dirname "$0")/src"

CERT_PATH="../certs/localhost+2.pem"
KEY_PATH="../certs/localhost+2-key.pem"

echo "Starting dev server with HTTPS..."
echo "Access locally:      https://localhost:8080"
echo "Access from phone:   https://DEV_PHONE_IP:8080"
echo ""
echo "Note: Accept the certificate warning in browser (or run 'sudo mkcert -install' to trust automatically)"
echo ""

gunicorn --certfile=$CERT_PATH --keyfile=$KEY_PATH --bind 0.0.0.0:8080 --reload app:app
