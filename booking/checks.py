from django.core.checks import Error, register


@register()
def check_meta_whatsapp_settings(app_configs, **kwargs):
    from django.conf import settings

    errors = []
    enabled = getattr(settings, "WHATSAPP_ENABLED", False)
    provider = (getattr(settings, "WHATSAPP_PROVIDER", "mock") or "mock").lower()
    if not enabled or provider != "meta":
        return errors

    required = [
        "META_WHATSAPP_ACCESS_TOKEN",
        "META_WHATSAPP_PHONE_NUMBER_ID",
        "META_WHATSAPP_VERIFY_TOKEN",
        "META_WHATSAPP_APP_SECRET",
        "META_WHATSAPP_API_VERSION",
        "WHATSAPP_BOOKING_CONFIRMATION_TEMPLATE",
        "WHATSAPP_BOOKING_CANCELLATION_TEMPLATE",
    ]
    missing = [name for name in required if not getattr(settings, name, "")]
    for name in missing:
        errors.append(
            Error(
                f"{name} is required when WHATSAPP_ENABLED=true and WHATSAPP_PROVIDER=meta.",
                id="booking.E001",
            )
        )

    if getattr(settings, "WHATSAPP_REMINDERS_ENABLED", False):
        if getattr(settings, "WHATSAPP_REMINDER_24H_ENABLED", True) and not getattr(
            settings, "WHATSAPP_REMINDER_24H_TEMPLATE", ""
        ):
            errors.append(
                Error(
                    "WHATSAPP_REMINDER_24H_TEMPLATE is required when reminders and "
                    "24h reminders are enabled with WHATSAPP_PROVIDER=meta.",
                    id="booking.E002",
                )
            )
        if getattr(settings, "WHATSAPP_REMINDER_1H_ENABLED", True) and not getattr(
            settings, "WHATSAPP_REMINDER_1H_TEMPLATE", ""
        ):
            errors.append(
                Error(
                    "WHATSAPP_REMINDER_1H_TEMPLATE is required when reminders and "
                    "1h reminders are enabled with WHATSAPP_PROVIDER=meta.",
                    id="booking.E003",
                )
            )
    return errors
