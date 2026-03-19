from django.db import models


class Site(models.Model):
    SITE_STANDARD = "STANDARD"
    SITE_LOCAL_CONTROLLER = "LOCAL_CTRL"

    SITE_TYPES = [
        (SITE_STANDARD, "Standard"),
        (SITE_LOCAL_CONTROLLER, "Local Controller"),
    ]

    name = models.CharField(max_length=120, unique=True)
    type = models.CharField(max_length=20, choices=SITE_TYPES, default=SITE_STANDARD)
    description = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.name


class Device(models.Model):
    hostname = models.CharField(max_length=120)
    ip = models.GenericIPAddressField()
    model = models.CharField(max_length=120, blank=True)
    os_version = models.CharField(max_length=120, blank=True)
    serial = models.CharField(max_length=120, blank=True)
    device_type = models.CharField(max_length=120, blank=True)
    site = models.ForeignKey(Site, on_delete=models.SET_NULL, null=True, blank=True)
    last_sync = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.hostname} ({self.ip})"


class Port(models.Model):
    device = models.ForeignKey(Device, on_delete=models.CASCADE)
    interface = models.CharField(max_length=64)
    status = models.CharField(max_length=16, blank=True)
    protocol = models.CharField(max_length=16, blank=True)
    vlan = models.IntegerField(null=True, blank=True)
    mode = models.CharField(max_length=16, blank=True)
    description = models.CharField(max_length=255, blank=True)
    speed = models.CharField(max_length=32, blank=True)
    duplex = models.CharField(max_length=16, blank=True)
    mac_address = models.CharField(max_length=64, blank=True)
    cdp_neighbor = models.CharField(max_length=255, blank=True)
    has_port_security = models.BooleanField(default=False)
    validation_action = models.CharField(max_length=64, blank=True)
    validation_reason = models.TextField(blank=True)
    validation_category = models.CharField(max_length=64, blank=True)
    last_change_request_id = models.IntegerField(null=True, blank=True)
    last_change_approved_by = models.CharField(max_length=150, blank=True)
    last_change_approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("device", "interface")

    def __str__(self) -> str:
        return f"{self.device.hostname}:{self.interface}"
