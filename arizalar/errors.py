"""Yagona xato formati: {"xato": "umumiy xabar", "maydonlar": {...}}."""
from django.http import Http404
from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


class ApiError(Exception):
    def __init__(self, status, xato, maydonlar=None):
        super().__init__(xato)
        self.status = status
        self.xato = xato
        self.maydonlar = maydonlar or {}


def validation_error(maydonlar, xato='Ma\'lumotlar noto\'g\'ri'):
    return ApiError(422, xato, maydonlar)


def _body(xato, maydonlar=None):
    return {'xato': xato, 'maydonlar': maydonlar or {}}


def exception_handler(exc, context):
    if isinstance(exc, ApiError):
        return Response(_body(exc.xato, exc.maydonlar), status=exc.status)
    if isinstance(exc, Http404):
        return Response(_body('Ariza topilmadi'), status=404)
    if isinstance(exc, exceptions.ParseError):
        return Response(_body(f'So\'rovni o\'qib bo\'lmadi: {exc.detail}'), status=422)
    if isinstance(exc, exceptions.UnsupportedMediaType):
        return Response(_body('So\'rov turi qo\'llab-quvvatlanmaydi', {'Content-Type': str(exc.detail)}), status=415)
    if isinstance(exc, exceptions.MethodNotAllowed):
        return Response(_body('Bu metod ruxsat etilmagan'), status=405)

    response = drf_exception_handler(exc, context)
    if response is not None:
        detail = response.data
        if isinstance(detail, dict) and 'detail' in detail:
            response.data = _body(str(detail['detail']))
        else:
            response.data = _body('So\'rov xatosi', detail if isinstance(detail, dict) else {})
    return response
