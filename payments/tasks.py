"""Celery tasks for payment reconciliation (optional async work)."""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger("payments.tasks")


@shared_task(name="payments.tasks.noop_reconcile_payments")
def noop_reconcile_payments() -> dict:
    """Placeholder for future provider reconciliation jobs."""
    logger.info("payments.reconcile_noop")
    return {"ok": True}
