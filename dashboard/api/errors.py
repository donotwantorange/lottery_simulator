from django.http import JsonResponse
from rest_framework.exceptions import (
    AuthenticationFailed, NotAuthenticated, NotFound, PermissionDenied,
    Throttled, ValidationError,
)
from rest_framework.views import exception_handler as drf_exception_handler


class APIError(Exception):
    def __init__(self, code, message, status=400, fields=None):
        self.code, self.message, self.status = code, message, status
        self.fields = fields or {}


def error_response(code, message, status=400, fields=None):
    response = JsonResponse({"error": {"code": code, "message": message,
                                       "fields": fields or {}}}, status=status)
    response["Cache-Control"] = "no-store"
    return response


def csrf_failure(request, reason=""):
    return error_response("forbidden", "CSRF校验失败，请刷新页面重试", 403)


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        return None
    if isinstance(exc, (NotAuthenticated, AuthenticationFailed)):
        response.status_code = 401
        code, message = "unauthenticated", "请重新登录"
    elif isinstance(exc, ValidationError):
        code, message = "validation_error", "请求参数无效"
    elif isinstance(exc, NotFound):
        code, message = "not_found", "资源不存在或不可访问"
    elif isinstance(exc, Throttled):
        code, message = "rate_limited", "请求过于频繁，请稍后重试"
    elif isinstance(exc, PermissionDenied):
        code, message = "forbidden", "无权执行此操作"
    else:
        code, message = "validation_error", "请求无法处理"
    response.data = {"error": {"code": code, "message": message, "fields": {}}}
    response["Cache-Control"] = "no-store"
    return response
