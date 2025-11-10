# charity/management/commands/generate_videos.py
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = "Test command to verify discovery."

    def add_arguments(self, parser):
        parser.add_argument("--name", default="world")

    def handle(self, *args, **opts):
        self.stdout.write(self.style.SUCCESS(f"Hello, {opts['name']}! Command is working."))
