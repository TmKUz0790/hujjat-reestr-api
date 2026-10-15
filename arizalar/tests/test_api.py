import json
import shutil
import tempfile
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from arizalar.arcgis import ArcGISError
from arizalar.models import Ariza

PDF = b'%PDF-1.4\n%test\n'
PNG = b'\x89PNG\r\n\x1a\n' + b'\0' * 16
ANDIJON = [[72.30, 40.75], [72.40, 40.75], [72.40, 40.81], [72.30, 40.81], [72.30, 40.75]]

BERUVCHI = {'HTTP_X_ROL': 'ariza_beruvchi'}
TEKSHIRUVCHI = {'HTTP_X_ROL': 'tekshiruvchi'}


def sample_data(**overrides):
    data = {
        'hujjat_nomi': 'Andijon shahri bosh rejasi',
        'hujjat_turi': 'БР',
        'soato_kodi': '1703401',
        'tasdiq_sanasi': '2026-03-12',
        'tasdiq_hujjati': '123-son qaror',
        'chegara': {'type': 'Polygon', 'coordinates': [ANDIJON]},
    }
    data.update(overrides)
    return data


def files(**overrides):
    result = {
        'asosiy_chizma': SimpleUploadedFile('chizma.pdf', PDF, 'application/pdf'),
        'tushuntirish_xati': SimpleUploadedFile('xat.pdf', PDF, 'application/pdf'),
        'tasdiqlovchi_hujjat': SimpleUploadedFile('qaror.png', PNG, 'image/png'),
    }
    result.update(overrides)
    return {k: v for k, v in result.items() if v is not None}


class FakeArcGIS:
    """ArcGIS mock: qatlamni xotirada saqlaydi, xatolarni simulyatsiya qila oladi."""
    instances = []

    def __init__(self, *args, **kwargs):
        self.features = FakeArcGIS.layer
        self.add_calls = 0
        FakeArcGIS.instances.append(self)

    def find_by_description(self, description):
        if FakeArcGIS.fail_query:
            raise ArcGISError('query timeout')
        for oid, feat in self.features.items():
            if feat['attributes']['description'] == description:
                return oid
        return None

    def add_feature(self, geometry, attributes):
        self.add_calls += 1
        FakeArcGIS.total_adds += 1
        oid = 100 + len(self.features)
        if FakeArcGIS.fail_add == 'error':
            raise ArcGISError('server error')
        self.features[oid] = {'geometry': geometry, 'attributes': attributes}
        if FakeArcGIS.fail_add == 'lost_response':
            # obyekt yozildi, lekin javob mijozga yetib bormadi
            raise ArcGISError('read timeout')
        return oid

    def query_url(self, oid):
        return f'https://example.test/query?where=objectid={oid}'

    layer_url = 'https://example.test/FeatureServer/2'


