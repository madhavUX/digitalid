"""Payment domain exceptions. Never leak provider secrets or raw SDK errors."""


class PaymentError(Exception):
    def __init__(self, message: str, *, code: str = "PAYMENT_ERROR"):
        super().__init__(message)
        self.code = code
        self.message = message


class PaymentNotEligible(PaymentError):
    def __init__(self, message: str = "Appointment is not eligible for payment."):
        super().__init__(message, code="PAYMENT_NOT_ELIGIBLE")


class PaymentAlreadyPaid(PaymentError):
    def __init__(self, message: str = "Appointment is already paid."):
        super().__init__(message, code="PAYMENT_ALREADY_PAID")


class PaymentSignatureInvalid(PaymentError):
    def __init__(self, message: str = "Payment signature is invalid."):
        super().__init__(message, code="PAYMENT_SIGNATURE_INVALID")


class PaymentProviderError(PaymentError):
    def __init__(self, message: str = "Payment provider error.", *, code: str = "PROVIDER_ERROR"):
        super().__init__(message, code=code)


class PaymentAmountInvalid(PaymentError):
    def __init__(self, message: str = "Payment amount is invalid."):
        super().__init__(message, code="PAYMENT_AMOUNT_INVALID")


class RefundNotAllowed(PaymentError):
    def __init__(self, message: str = "Refund is not allowed."):
        super().__init__(message, code="REFUND_NOT_ALLOWED")
