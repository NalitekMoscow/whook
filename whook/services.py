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
        apps = models.WebHookApp.objects.filter(events__contains=[event])
        base_payload = {
            "event": event,
            "action": action,
            "state": data,
        }
        for app in apps:
            payload_for_app = self._filter_data_by_selected_fields(app, event, base_payload)
            webhook_log = models.WebHookLog.objects.create(
                event=event,
                action=action,
                data=payload_for_app,
                status=models.WebHookLog.Status.PENDING,
                app=app,
                url=app.url,
            )
            self._evoke_webhook(app, payload_for_app, webhook_log)

    def evoke_webhook_async(self, event: tuple[str, str], action: str, data: dict) -> None:
        if celery:
            tasks.evoke_webhook.delay(event[0], action, data)
        else:
            tasks.evoke_webhook(event[0], action, data)

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

    def _evoke_webhook(self, app: models.WebHookApp, data: dict, webhook_log: models.WebHookLog) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode()
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

    if available_fields is not None:
        config.EVENT_AVAILABLE_FIELDS[event_code] = available_fields
