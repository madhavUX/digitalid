from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from rest_framework.exceptions import ValidationError

from businesses.models import Business


def generate_unique_business_slug(*, organization, name: str, exclude_id=None) -> str:
    base = slugify(name) or "business"
    slug = base
    suffix = 1
    while True:
        qs = Business.objects.filter(organization=organization, slug=slug)
        if exclude_id is not None:
            qs = qs.exclude(pk=exclude_id)
        if not qs.exists():
            return slug
        slug = f"{base}-{suffix}"
        suffix += 1


def list_businesses(*, organization):
    return Business.objects.filter(organization=organization).order_by("name")


def get_business_for_organization(*, organization, business_id) -> Business:
    return get_object_or_404(Business, organization=organization, pk=business_id)


@transaction.atomic
def create_business(
    *,
    organization,
    actor,
    name: str,
    vertical: str,
    description: str = "",
    logo_url: str = "",
    primary_domain: str | None = None,
    is_active: bool = True,
    slug: str | None = None,
) -> Business:
    name = name.strip()
    if not name:
        raise ValidationError({"name": "This field may not be blank."})

    primary_domain = _normalize_domain(primary_domain)
    resolved_slug = (
        slug.strip()
        if slug
        else generate_unique_business_slug(
            organization=organization,
            name=name,
        )
    )
    if not resolved_slug:
        raise ValidationError({"slug": "This field may not be blank."})

    if Business.objects.filter(organization=organization, slug=resolved_slug).exists():
        raise ValidationError({"slug": "A business with this slug already exists."})

    if primary_domain and Business.objects.filter(primary_domain=primary_domain).exists():
        raise ValidationError({"primary_domain": "This domain is already in use."})

    return Business.objects.create(
        organization=organization,
        name=name,
        slug=resolved_slug,
        vertical=vertical,
        description=description or "",
        logo_url=logo_url or "",
        primary_domain=primary_domain,
        is_active=is_active,
        created_by=actor,
        updated_by=actor,
    )


@transaction.atomic
def update_business(*, business: Business, actor, **fields) -> Business:
    if "name" in fields and fields["name"] is not None:
        name = fields["name"].strip()
        if not name:
            raise ValidationError({"name": "This field may not be blank."})
        business.name = name

    if "slug" in fields and fields["slug"] is not None:
        slug = fields["slug"].strip()
        if not slug:
            raise ValidationError({"slug": "This field may not be blank."})
        if (
            Business.objects.filter(organization=business.organization, slug=slug)
            .exclude(pk=business.pk)
            .exists()
        ):
            raise ValidationError({"slug": "A business with this slug already exists."})
        business.slug = slug

    if "vertical" in fields and fields["vertical"] is not None:
        business.vertical = fields["vertical"]

    if "description" in fields and fields["description"] is not None:
        business.description = fields["description"]

    if "logo_url" in fields and fields["logo_url"] is not None:
        business.logo_url = fields["logo_url"]

    if "primary_domain" in fields:
        primary_domain = _normalize_domain(fields["primary_domain"])
        if (
            primary_domain
            and Business.objects.filter(primary_domain=primary_domain)
            .exclude(pk=business.pk)
            .exists()
        ):
            raise ValidationError({"primary_domain": "This domain is already in use."})
        business.primary_domain = primary_domain

    if "is_active" in fields and fields["is_active"] is not None:
        business.is_active = fields["is_active"]

    business.updated_by = actor
    business.save()
    return business


@transaction.atomic
def soft_delete_business(*, business: Business, actor) -> None:
    business.soft_delete(actor=actor)


def _normalize_domain(value: str | None) -> str | None:
    if value is None:
        return None
    domain = value.strip().lower()
    return domain or None
