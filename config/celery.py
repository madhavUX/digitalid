import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("digitalid")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Ensure task modules are imported even when workers start before lazy discovery.
import messaging.tasks  # noqa: E402, F401
import payments.tasks  # noqa: E402, F401
