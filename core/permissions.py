from rest_framework.permissions import BasePermission

from organizations.models import Role


class HasOrganizationContext(BasePermission):
    message = "No organization is associated with this account."

    def has_permission(self, request, view) -> bool:
        return getattr(request, "organization", None) is not None


class IsOrganizationOwner(BasePermission):
    message = "Only organization owners can perform this action."

    def has_permission(self, request, view) -> bool:
        membership = getattr(request, "membership", None)
        return membership is not None and membership.role == Role.OWNER


class IsOrganizationManagerOrAbove(BasePermission):
    message = "Only organization owners or managers can perform this action."

    def has_permission(self, request, view) -> bool:
        membership = getattr(request, "membership", None)
        return membership is not None and membership.role in {
            Role.OWNER,
            Role.MANAGER,
        }
