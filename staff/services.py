from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError

from businesses.services import get_business_for_organization
from catalog.services import get_service_for_business
from locations.services import get_location_for_business
from organizations.models import OrganizationMember
from staff.models import StaffAvailability, StaffProfile, StaffService, StaffTimeOff, Weekday

User = get_user_model()


def _validate_duration(value: int, field: str = "duration_minutes") -> int:
    if value is None or value < 1:
        raise ValidationError({field: "Duration must be at least 1 minute."})
    return value


def _validate_price(value, field: str = "price") -> Decimal:
    amount = Decimal(str(value))
    if amount < 0:
        raise ValidationError({field: "Price cannot be negative."})
    return amount


def _normalize_currency(value: str | None) -> str:
    if value is None:
        return "INR"
    currency = value.strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ValidationError({"currency": "Enter a valid ISO 4217 currency code."})
    return currency


def _resolve_optional_user(*, organization, user_id):
    if user_id is None:
        return None
    user = get_object_or_404(User, pk=user_id, is_active=True)
    membership = OrganizationMember.objects.filter(
        organization=organization,
        user=user,
        is_active=True,
        organization__is_active=True,
    ).first()
    if membership is None:
        raise ValidationError(
            {"user_id": "User must be an active member of the current organization."}
        )
    return user


def list_staff_profiles(*, organization, business):
    return (
        StaffProfile.objects.filter(organization=organization, business=business)
        .select_related("location", "user")
        .order_by("display_name")
    )


def get_staff_profile_for_business(*, organization, business, staff_id) -> StaffProfile:
    return get_object_or_404(
        StaffProfile.objects.select_related("location", "user"),
        organization=organization,
        business=business,
        pk=staff_id,
    )


@transaction.atomic
def create_staff_profile(
    *,
    organization,
    business_id,
    actor,
    display_name: str,
    location_id,
    title: str = "",
    bio: str = "",
    photo_url: str = "",
    user_id=None,
    is_bookable: bool = True,
    is_active: bool = True,
) -> StaffProfile:
    business = get_business_for_organization(
        organization=organization,
        business_id=business_id,
    )
    display_name = display_name.strip()
    if not display_name:
        raise ValidationError({"display_name": "This field may not be blank."})

    location = get_location_for_business(
        organization=organization,
        business=business,
        location_id=location_id,
    )
    user = _resolve_optional_user(organization=organization, user_id=user_id)

    if (
        user is not None
        and StaffProfile.objects.filter(
            organization=organization,
            user=user,
        ).exists()
    ):
        raise ValidationError(
            {"user_id": "This user already has a staff profile in this organization."}
        )

    return StaffProfile.objects.create(
        organization=organization,
        business=business,
        location=location,
        user=user,
        display_name=display_name,
        title=title or "",
        bio=bio or "",
        photo_url=photo_url or "",
        is_bookable=is_bookable,
        is_active=is_active,
        created_by=actor,
        updated_by=actor,
    )


@transaction.atomic
def update_staff_profile(*, staff_profile: StaffProfile, actor, **fields) -> StaffProfile:
    if "display_name" in fields and fields["display_name"] is not None:
        name = fields["display_name"].strip()
        if not name:
            raise ValidationError({"display_name": "This field may not be blank."})
        staff_profile.display_name = name

    if "title" in fields and fields["title"] is not None:
        staff_profile.title = fields["title"]

    if "bio" in fields and fields["bio"] is not None:
        staff_profile.bio = fields["bio"]

    if "photo_url" in fields and fields["photo_url"] is not None:
        staff_profile.photo_url = fields["photo_url"]

    if "is_bookable" in fields and fields["is_bookable"] is not None:
        staff_profile.is_bookable = fields["is_bookable"]

    if "is_active" in fields and fields["is_active"] is not None:
        staff_profile.is_active = fields["is_active"]

    if "location_id" in fields and fields["location_id"] is not None:
        staff_profile.location = get_location_for_business(
            organization=staff_profile.organization,
            business=staff_profile.business,
            location_id=fields["location_id"],
        )

    if "user_id" in fields:
        user = _resolve_optional_user(
            organization=staff_profile.organization,
            user_id=fields["user_id"],
        )
        if (
            user is not None
            and StaffProfile.objects.filter(
                organization=staff_profile.organization,
                user=user,
            )
            .exclude(pk=staff_profile.pk)
            .exists()
        ):
            raise ValidationError(
                {"user_id": "This user already has a staff profile in this organization."}
            )
        staff_profile.user = user

    staff_profile.updated_by = actor
    staff_profile.save()
    return staff_profile


