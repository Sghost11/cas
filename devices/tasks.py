from celery import shared_task

from devices.models import Device
from devices.services import apply_validation_to_ports, sync_device


@shared_task(bind=True)
def sync_device_task(self, device_id: int) -> dict:
    self.update_state(state="PROGRESS", meta={"percent": 5, "stage": "start"})
    device = Device.objects.get(pk=device_id)
    self.update_state(state="PROGRESS", meta={"percent": 20, "stage": "connecting"})
    result, _ports = sync_device(device)
    percent = 100 if result.get("rc") == 0 else 100
    self.update_state(state="PROGRESS", meta={"percent": percent, "stage": "done"})
    return result


@shared_task(bind=True)
def validate_device_task(self, device_id: int) -> dict:
    self.update_state(state="PROGRESS", meta={"percent": 10, "stage": "start"})
    device = Device.objects.get(pk=device_id)
    self.update_state(state="PROGRESS", meta={"percent": 40, "stage": "analyzing"})
    ports = apply_validation_to_ports(device)
    self.update_state(state="PROGRESS", meta={"percent": 100, "stage": "done"})
    return {"status": "ok", "ports": len(ports)}
