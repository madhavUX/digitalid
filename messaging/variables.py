"""Allowlisted WhatsApp template variables. No arbitrary model access."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

ALLOWED_TEMPLATE_VARIABLES = frozenset(
    {
        "customer_name",
        "business_name",
        "location_name",
        "service_name",
        "staff_name",
        "appointment_date",
        "appointment_time",
        "appointment_reference",
        "booking_url",
        "business_phone",
        "review_url",
        "booking_reference",
    }
)

DEFAULT_TEMPLATE_LANGUAGE = "en"


def validate_variable_names(variables: list | None) -> list[str]:
    if variables is None:
        return []
    if not isinstance(variables, list):
        raise ValueError("variables must be a list")
    cleaned: list[str] = []
    for item in variables:
        name = str(item or "").strip()
        if name not in ALLOWED_TEMPLATE_VARIABLES:
            raise ValueError(name or "invalid")
        cleaned.append(name)
    return cleaned


def resolve_template_variables(appointment, names: list[str]) -> list[str]:
    """Return values for allowlisted names only. Unknown names become empty strings."""
    values = _public_values(appointment)
    return [values.get(name, "") if name in ALLOWED_TEMPLATE_VARIABLES else "" for name in names]


def render_template_snapshot(appointment, *, body: str, names: list[str]) -> tuple[list[str], str]:
    """Substitute allowlisted names. The text is a frozen snapshot."""
    values = _public_values(appointment)
    ordered = [values.get(name, "") if name in ALLOWED_TEMPLATE_VARIABLES else "" for name in names]
    text = body or ""
    for name in ALLOWED_TEMPLATE_VARIABLES:
        text = text.replace("{{" + name + "}}", values.get(name, ""))
    return ordered, text[:4000]


def _public_values(appointment) -> dict[str, str]:
    customer = appointment.customer
    location = appointment.location
    business = appointment.business
    item = (
        appointment.items.order_by("created_at").first() if hasattr(appointment, "items") else None
    )
    start = appointment.starts_at
    if start is not None and timezone.is_naive(start):
        start = timezone.make_aware(start, timezone.UTC)
    tz_name = getattr(location, "timezone", "") or "UTC"
    try:
        local_start = start.astimezone(ZoneInfo(tz_name)) if start is not None else None
    except Exception:
        local_start = start
    date_label = ""
    time_label = ""
    if local_start is not None:
        date_label = f"{local_start.day} {local_start.strftime('%B %Y')}"
        time_label = local_start.strftime("%I:%M %p").lstrip("0")
    slug = getattr(location, "slug", "") or ""
    base = (getattr(settings, "PUBLIC_APP_URL", "") or "http://localhost:3000").rstrip("/")
    booking_url = f"{base}/book/{slug}" if slug else ""
    review_url = _public_review_url(appointment)
    phone = (getattr(location, "phone", "") or "").strip()
    return {
        "customer_name": customer.full_name if customer is not None else "",
        "business_name": getattr(business, "name", "") or "",
        "location_name": getattr(location, "name", "") or "",
        "service_name": getattr(item, "service_name", "") or "",
        "staff_name": getattr(getattr(appointment, "staff_profile", None), "display_name", "")
        or "",
        "appointment_date": date_label,
        "appointment_time": time_label,
        "appointment_reference": appointment.public_reference or "",
        "booking_url": booking_url,
        "business_phone": phone,
        "review_url": review_url,
        "booking_reference": appointment.public_reference or "",
    }


def _public_review_url(appointment) -> str:
    from businesses.models import BusinessLaunchProfile

    profile = (
        BusinessLaunchProfile.objects.filter(
            organization_id=appointment.organization_id,
            business_id=appointment.business_id,
            location_id=appointment.location_id,
        )
        .only("google_review_url")
        .first()
    )
    url = (profile.google_review_url if profile else "") or ""
    if url.startswith("https://") and "/book/manage/" not in url and "token=" not in url.lower():
        return url[:500]
    return ""