class ApiTestBase(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        FakeArcGIS.layer = {}
        FakeArcGIS.fail_add = None
        FakeArcGIS.fail_query = False
        FakeArcGIS.total_adds = 0
        patcher = mock.patch('arizalar.services.ArcGISClient', FakeArcGIS)
        patcher.start()
        self.addCleanup(patcher.stop)
        view_patcher = mock.patch('arizalar.views.ArcGISClient', FakeArcGIS)
        view_patcher.start()
        self.addCleanup(view_patcher.stop)

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def submit(self, data=None, file_overrides=None, **headers):
        payload = {'data': json.dumps(data or sample_data(), ensure_ascii=False), **files(**(file_overrides or {}))}
        return self.client.post('/api/arizalar', payload, **(headers or BERUVCHI))

    def create(self, **data_overrides):
        resp = self.submit(sample_data(**data_overrides))
        self.assertEqual(resp.status_code, 201, resp.content)
        return resp.json()['id']


class CreateTests(ApiTestBase):
    def test_create_201(self):
        resp = self.submit()
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body['holat'], 'yuborilgan')
        ariza = Ariza.objects.get(pk=body['id'])
        self.assertIsNone(ariza.id_raqam)
        self.assertTrue(ariza.asosiy_chizma.name.startswith('arizalar/'))
        self.assertEqual(ariza.fayl_nomlari['asosiy_chizma'], 'chizma.pdf')

    def test_wrong_soato_422(self):
        resp = self.submit(sample_data(soato_kodi='9999999'))
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()['maydonlar']['soato_kodi'], "ro'yxatda yo'q")
        self.assertIn('xato', resp.json())

    def test_25mb_file_422(self):
        big = SimpleUploadedFile('katta.pdf', PDF + b'0' * (25 * 1024 * 1024), 'application/pdf')
        resp = self.submit(file_overrides={'asosiy_chizma': big})
        self.assertEqual(resp.status_code, 422)
        self.assertIn('asosiy_chizma', resp.json()['maydonlar'])
        self.assertEqual(Ariza.objects.count(), 0)

    def test_fake_extension_422(self):
        fake = SimpleUploadedFile('virus.pdf', b'MZ\x90\x00', 'application/pdf')
        resp = self.submit(file_overrides={'tushuntirish_xati': fake})
        self.assertEqual(resp.status_code, 422)
        self.assertIn('tushuntirish_xati', resp.json()['maydonlar'])

    def test_missing_file_422(self):
        resp = self.submit(file_overrides={'tasdiqlovchi_hujjat': None})
        self.assertEqual(resp.status_code, 422)
        self.assertIn('tasdiqlovchi_hujjat', resp.json()['maydonlar'])

    def test_unclosed_ring_and_paris_422(self):
        open_ring = ANDIJON[:-1] + [[72.31, 40.76]]
        resp = self.submit(sample_data(chegara={'type': 'Polygon', 'coordinates': [open_ring]}))
        self.assertEqual(resp.status_code, 422)
        self.assertIn('yopilmagan', resp.json()['maydonlar']['chegara'])
        paris = [[2.29, 48.85], [2.35, 48.85], [2.35, 48.88], [2.29, 48.85]]
        resp = self.submit(sample_data(chegara={'type': 'Polygon', 'coordinates': [paris]}))
        self.assertEqual(resp.status_code, 422)
        self.assertIn('tashqarida', resp.json()['maydonlar']['chegara'])

    def test_all_field_rules(self):
        resp = self.submit(sample_data(hujjat_nomi='  ', hujjat_turi='XX', tasdiq_sanasi='2999-01-01',
                                       tasdiq_hujjati='x' * 101))
        fields = resp.json()['maydonlar']
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(set(fields), {'hujjat_nomi', 'hujjat_turi', 'tasdiq_sanasi', 'tasdiq_hujjati'})

    def test_id_raqam_cannot_be_set_by_client(self):
        ariza_id = self.create(id_raqam='БР-0000000-2000', holat='hisobga_olingan')
        ariza = Ariza.objects.get(pk=ariza_id)
        self.assertIsNone(ariza.id_raqam)
        self.assertEqual(ariza.holat, 'yuborilgan')

    def test_invalid_json_422(self):
        resp = self.client.post('/api/arizalar', {'data': '{bad', **files()}, **BERUVCHI)
        self.assertEqual(resp.status_code, 422)
        self.assertIn('data', resp.json()['maydonlar'])


class RoleTests(ApiTestBase):
    def test_missing_role_403(self):
        resp = self.client.get('/api/arizalar')
        self.assertEqual(resp.status_code, 403)
        self.assertIn('X-Rol', resp.json()['maydonlar'])

    def test_reviewer_cannot_create(self):
        self.assertEqual(self.submit(**TEKSHIRUVCHI).status_code, 403)

    def test_applicant_cannot_approve(self):
        ariza_id = self.create()
        self.assertEqual(self.client.post(f'/api/arizalar/{ariza_id}/tasdiqlash', **BERUVCHI).status_code, 403)


