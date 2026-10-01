from django.conf import settings
from django.http import HttpResponseRedirect
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from businesses.google_services import (
    complete_google_oauth_callback,
    connect_google_location,
    disconnect_google_location,
    get_google_connection_status,
    list_google_business_accounts,
    list_google_business_locations,
    select_google_business_account,
    select_google_business_location,
    sync_location_booking_url,
)
from core.mixins import TenantContextMixin
from core.permissions import (
    HasOrganizationContext,
    IsOrganizationManagerOrAbove,
    IsOrganizationOwner,
)


class GoogleBusinessConnectionView(TenantContextMixin, APIView):
    """GET connection status (OWNER/MANAGER). POST connect / start OAuth (OWNER)."""

    permission_classes = [
        IsAuthenticated,
        HasOrganizationContext,
        IsOrganizationManagerOrAbove,
    ]

    def get_permissions(self):
        if self.request.method == "POST":
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

    def get(self, request, business_id, location_id):
        payload = get_google_connection_status(
            organization=request.organization,
            business_id=business_id,
            location_id=location_id,
        )
        return Response(payload)

    def post(self, request, business_id, location_id):
        payload = connect_google_location(
            organization=request.organization,
            business_id=business_id,
            location_id=location_id,
            actor=request.user,
        )
        return Response(payload, status=status.HTTP_200_OK)


class GoogleBusinessDisconnectView(TenantContextMixin, APIView):
    permission_classes = [
        IsAuthenticated,
        HasOrganizationContext,
        IsOrganizationOwner,
    ]

    def post(self, request, business_id, location_id):
        payload = disconnect_google_location(
            organization=request.organization,
            business_id=business_id,
            location_id=location_id,
            actor=request.user,
        )
        return Response(payload, status=status.HTTP_200_OK)


class GoogleBusinessAccountsView(TenantContextMixin, APIView):
    """List GBP accounts (OWNER/MANAGER). POST select account (OWNER)."""

    def get_permissions(self):
        if self.request.method == "POST":
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

    def get(self, request, business_id, location_id):
        payload = list_google_business_accounts(
            organization=request.organization,
            business_id=business_id,
            location_id=location_id,
            actor=request.user,
        )
        return Response(payload)

    def post(self, request, business_id, location_id):
        data = request.data if isinstance(request.data, dict) else {}
        payload = select_google_business_account(
            organization=request.organization,
            business_id=business_id,
            location_id=location_id,
            actor=request.user,
            account_name=data.get("google_account_name") or data.get("account_name") or "",
        )
        return Response(payload, status=status.HTTP_200_OK)


class GoogleBusinessLocationsView(TenantContextMixin, APIView):
    """List GBP locations for an account (OWNER/MANAGER)."""

    permission_classes = [
        IsAuthenticated,
        HasOrganizationContext,
        IsOrganizationManagerOrAbove,
    ]

    def get(self, request, business_id, location_id):
        account_name = request.query_params.get("account_name") or request.query_params.get(
            "google_account_name"
        )
        payload = list_google_business_locations(
            organization=request.organization,
            business_id=business_id,
            location_id=location_id,
            actor=request.user,
            account_name=account_name,
        )
        return Response(payload)


class GoogleBusinessSelectLocationView(TenantContextMixin, APIView):
    """Persist BookAnything Location ↔ Google Business Profile location mapping (OWNER)."""

    permission_classes = [
        IsAuthenticated,
        HasOrganizationContext,
        IsOrganizationOwner,
    ]

    def post(self, request, business_id, location_id):
        data = request.data if isinstance(request.data, dict) else {}
        payload = select_google_business_location(
            organization=request.organization,
            business_id=business_id,
            location_id=location_id,
            actor=request.user,
            google_location_id=data.get("google_location_id") or data.get("location_name") or "",
            google_account_name=data.get("google_account_name") or data.get("account_name"),
        )
        return Response(payload, status=status.HTTP_200_OK)


class GoogleBusinessSyncUrlView(TenantContextMixin, APIView):
    permission_classes = [
        IsAuthenticated,
        HasOrganizationContext,
        IsOrganizationOwner,
    ]

    def post(self, request, business_id, location_id):
        payload = sync_location_booking_url(
            organization=request.organization,
            business_id=business_id,
            location_id=location_id,
            actor=request.user,
        )
        http_status = status.HTTP_200_OK if payload.get("success") else status.HTTP_400_BAD_REQUEST
        return Response(payload, status=http_status)


class GoogleOAuthCallbackView(APIView):
    """
    Browser OAuth return URL. No JWT required — identity is bound via OAuth state.
    Never returns tokens; redirects to the owner UI.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        public_app = (getattr(settings, "PUBLIC_APP_URL", "") or "http://localhost:3000").rstrip(
            "/"
        )
        try:
            result = complete_google_oauth_callback(
                code=request.query_params.get("code"),
                state=request.query_params.get("state"),
                error=request.query_params.get("error"),
                actor=None,
            )
            path = result.get("redirect_path") or "/owner/onboarding?google=connected"
            return HttpResponseRedirect(f"{public_app}{path}")
        except Exception:
            return HttpResponseRedirect(f"{public_app}/owner/onboarding?google=error")
