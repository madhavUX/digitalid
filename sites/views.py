from uuid import UUID

from django.http import Http404, HttpResponse
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from businesses.services import get_business_for_organization
from core.mixins import TenantContextMixin
from core.permissions import HasOrganizationContext, IsOrganizationManagerOrAbove
from locations.services import get_location_for_business
from sites.analytics import aggregate_quickcard_events, record_quickcard_event, safe_referrer
from sites.serializers import (
    QuickCardEventSerializer,
    QuickCardUpdateSerializer,
    QuickCardWriteSerializer,
)
from sites.services import (
    create_quickcard,
    generate_quickcard_qr_png,
    get_quickcard_for_location,
    publish_quickcard,
    resolve_published_quickcard,
    serialize_managed_quickcard,
    serialize_public_quickcard,
    unpublish_quickcard,
    update_quickcard,
)


class PublicQuickCardThrottle(AnonRateThrottle):
    scope = "public_catalog"


class PublicQuickCardEventThrottle(AnonRateThrottle):
    scope = "public_quickcard_events"


class PublicQuickCardEventView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PublicQuickCardEventThrottle]

    def post(self, request, slug):
        length = request.META.get("CONTENT_LENGTH")
        if length and str(length).isdigit() and int(length) > 1024:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        serializer = QuickCardEventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record_quickcard_event(
            slug=slug,
            event_type=serializer.validated_data["event_type"],
            cta=serializer.validated_data["cta"],
            referrer=safe_referrer(request.META.get("HTTP_REFERER")),
        )
        response = Response(status=status.HTTP_204_NO_CONTENT)
        response["Cache-Control"] = "no-store"
        return response


def _analytics_location(request, business):
    raw = (request.query_params.get("location_id") or "").strip()
    if not raw:
        return None
    try:
        UUID(raw)
    except ValueError:
        raise Http404 from None
    return get_location_for_business(
        organization=request.organization,
        business=business,
        location_id=raw,
    )


class QuickCardAnalyticsView(TenantContextMixin, APIView):
    permission_classes = [
        IsAuthenticated,
        HasOrganizationContext,
        IsOrganizationManagerOrAbove,
    ]

    def get(self, request, business_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        payload = aggregate_quickcard_events(
            organization=request.organization,
            business=business,
            date_from=request.query_params.get("date_from"),
            date_to=request.query_params.get("date_to"),
            location=_analytics_location(request, business),
        )
        response = Response(payload)
        response["Cache-Control"] = "private, no-store"
        return response


class PublicQuickCardDetailView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [PublicQuickCardThrottle]

    def get(self, request, slug):
        card = resolve_published_quickcard(slug)
        response = Response(serialize_public_quickcard(card))
        response["Cache-Control"] = "public, max-age=60"
        return response


class QuickCardDetailView(TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get_permissions(self):
        if self.request.method in ("POST", "PATCH"):
            return [
                IsAuthenticated(),
                HasOrganizationContext(),
                IsOrganizationManagerOrAbove(),
            ]
        return [IsAuthenticated(), HasOrganizationContext()]

    def get(self, request, business_id, location_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        card = get_quickcard_for_location(
            organization=request.organization,
            business=business,
            location_id=location_id,
        )
        return Response(serialize_managed_quickcard(card))

    def post(self, request, business_id, location_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        serializer = QuickCardWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        card = create_quickcard(
            organization=request.organization,
            business=business,
            location_id=location_id,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(serialize_managed_quickcard(card), status=status.HTTP_201_CREATED)

    def patch(self, request, business_id, location_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        card = get_quickcard_for_location(
            organization=request.organization,
            business=business,
            location_id=location_id,
        )
        serializer = QuickCardUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        card = update_quickcard(
            quickcard=card,
            actor=request.user,
            **serializer.validated_data,
        )
        return Response(serialize_managed_quickcard(card))


class QuickCardPublishView(TenantContextMixin, APIView):
    permission_classes = [
        IsAuthenticated,
        HasOrganizationContext,
        IsOrganizationManagerOrAbove,
    ]

    def post(self, request, business_id, location_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        card = get_quickcard_for_location(
            organization=request.organization,
            business=business,
            location_id=location_id,
        )
        card = publish_quickcard(quickcard=card, actor=request.user)
        return Response(serialize_managed_quickcard(card))


class QuickCardUnpublishView(TenantContextMixin, APIView):
    permission_classes = [
        IsAuthenticated,
        HasOrganizationContext,
        IsOrganizationManagerOrAbove,
    ]

    def post(self, request, business_id, location_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        card = get_quickcard_for_location(
            organization=request.organization,
            business=business,
            location_id=location_id,
        )
        card = unpublish_quickcard(quickcard=card, actor=request.user)
        return Response(serialize_managed_quickcard(card))


class QuickCardQRView(TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get(self, request, business_id, location_id):
        business = get_business_for_organization(
            organization=request.organization,
            business_id=business_id,
        )
        card = get_quickcard_for_location(
            organization=request.organization,
            business=business,
            location_id=location_id,
        )
        png = generate_quickcard_qr_png(slug=card.slug)
        response = HttpResponse(png, content_type="image/png")
        response["Content-Disposition"] = f'inline; filename="quickcard-{card.slug}.png"'
        return response
