"""Ariza holatlari bo'yicha biznes-mantiq (3-bo'lim sxemasi)."""
import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from .arcgis import ArcGISClient, ArcGISError, make_description
from .errors import ApiError, validation_error
from .geo import geojson_to_esri
from .id_raqam import generate_id_raqam
from .models import FAYL_MAYDONLARI, Ariza, Holat
from .validation import validate_data, validate_file

log = logging.getLogger(__name__)


def _validate_payload(data, files, files_required):
    clean, errors = validate_data(data)
    for name in FAYL_MAYDONLARI:
        upload = files.get(name)
        if upload is None:
            if files_required:
                errors[name] = 'fayl biriktirilmagan'
            continue
        err = validate_file(upload)
        if err:
            errors[name] = err
    if errors:
        raise validation_error(errors)
    return clean


def _apply(ariza, clean, files):
    for key, value in clean.items():
        setattr(ariza, key, value)
    names = dict(ariza.fayl_nomlari or {})
    for name in FAYL_MAYDONLARI:
        upload = files.get(name)
        if upload is not None:
            old = getattr(ariza, name)
            if old:
                old.delete(save=False)
            getattr(ariza, name).save(upload.name, upload, save=False)
            names[name] = upload.name
    ariza.fayl_nomlari = names


def create_ariza(data, files) -> Ariza:
    clean = _validate_payload(data, files, files_required=True)
    ariza = Ariza(holat=Holat.YUBORILGAN, yuborilgan_vaqt=timezone.now())
    with transaction.atomic():
        _apply(ariza, clean, files)
        ariza.save()
    log.info('Ariza #%s yuborildi', ariza.pk)
    return ariza


def resubmit_ariza(pk, data, files) -> Ariza:
    with transaction.atomic():
        ariza = Ariza.objects.select_for_update().get(pk=pk)
        if ariza.holat != Holat.QAYTARILGAN:
            raise ApiError(409, f'Faqat qaytarilgan arizani tuzatish mumkin (hozirgi holat: {ariza.holat})')
        clean = _validate_payload(data, files, files_required=False)
        _apply(ariza, clean, files)
        ariza.holat = Holat.YUBORILGAN
        ariza.qaytarish_sababi = ''
        ariza.yuborilgan_vaqt = timezone.now()
        ariza.save()
    log.info('Ariza #%s qayta yuborildi', ariza.pk)
    return ariza


def return_ariza(pk, sabab) -> Ariza:
    if not isinstance(sabab, str) or not sabab.strip():
        raise validation_error({'sabab': 'qaytarish sababi majburiy'})
    with transaction.atomic():
        ariza = Ariza.objects.select_for_update().get(pk=pk)
        if ariza.holat != Holat.YUBORILGAN:
            raise ApiError(409, f'Faqat yuborilgan arizani qaytarish mumkin (hozirgi holat: {ariza.holat})')
        ariza.holat = Holat.QAYTARILGAN
        ariza.qaytarish_sababi = sabab.strip()
        ariza.save(update_fields=['holat', 'qaytarish_sababi', 'yangilangan'])
    log.info('Ariza #%s qaytarildi', ariza.pk)
    return ariza


def approve_ariza(pk, client: ArcGISClient | None = None) -> Ariza:
    """Tasdiqlash: ID yaratish -> ArcGIS'ga yozish -> saqlash.

    ArcGIS xato bersa hech narsa saqlanmaydi (502). Qayta urinishda avval qatlam
    tavsif bo'yicha so'raladi: oldingi urinishda obyekt yozilib, javob yo'qolgan
    bo'lsa, ikkinchi obyekt yaratilmaydi.
    """
    client = client or ArcGISClient()
    with transaction.atomic():
        ariza = Ariza.objects.select_for_update().get(pk=pk)
        if ariza.holat != Holat.YUBORILGAN:
            raise ApiError(409, f'Faqat yuborilgan arizani tasdiqlash mumkin (hozirgi holat: {ariza.holat})')

        id_raqam = generate_id_raqam(ariza.hujjat_turi, ariza.soato_kodi, ariza.tasdiq_sanasi)
        if Ariza.objects.filter(id_raqam=id_raqam).exclude(pk=ariza.pk).exists():
            raise ApiError(409, f'{id_raqam} ID raqamli hujjat allaqachon ro\'yxatga olingan',
                           {'id_raqam': 'takrorlanmoqda'})

        description = make_description(id_raqam, ariza.hujjat_nomi)
        try:
            object_id = client.find_by_description(description)
            if object_id is not None:
                log.info('Ariza #%s: ArcGIS obyekt %s allaqachon bor, qayta yozilmaydi', ariza.pk, object_id)
            else:
                object_id = client.add_feature(
                    geojson_to_esri(ariza.chegara),
                    {'description': description, 'symbolid': 0},
                )
                log.info('Ariza #%s: ArcGIS objectId=%s', ariza.pk, object_id)
        except ArcGISError as exc:
            log.error('Ariza #%s: ArcGIS xatosi: %s', ariza.pk, exc)
            raise ApiError(502, 'ArcGIS qatlamiga yozib bo\'lmadi, keyinroq qayta urinib ko\'ring',
                           {'arcgis': str(exc)})

        ariza.id_raqam = id_raqam
        ariza.arcgis_object_id = object_id
        ariza.holat = Holat.HISOBGA_OLINGAN
        try:
            with transaction.atomic():
                ariza.save(update_fields=['id_raqam', 'arcgis_object_id', 'holat', 'yangilangan'])
        except IntegrityError:
            # Parallel tasdiqlashda unique cheklov oxirgi himoya bo'lib xizmat qiladi
            raise ApiError(409, f'{id_raqam} ID raqamli hujjat allaqachon ro\'yxatga olingan',
                           {'id_raqam': 'takrorlanmoqda'})
    return ariza
