import hmac
import json
import secrets
import string
from datetime import timedelta
from hashlib import sha256
from json import JSONDecodeError

import requests
from django.utils import timezone

from . import config, models, tasks
from .settings import celery


class WebHookService:
    def evoke_webhook(self, event: str, action: str, data: dict) -> None:
        apps = models.WebHookApp.objects.filter(events__icontains=event)
        data = {
            "event": event,
            "action": action,
            "state": data,
        }
        for app in apps:
            webhook_log = models.WebHookLog.objects.create(
                event=event,
                action=action,
                data=data,
                status=models.WebHookLog.Status.PENDING,
                app=app,
                url=app.url,
            )
            self._evoke_webhook(app, data, webhook_log)

    def evoke_webhook_async(self, event: tuple[str, str], action: str, data: dict) -> None:
        if celery:
            tasks.evoke_webhook.delay(event[0], action, data)
        else:
            tasks.evoke_webhook(event[0], action, data)

    def _filter_data_by_selected_fields(self, app: models.WebHookApp, event: str, data: dict) -> dict:
        if not app.selected_fields or event not in app.selected_fields:
            return data

        selected_fields = app.selected_fields.get(event, [])

        if not selected_fields:
            return data

        filtered_data = {
            "event": data.get("event"),
            "action": data.get("action"),
            "state": {}
        }

        if "state" in data and isinstance(data["state"], dict):
            for field in selected_fields:
                if field in data["state"]:
                    filtered_data["state"][field] = data["state"][field]

        return filtered_data

    def _evoke_webhook(self, app: models.WebHookApp, data: dict, webhook_log: models.WebHookLog) -> None:
        filtered_data = self._filter_data_by_selected_fields(app, data.get("event"), data)

        payload = json.dumps(filtered_data, ensure_ascii=False).encode()
        signature = hmac.new(app.secret_key.encode(), msg=payload, digestmod=sha256).hexdigest()

        headers = {
            "Content-Type": "application/json",
            "X-WEBHOOK-SIGNATURE": signature,
        }
        response = None
        try:
            response = requests.post(url=app.url, data=payload, headers=headers, timeout=10)
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
            return
        except Exception as e:
            self._handle_failure(webhook_log, {"detail": str(e), "status": None})
            return

        webhook_log.status = models.WebHookLog.Status.SUCCESS
        webhook_log.save()

    def resend_webhook_by_log(self, log: models.WebHookLog) -> None:
        self._evoke_webhook(app=log.app, data=log.data, webhook_log=log)

    def _handle_failure(self, webhook_log: models.WebHookLog, detail: dict) -> None:
        webhook_log.status = models.WebHookLog.Status.FAILED
        webhook_log.detail = detail
        webhook_log.save(update_fields=("detail", "status", "retries"))
        delay_seconds = config.BASE_DELAY * (2 ** webhook_log.retries)
        eta = timezone.now() + timedelta(seconds=delay_seconds)
        if celery:
            tasks.retry_webhooks.apply_async((webhook_log.id,), eta=eta)
        else:
            tasks.retry_webhooks(webhook_log.id)


def generate_secret_key(length: int = 50) -> str:
    chars = string.ascii_letters + string.digits + string.punctuation
    return "".join(secrets.choice(chars) for _ in range(length))


def register_event(event_code: str, event_title: str, available_fields: list[tuple[str, str]] = None) -> None:
    from . import config

    config.EVENTS.append((event_code, event_title))

    if available_fields:
        config.EVENT_AVAILABLE_FIELDS[event_code] = available_fields
