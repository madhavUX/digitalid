from organizations.services import resolve_current_membership


class TenantContextMixin:
    """Attach organization and membership from the authenticated user, never from client input."""

    def perform_authentication(self, request):
        super().perform_authentication(request)
        request.membership = None
        request.organization = None
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return
        membership = resolve_current_membership(user)
        if membership is None:
            return
        request.membership = membership
        request.organization = membership.organization
