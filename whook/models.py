from django.contrib.postgres.fields import ArrayField
from django.db import models


class WebHookLog(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Ожидание"
        SUCCESS = "success", "Успешно"
        FAILED = "failed", "Ошибка"

    event = models.CharField("Ивент", max_length=256)
    action = models.CharField("Событие", max_length=256)
    data = models.JSONField("Отправленные данные")
    status = models.CharField("Статус отправки", choices=Status.choices, max_length=256, default=Status.PENDING)
    detail = models.JSONField("Информация об отправке", null=True, blank=True)
    url = models.CharField("Ссылка", max_length=200)
    created_at = models.DateTimeField("Дата создания", auto_now_add=True)
    app = models.ForeignKey("WebHookApp", on_delete=models.CASCADE, null=True)
    retries = models.SmallIntegerField("Количество попыток повторной отправки", default=0)

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

    def __str__(self) -> str:
        return f"#{self.id}-{self.title}"

    class Meta:
        verbose_name = "Приложение Вебхуков"
        verbose_name_plural = "Приложения Вебхуков"
        ordering = ("title",)
