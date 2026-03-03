from django.apps import AppConfig


class CharityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "charity"

    def ready(self):
        import charity.signals  # noqa: F401  # pylint: disable=unused-import — registers signal receivers
