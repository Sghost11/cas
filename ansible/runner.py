from __future__ import annotations

import os
from pathlib import Path

import ansible_runner


def run_playbook(
    playbook: str,
    extra_vars: dict,
    device_ip: str,
    limit: str | None = None,
) -> dict:
    base_dir = Path(__file__).resolve().parent
    inventory_path = os.environ.get(
        "NETAUTO_INVENTORY",
        str(base_dir / "inventory" / "generated.ini"),
    )
    result = ansible_runner.run(
        private_data_dir=str(base_dir),
        playbook=f"playbooks/{playbook}",
        inventory=inventory_path,
        extravars={"device_ip": device_ip, **extra_vars},
        limit=limit or device_ip,
        envvars={"ANSIBLE_CONFIG": str(base_dir / "ansible.cfg")},
    )
    return {
        "status": result.status,
        "rc": result.rc,
        "events": result.stats,
    }
