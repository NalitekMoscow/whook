from django.contrib.postgres.fields import ArrayField
from django.db import models


class WebHookLog(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Ожидание"
        SUCCESS = "success", "Успешно"
        HAS_NEWER_SUCCESS = "has_newer_success", "Более новый лог был успешным"
        FAILED = "failed", "Ошибка"

    event = models.CharField("Ивент", max_length=256)
    action = models.CharField("Событие", max_length=256)
    data = models.JSONField("Отправленные данные")
    status = models.CharField("Статус отправки", choices=Status.choices, max_length=256, default=Status.PENDING)
    detail = models.JSONField("Информация об отправке", null=True, blank=True)
    url = models.CharField("Ссылка", max_length=200)
    created_at = models.DateTimeField("Дата создания", auto_now_add=True, db_index=True)
    app = models.ForeignKey("WebHookApp", on_delete=models.CASCADE, null=True)
    retries = models.SmallIntegerField("Количество попыток повторной отправки", default=0)
    updated_at = models.DateTimeField("Время последней отправки", auto_now=True)
    next_retry_at = models.DateTimeField("Время следующей попытки отправки", null=True, default=None)
    locked = models.BooleanField("Заблокирован для повтора", default=False)
    instance_id = models.BigIntegerField("ID экземпляра", null=True, blank=True)
    event_timestamp = models.DateTimeField("Время события", null=True, blank=True)

    class Meta:
        verbose_name = "Логи отправки данных"
        verbose_name_plural = "Логи отправки данных"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.event}_{self.created_at}"


class WebHookApp(models.Model):
    title = models.CharField(max_length=256, verbose_name="Название")
    url = models.CharField(max_length=256, verbose_name="Ссылка")
    secret_key = models.CharField(max_length=512, verbose_name="Секретный ключ")
    events = ArrayField(models.CharField(max_length=256), default=list, blank=True, verbose_name="События")
    filters = models.JSONField(
        "Условия отбора сущностей для отправки вебхуков",
        default=dict,
        blank=True,
        help_text=(
            'Пример: {"article":{"origin_source": "infocenter","url": 123,},"info_unit":{"status": "approved"},} '
            'Вебхук отправляется, если значения указанных полей совпадают. '
            'Если поле отсутствует в сериализованных для отправки данных, условие по нему пропускается.'
        ),
    )
    selected_fields = models.JSONField(
        blank=True,
        default=dict,
        verbose_name="Выбранные поля для событий",
        help_text="Словарь вида {event_code: [field1, field2, ...]}",
    )

    def __str__(self) -> str:
        return f"#{self.id}-{self.title}"

    class Meta:
        verbose_name = "Приложение Вебхуков"
        verbose_name_plural = "Приложения Вебхуков"
        ordering = ("title",)
