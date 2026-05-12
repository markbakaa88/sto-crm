"""Vehicle catalog payload construction."""

from __future__ import annotations

import base64
import binascii
import json
import threading
import zlib
from typing import Any

CAR_CATALOG: list[dict[str, list[str] | str]] = [
    {"make": "Lada", "models": ["Granta", "Vesta", "Vesta SW", "Largus", "Niva Travel", "Niva Legend", "XRAY", "Priora", "Kalina"]},
    {"make": "GAZ", "models": ["Gazel", "Gazel Next", "Sobol", "Valdai Next"]},
    {"make": "UAZ", "models": ["Patriot", "Pickup", "Hunter", "Bukhanka", "Profi"]},
    {"make": "Moskvich", "models": ["3", "3e", "6", "8"]},
    {"make": "Toyota", "models": ["Camry", "Corolla", "RAV4", "Land Cruiser", "Prado", "Highlander", "C-HR", "Hilux", "Prius", "Yaris"]},
    {"make": "Lexus", "models": ["ES", "IS", "LS", "NX", "RX", "GX", "LX", "UX"]},
    {"make": "Nissan", "models": ["Almera", "Juke", "Qashqai", "X-Trail", "Teana", "Murano", "Pathfinder", "Patrol", "Navara"]},
    {"make": "Infiniti", "models": ["Q30", "Q50", "Q60", "QX50", "QX55", "QX60", "QX80"]},
    {"make": "Honda", "models": ["Civic", "Accord", "CR-V", "HR-V", "Pilot", "Fit", "Odyssey"]},
    {"make": "Mazda", "models": ["2", "3", "6", "CX-3", "CX-5", "CX-7", "CX-9", "CX-30"]},
    {"make": "Mitsubishi", "models": ["ASX", "Lancer", "Outlander", "Pajero", "Pajero Sport", "Eclipse Cross", "L200"]},
    {"make": "Subaru", "models": ["Impreza", "Legacy", "Outback", "Forester", "XV", "WRX", "Tribeca"]},
    {"make": "Hyundai", "models": ["Solaris", "Elantra", "Sonata", "Creta", "Tucson", "Santa Fe", "Palisade", "Staria"]},
    {"make": "Kia", "models": ["Rio", "Ceed", "Cerato", "K5", "Optima", "Seltos", "Sportage", "Sorento", "Carnival", "Mohave"]},
    {"make": "Genesis", "models": ["G70", "G80", "G90", "GV60", "GV70", "GV80"]},
    {"make": "Renault", "models": ["Logan", "Sandero", "Duster", "Kaptur", "Arkana", "Megane", "Fluence", "Koleos"]},
    {"make": "Skoda", "models": ["Rapid", "Octavia", "Superb", "Yeti", "Karoq", "Kodiaq", "Fabia"]},
    {"make": "Volkswagen", "models": ["Polo", "Jetta", "Passat", "Golf", "Tiguan", "Touareg", "Teramont", "Caddy", "Transporter"]},
    {"make": "Audi", "models": ["A3", "A4", "A5", "A6", "A7", "A8", "Q3", "Q5", "Q7", "Q8", "TT"]},
    {"make": "BMW", "models": ["1 Series", "2 Series", "3 Series", "4 Series", "5 Series", "7 Series", "X1", "X3", "X4", "X5", "X6", "X7"]},
    {"make": "Mercedes-Benz", "models": ["A-Class", "C-Class", "E-Class", "S-Class", "CLA", "CLS", "GLA", "GLC", "GLE", "GLS", "Vito", "Sprinter"]},
    {"make": "Porsche", "models": ["911", "Boxster", "Cayman", "Panamera", "Macan", "Cayenne", "Taycan"]},
    {"make": "Volvo", "models": ["S40", "S60", "S80", "S90", "V40", "XC40", "XC60", "XC70", "XC90"]},
    {"make": "Ford", "models": ["Focus", "Fiesta", "Mondeo", "Kuga", "Explorer", "Transit", "Ranger", "Mustang"]},
    {"make": "Chevrolet", "models": ["Aveo", "Cruze", "Lacetti", "Cobalt", "Captiva", "Tahoe", "Trailblazer", "Niva"]},
    {"make": "Opel", "models": ["Astra", "Corsa", "Insignia", "Mokka", "Antara", "Zafira", "Vivaro"]},
    {"make": "Peugeot", "models": ["206", "207", "208", "301", "308", "408", "508", "2008", "3008", "5008", "Partner"]},
    {"make": "Citroen", "models": ["C3", "C4", "C5", "C-Elysee", "C-Crosser", "Berlingo", "Jumpy", "SpaceTourer"]},
    {"make": "Land Rover", "models": ["Defender", "Discovery", "Discovery Sport", "Range Rover", "Range Rover Sport", "Range Rover Velar", "Range Rover Evoque"]},
    {"make": "Jaguar", "models": ["XE", "XF", "XJ", "E-Pace", "F-Pace", "I-Pace", "F-Type"]},
    {"make": "Tesla", "models": ["Model 3", "Model S", "Model X", "Model Y", "Cybertruck"]},
    {"make": "Chery", "models": ["Tiggo 4", "Tiggo 7 Pro", "Tiggo 8", "Tiggo 8 Pro", "Arrizo 8"]},
    {"make": "Exeed", "models": ["LX", "TXL", "VX", "RX"]},
    {"make": "Omoda", "models": ["C5", "S5"]},
    {"make": "Jaecoo", "models": ["J7", "J8"]},
    {"make": "Haval", "models": ["Jolion", "F7", "F7x", "Dargo", "H3", "H5", "H9", "M6"]},
    {"make": "Tank", "models": ["300", "400", "500", "700"]},
    {"make": "Great Wall", "models": ["Poer", "Wingle", "Hover", "Safe"]},
    {"make": "Geely", "models": ["Coolray", "Atlas", "Atlas Pro", "Monjaro", "Emgrand", "Tugella", "Okavango"]},
    {"make": "Changan", "models": ["Alsvin", "Eado Plus", "CS35 Plus", "CS55 Plus", "CS75 Plus", "Uni-K", "Uni-T", "Uni-V"]},
    {"make": "Jetour", "models": ["Dashing", "X70", "X70 Plus", "X90 Plus", "T2"]},
    {"make": "JAC", "models": ["J7", "JS3", "JS4", "JS6", "S3", "S5", "T6", "T8"]},
    {"make": "Dongfeng", "models": ["AX7", "580", "DF6", "Shine Max", "Aeolus Huge"]},
    {"make": "FAW", "models": ["Bestune B70", "Bestune T55", "Bestune T77", "Bestune T99", "Oley"]},
    {"make": "BAIC", "models": ["U5 Plus", "X35", "X55", "BJ40", "BJ60"]},
    {"make": "BYD", "models": ["Atto 3", "Dolphin", "Han", "Song Plus", "Tang", "Seal"]},
    {"make": "Li Auto", "models": ["L6", "L7", "L8", "L9", "Mega"]},
    {"make": "Zeekr", "models": ["001", "007", "009", "X"]},
    {"make": "Voyah", "models": ["Free", "Dream", "Passion"]},
]

_CAR_CATALOG_CACHE: dict[str, Any] | None = None
_CAR_CATALOG_LOCK = threading.Lock()
OFFICIAL_CAR_CATALOG_B64 = (
    "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"
)

def official_car_catalog_entries() -> list[dict[str, Any]]:
    try:
        raw = zlib.decompress(base64.b64decode(OFFICIAL_CAR_CATALOG_B64)).decode("utf-8")
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