class ApproveTests(ApiTestBase):
    def approve(self, ariza_id):
        return self.client.post(f'/api/arizalar/{ariza_id}/tasdiqlash', **TEKSHIRUVCHI)

    def test_approve_writes_to_arcgis(self):
        ariza_id = self.create()
        resp = self.approve(ariza_id)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['id_raqam'], 'БР-1703401-2026')
        oid = resp.json()['arcgis_object_id']
        feature = FakeArcGIS.layer[oid]
        self.assertEqual(feature['attributes'], {'description': 'БР-1703401-2026 | Andijon shahri bosh rejasi',
                                                 'symbolid': 0})
        self.assertEqual(feature['geometry']['spatialReference'], {'wkid': 102100})
        ariza = Ariza.objects.get(pk=ariza_id)
        self.assertEqual((ariza.holat, ariza.arcgis_object_id), ('hisobga_olingan', oid))

        detail = self.client.get(f'/api/arizalar/{ariza_id}', **BERUVCHI).json()
        self.assertIn(f'objectid={oid}', detail['arcgis_query_url'])
        self.assertEqual(len(detail['fayllar']), 3)

    def test_duplicate_id_409(self):
        first = self.create()
        second = self.create(hujjat_nomi='Boshqa nom')
        self.assertEqual(self.approve(first).status_code, 200)
        resp = self.approve(second)
        self.assertEqual(resp.status_code, 409)
        self.assertIn('allaqachon', resp.json()['xato'])
        self.assertEqual(FakeArcGIS.total_adds, 1)
        self.assertEqual(Ariza.objects.get(pk=second).holat, 'yuborilgan')

    def test_wrong_state_409(self):
        ariza_id = self.create()
        self.approve(ariza_id)
        self.assertEqual(self.approve(ariza_id).status_code, 409)

    def test_arcgis_error_502_keeps_state(self):
        ariza_id = self.create()
        FakeArcGIS.fail_add = 'error'
        resp = self.approve(ariza_id)
        self.assertEqual(resp.status_code, 502)
        self.assertIn('arcgis', resp.json()['maydonlar'])
        ariza = Ariza.objects.get(pk=ariza_id)
        self.assertEqual((ariza.holat, ariza.id_raqam, ariza.arcgis_object_id), ('yuborilgan', None, None))
        # Qayta urinish muvaffaqiyatli
        FakeArcGIS.fail_add = None
        self.assertEqual(self.approve(ariza_id).status_code, 200)

    def test_arcgis_unreachable_502(self):
        ariza_id = self.create()
        FakeArcGIS.fail_query = True
        self.assertEqual(self.approve(ariza_id).status_code, 502)
        self.assertIsNone(Ariza.objects.get(pk=ariza_id).id_raqam)

    def test_retry_after_lost_response_creates_no_duplicate(self):
        ariza_id = self.create()
        FakeArcGIS.fail_add = 'lost_response'
        self.assertEqual(self.approve(ariza_id).status_code, 502)
        self.assertEqual(len(FakeArcGIS.layer), 1)  # obyekt aslida yozilgan
        FakeArcGIS.fail_add = None
        resp = self.approve(ariza_id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(FakeArcGIS.layer), 1)  # ikkinchi obyekt yaratilmadi
        self.assertEqual(FakeArcGIS.total_adds, 1)
        self.assertEqual(resp.json()['arcgis_object_id'], next(iter(FakeArcGIS.layer)))


