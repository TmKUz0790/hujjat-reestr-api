import datetime as dt
import math
from unittest import mock

from django.test import SimpleTestCase, override_settings

from arizalar.arcgis import ArcGISClient, ArcGISError, make_description
from arizalar.geo import geojson_to_esri, lonlat_to_webmercator, signed_area
from arizalar.id_raqam import generate_id_raqam
from arizalar.muddat import ish_kuni_qosh
from arizalar.validation import ChegaraXatosi, validate_chegara

ANDIJON = [[72.30, 40.75], [72.40, 40.75], [72.40, 40.81], [72.30, 40.81], [72.30, 40.75]]


class IdGeneratorTests(SimpleTestCase):
    def test_format(self):
        self.assertEqual(generate_id_raqam('БР', '1703401', dt.date(2026, 3, 12)), 'БР-1703401-2026')

    def test_year_comes_from_tasdiq_sanasi(self):
        self.assertEqual(generate_id_raqam('ҚР', '1712401', dt.date(2019, 12, 31)), 'ҚР-1712401-2019')


class ChegaraTests(SimpleTestCase):
    def test_valid_polygon(self):
        validate_chegara({'type': 'Polygon', 'coordinates': [ANDIJON]})

    def test_valid_multipolygon(self):
        validate_chegara({'type': 'MultiPolygon', 'coordinates': [[ANDIJON], [ANDIJON]]})

    def test_unclosed_ring(self):
        with self.assertRaisesRegex(ChegaraXatosi, 'yopilmagan'):
            validate_chegara({'type': 'Polygon', 'coordinates': [ANDIJON[:-1] + [[72.31, 40.76]]]})

    def test_too_few_points(self):
        with self.assertRaisesRegex(ChegaraXatosi, '4 nuqta'):
            validate_chegara({'type': 'Polygon', 'coordinates': [[[72.3, 40.75], [72.4, 40.75], [72.3, 40.75]]]})

    def test_paris_is_outside(self):
        paris = [[2.29, 48.85], [2.35, 48.85], [2.35, 48.88], [2.29, 48.85]]
        with self.assertRaisesRegex(ChegaraXatosi, 'tashqarida'):
            validate_chegara({'type': 'Polygon', 'coordinates': [paris]})

    def test_wrong_type(self):
        with self.assertRaisesRegex(ChegaraXatosi, 'Polygon'):
            validate_chegara({'type': 'Point', 'coordinates': [72.3, 40.75]})

    def test_non_numeric(self):
        with self.assertRaises(ChegaraXatosi):
            validate_chegara({'type': 'Polygon', 'coordinates': [[['72.3', 40.75]] * 4]})


class GeoTests(SimpleTestCase):
    def test_origin(self):
        x, y = lonlat_to_webmercator(0, 0)
        self.assertAlmostEqual(x, 0.0, places=6)
        self.assertAlmostEqual(y, 0.0, places=6)

    def test_known_values(self):
        x, y = lonlat_to_webmercator(180, 0)
        self.assertAlmostEqual(x, 20037508.342789244, places=3)
        x, y = lonlat_to_webmercator(72.30, 40.75)
        # Mustaqil formulalar: x = lon * 20037508.34 / 180, y = R * atanh(sin(lat))
        self.assertAlmostEqual(x, 72.30 * 20037508.342789244 / 180, places=3)
        self.assertAlmostEqual(y, 6378137 * math.atanh(math.sin(math.radians(40.75))), places=3)
        self.assertAlmostEqual(y, 4975536.36, delta=0.05)

    def test_outer_ring_clockwise_hole_counterclockwise(self):
        hole = [[72.33, 40.77], [72.36, 40.77], [72.36, 40.79], [72.33, 40.79], [72.33, 40.77]]  # CCW
        outer_cw = list(reversed(ANDIJON))  # ataylab teskari yo'nalishda beramiz
        esri = geojson_to_esri({'type': 'Polygon', 'coordinates': [outer_cw, hole]})
        self.assertEqual(esri['spatialReference'], {'wkid': 102100})
        outer, inner = esri['rings']
        self.assertLess(signed_area(outer), 0)      # soat mili bo'yicha
        self.assertGreater(signed_area(inner), 0)   # teskari
        self.assertEqual(outer[0], outer[-1])

    def test_multipolygon_flattened_into_rings(self):
        esri = geojson_to_esri({'type': 'MultiPolygon', 'coordinates': [[ANDIJON], [ANDIJON]]})
        self.assertEqual(len(esri['rings']), 2)
        self.assertTrue(all(signed_area(r) < 0 for r in esri['rings']))


class MuddatTests(SimpleTestCase):
    def test_skips_weekend(self):
        friday = dt.datetime(2026, 10, 16, 10, 0)
        self.assertEqual(ish_kuni_qosh(friday), dt.datetime(2026, 10, 21, 10, 0))  # chorshanba

    def test_midweek(self):
        monday = dt.datetime(2026, 10, 12, 9, 0)
        self.assertEqual(ish_kuni_qosh(monday), dt.datetime(2026, 10, 15, 9, 0))


def _resp(payload):
    r = mock.Mock()
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    return r


@override_settings(ARCGIS_LAYER_URL='https://example.test/FeatureServer/2')
class ArcGISClientTests(SimpleTestCase):
    def test_description_truncated_to_75(self):
        text = make_description('БР-1703401-2026', 'Juda uzun nom ' * 10)
        self.assertLessEqual(len(text), 75)
        self.assertTrue(text.endswith('…'))
        self.assertTrue(text.startswith('БР-1703401-2026 | '))

    def test_add_feature_success(self):
        session = mock.Mock()
        session.request.return_value = _resp({'addResults': [{'objectId': 42, 'success': True}]})
        oid = ArcGISClient(session=session, retries=0).add_feature({'rings': []}, {'description': 'x'})
        self.assertEqual(oid, 42)
        method, url = session.request.call_args[0]
        self.assertEqual((method, url), ('POST', 'https://example.test/FeatureServer/2/applyEdits'))
        self.assertEqual(session.request.call_args[1]['data']['f'], 'json')

    def test_add_feature_failure_result(self):
        session = mock.Mock()
        session.request.return_value = _resp({'addResults': [{'success': False, 'error': {'description': 'bad geom'}}]})
        with self.assertRaisesRegex(ArcGISError, 'bad geom'):
            ArcGISClient(session=session, retries=0).add_feature({}, {})

    def test_error_object_with_http_200(self):
        session = mock.Mock()
        session.request.return_value = _resp({'error': {'code': 400, 'message': 'Invalid URL'}})
        with self.assertRaisesRegex(ArcGISError, 'Invalid URL'):
            ArcGISClient(session=session, retries=0).find_by_description('x')

    @mock.patch('arizalar.arcgis.time.sleep')
    def test_query_retries_but_applyedits_does_not(self, _sleep):
        import requests
        session = mock.Mock()
        session.request.side_effect = requests.ConnectionError('down')
        client = ArcGISClient(session=session, retries=2)
        with self.assertRaises(ArcGISError):
            client.find_by_description('x')
        self.assertEqual(session.request.call_count, 3)
        session.request.reset_mock()
        with self.assertRaises(ArcGISError):
            client.add_feature({}, {})
        self.assertEqual(session.request.call_count, 1)

    def test_description_quotes_escaped(self):
        session = mock.Mock()
        session.request.return_value = _resp({'objectIds': [7, 5]})
        oid = ArcGISClient(session=session).find_by_description("O'zbek")
        self.assertEqual(oid, 5)
        self.assertEqual(session.request.call_args[1]['params']['where'], "description = 'O''zbek'")
