from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.mixins import TenantContextMixin
from core.permissions import HasOrganizationContext
from organizations.serializers import OrganizationMemberSerializer, OrganizationSerializer
from organizations.services import list_organization_members


class CurrentOrganizationView(TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get(self, request):
        return Response(OrganizationSerializer(request.organization).data)


class OrganizationMemberListView(TenantContextMixin, APIView):
    permission_classes = [IsAuthenticated, HasOrganizationContext]

    def get(self, request):
        members = list_organization_members(request.organization)
        return Response(OrganizationMemberSerializer(members, many=True).data)
