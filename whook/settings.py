from django.conf import settings
from importlib import import_module


celery = None
celery_module_path = getattr(settings, "WHOOK_CELERY_MODULE", None)
celery_queue = getattr(settings, "WHOOK_CELERY_QUEUE", None)

if celery_module_path:
    try:
        celery_module = import_module(celery_module_path)
        celery = celery_module.app
    except Exception:
        celery = None
