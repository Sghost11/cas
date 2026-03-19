from django.conf import settings
from django.db import models

from devices.models import Device


class ChangeRequest(models.Model):
    STATUS_PENDING = "PENDING"
    STATUS_APPROVED = "APPROVED"
    STATUS_DEPLOYED = "DEPLOYED"
    STATUS_FAILED = "FAILED"
    STATUS_REJECTED = "REJECTED"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_DEPLOYED, "Deployed"),
        (STATUS_FAILED, "Failed"),
        (STATUS_REJECTED, "Rejected"),
    ]

    device = models.ForeignKey(Device, on_delete=models.CASCADE)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    ports_json = models.JSONField()
    generated_config = models.TextField(blank=True)
    site = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ChangeApproval(models.Model):
    change_request = models.ForeignKey(ChangeRequest, on_delete=models.CASCADE)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    comments = models.TextField(blank=True)
    approved_at = models.DateTimeField(auto_now_add=True)


class ChangeLog(models.Model):
    change_request = models.ForeignKey(ChangeRequest, on_delete=models.CASCADE)
    port_interface = models.CharField(max_length=64)
    field = models.CharField(max_length=64)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    deployed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    deployed_at = models.DateTimeField(auto_now_add=True)


class DeploymentResult(models.Model):
    change_request = models.ForeignKey(ChangeRequest, on_delete=models.CASCADE)
    success = models.BooleanField(default=False)
    ansible_output = models.TextField(blank=True)
    deployed_at = models.DateTimeField(auto_now_add=True)


class ConfigSnapshot(models.Model):
    change_request = models.ForeignKey(ChangeRequest, on_delete=models.CASCADE)
    device = models.ForeignKey(Device, on_delete=models.CASCADE)
    running_config = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
