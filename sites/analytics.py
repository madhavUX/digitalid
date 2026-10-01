"""Anonymous QuickCard page views and CTA clicks. No visitor identity."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlparse

from django.db.models import Count
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework.exceptions import ValidationError

from sites.models import QuickCard, QuickCardCtaType, QuickCardEvent, QuickCardEventType
from sites.services import resolve_published_quickcard


def safe_referrer(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw[:1000])
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    if parsed.username or parsed.password or "token=" in raw.lower():
        return ""
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"[:500]


def record_quickcard_event(*, slug: str, event_type: str, cta: str, referrer: str) -> None:
    card = resolve_published_quickcard(slug)
    QuickCardEvent.objects.create(
        organization_id=card.organization_id,
        business_id=card.business_id,
        location_id=card.location_id,
        quickcard=card,
        event_type=event_type,
        cta_type=cta,
        occurred_at=timezone.now(),
        referrer=safe_referrer(referrer),
    )


def _window(date_from: str | None, date_to: str | None) -> tuple[datetime, datetime]:
    now = timezone.now()
    start = now - timedelta(days=30)
    end = now
    if date_from:
        start = _parse_bound(date_from, end=False)
    if date_to:
        end = _parse_bound(date_to, end=True)
    if start > end:
        raise ValidationError({"date": "date_from must be before date_to."})
    return start, end


def _parse_bound(value: str, *, end: bool) -> datetime:
    parsed = parse_datetime(value)
    if parsed is None:
        day = parse_date(value)
        if day is None:
            raise ValidationError({"date": "Invalid date."})
        parsed = datetime.combine(day, time.max if end else time.min)
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def aggregate_quickcard_events(
    *,
    organization,
    business,
    date_from: str | None,
    date_to: str | None,
    location=None,
) -> dict:
    start, end = _window(date_from, date_to)
    card_ids = _quickcard_ids(organization=organization, business=business, location=location)
    base = QuickCardEvent.objects.filter(
        organization=organization,
        business=business,
        quickcard_id__in=card_ids,
        occurred_at__gte=start,
        occurred_at__lte=end,
    )
    clicks = {choice.lower(): 0 for choice in QuickCardCtaType.values}
    rows = (
        base.filter(event_type=QuickCardEventType.CTA_CLICK)
        .values("cta_type")
        .annotate(total=Count("id"))
    )
    for row in rows:
        key = (row["cta_type"] or "").lower()
        if key in clicks:
            clicks[key] = row["total"]
    bookings = _attributed_booking_count(
        organization=organization,
        business=business,
        start=start,
        end=end,
        card_ids=card_ids,
    )
    return {
        "views": base.filter(event_type=QuickCardEventType.PAGE_VIEW).count(),
        "cta_clicks": clicks,
        "bookings": bookings,
        "booking_conversion_rate": _booking_conversion_rate(
            bookings=bookings, book_clicks=clicks["book"]
        ),
        "date_from": start.date().isoformat(),
        "date_to": end.date().isoformat(),
    }


def _booking_conversion_rate(*, bookings: int, book_clicks: int) -> float | None:
    """Book Now clicks to attributed bookings. Undefined when there are no clicks."""
    if book_clicks <= 0:
        return None
    rate = (Decimal(bookings) * Decimal(100) / Decimal(book_clicks)).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    return float(rate)


def _quickcard_ids(*, organization, business, location):
    cards = QuickCard.all_objects.filter(organization=organization, business=business)
    if location is not None:
        cards = cards.filter(location=location)
    return cards.values("id")


def _attributed_booking_count(*, organization, business, start, end, card_ids) -> int:
    from booking.models import Appointment

    return Appointment.objects.filter(
        organization=organization,
        business=business,
        acquisition_source="QUICKCARD",
        acquisition_reference__in=card_ids,
        created_at__gte=start,
        created_at__lte=end,
    ).count()
