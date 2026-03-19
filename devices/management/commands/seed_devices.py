import os

from django.core.management.base import BaseCommand

from devices.models import Device, Site


class Command(BaseCommand):
    help = "Seed sample devices for mock lab"

    def handle(self, *args, **options):
        switch_ips = os.environ.get("SWITCH_IPS", "")
        switch_sites = os.environ.get("SWITCH_SITES", "")
        if not switch_ips:
            self.stdout.write(self.style.WARNING("SWITCH_IPS not set, skipping seed"))
            return

        sites = [site.strip() for site in switch_sites.split(",") if site.strip()]
        ip_items = [item.strip() for item in switch_ips.split(",") if item.strip()]

        for idx, raw in enumerate(ip_items):
            if "@" in raw:
                host, ip_port = raw.split("@", 1)
                hostname = host.strip()
                ip_port = ip_port.strip()
            else:
                ip_port = raw
                hostname = None

            if ":" in ip_port:
                ip, _port = ip_port.rsplit(":", 1)
                ip = ip.strip()
            else:
                ip = ip_port.strip()

            if not hostname:
                hostname = f"switch-{ip.split('.')[-1]}"
            site_name = sites[idx] if idx < len(sites) else "LAB"
            site, _ = Site.objects.get_or_create(name=site_name, type=Site.SITE_STANDARD)
            Device.objects.get_or_create(
                hostname=hostname,
                ip=ip,
                defaults={"hostname": hostname, "ip": ip, "device_type": "ios", "site": site},
            )

        self.stdout.write(self.style.SUCCESS("Seeded devices from SWITCH_IPS"))
