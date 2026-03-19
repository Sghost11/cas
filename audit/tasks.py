from __future__ import annotations

from celery import shared_task
from django.contrib.auth import get_user_model


@shared_task(bind=True)
def ai_approve_deploy_batch_task(
    self,
    user_id: int | None = None,
    interface_filter: str | None = None,
) -> dict:
    user = None
    if user_id:
        user_model = get_user_model()
        user = user_model.objects.filter(pk=user_id).first()

    def progress(percent: int, stage: str, extra: dict | None = None) -> None:
        meta = {"percent": int(percent), "stage": stage}
        if extra:
            meta.update(extra)
        self.update_state(state="PROGRESS", meta=meta)

    from audit.views import _run_ai_batch

    progress(0, "start", {"message": "Iniciando batch IA"})
    result = _run_ai_batch(
        request_user=user,
        progress_callback=progress,
        interface_filter=interface_filter,
    )
    progress(100, "done", {"message": "Batch IA finalizado"})
    return result
