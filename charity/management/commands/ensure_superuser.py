import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Creates an admin user non-interactively if it doesn't exist"

    def add_arguments(self, parser):
        parser.add_argument("--username", help="Admin's username")
        parser.add_argument("--email", help="Admin's email")
        parser.add_argument("--password", help="Admin's password")

    def handle(self, *args, **options):
        User = get_user_model()
        username = options["username"] or os.environ.get("DJANGO_SUPERUSER_USERNAME") or "admin"
        email = options["email"] or os.environ.get("DJANGO_SUPERUSER_EMAIL") or "admin@example.com"
        password = options["password"] or os.environ.get("DJANGO_SUPERUSER_PASSWORD") or "admin"

        if not User.objects.filter(username=username).exists():
            User.objects.create_superuser(username=username, email=email, password=password)
            self.stdout.write(self.style.SUCCESS(f'Superuser "{username}" created successfully'))
        else:
            u = User.objects.get(username=username)
            u.set_password(password)
            u.is_staff = True
            u.is_superuser = True
            u.save()
            self.stdout.write(
                self.style.SUCCESS(f'Superuser "{username}" password/permissions updated')
            )
