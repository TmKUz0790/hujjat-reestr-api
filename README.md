# ShGAT — shaharsozlik hujjatlari arizalari (backend)

Test topshirig'ining backend qismi (5- va 6-bo'limlar). Ariza beruvchi hujjat haqida ariza yuboradi, tekshiruvchi uni tasdiqlaydi yoki qaytaradi. Tasdiqlanganda server ID raqam yaratadi va hujjat chegarasini Esri'ning ochiq ArcGIS qatlamiga yozadi.

**Stek:** Python 3.13, Django 6, Django REST Framework, drf-spectacular (OpenAPI), requests. Baza: PostgreSQL yoki SQLite.

## Ishga tushirish

### 1-variant: lokal, SQLite (taxminan 3 daqiqa)

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py runserver
```

- API: `http://localhost:8000/api/...`
- Swagger: `http://localhost:8000/api/docs`
- OpenAPI sxema: `http://localhost:8000/api/schema`

### 2-variant: Docker Compose (API + PostgreSQL)

```bash
docker compose up --build
```

API `http://localhost:8000` manzilida ochiladi. Migratsiyalar konteyner ishga tushganda avtomatik bajariladi.

### Testlar

```bash
python manage.py test
```

46 ta test bor. Ularda ArcGIS mock qilingan, shuning uchun internet kerak emas.

## Rol

Rol so'rov sarlavhasida beriladi: `X-Rol: ariza_beruvchi` yoki `X-Rol: tekshiruvchi`. Sarlavha bo'lmasa yoki rol bu amalga ruxsat etilmagan bo'lsa, `403` qaytadi.

## API

