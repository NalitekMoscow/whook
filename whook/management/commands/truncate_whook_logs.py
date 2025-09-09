from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Q, QuerySet
from django.utils import timezone

from ...models import WebHookLog


class Command(BaseCommand):
    help = "Очистить лог http-запросов от устаревших записей"

    def add_arguments(self, parser):
        parser.add_argument("days", type=int, nargs="?")

    def handle(self, *args, **options):
        days = options.get("days")
        if days is None:
            days = getattr(settings, "WHOOK_LOGS", {}).get("FLUSH_DAYS", 14)

        deleted_records = (
            self.get_whook_log_record_queryset_to_delete()
            .filter(request_timestamp__lte=timezone.now() - timezone.timedelta(days=days))
            .delete()
        )
        self.stdout.write(f"Удалено записей изменений {deleted_records[0]}")

    @classmethod
    def get_whook_log_record_queryset_to_delete(cls) -> QuerySet:
        return WebHookLog.objects.all()