@transaction.atomic
def soft_delete_staff_profile(*, staff_profile: StaffProfile, actor) -> None:
    StaffService.objects.filter(staff_profile=staff_profile).delete()
    StaffAvailability.objects.filter(staff_profile=staff_profile).delete()
    StaffTimeOff.objects.filter(staff_profile=staff_profile).delete()
    staff_profile.soft_delete(actor=actor)


def list_staff_services(*, organization, staff_profile):
    return (
        StaffService.objects.filter(
            organization=organization,
            staff_profile=staff_profile,
        )
        .select_related("service", "staff_profile")
        .order_by("created_at")
    )


def get_staff_service(*, organization, staff_profile, staff_service_id) -> StaffService:
    return get_object_or_404(
        StaffService.objects.select_related("service", "staff_profile"),
        organization=organization,
        staff_profile=staff_profile,
        pk=staff_service_id,
    )


@transaction.atomic
def assign_staff_service(
    *,
    organization,
    business,
    staff_profile,
    actor,
    service_id,
    duration_minutes=None,
    price=None,
    currency: str = "",
) -> StaffService:
    service = get_service_for_business(
        organization=organization,
        business=business,
        service_id=service_id,
    )

    if service.business_id != staff_profile.business_id:
        raise ValidationError(
            {"service_id": "Service must belong to the same business as the staff profile."}
        )
    if (
        service.organization_id != organization.id
        or staff_profile.organization_id != organization.id
    ):
        raise ValidationError(
            {"detail": "Staff and service must belong to the current organization."}
        )

    if StaffService.objects.filter(staff_profile=staff_profile, service=service).exists():
        raise ValidationError(
            {"service_id": "This service is already assigned to this staff member."}
        )

    override_duration = None
    if duration_minutes is not None:
        override_duration = _validate_duration(duration_minutes)

    override_price = None
    override_currency = ""
    if price is not None:
        override_price = _validate_price(price)
        override_currency = _normalize_currency(currency or service.currency)

    return StaffService.objects.create(
        organization=organization,
        staff_profile=staff_profile,
        service=service,
        duration_minutes=override_duration,
        price=override_price,
        currency=override_currency,
        created_by=actor,
        updated_by=actor,
    )


@transaction.atomic
def update_staff_service(*, staff_service: StaffService, actor, **fields) -> StaffService:
    if "duration_minutes" in fields:
        value = fields["duration_minutes"]
        staff_service.duration_minutes = None if value is None else _validate_duration(value)

    if "price" in fields:
        value = fields["price"]
        if value is None:
            staff_service.price = None
            if "currency" not in fields:
                staff_service.currency = ""
        else:
            staff_service.price = _validate_price(value)
            if "currency" in fields and fields["currency"]:
                staff_service.currency = _normalize_currency(fields["currency"])
            elif not staff_service.currency:
                staff_service.currency = staff_service.service.currency

    if "currency" in fields and fields["currency"] is not None and "price" not in fields:
        if fields["currency"] == "":
            staff_service.currency = ""
        else:
            staff_service.currency = _normalize_currency(fields["currency"])

    staff_service.updated_by = actor
    staff_service.save()
    return staff_service


@transaction.atomic
def remove_staff_service(*, staff_service: StaffService) -> None:
    staff_service.delete()


# --- StaffAvailability ---


def _validate_weekday(value: int) -> int:
    if value not in Weekday.values:
        raise ValidationError(
            {"weekday": "Weekday must be an integer from 0 (Monday) to 6 (Sunday)."}
        )
    return value


def _assert_availability_window(*, starts_at, ends_at) -> None:
    if ends_at <= starts_at:
        raise ValidationError({"ends_at": "End time must be after start time."})


def _assert_no_availability_overlap(
    *,
    staff_profile,
    location,
    weekday: int,
    starts_at,
    ends_at,
    exclude_id=None,
) -> None:
    qs = StaffAvailability.objects.filter(
        staff_profile=staff_profile,
        location=location,
        weekday=weekday,
        starts_at__lt=ends_at,
        ends_at__gt=starts_at,
    )
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)
    if qs.exists():
        raise ValidationError(
            {
                "non_field_errors": [
                    "This availability overlaps an existing schedule for the same "
                    "staff, location, and weekday."
                ]
            }
        )


def list_staff_availabilities(*, organization, staff_profile):
    return (
        StaffAvailability.objects.filter(
            organization=organization,
            staff_profile=staff_profile,
        )
        .select_related("location", "staff_profile")
        .order_by("weekday", "starts_at")
    )


def get_staff_availability(*, organization, staff_profile, availability_id) -> StaffAvailability:
    return get_object_or_404(
        StaffAvailability.objects.select_related("location", "staff_profile"),
        organization=organization,
        staff_profile=staff_profile,
        pk=availability_id,
    )


