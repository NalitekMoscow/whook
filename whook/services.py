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
        tasks.evoke_webhook.delay(event[0], action, data)

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
        delay_seconds = config.BASE_DELAY * (2**webhook_log.retries)
        eta = timezone.now() + timedelta(seconds=delay_seconds)
        tasks.retry_webhooks.apply_async((webhook_log.id,), eta=eta)


def generate_secret_key(length: int = 50) -> str:
    chars = string.ascii_letters + string.digits + string.punctuation
    return "".join(secrets.choice(chars) for _ in range(length))


def register_event(event_code: str, event_title: str) -> None:
    from . import config

    config.EVENTS.append((event_code, event_title))
