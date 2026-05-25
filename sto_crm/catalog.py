"""Vehicle catalog payload construction."""

from __future__ import annotations

import base64
import binascii
import json
import threading
import zlib
from typing import Any

CAR_CATALOG: list[dict[str, list[str] | str]] = [
    {
        "make": "Lada",
        "models": [
            "Granta",
            "Vesta",
            "Vesta SW",
            "Largus",
            "Niva Travel",
            "Niva Legend",
            "XRAY",
            "Priora",
            "Kalina",
        ],
    },
    {"make": "GAZ", "models": ["Gazel", "Gazel Next", "Sobol", "Valdai Next"]},
    {"make": "UAZ", "models": ["Patriot", "Pickup", "Hunter", "Bukhanka", "Profi"]},
    {"make": "Moskvich", "models": ["3", "3e", "6", "8"]},
    {
        "make": "Toyota",
        "models": [
            "Camry",
            "Corolla",
            "RAV4",
            "Land Cruiser",
            "Prado",
            "Highlander",
            "C-HR",
            "Hilux",
            "Prius",
            "Yaris",
        ],
    },
    {"make": "Lexus", "models": ["ES", "IS", "LS", "NX", "RX", "GX", "LX", "UX"]},
    {
        "make": "Nissan",
        "models": [
            "Almera",
            "Juke",
            "Qashqai",
            "X-Trail",
            "Teana",
            "Murano",
            "Pathfinder",
            "Patrol",
            "Navara",
        ],
    },
    {
        "make": "Infiniti",
        "models": ["Q30", "Q50", "Q60", "QX50", "QX55", "QX60", "QX80"],
    },
    {
        "make": "Honda",
        "models": ["Civic", "Accord", "CR-V", "HR-V", "Pilot", "Fit", "Odyssey"],
    },
    {
        "make": "Mazda",
        "models": ["2", "3", "6", "CX-3", "CX-5", "CX-7", "CX-9", "CX-30"],
    },
    {
        "make": "Mitsubishi",
        "models": [
            "ASX",
            "Lancer",
            "Outlander",
            "Pajero",
            "Pajero Sport",
            "Eclipse Cross",
            "L200",
        ],
    },
    {
        "make": "Subaru",
        "models": ["Impreza", "Legacy", "Outback", "Forester", "XV", "WRX", "Tribeca"],
    },
    {
        "make": "Hyundai",
        "models": [
            "Solaris",
            "Elantra",
            "Sonata",
            "Creta",
            "Tucson",
            "Santa Fe",
            "Palisade",
            "Staria",
        ],
    },
    {
        "make": "Kia",
        "models": [
            "Rio",
            "Ceed",
            "Cerato",
            "K5",
            "Optima",
            "Seltos",
            "Sportage",
            "Sorento",
            "Carnival",
            "Mohave",
        ],
    },
    {"make": "Genesis", "models": ["G70", "G80", "G90", "GV60", "GV70", "GV80"]},
    {
        "make": "Renault",
        "models": [
            "Logan",
            "Sandero",
            "Duster",
            "Kaptur",
            "Arkana",
            "Megane",
            "Fluence",
            "Koleos",
        ],
    },
    {
        "make": "Skoda",
        "models": ["Rapid", "Octavia", "Superb", "Yeti", "Karoq", "Kodiaq", "Fabia"],
    },
    {
        "make": "Volkswagen",
        "models": [
            "Polo",
            "Jetta",
            "Passat",
            "Golf",
            "Tiguan",
            "Touareg",
            "Teramont",
            "Caddy",
            "Transporter",
        ],
    },
    {
        "make": "Audi",
        "models": ["A3", "A4", "A5", "A6", "A7", "A8", "Q3", "Q5", "Q7", "Q8", "TT"],
    },
    {
        "make": "BMW",
        "models": [
            "1 Series",
            "2 Series",
            "3 Series",
            "4 Series",
            "5 Series",
            "7 Series",
            "X1",
            "X3",
            "X4",
            "X5",
            "X6",
            "X7",
        ],
    },
    {
        "make": "Mercedes-Benz",
        "models": [
            "A-Class",
            "C-Class",
            "E-Class",
            "S-Class",
            "CLA",
            "CLS",
            "GLA",
            "GLC",
            "GLE",
            "GLS",
            "Vito",
            "Sprinter",
        ],
    },
    {
        "make": "Porsche",
        "models": [
            "911",
            "Boxster",
            "Cayman",
            "Panamera",
            "Macan",
            "Cayenne",
            "Taycan",
        ],
    },
    {
        "make": "Volvo",
        "models": ["S40", "S60", "S80", "S90", "V40", "XC40", "XC60", "XC70", "XC90"],
    },
    {
        "make": "Ford",
        "models": [
            "Focus",
            "Fiesta",
            "Mondeo",
            "Kuga",
            "Explorer",
            "Transit",
            "Ranger",
            "Mustang",
        ],
    },
    {
        "make": "Chevrolet",
        "models": [
            "Aveo",
            "Cruze",
            "Lacetti",
            "Cobalt",
            "Captiva",
            "Tahoe",
            "Trailblazer",
            "Niva",
        ],
    },
    {
        "make": "Opel",
        "models": ["Astra", "Corsa", "Insignia", "Mokka", "Antara", "Zafira", "Vivaro"],
    },
    {
        "make": "Peugeot",
        "models": [
            "206",
            "207",
            "208",
            "301",
            "308",
            "408",
            "508",
            "2008",
            "3008",
            "5008",
            "Partner",
        ],
    },
    {
        "make": "Citroen",
        "models": [
            "C3",
            "C4",
            "C5",
            "C-Elysee",
            "C-Crosser",
            "Berlingo",
            "Jumpy",
            "SpaceTourer",
        ],
    },
    {
        "make": "Land Rover",
        "models": [
            "Defender",
            "Discovery",
            "Discovery Sport",
            "Range Rover",
            "Range Rover Sport",
            "Range Rover Velar",
            "Range Rover Evoque",
        ],
    },
    {
        "make": "Jaguar",
        "models": ["XE", "XF", "XJ", "E-Pace", "F-Pace", "I-Pace", "F-Type"],
    },
    {
        "make": "Tesla",
        "models": ["Model 3", "Model S", "Model X", "Model Y", "Cybertruck"],
    },
    {
        "make": "Chery",
        "models": ["Tiggo 4", "Tiggo 7 Pro", "Tiggo 8", "Tiggo 8 Pro", "Arrizo 8"],
    },
    {"make": "Exeed", "models": ["LX", "TXL", "VX", "RX"]},
    {"make": "Omoda", "models": ["C5", "S5"]},
    {"make": "Jaecoo", "models": ["J7", "J8"]},
    {
        "make": "Haval",
        "models": ["Jolion", "F7", "F7x", "Dargo", "H3", "H5", "H9", "M6"],
    },
    {"make": "Tank", "models": ["300", "400", "500", "700"]},
    {"make": "Great Wall", "models": ["Poer", "Wingle", "Hover", "Safe"]},
    {
        "make": "Geely",
        "models": [
            "Coolray",
            "Atlas",
            "Atlas Pro",
            "Monjaro",
            "Emgrand",
            "Tugella",
            "Okavango",
        ],
    },
    {
        "make": "Changan",
        "models": [
            "Alsvin",
            "Eado Plus",
            "CS35 Plus",
            "CS55 Plus",
            "CS75 Plus",
            "Uni-K",
            "Uni-T",
            "Uni-V",
        ],
    },
    {"make": "Jetour", "models": ["Dashing", "X70", "X70 Plus", "X90 Plus", "T2"]},
    {"make": "JAC", "models": ["J7", "JS3", "JS4", "JS6", "S3", "S5", "T6", "T8"]},
    {"make": "Dongfeng", "models": ["AX7", "580", "DF6", "Shine Max", "Aeolus Huge"]},
    {
        "make": "FAW",
        "models": ["Bestune B70", "Bestune T55", "Bestune T77", "Bestune T99", "Oley"],
    },
    {"make": "BAIC", "models": ["U5 Plus", "X35", "X55", "BJ40", "BJ60"]},
    {
        "make": "BYD",
        "models": ["Atto 3", "Dolphin", "Han", "Song Plus", "Tang", "Seal"],
    },
    {"make": "Li Auto", "models": ["L6", "L7", "L8", "L9", "Mega"]},
    {"make": "Zeekr", "models": ["001", "007", "009", "X"]},
    {"make": "Voyah", "models": ["Free", "Dream", "Passion"]},
]

