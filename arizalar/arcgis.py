"""Ochiq ArcGIS Feature Service bilan ishlash (applyEdits va query)."""
import json
import logging
import time

import requests
from django.conf import settings

log = logging.getLogger(__name__)

DESCRIPTION_LEN = 75


class ArcGISError(Exception):
    pass


def make_description(id_raqam: str, hujjat_nomi: str) -> str:
    text = f'{id_raqam} | {hujjat_nomi}'
    if len(text) <= DESCRIPTION_LEN:
        return text
    return text[:DESCRIPTION_LEN - 1].rstrip() + '…'


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class ArcGISClient:
    def __init__(self, layer_url=None, timeout=None, retries=None, session=None):
        self.layer_url = (layer_url or settings.ARCGIS_LAYER_URL).rstrip('/')
        self.timeout = settings.ARCGIS_TIMEOUT if timeout is None else timeout
        self.retries = settings.ARCGIS_RETRIES if retries is None else retries
        self.session = session or requests.Session()

    # --- past daraja ---
    def _request(self, method, path, *, retry=True, **kwargs):
        """So'rov + JSON tekshiruvi. Faqat xavfsiz (takrorlansa zarar qilmaydigan) so'rovlar qayta uriniladi."""
        url = f'{self.layer_url}/{path}'
        attempts = 1 + (self.retries if retry else 0)
        last_exc = None
        for attempt in range(1, attempts + 1):
            try:
                resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
                resp.raise_for_status()
                data = resp.json()
            except (requests.RequestException, ValueError) as exc:
                last_exc = exc
                log.warning('ArcGIS %s %s: %s-urinish muvaffaqiyatsiz: %s', method, path, attempt, exc)
                if attempt < attempts:
                    time.sleep(min(0.5 * 2 ** (attempt - 1), 4))
                continue
            # ArcGIS xatoni ko'pincha HTTP 200 bilan {"error": {...}} ko'rinishida qaytaradi
            if isinstance(data, dict) and 'error' in data:
                err = data['error']
                raise ArcGISError(f"ArcGIS xatosi {err.get('code')}: {err.get('message')} {err.get('details') or ''}".strip())
            return data
        raise ArcGISError(f'ArcGIS javob bermadi: {last_exc}')

    # --- amallar ---
    def find_by_description(self, description: str):
        """Shu tavsifli obyekt bor bo'lsa objectId, aks holda None."""
        data = self._request('GET', 'query', params={
            'where': f'description = {_sql_str(description)}',
            'outFields': 'objectid',
            'returnIdsOnly': 'true',
            'f': 'json',
        })
        ids = data.get('objectIds') or []
        return min(ids) if ids else None

    def add_feature(self, geometry: dict, attributes: dict) -> int:
        adds = [{'geometry': geometry, 'attributes': attributes}]
        # Yozish so'rovi avtomatik takrorlanmaydi: javob yo'qolsa dublikat yaratmaslik uchun
        # takror urinish xizmat qatlamida avval query orqali tekshiriladi.
        data = self._request('POST', 'applyEdits', retry=False, data={
            'f': 'json',
            'adds': json.dumps(adds, ensure_ascii=False),
        })
        results = data.get('addResults') or []
        if not results:
            raise ArcGISError(f'applyEdits kutilmagan javob: {data}')
        first = results[0]
        if not first.get('success') or first.get('objectId') is None:
            err = first.get('error') or {}
            raise ArcGISError(f"Obyekt qo'shilmadi: {err.get('description') or err or first}")
        return int(first['objectId'])

    def query_url(self, object_id: int) -> str:
        return f'{self.layer_url}/query?where=objectid={object_id}&outFields=*&f=geojson'
