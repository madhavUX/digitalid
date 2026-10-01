from django.apps import AppConfig


class MessagingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "messaging"

    def ready(self) -> None:
        from booking.events import (
            AppointmentCancelled,
            AppointmentCompleted,
            AppointmentConfirmed,
            AppointmentCreated,
            AppointmentRescheduled,
            register_handler,
        )
        from messaging.lifecycle import observe_appointment_lifecycle

        for event_type in (
            AppointmentCreated,
            AppointmentConfirmed,
            AppointmentCancelled,
            AppointmentRescheduled,
            AppointmentCompleted,
        ):
            register_handler(event_type, observe_appointment_lifecycle)
