from __future__ import annotations

from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from devices.models import Device, Port
from devices.services import sync_device
from netauto.automation import run_playbook


TEST_PLAN = {
    "migrar": [
        ("TenGigabitEthernet1/0/9", "LAB-TEST-MIGRAR-1"),
        ("TenGigabitEthernet1/0/12", "LAB-TEST-MIGRAR-2"),
        ("TenGigabitEthernet1/0/14", "LAB-TEST-MIGRAR-3"),
        ("TenGigabitEthernet1/0/20", "LAB-TEST-MIGRAR-4"),
    ],
}


class Command(BaseCommand):
    help = "Aplica un escenario de pruebas 802.1X en puertos de laboratorio"

    def add_arguments(self, parser):
        parser.add_argument(
            "--device",
            default="switch-2",
            help="Hostname o IP del dispositivo (default: switch-2)",
        )
        parser.add_argument(
            "--skip-sync",
            action="store_true",
            help="No ejecutar sync/validacion al finalizar",
        )

    def handle(self, *args, **options):
        device_key = options["device"].strip()
        device = (
            Device.objects.filter(hostname=device_key).first()
            or Device.objects.filter(ip=device_key).first()
        )
        if not device:
            raise CommandError(f"No existe dispositivo con hostname/ip: {device_key}")

        config_lines: list[str] = []

        for interface, description in TEST_PLAN["migrar"]:
            config_lines.extend(
                [
                    f"interface {interface}",
                    f" description {description}",
                ]
            )

        result = run_playbook(
            playbook="deploy_config.yml",
            extra_vars={"config_lines": config_lines},
            device_ip=device.ip,
            limit=device.hostname or device.ip,
        )
        if result.get("rc") != 0:
            raise CommandError(f"Fallo aplicando escenario: rc={result.get('rc')}")

        self.stdout.write(self.style.SUCCESS("Escenario de pruebas aplicado en switch."))

        if options["skip_sync"]:
            return

        sync_result, _ports = sync_device(device)
        if sync_result.get("rc") != 0:
            raise CommandError(f"Sync fallo: rc={sync_result.get('rc')}")

        actions = Counter(
            (port.validation_action or "").upper() for port in Port.objects.filter(device=device)
        )
        self.stdout.write(f"Validacion por accion: {dict(actions)}")
