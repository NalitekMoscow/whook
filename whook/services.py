import datetime
import hmac
import json
import secrets
import string
from hashlib import sha256
from json import JSONDecodeError
import logging

import requests
from django.db import transaction
from django.db.models import OuterRef, Exists
from django.utils import timezone

from . import config, models

logger = logging.getLogger("default")


class WebHookService:
    def evoke_webhook(
        self,
        event: str,
        action: str,
        data: dict,
        timestamp: datetime.datetime,
        instance_id: int | None = None,
    ) -> None:
        apps = models.WebHookApp.objects.filter(events__contains=[event])
        base_payload = {
            "event": event,
            "action": action,
            "state": data,
        }
        for app in apps:

            if not self._matches_filter(app, event, data):
                continue

            payload_for_app = self._filter_data_by_selected_fields(app, event, base_payload)
            webhook_log = models.WebHookLog.objects.create(
                event=event,
                action=action,
                data=payload_for_app,
                status=models.WebHookLog.Status.PENDING,
                app=app,
                url=app.url,
                event_timestamp=timestamp,
                instance_id=instance_id,
            )
            self._evoke_webhook(app, payload_for_app, webhook_log)

    def _matches_filter(self, app: models.WebHookApp, event: str, data: dict) -> bool:
        event_filters = (app.filters or {}).get(event)
        if not event_filters:
            # Фильтрация не установленна, не блокируем отправку вебхука.
            return True

        for field, value in event_filters.items():
            # Если поле отсутствует, не блокируем отправку вебхука.
            if field not in data:
                logger.warning(
                    "Webhook filter field '%s' is missing from event data " 
                    "(app_id=%s, event=%s). Allowing webhook delivery.",
                    field, app.id, event, )
                continue
            if data.get(field) != value:
                return False
        return True

    def _filter_data_by_selected_fields(self, app: models.WebHookApp, event: str, data: dict) -> dict:
        mapping = app.selected_fields or {}
        selected = mapping.get(event)
        if not selected:
            return data
        state = data.get("state")
        if not isinstance(state, dict):
            return data
        filtered_state = {k: state[k] for k in selected if k in state}
        return {
            "event": data.get("event"),
            "action": data.get("action"),
            "state": filtered_state,
        }

    def _evoke_webhook(self, app: models.WebHookApp, data: dict, webhook_log: models.WebHookLog) -> models.WebHookLog:
        payload = json.dumps(data, ensure_ascii=False).encode()
        signature = hmac.new(app.secret_key.encode(), msg=payload, digestmod=sha256).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "X-WEBHOOK-SIGNATURE": signature,
        }
        response = None
        try:
            response = requests.post(url=app.url, data=payload, headers=headers, timeout=5)
            response.raise_for_status()
        except requests.HTTPError:
            try:
                response_json = {"data": response.json()} | {"status": response.status_code}
            except JSONDecodeError:
                response_json = {
                    "detail": getattr(response, "reason", "Unknown reason"),
                    "status": response.status_code,
                }
            self._handle_failure(webhook_log, response_json)
            return webhook_log
        except Exception as e:
            self._handle_failure(webhook_log, {"detail": str(e), "status": None})
            return webhook_log

        webhook_log.status = models.WebHookLog.Status.SUCCESS
        webhook_log.next_retry_at = None
        webhook_log.save()
        return webhook_log

    def resend_webhook_by_log(self, log: models.WebHookLog) -> None:
        self._evoke_webhook(app=log.app, data=log.data, webhook_log=log)

    def _handle_failure(self, webhook_log: models.WebHookLog, detail: dict) -> None:
        webhook_log.status = models.WebHookLog.Status.FAILED
        webhook_log.detail = detail
        delay_seconds = config.BASE_DELAY * (2**webhook_log.retries)
        webhook_log.next_retry_at = timezone.now() + datetime.timedelta(seconds=delay_seconds)
        webhook_log.retries += 1
        webhook_log.save(update_fields=("detail", "status", "retries", "next_retry_at"))

    def retry_webhooks(self, log_id: int | None = None) -> None:
        logger.info("Webhook retrying has been started")

        # Подбираем более ранний лог по тому же объекту, который уже завершился со статусом SUCCESS
        newer_success = models.WebHookLog.objects.filter(
            app=OuterRef("app"),
            event=OuterRef("event"),
            action=OuterRef("action"),
            instance_id=OuterRef("instance_id"),
            status=models.WebHookLog.Status.SUCCESS,
            event_timestamp__gt=OuterRef("event_timestamp"),
        )

        with transaction.atomic():
            logs = models.WebHookLog.objects.annotate(
                has_newer_success=Exists(newer_success),
            )

            if log_id is not None:
                logs = logs.filter(id=log_id)
            else:
                logs = (
                    logs.filter(
                        status=models.WebHookLog.Status.FAILED,
                        retries__lt=config.MAX_RETRIES,
                        next_retry_at__lte=timezone.now(),
                    )
                    .order_by("created_at")
                )

            logs = logs.select_for_update(skip_locked=True)

            for log in logs:
                if log.has_newer_success:
                    log.status = models.WebHookLog.Status.HAS_NEWER_SUCCESS
                    log.save(update_fields=["status", "updated_at"])
                    continue

                try:
                    self.resend_webhook_by_log(log)
                except Exception as e:
                    logger.error(
                        "Failed to resend webhook log",
                        extra={
                            "error": str(e),
                            "log_id": log.id,
                        },
                    )
        logger.info("Webhook retrying has been finished")


def generate_secret_key(length: int = 50) -> str:
    chars = string.ascii_letters + string.digits + string.punctuation
    return "".join(secrets.choice(chars) for _ in range(length))


def register_event(event_code: str, event_title: str, available_fields: list[tuple[str, str]] = None) -> None:
    from . import config

    config.EVENTS.append((event_code, event_title))

    if available_fields is not None:
        config.EVENT_AVAILABLE_FIELDS[event_code] = available_fields
