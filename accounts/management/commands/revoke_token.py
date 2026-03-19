from django.core.management.base import BaseCommand

from accounts.models import ApiToken


class Command(BaseCommand):
    help = "Revoke an API token"

    def add_arguments(self, parser):
        parser.add_argument("token")

    def handle(self, *args, **options):
        token_value = options["token"]
        try:
            token = ApiToken.objects.get(token=token_value)
        except ApiToken.DoesNotExist:
            self.stderr.write("Token not found")
            return
        token.is_active = False
        token.save(update_fields=["is_active"])
        self.stdout.write(self.style.SUCCESS("Token revoked"))
