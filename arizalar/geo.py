"""GeoJSON (WGS-84, gradus) -> Esri JSON (Web Mercator, metr) o'tkazish."""
import math

EARTH_RADIUS = 6378137.0  # WGS-84 katta yarim o'q, Web Mercator (EPSG:3857) shu radiusdan foydalanadi
MAX_LAT = 85.05112878     # Web Mercator chegarasi
WEB_MERCATOR_WKID = 102100


def lonlat_to_webmercator(lon: float, lat: float) -> tuple[float, float]:
    lat = max(min(lat, MAX_LAT), -MAX_LAT)
    x = math.radians(lon) * EARTH_RADIUS
    y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * EARTH_RADIUS
    return x, y


def signed_area(ring) -> float:
    """Shoelace formulasi: musbat — soat miliga teskari, manfiy — soat mili bo'yicha."""
    total = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        total += x1 * y2 - x2 * y1
    return total / 2


def orient(ring, clockwise: bool):
    is_cw = signed_area(ring) < 0
    return ring if is_cw == clockwise else list(reversed(ring))


def _polygons(geom):
    if geom['type'] == 'Polygon':
        return [geom['coordinates']]
    if geom['type'] == 'MultiPolygon':
        return geom['coordinates']
    raise ValueError(f"Qo'llab-quvvatlanmaydigan geometriya: {geom['type']}")


def geojson_to_esri(geom) -> dict:
    """GeoJSON Polygon/MultiPolygon -> Esri JSON polygon.

    Esri'da tashqi halqa soat mili bo'yicha, ichki (teshik) halqalar — teskari.
    GeoJSON (RFC 7946) aksincha, shuning uchun yo'nalishni har doim qayta o'rnatamiz.
    """
    rings = []
    for polygon in _polygons(geom):
        for idx, ring in enumerate(polygon):
            projected = [list(lonlat_to_webmercator(pt[0], pt[1])) for pt in ring]
            if projected[0] != projected[-1]:
                projected.append(projected[0])
            rings.append(orient(projected, clockwise=(idx == 0)))
    return {'rings': rings, 'spatialReference': {'wkid': WEB_MERCATOR_WKID}}
