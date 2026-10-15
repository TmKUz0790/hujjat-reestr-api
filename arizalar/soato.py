"""SOATO ro'yxati JSON fayldan o'qiladi (yo'li SOATO_FILE bilan almashtiriladi)."""
import json
import os
from functools import lru_cache
from pathlib import Path

DEFAULT_FILE = Path(__file__).resolve().parent / 'data' / 'soato.json'


@lru_cache(maxsize=1)
def soato_list():
    path = Path(os.environ.get('SOATO_FILE') or DEFAULT_FILE)
    with path.open(encoding='utf-8') as fh:
        rows = json.load(fh)
    return [{'kod': str(r['kod']), 'nomi': r['nomi']} for r in rows]


def soato_codes():
    return {r['kod'] for r in soato_list()}