| Metod va yo'l | Rol | Javoblar |
|---|---|---|
| `POST /api/arizalar` | ariza_beruvchi | `201 {id, holat}`, `422` |
| `GET /api/arizalar?holat=&hujjat_turi=&soato_kodi=&sahifa=&hajm=` | ikkalasi | `200 {items, jami, sahifa, hajm}`, `422` |
| `GET /api/arizalar/{id}` | ikkalasi | `200`, `404` |
| `PUT /api/arizalar/{id}` | ariza_beruvchi | `200`, `409` (holat qaytarilgan bo'lmasa), `422` |
| `POST /api/arizalar/{id}/tasdiqlash` | tekshiruvchi | `200 {id_raqam, arcgis_object_id}`, `409`, `502` |
| `POST /api/arizalar/{id}/qaytarish` `{"sabab": "..."}` | tekshiruvchi | `200`, `409`, `422` |
| `GET /api/soato` | ikkalasi | `200 [{kod, nomi}]` |
| `GET /api/arizalar/{id}/fayllar/{maydon}` | ikkalasi | fayl (fayl havolalari uchun qo'shimcha endpoint) |

**Xato formati** hamma joyda bir xil:

```json
{"xato": "umumiy xabar", "maydonlar": {"soato_kodi": "ro'yxatda yo'q"}}
```

**`POST` va `PUT` uchun multipart so'rov:**

- `data` — JSON matn (topshiriqdagi namuna).
- Uchta fayl: `asosiy_chizma`, `tushuntirish_xati`, `tasdiqlovchi_hujjat`.
- `PUT` da fayllar ixtiyoriy: yuborilmagan fayl avvalgisicha qoladi.

```bash
curl -X POST http://localhost:8000/api/arizalar \
  -H "X-Rol: ariza_beruvchi" \
  -F 'data={"hujjat_nomi":"Andijon shahri bosh rejasi","hujjat_turi":"БР","soato_kodi":"1703401","tasdiq_sanasi":"2026-03-12","tasdiq_hujjati":"123-son qaror","chegara":{"type":"Polygon","coordinates":[[[72.30,40.75],[72.40,40.75],[72.40,40.81],[72.30,40.81],[72.30,40.75]]]}}' \
  -F asosiy_chizma=@chizma.pdf -F tushuntirish_xati=@xat.pdf -F tasdiqlovchi_hujjat=@qaror.pdf

curl -X POST http://localhost:8000/api/arizalar/1/tasdiqlash -H "X-Rol: tekshiruvchi"
```

## Tuzilma

```
arizalar/
  models.py       Ariza modeli, holatlar, id_raqam ustida unique cheklov
  validation.py   4.1-bo'lim qoidalari: maydonlar, chegara, fayllar (hajm, kengaytma, ichki imzo)
  id_raqam.py     ID generatori: {tur}-{soato}-{yil}
  geo.py          WGS-84 -> Web Mercator, GeoJSON -> Esri JSON (halqa yo'nalishi bilan)
  arcgis.py       ArcGIS REST mijozi: applyEdits, query, timeout va qayta urinish
  services.py     Holat o'tishlari: yuborish, qaytarish, qayta yuborish, tasdiqlash
  views.py        7 ta endpoint, X-Rol tekshiruvi, OpenAPI izohlari
  errors.py       Yagona xato formati
  muddat.py       Tekshiruvchi uchun 3 ish kunlik muddat
  data/soato.json SOATO ro'yxati
  tests/          Unit va API testlar
```

## Muhim qarorlar

- **ArcGIS'ga yozish va qayta urinish.** ArcGIS xato qaytarsa yoki javob bermasa, ariza `yuborilgan` holatida qoladi, ID saqlanmaydi va `502` qaytadi. Javob yo'qolgan holat ham hisobga olingan: obyekt yozilgan, lekin javob kelmagan bo'lishi mumkin. Shuning uchun har bir tasdiqlashdan oldin qatlam `description = '{id_raqam} | {nom}'` bo'yicha so'raladi. Obyekt topilsa, uning `objectId`si qayta ishlatiladi va ikkinchi obyekt yaratilmaydi. `applyEdits` so'rovining o'zi avtomatik qayta yuborilmaydi; `query` so'rovlari esa timeout va backoff bilan qayta uriniladi (`ARCGIS_RETRIES`).
- **ID takrorlanishi.** Avval bazada tekshiriladi (`409`). `id_raqam` ustidagi unique cheklov parallel tasdiqlashlarda oxirgi himoya bo'ladi. Tasdiqlash `select_for_update` bilan bajariladi.
- **Geometriya.** Proyeksiya formula bilan hisoblanadi (pyproj kerak emas). Esri talabi bo'yicha tashqi halqa soat mili yo'nalishida, teshiklar teskari yo'nalishda bo'ladi. MultiPolygon bitta Esri poligonining `rings` ro'yxatiga yoyiladi.
- **Fayllar.** Diskka tasodifiy UUID nomi bilan yoziladi, asl nomi faqat bazada saqlanadi. Kengaytma va fayl boshidagi imzo (`%PDF`, JPEG, PNG) tekshiriladi. Fayl 20 MB dan oshsa, `422` qaytadi.
- **Ochiq ArcGIS qatlamida tekshirildi.** Ariza `БР-1703401-2026` yozildi va qatlamda `objectid=3033` sifatida paydo bo'ldi. `query?where=objectid=3033&outSR=4326` Andijon koordinatalarini (72.30–72.40, 40.75–40.81) qaytardi. Qatlam URL'i ataylab buzilganda (`/FeatureServer/999`) `502` qaytdi va holat o'zgarmadi.

## Qilingan ishlar

**6.1 Majburiy — hammasi bajarilgan:**

1. Multipart so'rov, validatsiya, fayllarni diskka va yozuvni bazaga saqlash.
2. Chegara tekshiruvi.
3. ID generatori va unique cheklov (`409`).
4. GeoJSON → Web Mercator → Esri JSON → `applyEdits`, `success` va `objectId` tekshiruvi.
5. ArcGIS xatosida `502`, qayta urinishda dublikat yaratilmaydi.
6. Qolgan endpointlar: filtr va sahifalash, ko'rish, qaytarish, qayta yuborish.
7. Unit testlar.
8. README.

**6.2 Qo'shimcha:**

- Docker Compose (API + PostgreSQL).
- OpenAPI/Swagger.
- ArcGIS so'rovlarida timeout va qayta urinish.
- 3 ish kunlik muddat ro'yxatda `muddat` va `muddat_otgan` maydonlari sifatida ko'rsatiladi.

## Qilinmagan ishlar va cheklovlar

- **JWT orqali rollar qilinmagan.** Topshiriqdagi soddalashtirilgan `X-Rol` sarlavhasi ishlatilgan.
- **SOATO ro'yxati namuna.** Topshiriqda beriladigan JSON fayl qo'limda yo'q edi. `arizalar/data/soato.json` da 12 ta viloyat markazi bor (Andijon `1703401` topshiriqdan olingan, qolganlari namuna sifatida). Haqiqiy ro'yxatni ulash uchun faylni almashtiring yoki `SOATO_FILE` muhit o'zgaruvchisini bering.
- **Muddat hisobida bayramlar e'tiborga olinmaydi.** Faqat shanba va yakshanba o'tkazib yuboriladi.
- **Docker Compose fayli yozilgan, lekin shu muhitda ishga tushirib sinalmagan** (Docker daemon ishlamayotgan edi).
- **Kamdan-kam uchraydigan holat.** Bir xil ID bilan ikkita parallel tasdiqlash bo'lsa, ArcGIS'ga obyekt yozilgandan keyin unique cheklov ishga tushishi mumkin. Bunda qatlamda bog'lanmagan obyekt qoladi. Buning oldini olish uchun ID oldindan bazada band qilinishi kerak bo'ladi.
- **Esri test serveri umumiy.** Unga boshqalar ham yozadi va u vaqti-vaqti bilan tozalanadi. Tasdiqlangan hujjatning obyekti keyinchalik qatlamda topilmasligi mumkin.

## Sarflangan vaqt

Taxminan 5 soat.
