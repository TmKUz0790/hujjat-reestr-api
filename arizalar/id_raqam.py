"""ID raqam generatori (4.2-bo'lim): {hujjat_turi}-{soato_kodi}-{yil}."""
import datetime as dt


def generate_id_raqam(hujjat_turi: str, soato_kodi: str, tasdiq_sanasi: dt.date) -> str:
    return f'{hujjat_turi}-{soato_kodi}-{tasdiq_sanasi.year}'
