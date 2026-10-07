from django.core.management.base import BaseCommand

from whook.models import WebHookLog


class Command(BaseCommand):
    help = "Заполняет instance_id и event_timestamp у существующих WebHookLog"

    BATCH_SIZE = 5000

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Показать количество записей без изменения данных",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        logs = (
            WebHookLog.objects
            .filter(event_timestamp__isnull=True)
            .order_by("id")
        )

        total = logs.count()
        updated = 0
        without_instance_id = 0

        self.stdout.write(f"Найдено логов: {total}")

        batch = []

        for log in logs.iterator(chunk_size=self.BATCH_SIZE):
            try:
                instance_id = log.data["state"]["id"]
            except (KeyError, TypeError):
                instance_id = None
                without_instance_id += 1

            log.instance_id = instance_id
            log.event_timestamp = log.created_at

            batch.append(log)

            if len(batch) < self.BATCH_SIZE:
                continue

            if not dry_run:
                WebHookLog.objects.bulk_update(
                    batch,
                    ["instance_id", "event_timestamp"],
                    batch_size=self.BATCH_SIZE,
                )
                updated += len(batch)

                self.stdout.write(
                    f"Обновлено: {updated}/{total}",
                )

            batch.clear()

        if batch:
            if not dry_run:
                WebHookLog.objects.bulk_update(
                    batch,
                    ["instance_id", "event_timestamp"],
                    batch_size=self.BATCH_SIZE,
                )
                updated += len(batch)

                self.stdout.write(
                    f"Обновлено: {updated}/{total}",
                )

            batch.clear()

        self.stdout.write(
            self.style.SUCCESS(
                f"Готово. Обновлено: {updated}",
            )
        )
        self.stdout.write(
            f"Без instance_id: {without_instance_id}",
        )