_CAR_CATALOG_CACHE: dict[str, Any] | None = None
_CAR_CATALOG_LOCK = threading.Lock()
OFFICIAL_CAR_CATALOG_B64 = (
    "eNrUvdty47iyKPgriH5YuyqmVdaNkrzfJOrmMiWrSFpW++wTE7TEkrlMiVqU6LLrxETMj8zDPM53nD+ZLznIC0gAkqu79zzsmAcx"
    "E0ACAkFcEonMxP/47ZgV+Tr+7d9/m8X5Nt6I7Pv3NNnHYh2dojTb/ruYT8OgL14XN644RMdjvN/GuUzNr2aL5dUpL9YvV0/F8SrZ"
    "r7PdIY1PsXiNn5N1GovjPjocn7OT+N/EMc6fo9NLkm6idXK1TbOnKK3JQmq7bBOnRzG7CcVG/uMxBupDHr8mWXEUQXgnXH8m1kUe"
    "nWTlVIm//f4b/8n/fno/xMff/v2//bYoK+dGuSSYFekpORT5ITvGokpccuU+yep/lmQhvIGEg+IonzfVWzDhb//999920Qv+x/9A"
    "TLZV49pxhFscT9lODOI0SuAP6VWgKheS//v/8XuZuy/+Ie6MDIvodMr2MipYZ8XJJP5y/LL+YlD3g+vmtYyRsHdtEkdHg3JU5JkY"
    "bZJTgqVPTmIWpRGgizj/nuW7aL+ONQI/MoLBIctPWjjMs8Pzexlh/PNTlJ+ezVZotkVwSDYxNI5Tr8Pz2pHPDj4Xxf4kK/eaWeUk"
    "RiFhHu2PyUnILmbSrcVC1qZIj1S1Kkc8yN5kxOkxzq2ioReZDTlcybDrwSMAdATojbfCnnCKt0jvxdt4v4EeheRzpPQR9z18IIrR"
    "AeKhhw9EMXqZbDNohUeZy6hScsqMGs2gZWZdeFhfNo3for1sSzGM9/vkKLxkl8ghYX7u/WsiP3gT25oDbT3gWAExWprhoDjEeZpd"
    "jARis0rfI+Fnu9h8hUbduWo0HBHEeRIfhZsVh//5/0C3bDTFdIHQhWfbwWcHn/DGMg+lO1fNukKRyEEiB/p8o9PGJ8Z0nbocX7mc"
    "r+A7Na7x7Zr1qxZnlw1RZ6DRYXASLhVKfVSO9zSTE2EZKbt+8or0LSqlzYV2MNhq4UMEpzzaRClkbNevOvzPbXjFDjy68AY9Fx+y"
    "MXaH+JT8lH02Po+pRss1/AO2b4eRY7GpMEmYJ/sTRcSnU4TY4VlR+ZjL78Ezx3ce5HFeQiE7UvVfw6g4PCdYn0kDHkmRJlGJiE/X"
    "TvNzFQwfFc5/XOJcKwnidUItMpGjl5pSfCvkHJdneZGdMCXEh2jIxhVfi32C42MS9vG5pKdofqkTBi9UUs0i+udZIueyDJEQQbY/"
    "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"
    "P/+P/wTtImK5"
)


