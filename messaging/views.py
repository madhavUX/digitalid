from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.mixins import TenantContextMixin
from core.pagination import StandardLimitOffsetPagination
from core.permissions import (
    HasOrganizationContext,
    IsOrganizationManagerOrAbove,
    IsOrganizationOwner,
)
from messaging.services import (
    connect_whatsapp_account,
    create_template,
    delete_template,
    disconnect_whatsapp_account,
    get_whatsapp_status,
    list_inbound_messages,
    list_messages,
    list_templates,
    serialize_inbound_message,
    serialize_message,
    serialize_template,
    submit_whatsapp_template,
    sync_whatsapp_templates,
    update_template,
)


class _OwnerWriteMixin:
    def get_permissions(self):
        if self.request.method in ("POST", "PATCH", "DELETE", "PUT"):
            return [
                IsAuthenticated(),
                HasOrganizationContext(),
                IsOrganizationOwner(),
            ]
        return [
            IsAuthenticated(),
            HasOrganizationContext(),
            IsOrganizationManagerOrAbove(),
        ]


class WhatsAppStatusView(_OwnerWriteMixin, TenantContextMixin, APIView):
    def get(self, request, business_id):
        return Response(
            get_whatsapp_status(organization=request.organization, business_id=business_id)
        )


class WhatsAppConnectView(TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext, IsOrganizationOwner]

    def post(self, request, business_id):
        data = request.data if isinstance(request.data, dict) else {}
        payload = connect_whatsapp_account(
            organization=request.organization,
            business_id=business_id,
            actor=request.user,
            access_token=data.get("access_token") or "",
            phone_number_id=data.get("phone_number_id") or "",
            business_account_id=data.get("business_account_id") or "",
            display_phone_number=data.get("display_phone_number") or "",
        )
        return Response(payload, status=status.HTTP_200_OK)


class WhatsAppDisconnectView(TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext, IsOrganizationOwner]

    def post(self, request, business_id):
        payload = disconnect_whatsapp_account(
            organization=request.organization,
            business_id=business_id,
            actor=request.user,
        )
        return Response(payload, status=status.HTTP_200_OK)


class WhatsAppTemplateListCreateView(_OwnerWriteMixin, TenantContextMixin, APIView):
    def get(self, request, business_id):
        queryset = list_templates(organization=request.organization, business_id=business_id)
        paginator = StandardLimitOffsetPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response([serialize_template(item) for item in page])

    def post(self, request, business_id):
        data = request.data if isinstance(request.data, dict) else {}
        payload = create_template(
            organization=request.organization,
            business_id=business_id,
            actor=request.user,
            name=data.get("name") or "",
            language=data.get("language") or "en",
            category=data.get("category") or "CUSTOM",
            body=data.get("body") or "",
            variables=data.get("variables") or [],
            purpose=data.get("purpose") or "",
            status=data.get("status") or "DRAFT",
        )
        return Response(payload, status=status.HTTP_201_CREATED)


class WhatsAppTemplateDetailView(_OwnerWriteMixin, TenantContextMixin, APIView):
    def patch(self, request, business_id, template_id):
        data = request.data if isinstance(request.data, dict) else {}
        payload = update_template(
            organization=request.organization,
            business_id=business_id,
            template_id=template_id,
            actor=request.user,
            **{
                key: data[key]
                for key in data
                if key
                in {
                    "name",
                    "language",
                    "category",
                    "purpose",
                    "body",
                    "variables",
                    "status",
                    "provider_template_id",
                }
            },
        )
        return Response(payload)

    def delete(self, request, business_id, template_id):
        delete_template(
            organization=request.organization,
            business_id=business_id,
            template_id=template_id,
            actor=request.user,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class WhatsAppTemplateSyncView(TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext, IsOrganizationOwner]

    def post(self, request, business_id):
        payload = sync_whatsapp_templates(
            organization=request.organization,
            business_id=business_id,
            actor=request.user,
        )
        return Response(payload)


class WhatsAppTemplateSubmitView(TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext, IsOrganizationOwner]

    def post(self, request, business_id, template_id):
        payload = submit_whatsapp_template(
            organization=request.organization,
            business_id=business_id,
            template_id=template_id,
            actor=request.user,
        )
        return Response(payload)


class WhatsAppMessageListView(TenantContextMixin, APIView):
    permission_classes = [
        IsAuthenticated,
        HasOrganizationContext,
        IsOrganizationManagerOrAbove,
    ]

    def get(self, request, business_id):
        from django.utils.dateparse import parse_datetime

        queryset = list_messages(
            organization=request.organization,
            business_id=business_id,
            appointment_id=request.query_params.get("appointment") or None,
            purpose=(request.query_params.get("purpose") or "").strip(),
            message_type=(request.query_params.get("message_type") or "").strip(),
            status=(request.query_params.get("status") or "").strip(),
            created_after=parse_datetime(request.query_params.get("created_after") or ""),
            created_before=parse_datetime(request.query_params.get("created_before") or ""),
        )
        paginator = StandardLimitOffsetPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response([serialize_message(item) for item in page])


class WhatsAppInboundListView(TenantContextMixin, APIView):
    permission_classes = [
        IsAuthenticated,
        HasOrganizationContext,
        IsOrganizationManagerOrAbove,
    ]

    def get(self, request, business_id):
        queryset = list_inbound_messages(
            organization=request.organization,
            business_id=business_id,
            customer_id=request.query_params.get("customer") or None,
            phone=(request.query_params.get("phone") or "").strip(),
            message_type=(request.query_params.get("message_type") or "").strip(),
            processing_status=(request.query_params.get("processing_status") or "").strip(),
            date_from=_inbound_bound(request.query_params.get("date_from"), end=False),
            date_to=_inbound_bound(request.query_params.get("date_to"), end=True),
        )
        paginator = StandardLimitOffsetPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response([serialize_inbound_message(item) for item in page])


def _inbound_bound(value, *, end: bool):
    from datetime import UTC, datetime, time

    from django.utils import timezone
    from django.utils.dateparse import parse_date, parse_datetime
    from rest_framework.exceptions import ValidationError

    raw = (value or "").strip()
    if not raw:
        return None
    parsed = parse_datetime(raw)
    if parsed is None:
        day = parse_date(raw)
        if day is None:
            raise ValidationError({"date": "Invalid date."})
        parsed = datetime.combine(day, time.max if end else time.min, tzinfo=UTC)
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, UTC)
    return parsed
