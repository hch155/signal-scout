#!/bin/bash

# Load env variables
source ../.env

export SSL_CERT_PATH
export SSL_KEY_PATH

# Print out the values to verify
echo "Certificate Path: $SSL_CERT_PATH"
echo "Key Path: $SSL_KEY_PATH"

# Use Python to read the SSL paths into variables
SSL_CERT_PATH=$(python3 -c "import os; print(os.getenv('SSL_CERT_PATH'))")
SSL_KEY_PATH=$(python3 -c "import os; print(os.getenv('SSL_KEY_PATH'))")

# Print out the values to verify
echo "Certificate Path after Python read: $SSL_CERT_PATH"
echo "Key Path after Python read: $SSL_KEY_PATH"

# Start Gunicorn with SSL configurations
gunicorn --certfile=$SSL_CERT_PATH --keyfile=$SSL_KEY_PATH --bind 192.168.1.17:8080 app:app


