#!/usr/bin/env bash
set -euo pipefail

python - <<'PY'
import os
import time

import psycopg2

host = os.environ.get("POSTGRES_HOST", "db")
port = int(os.environ.get("POSTGRES_PORT", "5432"))
name = os.environ.get("POSTGRES_DB", "netauto")
user = os.environ.get("POSTGRES_USER", "netauto")
password = os.environ.get("POSTGRES_PASSWORD", "netauto")

for _ in range(60):
    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            dbname=name,
            user=user,
            password=password,
        )
        conn.close()
        break
    except Exception:
        time.sleep(1)
else:
    raise SystemExit("PostgreSQL not ready")
PY

python - <<'PY'
import os
from pathlib import Path

base_dir = Path(__file__).resolve().parent
inventory_path = base_dir / "ansible" / "inventory" / "generated.ini"
vault_script = """#!/usr/bin/env bash
echo "${NETAUTO_VAULT_PASSWORD:-}"
"""
vault_path = Path("/app/ansible/vault_pass.sh")
vault_path.write_text(vault_script, encoding="utf-8")
vault_path.chmod(0o700)

switch_ips = os.environ.get("SWITCH_IPS", "")
switch_user = os.environ.get("SWITCH_USER", "admin")
switch_pass = os.environ.get("SWITCH_PASS", "")

if switch_ips:
    entries = []
    host_vars = []
    for raw in switch_ips.split(","):
        raw = raw.strip()
        if not raw:
            continue
        port = "22"
        if "@" in raw:
            host, ip_port = raw.split("@", 1)
            hostname = host.strip()
            ip_port = ip_port.strip()
        else:
            ip_port = raw
            hostname = None

        if ":" in ip_port:
            ip, port = ip_port.rsplit(":", 1)
            ip = ip.strip()
            port = port.strip() or "22"
        else:
            ip = ip_port.strip()

        if not hostname:
            hostname = f"switch-{ip.split('.')[-1]}"
        entries.append(
            f"{hostname} ansible_host={ip} ansible_port={port} ansible_user={switch_user} "
            "ansible_connection=ssh "
            "ansible_ssh_common_args='-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
            "-o KexAlgorithms=+diffie-hellman-group1-sha1 -o HostKeyAlgorithms=+ssh-rsa "
            "-o Ciphers=+aes128-cbc -o PasswordAuthentication=yes -o PubkeyAuthentication=no "
            "-o KbdInteractiveAuthentication=yes -o PreferredAuthentications=password,keyboard-interactive' "
            "ansible_ssh_executable=/usr/bin/ssh"
        )
        host_vars.append((hostname, ip))

    lines = ["[real]"] + entries + ["", "[all:vars]", "ansible_network_os=ios"]
    if switch_user:
        lines.append(f"ansible_user={switch_user}")
    if switch_pass:
        lines.append(f"ansible_password={switch_pass}")
    inventory_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

if [ "${NETAUTO_RUN_MIGRATIONS:-1}" = "1" ]; then
  python manage.py makemigrations
  python manage.py migrate
fi

if [ "${NETAUTO_SEED_DEVICES:-1}" = "1" ]; then
  python manage.py seed_devices
fi

exec "$@"
