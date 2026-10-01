from django.db import transaction
from django.utils.text import slugify

from organizations.models import Organization, OrganizationMember, Role


def generate_unique_slug(name: str) -> str:
    base = slugify(name) or "organization"
    slug = base
    suffix = 1
    while Organization.objects.filter(slug=slug).exists():
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


@transaction.atomic
def create_organization_with_owner(*, name: str, owner) -> tuple[Organization, OrganizationMember]:
    organization = Organization.objects.create(
        name=name.strip(),
        slug=generate_unique_slug(name),
    )
    membership = OrganizationMember.objects.create(
        organization=organization,
        user=owner,
        role=Role.OWNER,
    )
    if owner.active_organization_id != organization.id:
        owner.active_organization = organization
        owner.save(update_fields=["active_organization"])
    return organization, membership


def get_active_membership(*, user, organization: Organization) -> OrganizationMember | None:
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return (
        OrganizationMember.objects.select_related("organization", "user")
        .filter(
            user=user,
            organization=organization,
            is_active=True,
            organization__is_active=True,
        )
        .first()
    )


def resolve_current_membership(user) -> OrganizationMember | None:
    """Resolve tenant membership from persisted user context only.

    Client-supplied tenant_id / organization_id values are ignored.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return None

    memberships = OrganizationMember.objects.select_related("organization", "user").filter(
        user=user,
        is_active=True,
        organization__is_active=True,
    )

    active_organization_id = getattr(user, "active_organization_id", None)
    if active_organization_id:
        current = memberships.filter(organization_id=active_organization_id).first()
        if current is not None:
            return current

    current = memberships.order_by("created_at").first()
    if current is None:
        return None

    if user.active_organization_id != current.organization_id:
        user.active_organization = current.organization
        user.save(update_fields=["active_organization"])
    return current


def user_can_access_organization(user, organization: Organization) -> bool:
    if user is not None and getattr(user, "is_superuser", False):
        return True
    return get_active_membership(user=user, organization=organization) is not None


def list_organization_members(organization: Organization):
    return (
        OrganizationMember.objects.filter(organization=organization, is_active=True)
        .select_related("user", "organization")
        .order_by("created_at")
    )
