#!/usr/bin/env bash
set -euo pipefail

ARCHIVE="netauto-offline-bundle.tar.gz"

if [ ! -f "${ARCHIVE}" ]; then
  echo "No existe ${ARCHIVE} en el directorio actual."
  exit 1
fi

tar -xzf "${ARCHIVE}"

if [ ! -f "netauto-all-images.tar" ]; then
  echo "No existe netauto-all-images.tar despues de extraer."
  exit 1
fi

podman load -i netauto-all-images.tar

if command -v podman-compose >/dev/null 2>&1; then
  podman-compose -f docker-compose.offline.yml up -d
else
  podman compose -f docker-compose.offline.yml up -d
fi

echo "Listo. UI: http://<IP_SERVIDOR>:8000/devices/ui/ops/"
