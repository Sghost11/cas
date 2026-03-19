from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Seed default roles and permissions"

    def handle(self, *args, **options):
        engineer_group, _ = Group.objects.get_or_create(name="Engineer")
        approver_group, _ = Group.objects.get_or_create(name="Approver")
        admin_group, _ = Group.objects.get_or_create(name="Admin")

        perms = Permission.objects.filter(codename__in=["add_changerequest"])
        engineer_group.permissions.set(perms)
        approver_group.permissions.set(perms)
        admin_group.permissions.set(Permission.objects.all())

        self.stdout.write(self.style.SUCCESS("Seeded roles"))
