import json

from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .arcgis import ArcGISClient
from .errors import ApiError, validation_error
from .models import FAYL_MAYDONLARI, HUJJAT_TURLARI, Ariza, Holat
from .muddat import ish_kuni_qosh
from .soato import soato_list

ARIZA_BERUVCHI = 'ariza_beruvchi'
TEKSHIRUVCHI = 'tekshiruvchi'
ROLLAR = (ARIZA_BERUVCHI, TEKSHIRUVCHI)

X_ROL = OpenApiParameter('X-Rol', str, OpenApiParameter.HEADER, required=True, enum=list(ROLLAR))
XATO = inline_serializer('Xato', {'xato': serializers.CharField(), 'maydonlar': serializers.DictField()})


def require_role(request, *allowed):
    rol = request.headers.get('X-Rol', '')
    if rol not in ROLLAR:
        raise ApiError(403, 'X-Rol sarlavhasi kerak: ariza_beruvchi yoki tekshiruvchi', {'X-Rol': 'noto\'g\'ri yoki yo\'q'})
    if rol not in allowed:
        raise ApiError(403, f'Bu amal "{rol}" roli uchun ruxsat etilmagan')
    return rol


def parse_data_field(request):
    """multipart'dagi `data` maydoni (JSON matn). JSON so'rovda obyektning o'zi qabul qilinadi."""
    raw = request.data.get('data') if hasattr(request.data, 'get') else None
    if raw is None:
        raise validation_error({'data': 'majburiy (JSON matn)'})
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode('utf-8')
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise validation_error({'data': f'JSON xato: {exc.msg}'})
    return raw


# ---------- javob shakllari ----------

def _soato_nomi():
    return {r['kod']: r['nomi'] for r in soato_list()}


def _muddat(ariza):
    if ariza.holat != Holat.YUBORILGAN:
        return None, False
    deadline = ish_kuni_qosh(timezone.localtime(ariza.yuborilgan_vaqt))
    return deadline, timezone.now() > deadline


def ariza_short(ariza, nomlar):
    deadline, otgan = _muddat(ariza)
    return {
        'id': ariza.pk,
        'id_raqam': ariza.id_raqam,
        'hujjat_nomi': ariza.hujjat_nomi,
        'hujjat_turi': ariza.hujjat_turi,
        'soato_kodi': ariza.soato_kodi,
        'hudud_nomi': nomlar.get(ariza.soato_kodi, ''),
        'tasdiq_sanasi': ariza.tasdiq_sanasi.isoformat(),
        'holat': ariza.holat,
        'yuborilgan_vaqt': timezone.localtime(ariza.yuborilgan_vaqt).isoformat(),
        'muddat': deadline.isoformat() if deadline else None,
        'muddat_otgan': otgan,
    }


def ariza_full(request, ariza):
    data = ariza_short(ariza, _soato_nomi())
    client = ArcGISClient()
    data.update({
        'tasdiq_hujjati': ariza.tasdiq_hujjati,
        'chegara': ariza.chegara,
        'qaytarish_sababi': ariza.qaytarish_sababi or None,
        'arcgis_object_id': ariza.arcgis_object_id,
        'arcgis_qatlam_url': client.layer_url,
        'arcgis_query_url': client.query_url(ariza.arcgis_object_id) if ariza.arcgis_object_id else None,
        'fayllar': [
            {
                'maydon': name,
                'nomi': (ariza.fayl_nomlari or {}).get(name, ''),
                'url': request.build_absolute_uri(f'/api/arizalar/{ariza.pk}/fayllar/{name}'),
            }
            for name in FAYL_MAYDONLARI if getattr(ariza, name)
        ],
    })
    return data


MULTIPART_BODY = {
    'multipart/form-data': {
        'type': 'object',
        'properties': {
            'data': {'type': 'string', 'description': 'Ariza maydonlari JSON matn ko\'rinishida'},
            **{name: {'type': 'string', 'format': 'binary'} for name in FAYL_MAYDONLARI},
        },
        'required': ['data'],
    }
}


# ---------- endpointlar ----------

