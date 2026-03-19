from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("devices", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ChangeRequest",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pending"),
                            ("APPROVED", "Approved"),
                            ("DEPLOYED", "Deployed"),
                            ("FAILED", "Failed"),
                            ("REJECTED", "Rejected"),
                        ],
                        max_length=20,
                    ),
                ),
                ("ports_json", models.JSONField()),
                ("generated_config", models.TextField(blank=True)),
                ("site", models.CharField(blank=True, max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "device",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, to="devices.device"),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        null=True, on_delete=models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ChangeApproval",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("comments", models.TextField(blank=True)),
                ("approved_at", models.DateTimeField(auto_now_add=True)),
                (
                    "approved_by",
                    models.ForeignKey(
                        null=True, on_delete=models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL
                    ),
                ),
                (
                    "change_request",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, to="audit.changerequest"),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ChangeLog",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("port_interface", models.CharField(max_length=64)),
                ("field", models.CharField(max_length=64)),
                ("old_value", models.TextField(blank=True)),
                ("new_value", models.TextField(blank=True)),
                ("deployed_at", models.DateTimeField(auto_now_add=True)),
                (
                    "change_request",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, to="audit.changerequest"),
                ),
                (
                    "deployed_by",
                    models.ForeignKey(
                        null=True, on_delete=models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ConfigSnapshot",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("running_config", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "change_request",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, to="audit.changerequest"),
                ),
                (
                    "device",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, to="devices.device"),
                ),
            ],
        ),
        migrations.CreateModel(
            name="DeploymentResult",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("success", models.BooleanField(default=False)),
                ("ansible_output", models.TextField(blank=True)),
                ("deployed_at", models.DateTimeField(auto_now_add=True)),
                (
                    "change_request",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, to="audit.changerequest"),
                ),
            ],
        ),
    ]
