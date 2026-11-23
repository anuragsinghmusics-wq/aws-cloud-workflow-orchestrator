#!/usr/bin/env bash
# Generates self-signed TLS certificates for local production HTTPS simulation
set -euo pipefail

CERT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "${CERT_DIR}"

if [[ -f "${CERT_DIR}/server.crt" && -f "${CERT_DIR}/server.key" ]]; then
    echo "TLS certificates already exist in ${CERT_DIR}."
    exit 0
fi

echo "Generating 2048-bit RSA self-signed TLS certificate..."

openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout "${CERT_DIR}/server.key" \
    -out "${CERT_DIR}/server.crt" \
    -subj "/C=US/ST=Cloud/L=Orchestrator/O=Enterprise/OU=Platform/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,DNS:orchestrator.local,IP:127.0.0.1"

chmod 600 "${CERT_DIR}/server.key"
chmod 644 "${CERT_DIR}/server.crt"

echo "TLS certificates successfully generated at ${CERT_DIR}."
