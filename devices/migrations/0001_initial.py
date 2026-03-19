from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Site",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("name", models.CharField(max_length=120, unique=True)),
                (
                    "type",
                    models.CharField(
                        choices=[("STANDARD", "Standard"), ("LOCAL_CTRL", "Local Controller")],
                        default="STANDARD",
                        max_length=20,
                    ),
                ),
                ("description", models.TextField(blank=True)),
            ],
        ),
        migrations.CreateModel(
            name="Device",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("hostname", models.CharField(max_length=120)),
                ("ip", models.GenericIPAddressField()),
                ("model", models.CharField(blank=True, max_length=120)),
                ("os_version", models.CharField(blank=True, max_length=120)),
                ("serial", models.CharField(blank=True, max_length=120)),
                ("device_type", models.CharField(blank=True, max_length=120)),
                ("last_sync", models.DateTimeField(blank=True, null=True)),
                (
                    "site",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=models.deletion.SET_NULL, to="devices.site"
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Port",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("interface", models.CharField(max_length=64)),
                ("status", models.CharField(blank=True, max_length=16)),
                ("protocol", models.CharField(blank=True, max_length=16)),
                ("vlan", models.IntegerField(blank=True, null=True)),
                ("mode", models.CharField(blank=True, max_length=16)),
                ("description", models.CharField(blank=True, max_length=255)),
                ("speed", models.CharField(blank=True, max_length=32)),
                ("duplex", models.CharField(blank=True, max_length=16)),
                ("mac_address", models.CharField(blank=True, max_length=64)),
                ("cdp_neighbor", models.CharField(blank=True, max_length=255)),
                ("has_port_security", models.BooleanField(default=False)),
                ("validation_action", models.CharField(blank=True, max_length=64)),
                ("validation_reason", models.TextField(blank=True)),
                ("validation_category", models.CharField(blank=True, max_length=64)),
                ("last_change_request_id", models.IntegerField(blank=True, null=True)),
                ("last_change_approved_by", models.CharField(blank=True, max_length=150)),
                ("last_change_approved_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "device",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, to="devices.device"),
                ),
            ],
            options={
                "unique_together": {("device", "interface")},
            },
        ),
    ]
