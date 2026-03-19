from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import ApiToken


class Command(BaseCommand):
    help = "Rotate an API token"

    def add_arguments(self, parser):
        parser.add_argument("token")

    def handle(self, *args, **options):
        token_value = options["token"]
        try:
            token = ApiToken.objects.get(token=token_value, is_active=True)
        except ApiToken.DoesNotExist:
            self.stderr.write("Token not found")
            return
        new_value = ApiToken.generate()
        token.token = new_value
        token.rotated_at = timezone.now()
        token.save(update_fields=["token", "rotated_at"])
        self.stdout.write(self.style.SUCCESS(new_value))
