import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from devices.models import Device
from devices.services import sync_device


class Command(BaseCommand):
    help = "Continuously sync devices on a schedule"

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=int, default=300)

    def handle(self, *args, **options):
        interval = options["interval"]
        self.stdout.write(self.style.SUCCESS(f"Autosync every {interval}s"))
        while True:
            for device in Device.objects.all():
                result, _ports = sync_device(device)
                device.last_sync = timezone.now()
                device.save(update_fields=["last_sync"])
                status = result.get("status")
                self.stdout.write(f"[{timezone.now().isoformat()}] {device.hostname} {status}")
            time.sleep(interval)
