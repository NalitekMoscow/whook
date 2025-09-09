from core.celery import app as celery
from whook import config


@celery.task
def evoke_webhook(event: str, action: str, data: dict) -> None:
    from whook.services import WebHookService

    WebHookService().evoke_webhook(event, action, data)


@celery.task
def retry_webhooks(log_id: int) -> None:
    from whook.services import WebHookService

    from .models import WebHookLog

    try:
        log = WebHookLog.objects.get(id=log_id)
    except WebHookLog.DoesNotExist:
        return

    if log.retries >= config.MAX_RETRIES or log.status == WebHookLog.Status.SUCCESS:
        return

    log.retries += 1

    WebHookService().resend_webhook_by_log(log)
