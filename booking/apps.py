from django.apps import AppConfig


class BookingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "booking"

    def ready(self) -> None:
        from booking import checks  # noqa: F401
        from booking.events import AppointmentBooked, AppointmentCancelled, register_handler
        from booking.notifications import (
            handle_appointment_booked,
            handle_appointment_cancelled,
        )

        register_handler(AppointmentBooked, handle_appointment_booked)
        register_handler(AppointmentCancelled, handle_appointment_cancelled)