def official_car_catalog_entries() -> list[dict[str, Any]]:
    try:
        raw = zlib.decompress(base64.b64decode(OFFICIAL_CAR_CATALOG_B64)).decode(
            "utf-8"
        )
        payload = json.loads(raw)
    except (binascii.Error, zlib.error, UnicodeDecodeError, ValueError):
        return []
    entries = payload.get("makes", []) if isinstance(payload, dict) else []
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def car_catalog_payload() -> dict[str, Any]:
    global _CAR_CATALOG_CACHE
    cached = _CAR_CATALOG_CACHE
    if cached is not None:
        return cached
    with _CAR_CATALOG_LOCK:
        if _CAR_CATALOG_CACHE is not None:
            return _CAR_CATALOG_CACHE
        models_by_make: dict[str, list[str]] = {}
        seen_models: dict[str, set[str]] = {}
        make_names: dict[str, str] = {}
        makes: list[str] = []
        for entry in [*CAR_CATALOG, *official_car_catalog_entries()]:
            raw_make = str(entry.get("make", "")).strip()
            if not raw_make:
                continue
            make_key = raw_make.casefold()
            make = make_names.setdefault(make_key, raw_make)
            raw_models = entry.get("models", [])
            if not isinstance(raw_models, list):
                continue
            models = [str(model).strip() for model in raw_models if str(model).strip()]
            if make not in models_by_make:
                makes.append(make)
                models_by_make[make] = []
                seen_models[make] = set()
            for model in models:
                key = model.casefold()
                if key not in seen_models[make]:
                    models_by_make[make].append(model)
                    seen_models[make].add(key)
        makes = sorted(makes, key=str.casefold)
        for make in list(models_by_make):
            models_by_make[make] = sorted(models_by_make[make], key=str.casefold)
        _CAR_CATALOG_CACHE = {
            "makes": makes,
            "models": models_by_make,
            "stats": {
                "makes": len(makes),
                "models": sum(len(items) for items in models_by_make.values()),
                "empty_makes": sum(1 for items in models_by_make.values() if not items),
            },
        }
        return _CAR_CATALOG_CACHE
