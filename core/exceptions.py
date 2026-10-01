from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return response

    detail = response.data
    if isinstance(detail, dict) and "detail" in detail and len(detail) == 1:
        message = detail["detail"]
    else:
        message = detail

    payload = {
        "error": message,
        "status_code": response.status_code,
    }
    error_code = getattr(exc, "error_code", None)
    if error_code:
        payload["code"] = error_code
    response.data = payload
    return response
