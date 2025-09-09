from .settings import celery, celery_queue
from whook import config


def evoke_webhook(event: str, action: str, data: dict) -> None:
    from whook.services import WebHookService

    WebHookService().evoke_webhook(event, action, data)

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

if celery:
    evoke_webhook = celery.task(queue=celery_queue)(evoke_webhook)
    retry_webhooks = celery.task(queue=celery_queue)(retry_webhooks)