@transaction.atomic
def create_staff_availability(
    *,
    organization,
    business,
    staff_profile,
    actor,
    location_id,
    weekday: int,
    starts_at,
    ends_at,
) -> StaffAvailability:
    weekday = _validate_weekday(weekday)
    _assert_availability_window(starts_at=starts_at, ends_at=ends_at)

    location = get_location_for_business(
        organization=organization,
        business=business,
        location_id=location_id,
    )
    if location.business_id != staff_profile.business_id:
        raise ValidationError(
            {"location_id": "Location must belong to the same business as the staff profile."}
        )
    if location.organization_id != organization.id:
        raise ValidationError({"location_id": "Location must belong to the current organization."})

    _assert_no_availability_overlap(
        staff_profile=staff_profile,
        location=location,
        weekday=weekday,
        starts_at=starts_at,
        ends_at=ends_at,
    )

    return StaffAvailability.objects.create(
        organization=organization,
        staff_profile=staff_profile,
        location=location,
        weekday=weekday,
        starts_at=starts_at,
        ends_at=ends_at,
        created_by=actor,
        updated_by=actor,
    )


@transaction.atomic
def update_staff_availability(
    *,
    availability: StaffAvailability,
    actor,
    business,
    **fields,
) -> StaffAvailability:
    location = availability.location
    weekday = availability.weekday
    starts_at = availability.starts_at
    ends_at = availability.ends_at

    if "location_id" in fields and fields["location_id"] is not None:
        location = get_location_for_business(
            organization=availability.organization,
            business=business,
            location_id=fields["location_id"],
        )
        if location.business_id != availability.staff_profile.business_id:
            raise ValidationError(
                {"location_id": "Location must belong to the same business as the staff profile."}
            )

    if "weekday" in fields and fields["weekday"] is not None:
        weekday = _validate_weekday(fields["weekday"])

    if "starts_at" in fields and fields["starts_at"] is not None:
        starts_at = fields["starts_at"]

    if "ends_at" in fields and fields["ends_at"] is not None:
        ends_at = fields["ends_at"]

    _assert_availability_window(starts_at=starts_at, ends_at=ends_at)
    _assert_no_availability_overlap(
        staff_profile=availability.staff_profile,
        location=location,
        weekday=weekday,
        starts_at=starts_at,
        ends_at=ends_at,
        exclude_id=availability.pk,
    )

    availability.location = location
    availability.weekday = weekday
    availability.starts_at = starts_at
    availability.ends_at = ends_at
    availability.updated_by = actor
    availability.save()
    return availability


@transaction.atomic
def delete_staff_availability(*, availability: StaffAvailability) -> None:
    availability.delete()


# --- StaffTimeOff ---


def _assert_time_off_window(*, starts_at, ends_at) -> None:
    if ends_at <= starts_at:
        raise ValidationError({"ends_at": "End datetime must be after start datetime."})


def list_staff_time_offs(*, organization, staff_profile):
    return (
        StaffTimeOff.objects.filter(
            organization=organization,
            staff_profile=staff_profile,
        )
        .select_related("staff_profile")
        .order_by("-starts_at")
    )


def get_staff_time_off(*, organization, staff_profile, time_off_id) -> StaffTimeOff:
    return get_object_or_404(
        StaffTimeOff.objects.select_related("staff_profile"),
        organization=organization,
        staff_profile=staff_profile,
        pk=time_off_id,
    )


@transaction.atomic
def create_staff_time_off(
    *,
    organization,
    staff_profile,
    actor,
    starts_at,
    ends_at,
    reason: str = "",
) -> StaffTimeOff:
    _assert_time_off_window(starts_at=starts_at, ends_at=ends_at)
    return StaffTimeOff.objects.create(
        organization=organization,
        staff_profile=staff_profile,
        starts_at=starts_at,
        ends_at=ends_at,
        reason=(reason or "").strip(),
        created_by=actor,
        updated_by=actor,
    )


@transaction.atomic
def update_staff_time_off(*, time_off: StaffTimeOff, actor, **fields) -> StaffTimeOff:
    starts_at = time_off.starts_at
    ends_at = time_off.ends_at

    if "starts_at" in fields and fields["starts_at"] is not None:
        starts_at = fields["starts_at"]
    if "ends_at" in fields and fields["ends_at"] is not None:
        ends_at = fields["ends_at"]
    if "reason" in fields and fields["reason"] is not None:
        time_off.reason = fields["reason"].strip()

    _assert_time_off_window(starts_at=starts_at, ends_at=ends_at)
    time_off.starts_at = starts_at
    time_off.ends_at = ends_at
    time_off.updated_by = actor
    time_off.save()
    return time_off


@transaction.atomic
def delete_staff_time_off(*, time_off: StaffTimeOff) -> None:
    time_off.delete()
