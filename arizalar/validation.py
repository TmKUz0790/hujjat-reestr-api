"""Ariza ma'lumotlarini tekshirish (4.1-bo'lim). Har bir funksiya xatolarni {maydon: xabar} ko'rinishida beradi."""
import datetime as dt
import numbers
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from .models import HUJJAT_TURLARI
from .soato import soato_codes

# O'zbekiston hududi (4.1-bo'lim)
LON_MIN, LON_MAX = 55.9, 73.2
LAT_MIN, LAT_MAX = 37.1, 45.6

RUXSAT_ETILGAN_FAYLLAR = {
    '.pdf': (b'%PDF',),
    '.jpg': (b'\xff\xd8\xff',),
    '.jpeg': (b'\xff\xd8\xff',),
    '.png': (b'\x89PNG\r\n\x1a\n',),
}


class ChegaraXatosi(ValueError):
    pass


def _check_ring(ring, where):
    if not isinstance(ring, list) or len(ring) < 4:
        raise ChegaraXatosi(f'{where}: halqada kamida 4 nuqta bo\'lishi kerak')
    for i, pt in enumerate(ring):
        if (not isinstance(pt, list) or len(pt) < 2
                or not all(isinstance(v, numbers.Real) and not isinstance(v, bool) for v in pt[:2])):
            raise ChegaraXatosi(f'{where}, {i}-nuqta: [uzunlik, kenglik] sonlar bo\'lishi kerak')
        lon, lat = pt[0], pt[1]
        if not (LON_MIN <= lon <= LON_MAX and LAT_MIN <= lat <= LAT_MAX):
            raise ChegaraXatosi(
                f'{where}, {i}-nuqta [{lon}, {lat}] O\'zbekiston hududidan tashqarida '
                f'(uzunlik {LON_MIN}–{LON_MAX}, kenglik {LAT_MIN}–{LAT_MAX})')
    if list(ring[0][:2]) != list(ring[-1][:2]):
        raise ChegaraXatosi(f'{where}: halqa yopilmagan (birinchi va oxirgi nuqta bir xil bo\'lishi kerak)')


def _check_polygon(rings, where):
    if not isinstance(rings, list) or not rings:
        raise ChegaraXatosi(f'{where}: kamida bitta halqa bo\'lishi kerak')
    for j, ring in enumerate(rings):
        _check_ring(ring, f'{where}, {j}-halqa')


def validate_chegara(geom):
    """GeoJSON Polygon/MultiPolygon tekshiruvi. Xato bo'lsa ChegaraXatosi."""
    if not isinstance(geom, dict):
        raise ChegaraXatosi('GeoJSON obyekt bo\'lishi kerak')
    gtype = geom.get('type')
    coords = geom.get('coordinates')
    if gtype == 'Polygon':
        _check_polygon(coords, 'Poligon')
    elif gtype == 'MultiPolygon':
        if not isinstance(coords, list) or not coords:
            raise ChegaraXatosi('MultiPolygon bo\'sh')
        for k, poly in enumerate(coords):
            _check_polygon(poly, f'{k}-poligon')
    else:
        raise ChegaraXatosi('turi Polygon yoki MultiPolygon bo\'lishi kerak')
    return {'type': gtype, 'coordinates': coords}


def validate_data(data):
    """`data` JSON maydonini tekshiradi. (tozalangan_dict, xatolar) qaytaradi."""
    errors, clean = {}, {}
    if not isinstance(data, dict):
        return {}, {'data': 'JSON obyekt bo\'lishi kerak'}

    nomi = data.get('hujjat_nomi')
    if not isinstance(nomi, str) or not nomi.strip():
        errors['hujjat_nomi'] = 'bo\'sh bo\'lmasin'
    elif len(nomi.strip()) > 255:
        errors['hujjat_nomi'] = '255 belgidan oshmasin'
    else:
        clean['hujjat_nomi'] = nomi.strip()

    turi = data.get('hujjat_turi')
    if turi not in HUJJAT_TURLARI:
        errors['hujjat_turi'] = 'ruxsat etilgan qiymatlar: ' + ', '.join(HUJJAT_TURLARI)
    else:
        clean['hujjat_turi'] = turi

    soato = data.get('soato_kodi')
    if not isinstance(soato, str) or len(soato) != 7 or not soato.isdigit():
        errors['soato_kodi'] = '7 xonali raqam bo\'lishi kerak'
    elif soato not in soato_codes():
        errors['soato_kodi'] = 'ro\'yxatda yo\'q'
    else:
        clean['soato_kodi'] = soato

    sana = data.get('tasdiq_sanasi')
    try:
        if not isinstance(sana, str):
            raise ValueError
        parsed = dt.date.fromisoformat(sana)
        if len(sana) != 10:
            raise ValueError
    except ValueError:
        errors['tasdiq_sanasi'] = 'YYYY-MM-DD formatida bo\'lishi kerak'
    else:
        if parsed > timezone.localdate():
            errors['tasdiq_sanasi'] = 'kelajakdagi sana bo\'lmasin'
        else:
            clean['tasdiq_sanasi'] = parsed

    hujjat = data.get('tasdiq_hujjati')
    if not isinstance(hujjat, str) or not hujjat.strip():
        errors['tasdiq_hujjati'] = 'bo\'sh bo\'lmasin'
    elif len(hujjat.strip()) > 100:
        errors['tasdiq_hujjati'] = '100 belgidan oshmasin'
    else:
        clean['tasdiq_hujjati'] = hujjat.strip()

    if 'chegara' not in data:
        errors['chegara'] = 'majburiy'
    else:
        try:
            clean['chegara'] = validate_chegara(data['chegara'])
        except ChegaraXatosi as exc:
            errors['chegara'] = str(exc)

    return clean, errors


def validate_file(upload):
    """Yuklangan faylni tekshiradi; xato bo'lsa matn, aks holda None."""
    if upload.size > settings.MAX_FILE_SIZE:
        mb = settings.MAX_FILE_SIZE // (1024 * 1024)
        return f'fayl hajmi {mb} MB dan oshmasin (yuborilgan: {upload.size / 1024 / 1024:.1f} MB)'
    ext = Path(upload.name or '').suffix.lower()
    signatures = RUXSAT_ETILGAN_FAYLLAR.get(ext)
    if not signatures:
        return 'faqat PDF, JPG yoki PNG fayl'
    head = upload.read(8)
    upload.seek(0)
    if not any(head.startswith(sig) for sig in signatures):
        return f'fayl mazmuni {ext} formatiga mos emas'
    return None
