"""Meta WhatsApp Cloud API webhook HTTP endpoints."""

from __future__ import annotations

import json
import logging

from django.http import HttpResponse, JsonResponse
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from booking.whatsapp_webhooks import (
    process_meta_webhook_payload,
    verify_meta_signature,
    verify_webhook_subscribe,
)

logger = logging.getLogger(__name__)


class WhatsAppWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")
        if verify_webhook_subscribe(mode=mode, token=token) and challenge is not None:
            return HttpResponse(challenge, content_type="text/plain")
        return JsonResponse({"error": "Forbidden"}, status=403)

    def post(self, request):
        raw_body = request.body or b""
        signature = request.META.get("HTTP_X_HUB_SIGNATURE_256")
        if not verify_meta_signature(raw_body=raw_body, signature_header=signature):
            logger.warning("whatsapp.webhook_invalid_signature")
            return JsonResponse({"error": "Invalid signature"}, status=403)

        try:
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.warning("whatsapp.webhook_malformed_json")
            return JsonResponse({"error": "Bad request"}, status=400)

        try:
            applied = process_meta_webhook_payload(payload if isinstance(payload, dict) else {})
        except Exception:
            logger.exception("whatsapp.webhook_processing_failed")
            # Acknowledge to avoid Meta retry storms for unexpected shapes.
            return JsonResponse({"ok": True, "applied": 0})

        return JsonResponse({"ok": True, "applied": applied})