class ReturnAndResubmitTests(ApiTestBase):
    def test_return_requires_reason(self):
        ariza_id = self.create()
        resp = self.client.post(f'/api/arizalar/{ariza_id}/qaytarish', {'sabab': ' '},
                                content_type='application/json', **TEKSHIRUVCHI)
        self.assertEqual(resp.status_code, 422)
        self.assertIn('sabab', resp.json()['maydonlar'])

    def test_full_cycle(self):
        ariza_id = self.create()
        resp = self.client.post(f'/api/arizalar/{ariza_id}/qaytarish', {'sabab': 'Chizma o\'qilmaydi'},
                                content_type='application/json', **TEKSHIRUVCHI)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Ariza.objects.get(pk=ariza_id).holat, 'qaytarilgan')

        # qaytarilgan arizani tasdiqlab bo'lmaydi
        self.assertEqual(self.client.post(f'/api/arizalar/{ariza_id}/tasdiqlash', **TEKSHIRUVCHI).status_code, 409)

        new_file = SimpleUploadedFile('yangi.pdf', PDF, 'application/pdf')
        body = {'data': json.dumps(sample_data(hujjat_nomi='Tuzatilgan nom')), 'asosiy_chizma': new_file}
        # PUT multipart: Django test client'da encode_multipart orqali yuboriladi
        from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart
        resp = self.client.put(f'/api/arizalar/{ariza_id}', encode_multipart(BOUNDARY, body),
                               content_type=MULTIPART_CONTENT, **BERUVCHI)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['holat'], 'yuborilgan')
        ariza = Ariza.objects.get(pk=ariza_id)
        self.assertEqual(ariza.hujjat_nomi, 'Tuzatilgan nom')
        self.assertEqual(ariza.fayl_nomlari['asosiy_chizma'], 'yangi.pdf')
        self.assertEqual(ariza.fayl_nomlari['tushuntirish_xati'], 'xat.pdf')  # o'zgarmagan
        self.assertEqual(ariza.qaytarish_sababi, '')

        # yuborilgan holatda PUT -> 409
        resp = self.client.put(f'/api/arizalar/{ariza_id}', encode_multipart(BOUNDARY, {'data': json.dumps(sample_data())}),
                               content_type=MULTIPART_CONTENT, **BERUVCHI)
        self.assertEqual(resp.status_code, 409)


class ListTests(ApiTestBase):
    def test_filters_and_pagination(self):
        for i in range(5):
            self.create(hujjat_nomi=f'Hujjat {i}')
        self.create(hujjat_turi='ҚР')
        self.create(soato_kodi='1712401')

        resp = self.client.get('/api/arizalar', {'hajm': 2, 'sahifa': 2}, **TEKSHIRUVCHI)
        body = resp.json()
        self.assertEqual(body['jami'], 7)
        self.assertEqual(len(body['items']), 2)
        self.assertIsNotNone(body['items'][0]['muddat'])

        self.assertEqual(self.client.get('/api/arizalar', {'hujjat_turi': 'ҚР'}, **TEKSHIRUVCHI).json()['jami'], 1)
        self.assertEqual(self.client.get('/api/arizalar', {'soato_kodi': '1712401'}, **TEKSHIRUVCHI).json()['jami'], 1)
        self.assertEqual(self.client.get('/api/arizalar', {'holat': 'qaytarilgan'}, **TEKSHIRUVCHI).json()['jami'], 0)

    def test_bad_filter_422(self):
        resp = self.client.get('/api/arizalar', {'holat': 'nimadir', 'hajm': 1000}, **TEKSHIRUVCHI)
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(set(resp.json()['maydonlar']), {'holat', 'hajm'})

    def test_detail_404(self):
        resp = self.client.get('/api/arizalar/999', **TEKSHIRUVCHI)
        self.assertEqual(resp.status_code, 404)
        self.assertIn('xato', resp.json())

    def test_soato_list(self):
        resp = self.client.get('/api/soato', **BERUVCHI)
        self.assertEqual(resp.status_code, 200)
        self.assertIn({'kod': '1703401', 'nomi': 'Andijon shahri'}, resp.json())

    def test_file_download(self):
        ariza_id = self.create()
        resp = self.client.get(f'/api/arizalar/{ariza_id}/fayllar/asosiy_chizma', **BERUVCHI)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(b''.join(resp.streaming_content), PDF)
        resp.close()
