from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.serializers import (
    AuthResponseSerializer,
    LoginSerializer,
    RegisterSerializer,
    UserSerializer,
)
from accounts.services import login_user, register_user
from core.mixins import TenantContextMixin
from core.permissions import HasOrganizationContext
from organizations.serializers import OrganizationSerializer


class RegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = register_user(**serializer.validated_data)
        return Response(AuthResponseSerializer(result).data, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = login_user(**serializer.validated_data)
        except AuthenticationFailed as exc:
            # DRF rewrites AuthenticationFailed to 403 when no WWW-Authenticate
            # header is available (this view has no authenticators).
            return Response(
                {"error": exc.detail, "status_code": status.HTTP_401_UNAUTHORIZED},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        return Response(AuthResponseSerializer(result).data)


class MeView(TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        organization = getattr(request, "organization", None)
        membership = getattr(request, "membership", None)
        return Response(
            {
                "user": UserSerializer(request.user).data,
                "organization": OrganizationSerializer(organization).data if organization else None,
                "membership": {
                    "id": str(membership.id),
                    "role": membership.role,
                    "is_active": membership.is_active,
                }
                if membership
                else None,
            }
        )


class ProtectedExampleView(TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get(self, request):
        return Response(
            {
                "message": "Authenticated tenant context resolved server-side.",
                "user_id": str(request.user.id),
                "organization_id": str(request.organization.id),
                "organization_name": request.organization.name,
                "role": request.membership.role,
            }
        )