class ArizalarView(APIView):
    @extend_schema(
        summary='Arizalar ro\'yxati', operation_id='arizalar_list', parameters=[
            X_ROL,
            OpenApiParameter('holat', str, enum=[h.value for h in Holat]),
            OpenApiParameter('hujjat_turi', str, enum=HUJJAT_TURLARI),
            OpenApiParameter('soato_kodi', str),
            OpenApiParameter('sahifa', int, description='1 dan boshlanadi'),
            OpenApiParameter('hajm', int, description='1–100, standart 20'),
        ],
        responses={200: OpenApiTypes.OBJECT, 422: XATO},
    )
    def get(self, request):
        require_role(request, *ROLLAR)
        qs = Ariza.objects.all()
        errors = {}
        holat = request.query_params.get('holat')
        if holat:
            if holat not in Holat.values:
                errors['holat'] = 'ruxsat etilgan: ' + ', '.join(Holat.values)
            qs = qs.filter(holat=holat)
        turi = request.query_params.get('hujjat_turi')
        if turi:
            if turi not in HUJJAT_TURLARI:
                errors['hujjat_turi'] = 'ruxsat etilgan: ' + ', '.join(HUJJAT_TURLARI)
            qs = qs.filter(hujjat_turi=turi)
        soato = request.query_params.get('soato_kodi')
        if soato:
            qs = qs.filter(soato_kodi=soato)

        def int_param(name, default, lo, hi):
            raw = request.query_params.get(name)
            if raw in (None, ''):
                return default
            try:
                value = int(raw)
            except ValueError:
                value = None
            if value is None or not lo <= value <= hi:
                errors[name] = f'{lo}–{hi} oralig\'idagi butun son bo\'lishi kerak'
                return default
            return value

        sahifa = int_param('sahifa', 1, 1, 10 ** 6)
        hajm = int_param('hajm', 20, 1, 100)
        if errors:
            raise validation_error(errors, 'Filtr parametrlari noto\'g\'ri')

        jami = qs.count()
        start = (sahifa - 1) * hajm
        nomlar = _soato_nomi()
        items = [ariza_short(a, nomlar) for a in qs[start:start + hajm]]
        return Response({'items': items, 'jami': jami, 'sahifa': sahifa, 'hajm': hajm})

    @extend_schema(
        summary='Ariza yuborish', parameters=[X_ROL], request=MULTIPART_BODY,
        responses={201: inline_serializer('ArizaYaratildi', {'id': serializers.IntegerField(), 'holat': serializers.CharField()}),
                   422: XATO},
    )
    def post(self, request):
        require_role(request, ARIZA_BERUVCHI)
        ariza = services.create_ariza(parse_data_field(request), request.FILES)
        return Response({'id': ariza.pk, 'holat': ariza.holat}, status=201)


class ArizaView(APIView):
    @extend_schema(summary='Arizani ko\'rish', operation_id='ariza_retrieve', parameters=[X_ROL], responses={200: OpenApiTypes.OBJECT, 404: XATO})
    def get(self, request, pk):
        require_role(request, *ROLLAR)
        return Response(ariza_full(request, get_object_or_404(Ariza, pk=pk)))

    @extend_schema(
        summary='Qaytarilgan arizani tuzatib qayta yuborish', parameters=[X_ROL], request=MULTIPART_BODY,
        description='Fayllar ixtiyoriy: yuborilmagan fayl avvalgisicha qoladi.',
        responses={200: OpenApiTypes.OBJECT, 409: XATO, 422: XATO},
    )
    def put(self, request, pk):
        require_role(request, ARIZA_BERUVCHI)
        get_object_or_404(Ariza, pk=pk)
        ariza = services.resubmit_ariza(pk, parse_data_field(request), request.FILES)
        return Response(ariza_full(request, ariza))


class TasdiqlashView(APIView):
    @extend_schema(
        summary='Tasdiqlash: ID yaratish va chegarani ArcGIS\'ga yozish', parameters=[X_ROL], request=None,
        responses={200: inline_serializer('Tasdiqlandi', {'id_raqam': serializers.CharField(),
                                                          'arcgis_object_id': serializers.IntegerField()}),
                   409: XATO, 502: XATO},
    )
    def post(self, request, pk):
        require_role(request, TEKSHIRUVCHI)
        get_object_or_404(Ariza, pk=pk)
        ariza = services.approve_ariza(pk)
        return Response({'id_raqam': ariza.id_raqam, 'arcgis_object_id': ariza.arcgis_object_id})


class QaytarishView(APIView):
    @extend_schema(
        summary='Arizani qaytarish', parameters=[X_ROL],
        request=inline_serializer('Qaytarish', {'sabab': serializers.CharField()}),
        responses={200: OpenApiTypes.OBJECT, 409: XATO, 422: XATO},
    )
    def post(self, request, pk):
        require_role(request, TEKSHIRUVCHI)
        get_object_or_404(Ariza, pk=pk)
        sabab = request.data.get('sabab') if hasattr(request.data, 'get') else None
        ariza = services.return_ariza(pk, sabab)
        return Response({'id': ariza.pk, 'holat': ariza.holat, 'sabab': ariza.qaytarish_sababi})


class FaylView(APIView):
    @extend_schema(summary='Ariza faylini yuklab olish', parameters=[X_ROL], responses={200: OpenApiTypes.BINARY, 404: XATO})
    def get(self, request, pk, maydon):
        require_role(request, *ROLLAR)
        ariza = get_object_or_404(Ariza, pk=pk)
        if maydon not in FAYL_MAYDONLARI or not getattr(ariza, maydon):
            raise ApiError(404, 'Fayl topilmadi')
        field = getattr(ariza, maydon)
        name = (ariza.fayl_nomlari or {}).get(maydon) or field.name.rsplit('/', 1)[-1]
        return FileResponse(field.open('rb'), as_attachment=False, filename=name)


class SoatoView(APIView):
    @extend_schema(summary='SOATO ro\'yxati', parameters=[X_ROL],
                   responses={200: inline_serializer('Soato', {'kod': serializers.CharField(), 'nomi': serializers.CharField()}, many=True)})
    def get(self, request):
        require_role(request, *ROLLAR)
        return Response(soato_list())
