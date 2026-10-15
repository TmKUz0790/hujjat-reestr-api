"""Tekshiruvchi uchun 3 ish kunlik muddat (shanba va yakshanba hisobga olinmaydi)."""
import datetime as dt

ISH_KUNLARI = 3


def ish_kuni_qosh(start: dt.datetime, kunlar: int = ISH_KUNLARI) -> dt.datetime:
    result = start
    added = 0
    while added < kunlar:
        result += dt.timedelta(days=1)
        if result.weekday() < 5:  # 0-4: dushanba-juma
            added += 1
    return result
