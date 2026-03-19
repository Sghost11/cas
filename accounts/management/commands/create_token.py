from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import ApiToken


class Command(BaseCommand):
    help = "Create an API token for a user"

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("name")
        parser.add_argument("--expires-in", type=int, default=0)

    def handle(self, *args, **options):
        username = options["username"]
        name = options["name"]
        user_model = get_user_model()
        user = user_model.objects.get(username=username)
        token_value = ApiToken.generate()
        expires_in = options["expires_in"]
        expires_at = None
        if expires_in:
            expires_at = timezone.now() + timezone.timedelta(seconds=expires_in)
        ApiToken.objects.create(user=user, name=name, token=token_value, expires_at=expires_at)
        self.stdout.write(self.style.SUCCESS(token_value))
