import uuid
from pathlib import Path

from django.db import models


HUJJAT_TURLARI = ['БСХ', 'ҲРС', 'ТРЛ', 'БР', 'БРЛ', 'ҚР', 'ЛШ']

# Multipart so'rovdagi fayl maydonlari nomi -> modeldagi maydon
FAYL_MAYDONLARI = ('asosiy_chizma', 'tushuntirish_xati', 'tasdiqlovchi_hujjat')


def fayl_yoli(instance, filename):
    # Foydalanuvchi bergan nom diskka tushmaydi: path traversal va to'qnashuvdan himoya
    ext = Path(filename).suffix.lower()
    return f'arizalar/{uuid.uuid4().hex}{ext}'


class Holat(models.TextChoices):
    YUBORILGAN = 'yuborilgan', 'Yuborilgan'
    HISOBGA_OLINGAN = 'hisobga_olingan', 'Hisobga olingan'
    QAYTARILGAN = 'qaytarilgan', 'Qaytarilgan'


class Ariza(models.Model):
    hujjat_nomi = models.CharField(max_length=255)
    hujjat_turi = models.CharField(max_length=8, choices=[(t, t) for t in HUJJAT_TURLARI])
    soato_kodi = models.CharField(max_length=7, db_index=True)
    tasdiq_sanasi = models.DateField()
    tasdiq_hujjati = models.CharField(max_length=100)
    chegara = models.JSONField()

    asosiy_chizma = models.FileField(upload_to=fayl_yoli)
    tushuntirish_xati = models.FileField(upload_to=fayl_yoli)
    tasdiqlovchi_hujjat = models.FileField(upload_to=fayl_yoli)
    # Asl fayl nomlari faqat ko'rsatish uchun
    fayl_nomlari = models.JSONField(default=dict)

    id_raqam = models.CharField(max_length=40, unique=True, null=True, blank=True)
    holat = models.CharField(max_length=20, choices=Holat.choices, default=Holat.YUBORILGAN, db_index=True)
    arcgis_object_id = models.BigIntegerField(null=True, blank=True)
    qaytarish_sababi = models.TextField(blank=True)

    yuborilgan_vaqt = models.DateTimeField()
    yaratilgan = models.DateTimeField(auto_now_add=True)
    yangilangan = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-yuborilgan_vaqt', '-id']
        indexes = [models.Index(fields=['holat', 'hujjat_turi'])]

    def __str__(self):
        return self.id_raqam or f'Ariza #{self.pk}'
