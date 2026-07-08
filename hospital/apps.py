from django.apps import AppConfig


class HospitalConfig(AppConfig):
    name = 'hospital'

    def ready(self):
        from . import signals  # noqa: F401
