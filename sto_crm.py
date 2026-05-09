#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Локальная CRM для автосервиса.

Один файл запускает HTTP-приложение на 127.0.0.1, открывает браузер и хранит
данные в SQLite в профиле пользователя.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import html
import io
import json
import math
import os
import re
import secrets
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zlib
from collections import defaultdict
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


APP_NAME = "СТО CRM"
APP_VERSION = "1.17.0"
DEFAULT_PORT = 8765
MAX_BODY_BYTES = 2_000_000
LOOKUP_LIMIT = 5_000
INTERNAL_ERROR_MESSAGE = "Внутренняя ошибка сервера. Подробности записаны в журнал приложения."
GITHUB_REPOSITORY = "markbakaa88/sto-crm"
GITHUB_UPDATES_CONFIG_ENV = "STO_CRM_UPDATE_REPOSITORY"
GITHUB_UPDATE_TIMEOUT = 15
GITHUB_UPDATE_MAX_ASSET_BYTES = 250 * 1024 * 1024
GITHUB_RELEASE_MANIFEST_NAME = "latest.json"
GITHUB_RELEASE_NOTES_NAME = "README.md"
EXE_ASSET_RE = re.compile(r"(?:^|[-_.])STO[-_]?CRM(?:[-_.]|$).*\.exe$|^STO_CRM\.exe$", re.IGNORECASE)
MANIFEST_ASSET_RE = re.compile(r"(?:^|[-_.])latest(?:[-_.]|$).*\.json$|^latest\.json$", re.IGNORECASE)
VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SENSITIVE_QUERY_RE = re.compile(r"([?&](?:token|csrf|csrf_token)=)([^&\s]+)", re.IGNORECASE)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TRUSTED_UPDATE_DOWNLOAD_HOSTS = {
    "api.github.com",
    "github.com",
    "github-releases.githubusercontent.com",
    "objects.githubusercontent.com",
}
MIN_VEHICLE_YEAR = 1900
PREFERRED_CHANNELS = {"phone": "Телефон", "sms": "SMS", "email": "Email", "messenger": "Мессенджер", "none": "Не писать"}
ORDER_PRIORITIES = {"low": "Низкий", "normal": "Обычный", "high": "Высокий", "urgent": "Срочно"}

ORDER_STATUSES = {
    "new": "Новый",
    "diagnostics": "Диагностика",
    "estimate": "Смета",
    "approved": "Согласован",
    "in_progress": "В работе",
    "done": "Готов",
    "closed": "Закрыт",
    "cancelled": "Отменен",
}
CONSUMING_STATUSES = {"closed"}

APPOINTMENT_STATUSES = {
    "scheduled": "Запланирована",
    "confirmed": "Подтверждена",
    "arrived": "Клиент приехал",
    "done": "Завершена",
    "no_show": "Не приехал",
    "cancelled": "Отменена",
}
APPOINTMENT_ACTIVE_STATUSES = {"scheduled", "confirmed", "arrived"}

ITEM_APPROVAL_STATUSES = {
    "approved": "Согласовано",
    "deferred": "Отложено",
    "declined": "Отказ",
}
BILLABLE_ITEM_STATUSES = {"approved"}

INSPECTION_STATUSES = {
    "draft": "Черновик",
    "ready": "Готов",
    "sent": "Отправлен клиенту",
    "archived": "Архив",
}

INSPECTION_CONDITIONS = {
    "ok": "Норма",
    "attention": "Внимание",
    "critical": "Критично",
}

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

CAR_CATALOG.extend(
    [
        {"make": "Toyota", "models": ["4Runner", "Alphard", "Avalon", "Avensis", "bZ4X", "Crown", "Fortuner", "Harrier", "Mark II", "Noah", "Probox", "Sequoia", "Sienna", "Supra", "Tacoma", "Tundra", "Venza", "Vitz"]},
        {"make": "Volkswagen", "models": ["Arteon", "Bora", "Caravelle", "Crafter", "ID.3", "ID.4", "ID.6", "Multivan", "Passat CC", "Phaeton", "Scirocco", "Sharan", "Taos", "Touran"]},
        {"make": "BMW", "models": ["6 Series", "8 Series", "i3", "i4", "i5", "i7", "i8", "iX", "iX1", "iX3", "M2", "M3", "M4", "M5", "M8", "Z4"]},
        {"make": "Mercedes-Benz", "models": ["B-Class", "GLB", "G-Class", "Maybach S-Class", "EQB", "EQC", "EQE", "EQS", "GLK", "M-Class", "R-Class", "SL", "SLC"]},
        {"make": "Audi", "models": ["A1", "A2", "Q2", "S3", "S4", "S5", "S6", "S7", "S8", "RS3", "RS4", "RS5", "RS6", "RS7", "e-tron"]},
        {"make": "Ford", "models": ["Bronco", "EcoSport", "Edge", "Escape", "Expedition", "Explorer Sport Trac", "F-150", "Fusion", "Galaxy", "Maverick", "S-Max", "Taurus"]},
        {"make": "Nissan", "models": ["350Z", "370Z", "Ariya", "Armada", "Bluebird", "GT-R", "Leaf", "Maxima", "Micra", "Note", "Primera", "Sentra", "Skyline", "Tiida", "Versa"]},
        {"make": "Hyundai", "models": ["Accent", "Bayon", "Genesis", "Getz", "Grandeur", "H-1", "i10", "i20", "i30", "i40", "Ioniq", "Ioniq 5", "Ioniq 6", "Kona", "Matrix", "Porter"]},
        {"make": "Kia", "models": ["Carens", "Forte", "K3", "K7", "K8", "Niro", "Picanto", "Quoris", "Ray", "Soul", "Stinger", "Telluride", "Venga", "XCeed"]},
        {"make": "Mazda", "models": ["5", "8", "Atenza", "Axela", "BT-50", "CX-4", "CX-50", "CX-60", "CX-8", "Demio", "MX-5", "RX-8", "Tribute"]},
        {"make": "Honda", "models": ["City", "Crosstour", "Element", "Elysion", "Freed", "Insight", "Jazz", "Legend", "Ridgeline", "Stepwgn", "Stream", "Vezel"]},
        {"make": "Mitsubishi", "models": ["Airtrek", "Colt", "Delica", "Galant", "Grandis", "i-MiEV", "Mirage", "Montero", "Space Star", "Xpander"]},
        {"make": "Subaru", "models": ["Ascent", "BRZ", "Exiga", "Justy", "Levorg", "Solterra", "Stella", "Trezia"]},
        {"make": "Suzuki", "models": ["Alto", "Baleno", "Celerio", "Grand Vitara", "Ignis", "Jimny", "Kizashi", "Liana", "S-Cross", "Splash", "Swift", "SX4", "Vitara", "Wagon R"]},
        {"make": "Acura", "models": ["CL", "ILX", "Integra", "MDX", "NSX", "RDX", "RL", "RLX", "RSX", "TL", "TLX", "TSX", "ZDX"]},
        {"make": "Alfa Romeo", "models": ["145", "147", "156", "159", "166", "Brera", "Giulia", "Giulietta", "MiTo", "Spider", "Stelvio", "Tonale"]},
        {"make": "Aston Martin", "models": ["DB9", "DB11", "DB12", "DBS", "DBX", "Rapide", "Vantage", "Vanquish", "Virage"]},
        {"make": "Bentley", "models": ["Arnage", "Bentayga", "Brooklands", "Continental GT", "Flying Spur", "Mulsanne"]},
        {"make": "Bugatti", "models": ["Chiron", "Divo", "Tourbillon", "Veyron"]},
        {"make": "Buick", "models": ["Century", "Enclave", "Encore", "Envision", "LaCrosse", "LeSabre", "Lucerne", "Regal"]},
        {"make": "Cadillac", "models": ["ATS", "CT4", "CT5", "CT6", "CTS", "DeVille", "Escalade", "SRX", "XT4", "XT5", "XT6", "XTS"]},
        {"make": "Chrysler", "models": ["200", "300", "300C", "Aspen", "Pacifica", "PT Cruiser", "Sebring", "Town & Country", "Voyager"]},
        {"make": "Dodge", "models": ["Avenger", "Caliber", "Caravan", "Challenger", "Charger", "Dakota", "Dart", "Durango", "Journey", "Neon", "Ram", "Viper"]},
        {"make": "Ferrari", "models": ["296", "458 Italia", "488", "812", "California", "F8", "F12berlinetta", "FF", "Portofino", "Purosangue", "Roma", "SF90"]},
        {"make": "Fiat", "models": ["124 Spider", "500", "500L", "500X", "Albea", "Bravo", "Doblo", "Ducato", "Linea", "Panda", "Punto", "Tipo"]},
        {"make": "GMC", "models": ["Acadia", "Canyon", "Envoy", "Savana", "Sierra", "Terrain", "Yukon"]},
        {"make": "Jeep", "models": ["Cherokee", "Commander", "Compass", "Gladiator", "Grand Cherokee", "Liberty", "Patriot", "Renegade", "Wrangler"]},
        {"make": "Lamborghini", "models": ["Aventador", "Gallardo", "Huracan", "Murcielago", "Revuelto", "Urus"]},
        {"make": "Lincoln", "models": ["Aviator", "Continental", "Corsair", "MKC", "MKS", "MKT", "MKX", "MKZ", "Navigator", "Town Car"]},
        {"make": "Maserati", "models": ["Ghibli", "GranCabrio", "GranTurismo", "Grecale", "Levante", "Quattroporte"]},
        {"make": "MINI", "models": ["Clubman", "Convertible", "Cooper", "Countryman", "Coupe", "Paceman", "Roadster"]},
        {"make": "RAM", "models": ["1500", "2500", "3500", "ProMaster"]},
        {"make": "Rolls-Royce", "models": ["Cullinan", "Dawn", "Ghost", "Phantom", "Spectre", "Wraith"]},
        {"make": "Saab", "models": ["9-3", "9-5", "9-7X", "900", "9000"]},
        {"make": "Smart", "models": ["Forfour", "Fortwo", "Roadster"]},
        {"make": "SEAT", "models": ["Alhambra", "Altea", "Arona", "Ateca", "Cordoba", "Ibiza", "Leon", "Tarraco", "Toledo"]},
        {"make": "Cupra", "models": ["Ateca", "Born", "Formentor", "Leon", "Tavascan"]},
        {"make": "Dacia", "models": ["Dokker", "Duster", "Jogger", "Logan", "Sandero", "Spring"]},
        {"make": "DS", "models": ["DS 3", "DS 4", "DS 5", "DS 7", "DS 9"]},
        {"make": "MG", "models": ["3", "4", "5", "6", "GS", "HS", "Marvel R", "MG ZS", "RX5"]},
        {"make": "Rover", "models": ["25", "45", "75", "Streetwise"]},
        {"make": "Daewoo", "models": ["Espero", "Gentra", "Lanos", "Leganza", "Matiz", "Nexia", "Nubira"]},
        {"make": "Ravon", "models": ["Gentra", "Nexia R3", "R2", "R4"]},
        {"make": "SsangYong", "models": ["Actyon", "Korando", "Kyron", "Musso", "Rexton", "Rodius", "Tivoli"]},
        {"make": "Daihatsu", "models": ["Be-Go", "Boon", "Charade", "Copen", "Materia", "Mira", "Move", "Sirion", "Terios"]},
        {"make": "Isuzu", "models": ["D-Max", "MU-X", "Trooper", "VehiCross"]},
        {"make": "Holden", "models": ["Astra", "Barina", "Captiva", "Colorado", "Commodore", "Cruze"]},
        {"make": "Hummer", "models": ["H1", "H2", "H3", "EV"]},
        {"make": "Lotus", "models": ["Elise", "Emira", "Emeya", "Esprit", "Evora", "Eletre", "Exige"]},
        {"make": "Polestar", "models": ["1", "2", "3", "4"]},
        {"make": "Lucid", "models": ["Air", "Gravity"]},
        {"make": "Rivian", "models": ["R1S", "R1T"]},
        {"make": "Fisker", "models": ["Karma", "Ocean"]},
        {"make": "McLaren", "models": ["540C", "570S", "600LT", "650S", "720S", "750S", "Artura", "GT", "MP4-12C", "Senna"]},
        {"make": "Pagani", "models": ["Huayra", "Utopia", "Zonda"]},
        {"make": "Koenigsegg", "models": ["Agera", "CCX", "Gemera", "Jesko", "Regera"]},
        {"make": "Aurus", "models": ["Komendant", "Senat"]},
        {"make": "ZAZ", "models": ["Chance", "Forza", "Lanos", "Sens", "Vida"]},
        {"make": "Bogdan", "models": ["2110", "2111", "2310"]},
        {"make": "Izh", "models": ["2126 Oda", "2717"]},
        {"make": "Vortex", "models": ["Corda", "Estina", "Tingo"]},
        {"make": "TagAZ", "models": ["C10", "C190", "Road Partner", "Tager", "Vega"]},
        {"make": "Lifan", "models": ["Breez", "Cebrium", "Celliya", "Murman", "Myway", "Solano", "Smily", "X50", "X60", "X70"]},
        {"make": "Brilliance", "models": ["H230", "H530", "M1", "M2", "V3", "V5"]},
        {"make": "Zotye", "models": ["Coupa", "T600", "Z300", "Z500"]},
        {"make": "Foton", "models": ["Sauvana", "Toano", "Tunland"]},
        {"make": "GAC", "models": ["Empow", "GS3", "GS4", "GS5", "GS8", "M8", "M6"]},
        {"make": "Hongqi", "models": ["E-HS9", "H5", "H7", "H9", "HS3", "HS5", "HS7"]},
        {"make": "Lynk & Co", "models": ["01", "02", "03", "05", "08", "09"]},
        {"make": "Nio", "models": ["EC6", "EC7", "ES6", "ES7", "ES8", "ET5", "ET7"]},
        {"make": "Xpeng", "models": ["G3", "G6", "G9", "Mona M03", "P5", "P7", "X9"]},
        {"make": "Denza", "models": ["D9", "N7", "N8", "Z9"]},
        {"make": "Aito", "models": ["M5", "M7", "M9"]},
        {"make": "Avatr", "models": ["07", "11", "12"]},
        {"make": "Deepal", "models": ["G318", "S05", "S07", "SL03"]},
        {"make": "Leapmotor", "models": ["C01", "C10", "C11", "T03"]},
        {"make": "Seres", "models": ["3", "5", "7", "M5", "M7"]},
        {"make": "Kaiyi", "models": ["E5", "X3", "X3 Pro", "X7 Kunlun"]},
        {"make": "SWM", "models": ["G01", "G05 Pro", "G07 Pro"]},
        {"make": "Livan", "models": ["S6 Pro", "X3 Pro", "X6 Pro"]},
        {"make": "Wey", "models": ["Coffee 01", "Coffee 02", "Mocha", "Tank 300"]},
        {"make": "Ora", "models": ["Ballet Cat", "Good Cat", "Lightning Cat"]},
        {"make": "Haima", "models": ["3", "7", "8S", "M3", "S5", "S7"]},
        {"make": "Maxus", "models": ["D60", "D90", "G10", "G50", "G90", "T60", "T90", "V80"]},
        {"make": "JMC", "models": ["Baodian", "Vigus", "Yuhu"]},
        {"make": "Bestune", "models": ["B70", "T55", "T77", "T90", "T99"]},
        {"make": "Venucia", "models": ["D60", "T60", "T70", "T90", "VX6"]},
        {"make": "Neta", "models": ["AYA", "GT", "L", "S", "U", "V", "X"]},
        {"make": "Roewe", "models": ["350", "550", "750", "RX5", "RX8", "i5", "i6"]},
        {"make": "Proton", "models": ["Exora", "Persona", "Preve", "Saga", "Waja", "X50", "X70"]},
        {"make": "Perodua", "models": ["Alza", "Ativa", "Axia", "Bezza", "Myvi"]},
        {"make": "Tata", "models": ["Harrier", "Hexa", "Indica", "Indigo", "Nexon", "Safari", "Tiago", "Tigor"]},
        {"make": "Mahindra", "models": ["Bolero", "KUV100", "Scorpio", "Thar", "XUV300", "XUV500", "XUV700"]},
        {"make": "Maruti Suzuki", "models": ["Alto", "Baleno", "Brezza", "Celerio", "Ciaz", "Dzire", "Ertiga", "Swift", "Wagon R"]},
    ]
)
_CAR_CATALOG_CACHE: dict[str, Any] | None = None
OFFICIAL_CAR_CATALOG_B64 = (
    "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"
)


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def user_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "STO_CRM"
    if os.name == "nt":
        return Path.home() / "AppData" / "Local" / "STO_CRM"
    return Path.home() / ".local" / "share" / "sto_crm"


def directory_writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / f".sto_crm_write_test_{os.getpid()}.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def default_db_path() -> Path:
    candidates = [user_data_dir(), app_dir()] if is_frozen() else [app_dir(), user_data_dir()]
    for directory in candidates:
        if directory_writable(directory):
            directory.mkdir(parents=True, exist_ok=True)
            return directory / "sto_crm.sqlite3"
    fallback = user_data_dir()
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback / "sto_crm.sqlite3"


def display_path(path: Path) -> str:
    """Показывает путь пользователю без раскрытия имени домашнего профиля."""
    try:
        resolved = path.resolve()
        home = Path.home().resolve()
        return "~" if resolved == home else f"~/{resolved.relative_to(home).as_posix()}"
    except (OSError, ValueError):
        return path.name or str(path)


def app_executable_path() -> Path:
    """Возвращает путь к текущему исполняемому артефакту приложения."""
    return Path(sys.executable if is_frozen() else __file__).resolve()


def updater_log_path() -> Path:
    return user_data_dir() / "updater.log"


def normalize_github_repository(value: str | None = None) -> str:
    """Нормализует owner/repo из переменной окружения или URL GitHub."""
    raw = clean_text(value or os.environ.get(GITHUB_UPDATES_CONFIG_ENV) or GITHUB_REPOSITORY, 220)
    if not raw:
        return GITHUB_REPOSITORY
    if raw.startswith("http://") or raw.startswith("https://"):
        parsed = urllib.parse.urlparse(raw)
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(parts) >= 2 and parsed.netloc.lower().endswith("github.com"):
            raw = "/".join(parts[:2])
    raw = raw.removesuffix(".git").strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", raw):
        return GITHUB_REPOSITORY
    return raw


def github_repository_url(repository: str | None = None) -> str:
    return f"https://github.com/{normalize_github_repository(repository)}"


def github_latest_release_api_url(repository: str | None = None) -> str:
    return f"https://api.github.com/repos/{normalize_github_repository(repository)}/releases/latest"


def github_latest_release_url(repository: str | None = None) -> str:
    return f"{github_repository_url(repository)}/releases/latest"


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def parse_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        normalized = str(value).replace("\u00a0", "").replace(" ", "").replace(",", ".")
        parsed = float(normalized)
        return parsed if math.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def parse_int(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return int(value)
    try:
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value) if math.isfinite(value) else default
        normalized = str(value).replace(" ", "").replace(" ", "").strip()
        if re.fullmatch(r"[+-]?\d+", normalized):
            return int(normalized)
        if re.fullmatch(r"[+-]?\d+[\.,]\d+", normalized):
            parsed = float(normalized.replace(",", "."))
            return int(parsed) if math.isfinite(parsed) else default
        return default
    except (TypeError, ValueError, OverflowError):
        return default


def is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip()) or value == ""


def parse_float_field(value: Any, field_name: str, default: float = 0.0) -> float:
    """Строгий парсер пользовательского денежного/количественного ввода."""
    if is_blank(value):
        return default
    try:
        normalized = str(value).replace("\u00a0", "").replace(" ", "").replace(",", ".").strip()
        parsed = float(normalized)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Некорректное число: {field_name}.") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"Некорректное число: {field_name}.")
    return parsed


def parse_int_field(value: Any, field_name: str, default: int = 0) -> int:
    """Строгий парсер пользовательского целочисленного ввода."""
    if is_blank(value):
        return default
    if isinstance(value, bool):
        return int(value)
    try:
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if not math.isfinite(value) or not value.is_integer():
                raise ValueError
            return int(value)
        normalized = str(value).replace("\u00a0", "").replace(" ", "").strip()
        if re.fullmatch(r"[+-]?\d+", normalized):
            return int(normalized)
        if re.fullmatch(r"[+-]?\d+[\.,]\d+", normalized):
            parsed = float(normalized.replace(",", "."))
            if not math.isfinite(parsed) or not parsed.is_integer():
                raise ValueError
            return int(parsed)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"Некорректное целое число: {field_name}.") from exc
    raise ValueError(f"Некорректное целое число: {field_name}.")


def clean_text(value: Any, max_len: int = 500, default: str = "") -> str:
    text = default if value is None else str(value)
    text = " ".join(text.replace("\x00", "").split())
    return text[:max_len]


def clean_multiline(value: Any, max_len: int = 4000) -> str:
    text = "" if value is None else str(value).replace("\x00", "")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)[:max_len]


def parse_datetime_local(value: Any, field_name: str, required: bool = False) -> str:
    text = clean_text(value, 40)
    if not text:
        if required:
            raise ValueError(f"Укажите дату: {field_name}.")
        return ""
    normalized = text.replace(" ", "T")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", normalized):
        raise ValueError(f"Некорректная дата: {field_name}.")
    try:
        return datetime.fromisoformat(normalized).isoformat(timespec="minutes")
    except ValueError as exc:
        raise ValueError(f"Некорректная дата: {field_name}.") from exc


def parse_date_iso(value: Any, field_name: str, required: bool = False) -> str:
    text = clean_text(value, 40)
    if not text:
        if required:
            raise ValueError(f"Укажите дату: {field_name}.")
        return ""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise ValueError(f"Некорректная дата: {field_name}.")
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError as exc:
        raise ValueError(f"Некорректная дата: {field_name}.") from exc


def validate_vehicle_year(value: Any) -> int:
    year = parse_int_field(value, "год автомобиля")
    if not year:
        return 0
    max_year = datetime.now().year + 1
    if year < MIN_VEHICLE_YEAR or year > max_year:
        raise ValueError(f"Некорректный год автомобиля. Укажите год от {MIN_VEHICLE_YEAR} до {max_year}.")
    return year


def validate_vin(value: str) -> str:
    vin = clean_text(value, 40).upper()
    if vin and not VIN_RE.fullmatch(vin):
        raise ValueError("Некорректный VIN. VIN должен содержать 17 символов без I, O и Q.")
    return vin


def official_car_catalog_entries() -> list[dict[str, Any]]:
    raw = zlib.decompress(base64.b64decode(OFFICIAL_CAR_CATALOG_B64)).decode("utf-8")
    payload = json.loads(raw)
    entries = payload.get("makes", [])
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def car_catalog_payload() -> dict[str, Any]:
    global _CAR_CATALOG_CACHE
    if _CAR_CATALOG_CACHE is not None:
        return _CAR_CATALOG_CACHE
    models_by_make: dict[str, list[str]] = {}
    seen_models: dict[str, set[str]] = {}
    make_names: dict[str, str] = {}
    makes: list[str] = []
    for entry in [*CAR_CATALOG, *official_car_catalog_entries()]:
        raw_make = str(entry["make"]).strip()
        if not raw_make:
            continue
        make_key = raw_make.casefold()
        make = make_names.setdefault(make_key, raw_make)
        models = [str(model).strip() for model in entry["models"] if str(model).strip()]
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
    for make, models in models_by_make.items():
        models_by_make[make] = sorted(models, key=str.casefold)
    _CAR_CATALOG_CACHE = {
        "makes": makes,
        "models": models_by_make,
        "stats": {
            "makes": len(makes),
            "models": sum(len(models) for models in models_by_make.values()),
            "empty_makes": sum(1 for models in models_by_make.values() if not models),
        },
    }
    return _CAR_CATALOG_CACHE


def money(value: Any) -> str:
    amount = parse_float(value)
    return f"{amount:,.2f} ₽".replace(",", "\u202f").replace(".", ",")


def csv_cell(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.lstrip()
    if stripped and stripped[0] in ("=", "+", "-", "@", "\t", "\r", "\n"):
        return "'" + value
    return value


def sql_limit(limit: int | None) -> tuple[str, list[Any]]:
    if limit is None:
        return "", []
    return "LIMIT ?", [max(parse_int(limit, 1000), 1)]


def search_needle(q: str) -> str:
    return f"%{q.casefold()}%"


def redact_sensitive_query(message: str) -> str:
    """Маскирует токены из URL перед выводом в локальный журнал."""
    return SENSITIVE_QUERY_RE.sub(r"\1***", message)


def safe_log(message: str) -> None:
    stream = getattr(sys, "stdout", None)
    if not stream:
        return
    try:
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "?", redact_sensitive_query(str(message)))
        text = text.replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\t")
        stream.write(text + "\n")
        stream.flush()
    except Exception:
        pass


@dataclass(frozen=True)
class Runtime:
    db_path: Path
    start_time: float
    csrf_token: str = ""


RUNTIME = Runtime(db_path=default_db_path(), start_time=time.time(), csrf_token=secrets.token_urlsafe(32))


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(RUNTIME.db_path, timeout=30, isolation_level="DEFERRED")
    conn.row_factory = sqlite3.Row
    try:
        conn.create_function("CASEFOLD", 1, lambda value: str(value or "").casefold(), deterministic=True)
    except sqlite3.NotSupportedError:
        conn.create_function("CASEFOLD", 1, lambda value: str(value or "").casefold())
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA temp_store = MEMORY")
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
        if conn.in_transaction:
            conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def write_db() -> Iterator[sqlite3.Connection]:
    """Open a write transaction early to serialize check-then-write business rules."""
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        yield conn


def init_db(seed_demo: bool = False) -> None:
    RUNTIME.db_path.parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS customers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    phone TEXT NOT NULL DEFAULT '',
                    email TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    preferred_channel TEXT NOT NULL DEFAULT 'phone',
                    reminder_consent INTEGER NOT NULL DEFAULT 1,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );

                CREATE TABLE IF NOT EXISTS vehicles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER NOT NULL REFERENCES customers(id),
                    make TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    year INTEGER NOT NULL DEFAULT 0,
                    plate TEXT NOT NULL DEFAULT '',
                    vin TEXT NOT NULL DEFAULT '',
                    mileage INTEGER NOT NULL DEFAULT 0,
                    next_service_at TEXT NOT NULL DEFAULT '',
                    next_service_mileage INTEGER NOT NULL DEFAULT 0,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );

                CREATE TABLE IF NOT EXISTS inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sku TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL,
                    brand TEXT NOT NULL DEFAULT '',
                    unit TEXT NOT NULL DEFAULT 'шт',
                    quantity REAL NOT NULL DEFAULT 0,
                    min_quantity REAL NOT NULL DEFAULT 0,
                    price REAL NOT NULL DEFAULT 0,
                    cost REAL NOT NULL DEFAULT 0,
                    supplier TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );

                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    number TEXT NOT NULL UNIQUE,
                    customer_id INTEGER NOT NULL REFERENCES customers(id),
                    vehicle_id INTEGER REFERENCES vehicles(id),
                    status TEXT NOT NULL DEFAULT 'new',
                    priority TEXT NOT NULL DEFAULT 'normal',
                    advisor TEXT NOT NULL DEFAULT '',
                    mechanic TEXT NOT NULL DEFAULT '',
                    promised_at TEXT NOT NULL DEFAULT '',
                    odometer INTEGER NOT NULL DEFAULT 0,
                    complaint TEXT NOT NULL DEFAULT '',
                    diagnosis TEXT NOT NULL DEFAULT '',
                    recommendations TEXT NOT NULL DEFAULT '',
                    discount REAL NOT NULL DEFAULT 0,
                    tax_rate REAL NOT NULL DEFAULT 0,
                    paid REAL NOT NULL DEFAULT 0,
                    payment_method TEXT NOT NULL DEFAULT '',
                    authorized_by TEXT NOT NULL DEFAULT '',
                    authorized_at TEXT NOT NULL DEFAULT '',
                    follow_up_at TEXT NOT NULL DEFAULT '',
                    closed_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );

                CREATE TABLE IF NOT EXISTS order_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL CHECK(kind IN ('service', 'part')),
                    inventory_id INTEGER REFERENCES inventory(id),
                    title TEXT NOT NULL,
                    approval_status TEXT NOT NULL DEFAULT 'approved',
                    quantity REAL NOT NULL DEFAULT 1,
                    unit_price REAL NOT NULL DEFAULT 0,
                    unit_cost REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS appointments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER NOT NULL REFERENCES customers(id),
                    vehicle_id INTEGER REFERENCES vehicles(id),
                    scheduled_at TEXT NOT NULL DEFAULT '',
                    duration_minutes INTEGER NOT NULL DEFAULT 60,
                    status TEXT NOT NULL DEFAULT 'scheduled',
                    advisor TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );

                CREATE TABLE IF NOT EXISTS inspections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER NOT NULL REFERENCES customers(id),
                    vehicle_id INTEGER REFERENCES vehicles(id),
                    order_id INTEGER REFERENCES orders(id),
                    status TEXT NOT NULL DEFAULT 'draft',
                    inspector TEXT NOT NULL DEFAULT '',
                    inspected_at TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );

                CREATE TABLE IF NOT EXISTS inspection_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    inspection_id INTEGER NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
                    area TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL,
                    condition_status TEXT NOT NULL DEFAULT 'ok',
                    approval_status TEXT NOT NULL DEFAULT 'approved',
                    recommendation TEXT NOT NULL DEFAULT '',
                    estimate REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_customers_active_name ON customers(deleted_at, name);
                CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);
                CREATE INDEX IF NOT EXISTS idx_vehicles_active_customer ON vehicles(deleted_at, customer_id);
                CREATE INDEX IF NOT EXISTS idx_vehicles_plate ON vehicles(plate);
                CREATE INDEX IF NOT EXISTS idx_inventory_active_name ON inventory(deleted_at, name);
                CREATE INDEX IF NOT EXISTS idx_orders_active_status ON orders(deleted_at, status);
                CREATE INDEX IF NOT EXISTS idx_orders_deleted ON orders(deleted_at);
                CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
                CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items(order_id);
                CREATE INDEX IF NOT EXISTS idx_appointments_schedule ON appointments(deleted_at, scheduled_at);
                CREATE INDEX IF NOT EXISTS idx_appointments_customer ON appointments(customer_id);
                CREATE INDEX IF NOT EXISTS idx_inspections_vehicle ON inspections(deleted_at, vehicle_id, inspected_at);
                CREATE INDEX IF NOT EXISTS idx_inspections_customer ON inspections(customer_id);
                CREATE INDEX IF NOT EXISTS idx_inspection_items_inspection ON inspection_items(inspection_id);
                """
            )
            ensure_schema(conn)
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
    if seed_demo:
        seed_demo_data()


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> bool:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column in columns:
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    return True


def active_duplicate_values(conn: sqlite3.Connection, table: str, column: str, limit: int = 5) -> list[sqlite3.Row]:
    allowed_columns = {
        ("inventory", "sku"),
        ("vehicles", "vin"),
        ("vehicles", "plate"),
    }
    if (table, column) not in allowed_columns:
        raise ValueError("Некорректная проверка дублей.")
    return conn.execute(
        f"""
        SELECT CASEFOLD({column}) AS key, MIN({column}) AS value, COUNT(*) AS count, GROUP_CONCAT(id) AS ids
        FROM {table}
        WHERE deleted_at IS NULL AND {column} <> ''
        GROUP BY CASEFOLD({column})
        HAVING COUNT(*) > 1
        ORDER BY count DESC, value COLLATE NOCASE
        LIMIT ?
        """,
        (max(parse_int(limit, 5), 1),),
    ).fetchall()


def resolve_active_duplicate_values(conn: sqlite3.Connection, table: str, column: str, label: str) -> int:
    resolved = 0
    stamp = now_iso()
    for duplicate in active_duplicate_values(conn, table, column, LOOKUP_LIMIT):
        rows = conn.execute(
            f"""
            SELECT id, {column} AS value, notes
            FROM {table}
            WHERE deleted_at IS NULL AND {column} <> '' AND CASEFOLD({column}) = ?
            ORDER BY id
            """,
            (duplicate["key"],),
        ).fetchall()
        if len(rows) < 2:
            continue
        kept_id = int(rows[0]["id"])
        kept_value = str(rows[0]["value"] or "")
        for row in rows[1:]:
            original_value = str(row["value"] or "")
            note = (
                f"Системная миграция {APP_VERSION}: очищено дублирующее значение поля «{label}» "
                f"({original_value}); исходное значение оставлено у записи id {kept_id} ({kept_value})."
            )
            notes = clean_multiline("\n".join(part for part in [str(row["notes"] or "").strip(), note] if part), 2000)
            conn.execute(f"UPDATE {table} SET {column} = '', notes = ?, updated_at = ? WHERE id = ?", (notes, stamp, int(row["id"])))
            resolved += 1
    return resolved


def ensure_unique_index(conn: sqlite3.Connection, statement: str, table: str, column: str, label: str) -> None:
    try:
        conn.execute(statement)
    except sqlite3.IntegrityError as exc:
        resolved = resolve_active_duplicate_values(conn, table, column, label)
        if resolved:
            safe_log(f"Исправлены активные дубли поля «{label}»: очищено значений у записей: {resolved}.")
            conn.execute(statement)
            return
        duplicates = active_duplicate_values(conn, table, column)
        details = "; ".join(
            f"{row['value']} — {row['count']} записей (id: {row['ids']})" for row in duplicates
        ) or str(exc)
        raise RuntimeError(
            f"Невозможно включить защиту уникальности для поля «{label}»: найдены активные дубли. "
            f"Объедините или удалите дублирующиеся записи и перезапустите CRM. Примеры: {details}."
        ) from exc


def ensure_schema(conn: sqlite3.Connection) -> None:
    ensure_column(conn, "customers", "phone", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "customers", "email", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "customers", "source", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "customers", "preferred_channel", "TEXT NOT NULL DEFAULT 'phone'")
    ensure_column(conn, "customers", "reminder_consent", "INTEGER NOT NULL DEFAULT 1")
    ensure_column(conn, "customers", "notes", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "customers", "created_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "customers", "updated_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "customers", "deleted_at", "TEXT")

    ensure_column(conn, "vehicles", "make", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "vehicles", "model", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "vehicles", "year", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "vehicles", "plate", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "vehicles", "vin", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "vehicles", "mileage", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "vehicles", "next_service_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "vehicles", "next_service_mileage", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "vehicles", "notes", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "vehicles", "created_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "vehicles", "updated_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "vehicles", "deleted_at", "TEXT")

    ensure_column(conn, "inventory", "sku", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "inventory", "brand", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "inventory", "unit", "TEXT NOT NULL DEFAULT 'шт'")
    ensure_column(conn, "inventory", "quantity", "REAL NOT NULL DEFAULT 0")
    ensure_column(conn, "inventory", "min_quantity", "REAL NOT NULL DEFAULT 0")
    ensure_column(conn, "inventory", "price", "REAL NOT NULL DEFAULT 0")
    ensure_column(conn, "inventory", "cost", "REAL NOT NULL DEFAULT 0")
    ensure_column(conn, "inventory", "supplier", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "inventory", "notes", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "inventory", "created_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "inventory", "updated_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "inventory", "deleted_at", "TEXT")

    ensure_column(conn, "orders", "priority", "TEXT NOT NULL DEFAULT 'normal'")
    ensure_column(conn, "orders", "advisor", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "orders", "mechanic", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "orders", "promised_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "orders", "odometer", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "orders", "complaint", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "orders", "diagnosis", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "orders", "recommendations", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "orders", "discount", "REAL NOT NULL DEFAULT 0")
    ensure_column(conn, "orders", "tax_rate", "REAL NOT NULL DEFAULT 0")
    ensure_column(conn, "orders", "paid", "REAL NOT NULL DEFAULT 0")
    ensure_column(conn, "orders", "payment_method", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "orders", "authorized_by", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "orders", "authorized_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "orders", "follow_up_at", "TEXT NOT NULL DEFAULT ''")
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(orders)").fetchall()}
    if "closed_at" not in columns:
        conn.execute("ALTER TABLE orders ADD COLUMN closed_at TEXT NOT NULL DEFAULT ''")
        conn.execute(
            """
            UPDATE orders
            SET closed_at = COALESCE(NULLIF(updated_at, ''), created_at)
            WHERE status = 'closed' AND closed_at = ''
            """
        )
    ensure_column(conn, "order_items", "approval_status", "TEXT NOT NULL DEFAULT 'approved'")
    ensure_column(conn, "appointments", "scheduled_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "appointments", "duration_minutes", "INTEGER NOT NULL DEFAULT 60")
    ensure_column(conn, "appointments", "status", "TEXT NOT NULL DEFAULT 'scheduled'")
    ensure_column(conn, "appointments", "advisor", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "appointments", "reason", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "appointments", "notes", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "appointments", "created_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "appointments", "updated_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "appointments", "deleted_at", "TEXT")

    ensure_column(conn, "inspections", "order_id", "INTEGER REFERENCES orders(id)")
    ensure_column(conn, "inspections", "status", "TEXT NOT NULL DEFAULT 'draft'")
    ensure_column(conn, "inspections", "inspector", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "inspections", "inspected_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "inspections", "summary", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "inspections", "created_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "inspections", "updated_at", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "inspections", "deleted_at", "TEXT")

    ensure_column(conn, "inspection_items", "area", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "inspection_items", "condition_status", "TEXT NOT NULL DEFAULT 'ok'")
    ensure_column(conn, "inspection_items", "approval_status", "TEXT NOT NULL DEFAULT 'approved'")
    ensure_column(conn, "inspection_items", "recommendation", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "inspection_items", "estimate", "REAL NOT NULL DEFAULT 0")
    ensure_column(conn, "inspection_items", "created_at", "TEXT NOT NULL DEFAULT ''")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_closed_at ON orders(closed_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_follow_up_at ON orders(follow_up_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_vehicles_next_service ON vehicles(next_service_at, next_service_mileage)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_appointments_schedule ON appointments(deleted_at, scheduled_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_appointments_customer ON appointments(customer_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_inspections_vehicle ON inspections(deleted_at, vehicle_id, inspected_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_inspections_customer ON inspections(customer_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_inspection_items_inspection ON inspection_items(inspection_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_order_items_inventory ON order_items(inventory_id)")
    unique_indexes = (
        (
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_inventory_sku_active ON inventory(CASEFOLD(sku)) WHERE deleted_at IS NULL AND sku <> ''",
            "inventory",
            "sku",
            "артикул склада",
        ),
        (
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_vehicles_vin_active ON vehicles(CASEFOLD(vin)) WHERE deleted_at IS NULL AND vin <> ''",
            "vehicles",
            "vin",
            "VIN автомобиля",
        ),
        (
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_vehicles_plate_active ON vehicles(CASEFOLD(plate)) WHERE deleted_at IS NULL AND plate <> ''",
            "vehicles",
            "plate",
            "госномер автомобиля",
        ),
    )
    for statement, table, column, label in unique_indexes:
        ensure_unique_index(conn, statement, table, column, label)


def seed_demo_data() -> None:
    with write_db() as conn:
        try:
            count = conn.execute("SELECT COUNT(*) FROM customers WHERE deleted_at IS NULL").fetchone()[0]
            if count:
                conn.execute("COMMIT")
                return
            stamp = now_iso()
            customers = [
                ("Иван Петров", "+7 900 111-22-33", "ivan@example.ru", "Рекомендация", "Постоянный клиент"),
                ("ООО Таксопарк Север", "+7 900 222-33-44", "fleet@example.ru", "Сайт", "Обслуживание парка"),
                ("Мария Соколова", "+7 900 333-44-55", "maria@example.ru", "2ГИС", ""),
            ]
            customer_ids: list[int] = []
            for item in customers:
                cur = conn.execute(
                    """
                    INSERT INTO customers(name, phone, email, source, notes, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (*item, stamp, stamp),
                )
                customer_ids.append(int(cur.lastrowid))

            next_service_date = (datetime.now() + timedelta(days=10)).date().isoformat()
            vehicles = [
                (customer_ids[0], "Toyota", "Camry", 2018, "A123AA", "JTNB11HK303000001", 82000, next_service_date, 90000, ""),
                (customer_ids[1], "Hyundai", "Solaris", 2021, "T451TX", "Z94K241CBMR000002", 146000, "", 150000, "Такси"),
                (customer_ids[2], "Kia", "Sportage", 2020, "M777MA", "XWEPH81BDL0000003", 61000, "", 0, ""),
            ]
            vehicle_ids: list[int] = []
            for item in vehicles:
                cur = conn.execute(
                    """
                    INSERT INTO vehicles(customer_id, make, model, year, plate, vin, mileage, next_service_at, next_service_mileage, notes, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (*item, stamp, stamp),
                )
                vehicle_ids.append(int(cur.lastrowid))

            parts = [
                ("OF-TY-041", "Фильтр масляный", "Toyota", "шт", 18, 5, 850, 520, "АвтоПартс"),
                ("OIL-5W30-4L", "Масло моторное 5W-30 4 л", "Shell", "шт", 10, 3, 3900, 2850, "МаслоСклад"),
                ("PAD-FR-211", "Колодки тормозные передние", "Nibk", "компл", 4, 2, 5200, 3600, "ТормозМаркет"),
                ("AIR-HY-001", "Фильтр воздушный", "Hyundai", "шт", 2, 4, 1200, 780, "АвтоПартс"),
                ("BATT-60", "АКБ 60 А·ч", "Mutlu", "шт", 3, 1, 8200, 6400, "ЭлектроСнаб"),
            ]
            part_ids: list[int] = []
            for item in parts:
                cur = conn.execute(
                    """
                    INSERT INTO inventory(sku, name, brand, unit, quantity, min_quantity, price, cost, supplier, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (*item, stamp, stamp),
                )
                part_ids.append(int(cur.lastrowid))

            promised = (datetime.now() + timedelta(days=1)).replace(microsecond=0).isoformat(timespec="minutes")
            order_id = create_order_tx(
                conn,
                {
                    "customer_id": customer_ids[0],
                    "vehicle_id": vehicle_ids[0],
                    "status": "in_progress",
                    "priority": "normal",
                    "advisor": "Администратор",
                    "mechanic": "Сергей",
                    "promised_at": promised,
                    "odometer": 82000,
                    "complaint": "Плановое ТО, шум при торможении.",
                    "diagnosis": "Требуется замена масла и проверка тормозной системы.",
                    "recommendations": "Контрольный осмотр через 10 000 км.",
                    "discount": 0,
                    "tax_rate": 0,
                    "paid": 0,
                    "items": [
                        {"kind": "service", "title": "Замена масла и фильтра", "quantity": 1, "unit_price": 2200, "unit_cost": 0},
                        {"kind": "part", "inventory_id": part_ids[0], "title": "Фильтр масляный", "quantity": 1, "unit_price": 850, "unit_cost": 520},
                        {"kind": "part", "inventory_id": part_ids[1], "title": "Масло моторное 5W-30 4 л", "quantity": 1, "unit_price": 3900, "unit_cost": 2850},
                    ],
                },
            )
            _ = order_id

            create_order_tx(
                conn,
                {
                    "customer_id": customer_ids[1],
                    "vehicle_id": vehicle_ids[1],
                    "status": "new",
                    "priority": "high",
                    "advisor": "Администратор",
                    "mechanic": "",
                    "promised_at": (datetime.now() + timedelta(hours=5)).replace(microsecond=0).isoformat(timespec="minutes"),
                    "odometer": 146000,
                    "complaint": "Неравномерная работа двигателя.",
                    "diagnosis": "",
                    "recommendations": "",
                    "discount": 0,
                    "tax_rate": 0,
                    "paid": 0,
                    "items": [
                        {"kind": "service", "title": "Компьютерная диагностика", "quantity": 1, "unit_price": 1800, "unit_cost": 0}
                    ],
                },
            )
            appointment_time = (datetime.now() + timedelta(hours=2)).replace(microsecond=0).isoformat(timespec="minutes")
            conn.execute(
                """
                INSERT INTO appointments(customer_id, vehicle_id, scheduled_at, duration_minutes, status,
                                         advisor, reason, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    customer_ids[2],
                    vehicle_ids[2],
                    appointment_time,
                    60,
                    "confirmed",
                    "Администратор",
                    "Диагностика подвески",
                    "Подготовить подъемник и проверить историю обслуживания.",
                    stamp,
                    stamp,
                ),
            )
            inspection_time = datetime.now().replace(microsecond=0).isoformat(timespec="minutes")
            cur = conn.execute(
                """
                INSERT INTO inspections(customer_id, vehicle_id, order_id, status, inspector, inspected_at,
                                        summary, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    customer_ids[0],
                    vehicle_ids[0],
                    order_id,
                    "ready",
                    "Сергей",
                    inspection_time,
                    "Мульти-точечный осмотр перед согласованием дополнительных работ.",
                    stamp,
                    stamp,
                ),
            )
            inspection_id = int(cur.lastrowid)
            conn.executemany(
                """
                INSERT INTO inspection_items(inspection_id, area, title, condition_status, approval_status,
                                             recommendation, estimate, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (inspection_id, "Тормоза", "Передние тормозные колодки", "attention", "deferred", "Рекомендовать замену в ближайший визит.", 5200, stamp),
                    (inspection_id, "Жидкости", "Уровень и состояние моторного масла", "ok", "approved", "Без замечаний.", 0, stamp),
                    (inspection_id, "Свет", "Проверка наружного освещения", "ok", "approved", "Без замечаний.", 0, stamp),
                ],
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise


def generate_order_number(conn: sqlite3.Connection) -> str:
    """Генерирует уникальный номер заказ-наряда."""
    prefix = datetime.now().strftime("СТО-%Y%m%d")
    rows = conn.execute(
        "SELECT number FROM orders WHERE number LIKE ?",
        (f"{prefix}-%",),
    ).fetchall()
    max_suffix = 0
    for row in rows:
        try:
            max_suffix = max(max_suffix, int(str(row["number"]).rsplit("-", 1)[1]))
        except (IndexError, ValueError):
            continue
    return f"{prefix}-{max_suffix + 1:03d}"


def validate_customer(payload: dict[str, Any]) -> dict[str, Any]:
    name = clean_text(payload.get("name"), 180)
    if not name:
        raise ValueError("Укажите имя клиента.")
    preferred_channel = clean_text(payload.get("preferred_channel"), 30, "phone")
    if preferred_channel not in PREFERRED_CHANNELS:
        raise ValueError("Некорректный канал связи клиента.")
    phone = clean_text(payload.get("phone"), 80)
    email = clean_text(payload.get("email"), 180).lower()
    if email and not EMAIL_RE.fullmatch(email):
        raise ValueError("Некорректный email клиента.")
    return {
        "name": name,
        "phone": phone,
        "email": email,
        "source": clean_text(payload.get("source"), 120),
        "preferred_channel": preferred_channel,
        "reminder_consent": 1 if parse_int_field(payload.get("reminder_consent"), "согласие на напоминания", 1) else 0,
        "notes": clean_multiline(payload.get("notes"), 2000),
    }


def validate_vehicle(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    customer_id = parse_int_field(payload.get("customer_id"), "клиент")
    if not customer_id or not active_exists(conn, "customers", customer_id):
        raise ValueError("Выберите действующего клиента.")
    make = clean_text(payload.get("make"), 120)
    model = clean_text(payload.get("model"), 120)
    plate = clean_text(payload.get("plate"), 40).upper()
    vin = validate_vin(payload.get("vin"))
    if not (make or model or plate or vin):
        raise ValueError("Укажите автомобиль: марку, модель, номер или VIN.")
    return {
        "customer_id": customer_id,
        "make": make,
        "model": model,
        "year": validate_vehicle_year(payload.get("year")),
        "plate": plate,
        "vin": vin,
        "mileage": max(parse_int_field(payload.get("mileage"), "пробег"), 0),
        "next_service_at": parse_date_iso(payload.get("next_service_at"), "дата следующего сервиса"),
        "next_service_mileage": max(parse_int_field(payload.get("next_service_mileage"), "сервисный пробег"), 0),
        "notes": clean_multiline(payload.get("notes"), 2000),
    }


def validate_inventory(payload: dict[str, Any]) -> dict[str, Any]:
    name = clean_text(payload.get("name"), 220)
    if not name:
        raise ValueError("Укажите название позиции склада.")
    return {
        "sku": clean_text(payload.get("sku"), 100).upper(),
        "name": name,
        "brand": clean_text(payload.get("brand"), 140),
        "unit": clean_text(payload.get("unit"), 30, "шт") or "шт",
        "quantity": max(parse_float_field(payload.get("quantity"), "остаток"), 0),
        "min_quantity": max(parse_float_field(payload.get("min_quantity"), "минимальный остаток"), 0),
        "price": max(parse_float_field(payload.get("price"), "цена"), 0),
        "cost": max(parse_float_field(payload.get("cost"), "себестоимость"), 0),
        "supplier": clean_text(payload.get("supplier"), 180),
        "notes": clean_multiline(payload.get("notes"), 2000),
    }


def validate_order(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    customer_id = parse_int_field(payload.get("customer_id"), "клиент")
    if not customer_id or not active_exists(conn, "customers", customer_id):
        raise ValueError("Выберите действующего клиента.")

    vehicle_id_raw = parse_int_field(payload.get("vehicle_id"), "автомобиль") or None
    vehicle_id = ensure_vehicle_belongs_to_customer(conn, vehicle_id_raw, customer_id)

    status = clean_text(payload.get("status"), 40, "new")
    if status not in ORDER_STATUSES:
        raise ValueError("Некорректный статус заказа.")

    priority = clean_text(payload.get("priority"), 20, "normal")
    if priority not in ORDER_PRIORITIES:
        raise ValueError("Некорректный приоритет заказа.")

    raw_items = payload.get("items") or []
    if not isinstance(raw_items, list):
        raise ValueError("Позиции заказ-наряда должны быть списком.")
    items = [validate_order_item(conn, item) for item in raw_items]
    items = [item for item in items if item["title"]]
    if not items:
        raise ValueError("Добавьте хотя бы одну работу или запчасть.")

    data = {
        "customer_id": customer_id,
        "vehicle_id": vehicle_id,
        "status": status,
        "priority": priority,
        "advisor": clean_text(payload.get("advisor"), 120),
        "mechanic": clean_text(payload.get("mechanic"), 120),
        "promised_at": parse_datetime_local(payload.get("promised_at"), "срок заказа"),
        "odometer": max(parse_int_field(payload.get("odometer"), "пробег в заказе"), 0),
        "complaint": clean_multiline(payload.get("complaint"), 3000),
        "diagnosis": clean_multiline(payload.get("diagnosis"), 3000),
        "recommendations": clean_multiline(payload.get("recommendations"), 3000),
        "discount": max(parse_float_field(payload.get("discount"), "скидка"), 0),
        "tax_rate": min(max(parse_float_field(payload.get("tax_rate"), "налог"), 0), 100),
        "paid": max(parse_float_field(payload.get("paid"), "оплачено"), 0),
        "payment_method": clean_text(payload.get("payment_method"), 80),
        "authorized_by": clean_text(payload.get("authorized_by"), 120),
        "authorized_at": parse_datetime_local(payload.get("authorized_at"), "дата согласования"),
        "follow_up_at": parse_datetime_local(payload.get("follow_up_at"), "follow-up"),
        "items": items,
    }
    normalize_order_money(data)
    return data


def validate_appointment(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    customer_id = parse_int_field(payload.get("customer_id"), "клиент")
    if not customer_id or not active_exists(conn, "customers", customer_id):
        raise ValueError("Выберите действующего клиента.")

    vehicle_id_raw = parse_int_field(payload.get("vehicle_id"), "автомобиль") or None
    vehicle_id = ensure_vehicle_belongs_to_customer(conn, vehicle_id_raw, customer_id)

    scheduled_at = parse_datetime_local(payload.get("scheduled_at"), "дата и время записи", required=True)

    duration_minutes = parse_int_field(payload.get("duration_minutes"), "длительность записи", 60)
    duration_minutes = min(max(duration_minutes, 15), 480)
    status = clean_text(payload.get("status"), 30, "scheduled")
    if status not in APPOINTMENT_STATUSES:
        raise ValueError("Некорректный статус записи.")

    return {
        "customer_id": customer_id,
        "vehicle_id": vehicle_id,
        "scheduled_at": scheduled_at,
        "duration_minutes": duration_minutes,
        "status": status,
        "advisor": clean_text(payload.get("advisor"), 120),
        "reason": clean_text(payload.get("reason"), 220),
        "notes": clean_multiline(payload.get("notes"), 2000),
    }


def validate_inspection(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    customer_id = parse_int_field(payload.get("customer_id"), "клиент")
    if not customer_id or not active_exists(conn, "customers", customer_id):
        raise ValueError("Выберите действующего клиента.")

    vehicle_id_raw = parse_int_field(payload.get("vehicle_id"), "автомобиль") or None
    vehicle_id = ensure_vehicle_belongs_to_customer(conn, vehicle_id_raw, customer_id)

    order_id = parse_int_field(payload.get("order_id"), "заказ-наряд") or None
    if order_id:
        order = conn.execute(
            """
            SELECT customer_id, vehicle_id
            FROM orders
            WHERE id = ? AND deleted_at IS NULL
            """,
            (order_id,),
        ).fetchone()
        if not order:
            raise ValueError("Выберите действующий заказ-наряд.")
        if int(order["customer_id"]) != customer_id:
            raise ValueError("Выбранный заказ-наряд принадлежит другому клиенту.")
        if vehicle_id and order["vehicle_id"] and int(order["vehicle_id"]) != vehicle_id:
            raise ValueError("Заказ-наряд привязан к другому автомобилю.")
        if not vehicle_id and order["vehicle_id"]:
            vehicle_id = ensure_vehicle_belongs_to_customer(conn, int(order["vehicle_id"]), customer_id, required=True)

    status = clean_text(payload.get("status"), 30, "draft")
    if status not in INSPECTION_STATUSES:
        raise ValueError("Некорректный статус осмотра.")

    inspected_at = parse_datetime_local(payload.get("inspected_at"), "дата осмотра")
    if not inspected_at:
        inspected_at = datetime.now().replace(microsecond=0).isoformat(timespec="minutes")

    raw_items = payload.get("items") or []
    if not isinstance(raw_items, list):
        raise ValueError("Пункты осмотра должны быть списком.")
    items = [validate_inspection_item(item) for item in raw_items]
    items = [item for item in items if item["title"]]
    if not items:
        raise ValueError("Добавьте хотя бы один пункт осмотра.")

    return {
        "customer_id": customer_id,
        "vehicle_id": vehicle_id,
        "order_id": order_id,
        "status": status,
        "inspector": clean_text(payload.get("inspector"), 120),
        "inspected_at": inspected_at,
        "summary": clean_multiline(payload.get("summary"), 2500),
        "items": items,
    }


def validate_inspection_item(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Пункт осмотра должен быть JSON-объектом.")
    condition_status = clean_text(payload.get("condition_status"), 30, "ok")
    if condition_status not in INSPECTION_CONDITIONS:
        raise ValueError("Некорректное состояние пункта осмотра.")
    default_approval = "approved" if condition_status == "ok" else "deferred"
    approval_status = clean_text(payload.get("approval_status"), 30, default_approval)
    if approval_status not in ITEM_APPROVAL_STATUSES:
        raise ValueError("Некорректный статус согласования пункта осмотра.")
    return {
        "area": clean_text(payload.get("area"), 120),
        "title": clean_text(payload.get("title"), 220),
        "condition_status": condition_status,
        "approval_status": approval_status,
        "recommendation": clean_multiline(payload.get("recommendation"), 2000),
        "estimate": max(parse_float_field(payload.get("estimate"), "оценка пункта осмотра"), 0),
    }


def normalize_order_money(order_data: dict[str, Any]) -> None:
    items = order_data.get("items", [])
    subtotal = sum(
        parse_float(item.get("quantity")) * parse_float(item.get("unit_price"))
        for item in items
        if item_is_billable(item)
    )
    order_data["discount"] = min(parse_float(order_data.get("discount")), subtotal)
    tax_rate = min(parse_float(order_data.get("tax_rate")), 100)
    order_data["tax_rate"] = tax_rate
    total = max(subtotal - order_data["discount"], 0) * (1 + tax_rate / 100)
    order_data["paid"] = min(parse_float(order_data.get("paid")), total)


def validate_order_item(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Позиция заказ-наряда должна быть JSON-объектом.")
    kind = clean_text(payload.get("kind"), 20, "service")
    if kind not in {"service", "part"}:
        raise ValueError("Некорректный тип позиции заказ-наряда.")
    inventory_id = parse_int_field(payload.get("inventory_id"), "складская позиция") if kind == "part" else None
    if inventory_id is not None and inventory_id <= 0:
        inventory_id = None
    title = clean_text(payload.get("title"), 220)
    unit_price = max(parse_float_field(payload.get("unit_price"), "цена позиции"), 0) if "unit_price" in payload else 0
    unit_cost = max(parse_float_field(payload.get("unit_cost"), "себестоимость позиции"), 0) if "unit_cost" in payload else 0
    approval_status = clean_text(payload.get("approval_status"), 30, "approved")
    if approval_status not in ITEM_APPROVAL_STATUSES:
        raise ValueError("Некорректный статус согласования позиции заказ-наряда.")

    if kind == "part" and inventory_id:
        part = conn.execute(
            "SELECT id, name, price, cost FROM inventory WHERE id = ? AND deleted_at IS NULL",
            (inventory_id,),
        ).fetchone()
        if not part:
            raise ValueError("Выбранная складская позиция не найдена.")
        if not title:
            title = str(part["name"])
        if unit_price == 0:
            unit_price = parse_float(part["price"])
        if unit_cost == 0:
            unit_cost = parse_float(part["cost"])
    elif kind == "service":
        inventory_id = None

    if not title:
        raise ValueError("Укажите наименование запчасти или работы.")

    quantity = max(parse_float_field(payload.get("quantity"), "количество позиции", 1), 0)
    if quantity <= 0:
        raise ValueError("Количество в позиции должно быть больше нуля.")

    return {
        "kind": kind,
        "inventory_id": inventory_id,
        "title": title,
        "approval_status": approval_status,
        "quantity": quantity,
        "unit_price": unit_price,
        "unit_cost": unit_cost,
    }


def item_is_billable(item: dict[str, Any]) -> bool:
    return str(item.get("approval_status") or "approved") in BILLABLE_ITEM_STATUSES


def active_exists(conn: sqlite3.Connection, table: str, record_id: int) -> bool:
    if table not in {"customers", "vehicles", "inventory", "orders", "appointments", "inspections"}:
        return False
    row = conn.execute(f"SELECT 1 FROM {table} WHERE id = ? AND deleted_at IS NULL", (record_id,)).fetchone()
    return row is not None


def ensure_unique_active_value(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    value: str,
    message: str,
    record_id: int | None = None,
) -> None:
    if not value:
        return
    allowed_columns = {
        ("inventory", "sku"),
        ("vehicles", "vin"),
        ("vehicles", "plate"),
    }
    if (table, column) not in allowed_columns:
        raise ValueError("Некорректная проверка уникальности.")
    query = f"SELECT id FROM {table} WHERE CASEFOLD({column}) = CASEFOLD(?) AND deleted_at IS NULL"
    params: list[Any] = [value]
    if record_id:
        query += " AND id <> ?"
        params.append(record_id)
    if conn.execute(query, params).fetchone():
        raise ValueError(message)


def ensure_vehicle_belongs_to_customer(
    conn: sqlite3.Connection,
    vehicle_id: int | None,
    customer_id: int,
    *,
    required: bool = False,
) -> int | None:
    if not vehicle_id:
        if required:
            raise ValueError("Выберите действующий автомобиль.")
        return None
    vehicle_owner = conn.execute(
        "SELECT customer_id FROM vehicles WHERE id = ? AND deleted_at IS NULL",
        (vehicle_id,),
    ).fetchone()
    if not vehicle_owner:
        raise ValueError("Выберите действующий автомобиль.")
    if int(vehicle_owner["customer_id"]) != customer_id:
        raise ValueError("Выбранный автомобиль принадлежит другому клиенту.")
    return vehicle_id


def ensure_no_appointment_conflict(
    conn: sqlite3.Connection,
    scheduled_at: str,
    duration_minutes: int,
    *,
    record_id: int | None = None,
) -> None:
    start = datetime.fromisoformat(scheduled_at)
    end = start + timedelta(minutes=duration_minutes)
    if end <= start:
        raise ValueError("Длительность записи должна быть больше нуля.")
    window_start = (start - timedelta(minutes=480)).isoformat(timespec="minutes")
    window_end = end.isoformat(timespec="minutes")

    rows = conn.execute(
        """
        SELECT a.id, a.scheduled_at, a.duration_minutes, c.name AS customer_name
        FROM appointments a
        JOIN customers c ON c.id = a.customer_id
        WHERE a.deleted_at IS NULL
          AND a.status IN ('scheduled', 'confirmed', 'arrived')
          AND a.scheduled_at >= ?
          AND a.scheduled_at < ?
          AND (? IS NULL OR a.id <> ?)
        """,
        (window_start, window_end, record_id, record_id),
    ).fetchall()
    for row in rows:
        try:
            existing_start = datetime.fromisoformat(str(row["scheduled_at"]))
        except ValueError:
            continue
        existing_end = existing_start + timedelta(minutes=max(parse_int(row["duration_minutes"], 60), 15))
        if start < existing_end and end > existing_start:
            when = existing_start.strftime("%d.%m.%Y %H:%M")
            raise ValueError(f"На это время уже есть запись: {row['customer_name']} в {when}.")


def active_appointment_count_for_customer(conn: sqlite3.Connection, customer_id: int) -> int:
    return int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM appointments
            WHERE customer_id = ?
              AND deleted_at IS NULL
              AND status IN ('scheduled', 'confirmed', 'arrived')
            """,
            (customer_id,),
        ).fetchone()[0]
    )


def active_appointment_count_for_vehicle(conn: sqlite3.Connection, vehicle_id: int) -> int:
    return int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM appointments
            WHERE vehicle_id = ?
              AND deleted_at IS NULL
              AND status IN ('scheduled', 'confirmed', 'arrived')
            """,
            (vehicle_id,),
        ).fetchone()[0]
    )


def create_customer(payload: dict[str, Any]) -> dict[str, Any]:
    data = validate_customer(payload)
    stamp = now_iso()
    with write_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO customers(name, phone, email, source, preferred_channel, reminder_consent, notes, created_at, updated_at)
            VALUES (:name, :phone, :email, :source, :preferred_channel, :reminder_consent, :notes, :created_at, :updated_at)
            """,
            {**data, "created_at": stamp, "updated_at": stamp},
        )
        return get_customer(conn, int(cur.lastrowid))


def update_customer(record_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    data = validate_customer(payload)
    with write_db() as conn:
        if not active_exists(conn, "customers", record_id):
            raise KeyError("Клиент не найден.")
        conn.execute(
            """
            UPDATE customers
            SET name=:name, phone=:phone, email=:email, source=:source, preferred_channel=:preferred_channel,
                reminder_consent=:reminder_consent, notes=:notes, updated_at=:updated_at
            WHERE id=:id AND deleted_at IS NULL
            """,
            {**data, "updated_at": now_iso(), "id": record_id},
        )
        return get_customer(conn, record_id)


def delete_customer(record_id: int) -> dict[str, Any]:
    with write_db() as conn:
        if not active_exists(conn, "customers", record_id):
            raise KeyError("Клиент не найден.")
        orders_count = conn.execute(
            """
            SELECT COUNT(*) FROM orders
            WHERE customer_id = ? AND deleted_at IS NULL
            """,
            (record_id,),
        ).fetchone()[0]
        if orders_count:
            raise ValueError("У клиента есть заказ-наряды. Сначала удалите или перенесите связанные заказы.")
        appointments_count = active_appointment_count_for_customer(conn, record_id)
        if appointments_count:
            raise ValueError("У клиента есть активные записи в календаре. Завершите или отмените их перед удалением клиента.")
        inspections_count = conn.execute(
            """
            SELECT COUNT(*) FROM inspections
            WHERE customer_id = ? AND deleted_at IS NULL
            """,
            (record_id,),
        ).fetchone()[0]
        if inspections_count:
            raise ValueError("У клиента есть цифровые осмотры. Сначала удалите или перенесите связанные осмотры.")
        stamp = now_iso()
        for vehicle in conn.execute(
            "SELECT id FROM vehicles WHERE customer_id = ? AND deleted_at IS NULL", (record_id,)
        ).fetchall():
            vid = vehicle["id"]
            if conn.execute(
                "SELECT COUNT(*) FROM orders WHERE vehicle_id = ? AND deleted_at IS NULL", (vid,)
            ).fetchone()[0]:
                raise ValueError("У клиента есть автомобили с заказ-нарядами. Сначала удалите или перенесите заказы.")
            if active_appointment_count_for_vehicle(conn, vid):
                raise ValueError("У клиента есть автомобили с активными записями в календаре. Завершите или отмените их перед удалением.")
        conn.execute("UPDATE customers SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL", (stamp, stamp, record_id))
        conn.execute("UPDATE vehicles SET deleted_at=?, updated_at=? WHERE customer_id=? AND deleted_at IS NULL", (stamp, stamp, record_id))
        return {"deleted": True}


def get_customer(conn: sqlite3.Connection, record_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM customers WHERE id = ? AND deleted_at IS NULL", (record_id,)).fetchone()
    if not row:
        raise KeyError("Клиент не найден.")
    return dict(row)


def create_vehicle(payload: dict[str, Any]) -> dict[str, Any]:
    with write_db() as conn:
        data = validate_vehicle(conn, payload)
        ensure_unique_active_value(conn, "vehicles", "vin", data["vin"], "Автомобиль с таким VIN уже есть в базе.")
        ensure_unique_active_value(conn, "vehicles", "plate", data["plate"], "Автомобиль с таким госномером уже есть в базе.")
        stamp = now_iso()
        cur = conn.execute(
            """
            INSERT INTO vehicles(customer_id, make, model, year, plate, vin, mileage, next_service_at,
                                 next_service_mileage, notes, created_at, updated_at)
            VALUES (:customer_id, :make, :model, :year, :plate, :vin, :mileage, :next_service_at,
                    :next_service_mileage, :notes, :created_at, :updated_at)
            """,
            {**data, "created_at": stamp, "updated_at": stamp},
        )
        return get_vehicle(conn, int(cur.lastrowid))


def update_vehicle(record_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    with write_db() as conn:
        try:
            old = conn.execute("SELECT customer_id FROM vehicles WHERE id = ? AND deleted_at IS NULL", (record_id,)).fetchone()
            if not old:
                raise KeyError("Автомобиль не найден.")
            data = validate_vehicle(conn, payload)
            ensure_unique_active_value(conn, "vehicles", "vin", data["vin"], "Автомобиль с таким VIN уже есть в базе.", record_id)
            ensure_unique_active_value(conn, "vehicles", "plate", data["plate"], "Автомобиль с таким госномером уже есть в базе.", record_id)
            if int(old["customer_id"]) != int(data["customer_id"]):
                orders_count = conn.execute(
                    "SELECT COUNT(*) FROM orders WHERE vehicle_id = ? AND deleted_at IS NULL",
                    (record_id,),
                ).fetchone()[0]
                if orders_count:
                    raise ValueError("Нельзя сменить клиента у автомобиля с заказ-нарядами.")
                if active_appointment_count_for_vehicle(conn, record_id):
                    raise ValueError("Нельзя сменить клиента у автомобиля с активными записями в календаре.")
                inspections_count = conn.execute(
                    "SELECT COUNT(*) FROM inspections WHERE vehicle_id = ? AND deleted_at IS NULL",
                    (record_id,),
                ).fetchone()[0]
                if inspections_count:
                    raise ValueError("Нельзя сменить клиента у автомобиля с цифровыми осмотрами.")
            conn.execute(
                """
                UPDATE vehicles
                SET customer_id=:customer_id, make=:make, model=:model, year=:year, plate=:plate,
                    vin=:vin, mileage=:mileage, next_service_at=:next_service_at,
                    next_service_mileage=:next_service_mileage, notes=:notes, updated_at=:updated_at
                WHERE id=:id AND deleted_at IS NULL
                """,
                {**data, "updated_at": now_iso(), "id": record_id},
            )
            vehicle = get_vehicle(conn, record_id)
            conn.execute("COMMIT")
            return vehicle
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise


def delete_vehicle(record_id: int) -> dict[str, Any]:
    with write_db() as conn:
        if not active_exists(conn, "vehicles", record_id):
            raise KeyError("Автомобиль не найден.")
        orders_count = conn.execute(
            """
            SELECT COUNT(*) FROM orders
            WHERE vehicle_id = ? AND deleted_at IS NULL
            """,
            (record_id,),
        ).fetchone()[0]
        if orders_count:
            raise ValueError("По автомобилю есть заказ-наряды. Сначала удалите или измените связанные заказы.")
        appointments_count = active_appointment_count_for_vehicle(conn, record_id)
        if appointments_count:
            raise ValueError("По автомобилю есть активные записи в календаре. Завершите или отмените их перед удалением автомобиля.")
        inspections_count = conn.execute(
            """
            SELECT COUNT(*) FROM inspections
            WHERE vehicle_id = ? AND deleted_at IS NULL
            """,
            (record_id,),
        ).fetchone()[0]
        if inspections_count:
            raise ValueError("По автомобилю есть цифровые осмотры. Сначала удалите или измените связанные осмотры.")
        stamp = now_iso()
        conn.execute("UPDATE vehicles SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL", (stamp, stamp, record_id))
        return {"deleted": True}


def get_vehicle(conn: sqlite3.Connection, record_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT v.*, c.name AS customer_name
        FROM vehicles v
        JOIN customers c ON c.id = v.customer_id
        WHERE v.id = ? AND v.deleted_at IS NULL
        """,
        (record_id,),
    ).fetchone()
    if not row:
        raise KeyError("Автомобиль не найден.")
    return dict(row)


def create_appointment(payload: dict[str, Any]) -> dict[str, Any]:
    with write_db() as conn:
        try:
            data = validate_appointment(conn, payload)
            if data["status"] in APPOINTMENT_ACTIVE_STATUSES:
                ensure_no_appointment_conflict(conn, data["scheduled_at"], data["duration_minutes"])
            stamp = now_iso()
            cur = conn.execute(
                """
                INSERT INTO appointments(customer_id, vehicle_id, scheduled_at, duration_minutes, status,
                                         advisor, reason, notes, created_at, updated_at)
                VALUES (:customer_id, :vehicle_id, :scheduled_at, :duration_minutes, :status,
                        :advisor, :reason, :notes, :created_at, :updated_at)
                """,
                {**data, "created_at": stamp, "updated_at": stamp},
            )
            appointment = get_appointment(conn, int(cur.lastrowid))
            conn.execute("COMMIT")
            return appointment
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise


def update_appointment(record_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    with write_db() as conn:
        try:
            if not active_exists(conn, "appointments", record_id):
                raise KeyError("Запись не найдена.")
            data = validate_appointment(conn, payload)
            if data["status"] in APPOINTMENT_ACTIVE_STATUSES:
                ensure_no_appointment_conflict(conn, data["scheduled_at"], data["duration_minutes"], record_id=record_id)
            conn.execute(
                """
                UPDATE appointments
                SET customer_id=:customer_id, vehicle_id=:vehicle_id, scheduled_at=:scheduled_at,
                    duration_minutes=:duration_minutes, status=:status, advisor=:advisor,
                    reason=:reason, notes=:notes, updated_at=:updated_at
                WHERE id=:id AND deleted_at IS NULL
                """,
                {**data, "updated_at": now_iso(), "id": record_id},
            )
            appointment = get_appointment(conn, record_id)
            conn.execute("COMMIT")
            return appointment
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise


def delete_appointment(record_id: int) -> dict[str, Any]:
    with write_db() as conn:
        if not active_exists(conn, "appointments", record_id):
            raise KeyError("Запись не найдена.")
        stamp = now_iso()
        conn.execute("UPDATE appointments SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL", (stamp, stamp, record_id))
        return {"deleted": True}


def get_appointment(conn: sqlite3.Connection, record_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT a.*, c.name AS customer_name, c.phone AS customer_phone,
               v.make AS vehicle_make, v.model AS vehicle_model, v.year AS vehicle_year,
               v.plate AS vehicle_plate, v.vin AS vehicle_vin
        FROM appointments a
        JOIN customers c ON c.id = a.customer_id
        LEFT JOIN vehicles v ON v.id = a.vehicle_id
        WHERE a.id = ? AND a.deleted_at IS NULL AND c.deleted_at IS NULL
        """,
        (record_id,),
    ).fetchone()
    if not row:
        raise KeyError("Запись не найдена.")
    return dict(row)


def create_inspection(payload: dict[str, Any]) -> dict[str, Any]:
    with write_db() as conn:
        try:
            data = validate_inspection(conn, payload)
            stamp = now_iso()
            cur = conn.execute(
                """
                INSERT INTO inspections(customer_id, vehicle_id, order_id, status, inspector, inspected_at,
                                        summary, created_at, updated_at)
                VALUES (:customer_id, :vehicle_id, :order_id, :status, :inspector, :inspected_at,
                        :summary, :created_at, :updated_at)
                """,
                {**{k: v for k, v in data.items() if k != "items"}, "created_at": stamp, "updated_at": stamp},
            )
            inspection_id = int(cur.lastrowid)
            insert_inspection_items(conn, inspection_id, data["items"])
            conn.execute("COMMIT")
            return get_inspection(conn, inspection_id)
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise


def update_inspection(record_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    with write_db() as conn:
        try:
            if not active_exists(conn, "inspections", record_id):
                raise KeyError("Осмотр не найден.")
            data = validate_inspection(conn, payload)
            conn.execute(
                """
                UPDATE inspections
                SET customer_id=:customer_id, vehicle_id=:vehicle_id, order_id=:order_id,
                    status=:status, inspector=:inspector, inspected_at=:inspected_at,
                    summary=:summary, updated_at=:updated_at
                WHERE id=:id AND deleted_at IS NULL
                """,
                {**{k: v for k, v in data.items() if k != "items"}, "updated_at": now_iso(), "id": record_id},
            )
            conn.execute("DELETE FROM inspection_items WHERE inspection_id=?", (record_id,))
            insert_inspection_items(conn, record_id, data["items"])
            conn.execute("COMMIT")
            return get_inspection(conn, record_id)
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise


def delete_inspection(record_id: int) -> dict[str, Any]:
    with write_db() as conn:
        if not active_exists(conn, "inspections", record_id):
            raise KeyError("Осмотр не найден.")
        stamp = now_iso()
        conn.execute("UPDATE inspections SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL", (stamp, stamp, record_id))
        return {"deleted": True}


def insert_inspection_items(conn: sqlite3.Connection, inspection_id: int, items: list[dict[str, Any]]) -> None:
    stamp = now_iso()
    conn.executemany(
        """
        INSERT INTO inspection_items(inspection_id, area, title, condition_status, approval_status,
                                     recommendation, estimate, created_at)
        VALUES (:inspection_id, :area, :title, :condition_status, :approval_status,
                :recommendation, :estimate, :created_at)
        """,
        [{**item, "inspection_id": inspection_id, "created_at": stamp} for item in items],
    )


def list_inspection_items(conn: sqlite3.Connection, inspection_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM inspection_items
        WHERE inspection_id=?
        ORDER BY id
        """,
        (inspection_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_inspection(conn: sqlite3.Connection, record_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT i.*, c.name AS customer_name, c.phone AS customer_phone,
               v.make AS vehicle_make, v.model AS vehicle_model, v.year AS vehicle_year,
               v.plate AS vehicle_plate, v.vin AS vehicle_vin,
               o.number AS order_number
        FROM inspections i
        JOIN customers c ON c.id = i.customer_id
        LEFT JOIN vehicles v ON v.id = i.vehicle_id
        LEFT JOIN orders o ON o.id = i.order_id
        WHERE i.id = ? AND i.deleted_at IS NULL AND c.deleted_at IS NULL
        """,
        (record_id,),
    ).fetchone()
    if not row:
        raise KeyError("Осмотр не найден.")
    inspection = dict(row)
    inspection["items"] = list_inspection_items(conn, record_id)
    inspection.update(inspection_totals(inspection["items"]))
    return inspection


def create_inventory(payload: dict[str, Any]) -> dict[str, Any]:
    data = validate_inventory(payload)
    stamp = now_iso()
    with write_db() as conn:
        ensure_unique_active_value(conn, "inventory", "sku", data["sku"], "Складская позиция с таким артикулом уже есть в базе.")
        cur = conn.execute(
            """
            INSERT INTO inventory(sku, name, brand, unit, quantity, min_quantity, price, cost, supplier, notes, created_at, updated_at)
            VALUES (:sku, :name, :brand, :unit, :quantity, :min_quantity, :price, :cost, :supplier, :notes, :created_at, :updated_at)
            """,
            {**data, "created_at": stamp, "updated_at": stamp},
        )
        return get_inventory(conn, int(cur.lastrowid))


def update_inventory(record_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    data = validate_inventory(payload)
    with write_db() as conn:
        ensure_unique_active_value(conn, "inventory", "sku", data["sku"], "Складская позиция с таким артикулом уже есть в базе.", record_id)
        current = get_inventory(conn, record_id)
        if not current:
            raise KeyError("Складская позиция не найдена.")
        has_closed_history = conn.execute(
            """
            SELECT 1
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            WHERE oi.inventory_id = ?
              AND oi.approval_status IN ('approved')
              AND o.status = 'closed'
              AND o.deleted_at IS NULL
            LIMIT 1
            """,
            (record_id,),
        ).fetchone()
        if has_closed_history and abs(parse_float(data["quantity"]) - parse_float(current["quantity"])) > 0.000001:
            raise ValueError(
                "Остаток позиции участвует в закрытых заказах. Создайте отдельную складскую корректировку или отмените связанный закрытый заказ без изменения его позиций."
            )
        conn.execute(
            """
            UPDATE inventory
            SET sku=:sku, name=:name, brand=:brand, unit=:unit, quantity=:quantity, min_quantity=:min_quantity,
                price=:price, cost=:cost, supplier=:supplier, notes=:notes, updated_at=:updated_at
            WHERE id=:id AND deleted_at IS NULL
            """,
            {**data, "updated_at": now_iso(), "id": record_id},
        )
        return get_inventory(conn, record_id)


def delete_inventory(record_id: int) -> dict[str, Any]:
    with write_db() as conn:
        if not active_exists(conn, "inventory", record_id):
            raise KeyError("Складская позиция не найдена.")
        order_usage = conn.execute(
            """
            SELECT COUNT(*)
            FROM order_items oi
            JOIN orders o ON o.id = oi.order_id
            WHERE oi.inventory_id = ? AND o.deleted_at IS NULL
            """,
            (record_id,),
        ).fetchone()[0]
        if order_usage:
            raise ValueError("Позиция используется в заказ-нарядах. Сначала удалите или измените связанные заказы.")
        stamp = now_iso()
        conn.execute("UPDATE inventory SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL", (stamp, stamp, record_id))
        return {"deleted": True}


def get_inventory(conn: sqlite3.Connection, record_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM inventory WHERE id = ? AND deleted_at IS NULL", (record_id,)).fetchone()
    if not row:
        raise KeyError("Складская позиция не найдена.")
    return dict(row)


def create_order(payload: dict[str, Any]) -> dict[str, Any]:
    with write_db() as conn:
        try:
            order_id = create_order_tx(conn, payload)
            conn.execute("COMMIT")
            return get_order(conn, order_id)
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise


def create_order_tx(conn: sqlite3.Connection, payload: dict[str, Any]) -> int:
    data = validate_order(conn, payload)
    stamp = now_iso()
    number = generate_order_number(conn)
    if data["status"] == "closed" and not data["follow_up_at"]:
        data["follow_up_at"] = (datetime.now() + timedelta(days=1)).replace(microsecond=0).isoformat(timespec="minutes")
    apply_inventory_delta(conn, "", data["status"], [], data["items"])
    cur = conn.execute(
        """
        INSERT INTO orders(number, customer_id, vehicle_id, status, priority, advisor, mechanic, promised_at,
                           odometer, complaint, diagnosis, recommendations, discount, tax_rate, paid,
                           payment_method, authorized_by, authorized_at, follow_up_at, closed_at, created_at, updated_at)
        VALUES (:number, :customer_id, :vehicle_id, :status, :priority, :advisor, :mechanic, :promised_at,
                :odometer, :complaint, :diagnosis, :recommendations, :discount, :tax_rate, :paid,
                :payment_method, :authorized_by, :authorized_at, :follow_up_at, :closed_at, :created_at, :updated_at)
        """,
        {
            **{k: v for k, v in data.items() if k != "items"},
            "number": number,
            "closed_at": stamp if data["status"] == "closed" else "",
            "created_at": stamp,
            "updated_at": stamp,
        },
    )
    order_id = int(cur.lastrowid)
    insert_order_items(conn, order_id, data["items"])
    return order_id


def update_order(record_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    with write_db() as conn:
        try:
            old = conn.execute("SELECT * FROM orders WHERE id=? AND deleted_at IS NULL", (record_id,)).fetchone()
            if not old:
                raise KeyError("Заказ-наряд не найден.")
            old_items = list_order_items(conn, record_id)
            data = validate_order(conn, payload)
            old_status = str(old["status"])
            new_status = data["status"]
            if old_status == "closed":
                ensure_closed_order_not_changed(old, old_items, data)
            closed_at = compute_closed_at(old_status, str(old["closed_at"] or ""), new_status)
            if data["status"] == "closed" and not data["follow_up_at"]:
                data["follow_up_at"] = str(old["follow_up_at"] or "") or (datetime.now() + timedelta(days=1)).replace(microsecond=0).isoformat(timespec="minutes")
            apply_inventory_delta(conn, old_status, new_status, old_items, data["items"])
            conn.execute(
                """
                UPDATE orders
                SET customer_id=:customer_id, vehicle_id=:vehicle_id, status=:status, priority=:priority,
                    advisor=:advisor, mechanic=:mechanic, promised_at=:promised_at, odometer=:odometer,
                    complaint=:complaint, diagnosis=:diagnosis, recommendations=:recommendations,
                    discount=:discount, tax_rate=:tax_rate, paid=:paid, payment_method=:payment_method,
                    authorized_by=:authorized_by, authorized_at=:authorized_at, follow_up_at=:follow_up_at,
                    closed_at=:closed_at, updated_at=:updated_at
                WHERE id=:id AND deleted_at IS NULL
                """,
                {
                    **{k: v for k, v in data.items() if k != "items"},
                    "closed_at": closed_at,
                    "updated_at": now_iso(),
                    "id": record_id,
                },
            )
            conn.execute("DELETE FROM order_items WHERE order_id=?", (record_id,))
            insert_order_items(conn, record_id, data["items"])
            conn.execute("COMMIT")
            return get_order(conn, record_id)
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise


def compute_closed_at(old_status: str, old_closed_at: str, new_status: str) -> str:
    if new_status != "closed":
        return ""
    if old_status == "closed" and old_closed_at:
        return old_closed_at
    return now_iso()


def delete_order(record_id: int) -> dict[str, Any]:
    with write_db() as conn:
        try:
            old = conn.execute("SELECT * FROM orders WHERE id=? AND deleted_at IS NULL", (record_id,)).fetchone()
            if not old:
                raise KeyError("Заказ-наряд не найден.")
            if str(old["status"]) in CONSUMING_STATUSES:
                raise ValueError(
                    "Закрытый заказ-наряд сначала переведите в статус «Отменен», "
                    "чтобы возврат складских остатков был явным."
                )
            linked_inspections_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM inspections
                WHERE order_id = ? AND deleted_at IS NULL
                """,
                (record_id,),
            ).fetchone()[0]
            if linked_inspections_count:
                raise ValueError("К заказ-наряду привязаны цифровые осмотры. Сначала удалите или отвяжите связанные осмотры.")
            old_items = list_order_items(conn, record_id)
            apply_inventory_delta(conn, str(old["status"]), "", old_items, [])
            stamp = now_iso()
            conn.execute("UPDATE orders SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL", (stamp, stamp, record_id))
            conn.execute("COMMIT")
            return {"deleted": True}
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise


def insert_order_items(conn: sqlite3.Connection, order_id: int, items: list[dict[str, Any]]) -> None:
    stamp = now_iso()
    conn.executemany(
        """
        INSERT INTO order_items(order_id, kind, inventory_id, title, approval_status, quantity, unit_price, unit_cost, created_at)
        VALUES (:order_id, :kind, :inventory_id, :title, :approval_status, :quantity, :unit_price, :unit_cost, :created_at)
        """,
        [{**item, "order_id": order_id, "created_at": stamp} for item in items],
    )


def list_order_items(conn: sqlite3.Connection, order_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT oi.*, i.sku AS inventory_sku, i.name AS inventory_name
        FROM order_items oi
        LEFT JOIN inventory i ON i.id = oi.inventory_id
        WHERE oi.order_id=?
        ORDER BY oi.id
        """,
        (order_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def part_quantities(items: list[dict[str, Any]]) -> dict[int, float]:
    result: dict[int, float] = defaultdict(float)
    for item in items:
        if item.get("kind") == "part" and item.get("inventory_id") and item_is_billable(item):
            result[int(item["inventory_id"])] += parse_float(item.get("quantity"))
    return dict(result)


def closed_item_signature(item: dict[str, Any]) -> tuple[Any, ...]:
    """Стабильный финансовый снимок строки закрытого заказ-наряда."""
    return (
        str(item.get("kind") or ""),
        int(item.get("inventory_id") or 0),
        str(item.get("title") or ""),
        str(item.get("approval_status") or "approved"),
        round(parse_float(item.get("quantity")), 6),
        round(parse_float(item.get("unit_price")), 2),
        round(parse_float(item.get("unit_cost")), 2),
    )


def closed_order_signature(order: dict[str, Any] | sqlite3.Row, items: list[dict[str, Any]]) -> tuple[Any, ...]:
    return (
        str(order["status"]),
        int(order["customer_id"]),
        int(order["vehicle_id"] or 0),
        str(order["priority"] or ""),
        str(order["advisor"] or ""),
        str(order["mechanic"] or ""),
        str(order["promised_at"] or ""),
        int(parse_int(order["odometer"])),
        str(order["complaint"] or ""),
        str(order["diagnosis"] or ""),
        str(order["recommendations"] or ""),
        round(parse_float(order["discount"]), 2),
        round(parse_float(order["tax_rate"]), 4),
        round(parse_float(order["paid"]), 2),
        str(order["payment_method"] or ""),
        str(order["authorized_by"] or ""),
        str(order["authorized_at"] or ""),
        tuple(closed_item_signature(item) for item in items),
    )


def ensure_closed_order_not_changed(old: sqlite3.Row, old_items: list[dict[str, Any]], data: dict[str, Any]) -> None:
    if int(old["customer_id"]) != data["customer_id"] or (old["vehicle_id"] or None) != data["vehicle_id"]:
        raise ValueError("Закрытый заказ нельзя перепривязать к другому клиенту или автомобилю.")
    if data["status"] not in {"closed", "cancelled"}:
        raise ValueError("Закрытый заказ можно только оставить закрытым или отменить без изменения финансовых данных.")
    comparable_data = {k: v for k, v in data.items() if k != "items"}
    if data["status"] == "cancelled":
        comparable_data["status"] = "closed"
    if closed_order_signature(old, old_items) != closed_order_signature(comparable_data, data["items"]):
        if data["status"] == "cancelled":
            raise ValueError("При отмене закрытого заказа нельзя менять финансовые данные и позиции.")
        raise ValueError("Финансовые данные и позиции закрытого заказа нельзя изменить после закрытия. Создайте отдельный корректирующий заказ.")


def apply_inventory_delta(
    conn: sqlite3.Connection,
    old_status: str,
    new_status: str,
    old_items: list[dict[str, Any]],
    new_items: list[dict[str, Any]],
) -> None:
    old_consumed = part_quantities(old_items) if old_status in CONSUMING_STATUSES else {}
    new_consumed = part_quantities(new_items) if new_status in CONSUMING_STATUSES else {}
    all_part_ids = sorted(set(old_consumed) | set(new_consumed))
    for part_id in all_part_ids:
        delta = new_consumed.get(part_id, 0.0) - old_consumed.get(part_id, 0.0)
        if abs(delta) < 0.000001:
            continue
        part = conn.execute("SELECT id, name, quantity, deleted_at FROM inventory WHERE id=?", (part_id,)).fetchone()
        if not part:
            raise ValueError("Складская позиция для списания не найдена.")
        if delta > 0 and part["deleted_at"]:
            raise ValueError(f"Складская позиция недоступна для списания: {part['name']}.")
        current_qty = parse_float(part["quantity"])
        if delta > 0 and current_qty + 0.000001 < delta:
            raise ValueError(f"Недостаточно на складе: {part['name']}. Доступно {current_qty:g}, требуется {delta:g}.")
        conn.execute(
            "UPDATE inventory SET quantity = quantity - ?, updated_at = ? WHERE id = ?",
            (delta, now_iso(), part_id),
        )


def list_customers(q: str = "", limit: int | None = 1000) -> list[dict[str, Any]]:
    with db() as conn:
        params: list[Any] = []
        where = "WHERE c.deleted_at IS NULL"
        if q:
            where += " AND (CASEFOLD(c.name) LIKE ? OR CASEFOLD(c.phone) LIKE ? OR CASEFOLD(c.email) LIKE ?)"
            needle = search_needle(q)
            params.extend([needle, needle, needle])
        limit_sql, limit_params = sql_limit(limit)
        params.extend(limit_params)
        rows = conn.execute(
            f"""
            SELECT c.*,
                   COUNT(DISTINCT v.id) AS vehicles_count,
                   COUNT(DISTINCT o.id) AS orders_count,
                   MAX(o.updated_at) AS last_order_at
            FROM customers c
            LEFT JOIN vehicles v ON v.customer_id = c.id AND v.deleted_at IS NULL
            LEFT JOIN orders o ON o.customer_id = c.id AND o.deleted_at IS NULL
            {where}
            GROUP BY c.id
            ORDER BY c.updated_at DESC, c.id DESC
            {limit_sql}
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]


def list_vehicles(q: str = "", limit: int | None = 1000) -> list[dict[str, Any]]:
    with db() as conn:
        params: list[Any] = []
        where = "WHERE v.deleted_at IS NULL AND c.deleted_at IS NULL"
        if q:
            where += """
                AND (CASEFOLD(v.make) LIKE ? OR CASEFOLD(v.model) LIKE ? OR CASEFOLD(v.plate) LIKE ?
                     OR CASEFOLD(v.vin) LIKE ? OR CASEFOLD(c.name) LIKE ?)
            """
            needle = search_needle(q)
            params.extend([needle, needle, needle, needle, needle])
        limit_sql, limit_params = sql_limit(limit)
        params.extend(limit_params)
        rows = conn.execute(
            f"""
            SELECT v.*, c.name AS customer_name, c.phone AS customer_phone,
                   c.preferred_channel AS customer_preferred_channel,
                   c.reminder_consent AS customer_reminder_consent
            FROM vehicles v
            JOIN customers c ON c.id = v.customer_id
            {where}
            ORDER BY v.updated_at DESC, v.id DESC
            {limit_sql}
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]


def list_inventory(q: str = "", limit: int | None = 1000) -> list[dict[str, Any]]:
    with db() as conn:
        params: list[Any] = []
        where = "WHERE deleted_at IS NULL"
        if q:
            where += " AND (CASEFOLD(sku) LIKE ? OR CASEFOLD(name) LIKE ? OR CASEFOLD(brand) LIKE ? OR CASEFOLD(supplier) LIKE ?)"
            needle = search_needle(q)
            params.extend([needle, needle, needle, needle])
        limit_sql, limit_params = sql_limit(limit)
        params.extend(limit_params)
        rows = conn.execute(
            f"""
            SELECT *,
                   CASE WHEN quantity <= min_quantity THEN 1 ELSE 0 END AS is_low
            FROM inventory
            {where}
            ORDER BY is_low DESC, updated_at DESC, id DESC
            {limit_sql}
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]


def list_appointments(q: str = "", status: str = "all", limit: int | None = 1000) -> list[dict[str, Any]]:
    if status not in {"all", *APPOINTMENT_STATUSES}:
        raise ValueError("Некорректный статус записи.")
    with db() as conn:
        params: list[Any] = []
        where = "WHERE a.deleted_at IS NULL"
        if status and status != "all":
            where += " AND a.status = ?"
            params.append(status)
        if q:
            where += """
                AND (CASEFOLD(c.name) LIKE ? OR CASEFOLD(c.phone) LIKE ? OR CASEFOLD(c.email) LIKE ?
                     OR CASEFOLD(v.plate) LIKE ? OR CASEFOLD(v.vin) LIKE ? OR CASEFOLD(v.make) LIKE ?
                     OR CASEFOLD(v.model) LIKE ? OR CASEFOLD(a.reason) LIKE ? OR CASEFOLD(a.advisor) LIKE ?)
            """
            needle = search_needle(q)
            params.extend([needle, needle, needle, needle, needle, needle, needle, needle, needle])
        limit_sql, limit_params = sql_limit(limit)
        params.extend(limit_params)
        rows = conn.execute(
            f"""
            SELECT a.*, c.name AS customer_name, c.phone AS customer_phone,
                   v.make AS vehicle_make, v.model AS vehicle_model, v.year AS vehicle_year,
                   v.plate AS vehicle_plate, v.vin AS vehicle_vin
            FROM appointments a
            JOIN customers c ON c.id = a.customer_id
            LEFT JOIN vehicles v ON v.id = a.vehicle_id
            {where}
            ORDER BY
                CASE WHEN a.status IN ('done', 'no_show', 'cancelled') THEN 1 ELSE 0 END,
                a.scheduled_at,
                a.id
            {limit_sql}
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]


def list_inspections(q: str = "", status: str = "all", limit: int | None = 1000) -> list[dict[str, Any]]:
    if status not in {"all", *INSPECTION_STATUSES}:
        raise ValueError("Некорректный статус осмотра.")
    with db() as conn:
        params: list[Any] = []
        where = "WHERE i.deleted_at IS NULL AND c.deleted_at IS NULL"
        if status and status != "all":
            where += " AND i.status = ?"
            params.append(status)
        if q:
            where += """
                AND (CASEFOLD(c.name) LIKE ? OR CASEFOLD(c.phone) LIKE ? OR CASEFOLD(v.plate) LIKE ?
                     OR CASEFOLD(v.vin) LIKE ? OR CASEFOLD(v.make) LIKE ? OR CASEFOLD(v.model) LIKE ?
                     OR CASEFOLD(o.number) LIKE ? OR CASEFOLD(i.inspector) LIKE ? OR CASEFOLD(i.summary) LIKE ?)
            """
            needle = search_needle(q)
            params.extend([needle, needle, needle, needle, needle, needle, needle, needle, needle])
        limit_sql, limit_params = sql_limit(limit)
        params.extend(limit_params)
        rows = conn.execute(
            f"""
            SELECT i.*, c.name AS customer_name, c.phone AS customer_phone,
                   v.make AS vehicle_make, v.model AS vehicle_model, v.year AS vehicle_year,
                   v.plate AS vehicle_plate, v.vin AS vehicle_vin,
                   o.number AS order_number
            FROM inspections i
            JOIN customers c ON c.id = i.customer_id
            LEFT JOIN vehicles v ON v.id = i.vehicle_id
            LEFT JOIN orders o ON o.id = i.order_id
            {where}
            ORDER BY i.inspected_at DESC, i.updated_at DESC, i.id DESC
            {limit_sql}
            """,
            params,
        ).fetchall()
        inspections = [dict(row) for row in rows]
        attach_inspection_items_and_totals(conn, inspections)
        return inspections


def attach_inspection_items_and_totals(conn: sqlite3.Connection, inspections: list[dict[str, Any]]) -> None:
    if not inspections:
        return
    inspection_ids = [int(inspection["id"]) for inspection in inspections]
    placeholders = ",".join("?" for _ in inspection_ids)
    rows = conn.execute(
        f"""
        SELECT *
        FROM inspection_items
        WHERE inspection_id IN ({placeholders})
        ORDER BY id
        """,
        inspection_ids,
    ).fetchall()
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[int(row["inspection_id"])].append(dict(row))
    for inspection in inspections:
        items = grouped.get(int(inspection["id"]), [])
        inspection["items"] = items
        inspection.update(inspection_totals(items))


def inspection_totals(items: list[dict[str, Any]]) -> dict[str, Any]:
    attention_count = sum(1 for item in items if item.get("condition_status") == "attention")
    critical_count = sum(1 for item in items if item.get("condition_status") == "critical")
    recommended_total = sum(
        parse_float(item.get("estimate"))
        for item in items
        if str(item.get("condition_status")) in {"attention", "critical"}
        and str(item.get("approval_status") or "deferred") != "approved"
    )
    return {
        "items_count": len(items),
        "attention_count": attention_count,
        "critical_count": critical_count,
        "recommended_total": round(recommended_total, 2),
    }


def list_orders(q: str = "", status: str = "", limit: int | None = 1000) -> list[dict[str, Any]]:
    with db() as conn:
        params: list[Any] = []
        where = "WHERE o.deleted_at IS NULL"
        if status and status != "all":
            where += " AND o.status = ?"
            params.append(status)
        if q:
            where += """
                AND (CASEFOLD(o.number) LIKE ? OR CASEFOLD(c.name) LIKE ? OR CASEFOLD(c.phone) LIKE ?
                     OR CASEFOLD(c.email) LIKE ? OR CASEFOLD(v.plate) LIKE ? OR CASEFOLD(v.vin) LIKE ?
                     OR CASEFOLD(v.make) LIKE ? OR CASEFOLD(v.model) LIKE ? OR CASEFOLD(o.complaint) LIKE ?)
            """
            needle = search_needle(q)
            params.extend([needle, needle, needle, needle, needle, needle, needle, needle, needle])
        limit_sql, limit_params = sql_limit(limit)
        params.extend(limit_params)
        rows = conn.execute(
            f"""
            SELECT o.*, c.name AS customer_name, c.phone AS customer_phone,
                   v.make AS vehicle_make, v.model AS vehicle_model, v.year AS vehicle_year,
                   v.plate AS vehicle_plate, v.vin AS vehicle_vin
            FROM orders o
            JOIN customers c ON c.id = o.customer_id
            LEFT JOIN vehicles v ON v.id = o.vehicle_id
            {where}
            ORDER BY
                CASE
                    WHEN o.status IN ('closed', 'cancelled') THEN 1
                    ELSE 0
                END,
                CASE o.priority
                    WHEN 'urgent' THEN 0
                    WHEN 'high' THEN 1
                    WHEN 'normal' THEN 2
                    WHEN 'low' THEN 3
                    ELSE 4
                END,
                CASE o.status
                    WHEN 'new' THEN 1
                    WHEN 'diagnostics' THEN 2
                    WHEN 'estimate' THEN 3
                    WHEN 'approved' THEN 4
                    WHEN 'in_progress' THEN 5
                    WHEN 'done' THEN 6
                    WHEN 'closed' THEN 7
                    ELSE 8
                END,
                o.updated_at DESC,
                o.id DESC
            {limit_sql}
            """,
            params,
        ).fetchall()
        orders = [dict(row) for row in rows]
        attach_items_and_totals(conn, orders)
        return orders


def get_order(conn: sqlite3.Connection, record_id: int) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT o.*, c.name AS customer_name, c.phone AS customer_phone, c.email AS customer_email,
               v.make AS vehicle_make, v.model AS vehicle_model, v.year AS vehicle_year,
               v.plate AS vehicle_plate, v.vin AS vehicle_vin, v.mileage AS vehicle_mileage
        FROM orders o
        JOIN customers c ON c.id = o.customer_id
        LEFT JOIN vehicles v ON v.id = o.vehicle_id
        WHERE o.id = ? AND o.deleted_at IS NULL
        """,
        (record_id,),
    ).fetchone()
    if not row:
        raise KeyError("Заказ-наряд не найден.")
    order = dict(row)
    order["items"] = list_order_items(conn, record_id)
    order.update(calculate_totals(order, order["items"]))
    return order


def attach_items_and_totals(conn: sqlite3.Connection, orders: list[dict[str, Any]]) -> None:
    if not orders:
        return
    order_ids = [int(order["id"]) for order in orders]
    placeholders = ",".join("?" for _ in order_ids)
    rows = conn.execute(
        f"""
        SELECT oi.*, i.sku AS inventory_sku, i.name AS inventory_name
        FROM order_items oi
        LEFT JOIN inventory i ON i.id = oi.inventory_id
        WHERE oi.order_id IN ({placeholders})
        ORDER BY oi.id
        """,
        order_ids,
    ).fetchall()
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[int(row["order_id"])].append(dict(row))
    for order in orders:
        items = grouped.get(int(order["id"]), [])
        order["items"] = items
        order.update(calculate_totals(order, items))


def calculate_totals(order: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, float]:
    billable_items = [item for item in items if item_is_billable(item)]
    service_total = sum(parse_float(i.get("quantity")) * parse_float(i.get("unit_price")) for i in billable_items if i.get("kind") == "service")
    parts_total = sum(parse_float(i.get("quantity")) * parse_float(i.get("unit_price")) for i in billable_items if i.get("kind") == "part")
    cost_total = sum(parse_float(i.get("quantity")) * parse_float(i.get("unit_cost")) for i in billable_items)
    subtotal = service_total + parts_total
    discount = min(max(parse_float(order.get("discount")), 0), subtotal)
    taxable = max(subtotal - discount, 0)
    tax_rate = min(max(parse_float(order.get("tax_rate")), 0), 100)
    tax = taxable * tax_rate / 100
    total = taxable + tax
    paid = min(max(parse_float(order.get("paid")), 0), total)
    due = max(total - paid, 0)
    gross_margin = total - cost_total
    margin_percent = (gross_margin / total * 100) if total else 0
    return {
        "service_total": round(service_total, 2),
        "parts_total": round(parts_total, 2),
        "cost_total": round(cost_total, 2),
        "subtotal": round(subtotal, 2),
        "tax": round(tax, 2),
        "total": round(total, 2),
        "paid": round(paid, 2),
        "due": round(due, 2),
        "margin": round(gross_margin, 2),
        "margin_percent": round(margin_percent, 1),
    }


def build_reports(
    orders: list[dict[str, Any]],
    inventory: list[dict[str, Any]],
    vehicles: list[dict[str, Any]],
    appointments: list[dict[str, Any]],
    inspections: list[dict[str, Any]],
) -> dict[str, Any]:
    now = datetime.now()
    today = now.date()
    month_prefix = now.strftime("%Y-%m")
    active_statuses = {"new", "diagnostics", "estimate", "approved", "in_progress", "done"}
    active_orders = [o for o in orders if o.get("status") in active_statuses]

    def parse_local_datetime(value: Any) -> datetime | None:
        text = str(value or "").strip().replace(" ", "T")
        if not text:
            return None
        try:
            return datetime.fromisoformat(text[:16])
        except ValueError:
            return None

    def summarize_order(order: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": order.get("id"),
            "number": order.get("number"),
            "status": order.get("status"),
            "priority": order.get("priority"),
            "customer_id": order.get("customer_id"),
            "customer_name": order.get("customer_name"),
            "customer_phone": order.get("customer_phone"),
            "vehicle": orderVehicleText(order),
            "promised_at": order.get("promised_at"),
            "advisor": order.get("advisor"),
            "mechanic": order.get("mechanic"),
            "total": round(parse_float(order.get("total")), 2),
            "due": round(parse_float(order.get("due")), 2),
            "margin": round(parse_float(order.get("margin")), 2),
            "updated_at": order.get("updated_at"),
        }
    month_closed = [o for o in orders if str(o.get("closed_at", "")).startswith(month_prefix) and o.get("status") == "closed"]
    revenue_month = sum(parse_float(o.get("total")) for o in month_closed)
    gross_margin_month = sum(parse_float(o.get("margin")) for o in month_closed)
    margin_percent_month = (gross_margin_month / revenue_month * 100) if revenue_month else 0
    due_total = sum(parse_float(o.get("due")) for o in orders if o.get("status") != "cancelled")
    avg_check = revenue_month / len(month_closed) if month_closed else 0
    conversion_base = [o for o in orders if o.get("status") in {"estimate", "approved", "in_progress", "done", "closed"}]
    conversion_won = [o for o in conversion_base if o.get("status") in {"approved", "in_progress", "done", "closed"}]
    conversion_rate = (len(conversion_won) / len(conversion_base) * 100) if conversion_base else 0
    pipeline_value = sum(parse_float(o.get("total")) for o in active_orders)
    pipeline_due = sum(parse_float(o.get("due")) for o in active_orders)
    status_counts = {status: 0 for status in ORDER_STATUSES}
    for order in orders:
        status_counts[str(order.get("status"))] = status_counts.get(str(order.get("status")), 0) + 1
    low_stock = [p for p in inventory if parse_float(p.get("quantity")) <= parse_float(p.get("min_quantity"))]
    inventory_value = sum(parse_float(p.get("quantity")) * parse_float(p.get("cost")) for p in inventory)
    promised_today = []
    overdue_orders = []
    for order in active_orders:
        promised_at = str(order.get("promised_at") or "")
        promised_dt = parse_local_datetime(promised_at)
        if promised_at.startswith(today.isoformat()):
            promised_today.append(order)
        if promised_dt and promised_dt < now:
            overdue_orders.append(order)
    reminder_horizon = today + timedelta(days=14)
    service_reminders = []
    for vehicle in vehicles:
        if parse_int(vehicle.get("customer_reminder_consent"), 1) == 0:
            continue
        next_service_at = str(vehicle.get("next_service_at") or "")
        next_service_mileage = parse_int(vehicle.get("next_service_mileage"))
        mileage = parse_int(vehicle.get("mileage"))
        due_by_date = False
        if next_service_at:
            try:
                due_by_date = datetime.fromisoformat(next_service_at[:10]).date() <= reminder_horizon
            except ValueError:
                due_by_date = False
        due_by_mileage = bool(next_service_mileage and mileage and next_service_mileage <= mileage + 500)
        if due_by_date or due_by_mileage:
            service_reminders.append({**vehicle, "due_by_date": due_by_date, "due_by_mileage": due_by_mileage})
    followups_due = []
    for order in orders:
        follow_up_at = str(order.get("follow_up_at") or "")
        if order.get("status") != "closed" or not follow_up_at:
            continue
        try:
            if datetime.fromisoformat(follow_up_at[:10]).date() <= today:
                followups_due.append(order)
        except ValueError:
            continue
    authorizations_pending = [order for order in orders if order.get("status") == "estimate" and not order.get("authorized_at")]
    deferred_work = []
    for order in orders:
        if order.get("status") == "cancelled":
            continue
        for item in order.get("items", []):
            approval_status = str(item.get("approval_status") or "approved")
            if approval_status in {"deferred", "declined"}:
                deferred_work.append(
                    {
                        "order_id": order.get("id"),
                        "order_number": order.get("number"),
                        "customer_name": order.get("customer_name"),
                        "customer_phone": order.get("customer_phone"),
                        "vehicle": orderVehicleText(order),
                        "title": item.get("title"),
                        "approval_status": approval_status,
                        "amount": round(parse_float(item.get("quantity")) * parse_float(item.get("unit_price")), 2),
                    }
                )
    appointment_active_statuses = {"scheduled", "confirmed", "arrived"}
    appointments_today = [
        appointment
        for appointment in appointments
        if appointment.get("status") in appointment_active_statuses
        and str(appointment.get("scheduled_at") or "").startswith(today.isoformat())
    ]
    appointments_upcoming = [
        appointment
        for appointment in appointments
        if appointment.get("status") in appointment_active_statuses
        and str(appointment.get("scheduled_at") or "")[:10] >= today.isoformat()
    ][:8]
    appointment_load_7_days = []
    for offset in range(7):
        day = today + timedelta(days=offset)
        day_prefix = day.isoformat()
        day_appointments = [
            appointment
            for appointment in appointments
            if appointment.get("status") in appointment_active_statuses
            and str(appointment.get("scheduled_at") or "").startswith(day_prefix)
        ]
        appointment_load_7_days.append(
            {
                "date": day_prefix,
                "label": day.strftime("%d.%m"),
                "count": len(day_appointments),
                "appointments": day_appointments[:5],
            }
        )
    inspection_alerts = []
    for inspection in inspections:
        if inspection.get("status") == "archived":
            continue
        for item in inspection.get("items", []):
            if item.get("condition_status") not in {"attention", "critical"}:
                continue
            if str(item.get("approval_status") or "deferred") == "approved":
                continue
            inspection_alerts.append(
                {
                    "inspection_id": inspection.get("id"),
                    "customer_name": inspection.get("customer_name"),
                    "customer_phone": inspection.get("customer_phone"),
                    "vehicle": orderVehicleText(inspection),
                    "inspected_at": inspection.get("inspected_at"),
                    "area": item.get("area"),
                    "title": item.get("title"),
                    "condition_status": item.get("condition_status"),
                    "approval_status": item.get("approval_status"),
                    "estimate": round(parse_float(item.get("estimate")), 2),
                }
            )
    inspection_alerts = sorted(
        inspection_alerts,
        key=lambda item: (0 if item.get("condition_status") == "critical" else 1, str(item.get("inspected_at") or "")),
    )
    procurement_plan = []
    for part in low_stock:
        quantity = max(parse_float(part.get("quantity")), 0)
        min_quantity = max(parse_float(part.get("min_quantity")), 0)
        target_quantity = max(min_quantity * 2, min_quantity + 1, 1)
        reorder_quantity = max(target_quantity - quantity, 0)
        unit_budget = parse_float(part.get("cost")) or parse_float(part.get("price"))
        procurement_plan.append(
            {
                "id": part.get("id"),
                "sku": part.get("sku"),
                "name": part.get("name"),
                "unit": part.get("unit"),
                "quantity": round(quantity, 2),
                "min_quantity": round(min_quantity, 2),
                "reorder_quantity": round(reorder_quantity, 2),
                "budget": round(reorder_quantity * unit_budget, 2),
                "supplier": part.get("supplier"),
                "urgency": "critical" if quantity <= 0 else "low",
            }
        )
    procurement_plan.sort(key=lambda item: (0 if item["urgency"] == "critical" else 1, -parse_float(item.get("budget"))))

    pipeline_by_status = []
    for status, label in ORDER_STATUSES.items():
        status_orders = [order for order in orders if order.get("status") == status]
        overdue_ids = {int(order["id"]) for order in overdue_orders if order.get("id")}
        status_overdue = [order for order in status_orders if int(order.get("id") or 0) in overdue_ids]
        pipeline_by_status.append(
            {
                "status": status,
                "label": label,
                "count": len(status_orders),
                "total": round(sum(parse_float(order.get("total")) for order in status_orders), 2),
                "due": round(sum(parse_float(order.get("due")) for order in status_orders), 2),
                "overdue_count": len(status_overdue),
                "orders": [summarize_order(order) for order in status_orders[:6]],
            }
        )

    overdue_ids = {int(order["id"]) for order in overdue_orders if order.get("id")}
    workload: dict[str, dict[str, Any]] = {}
    for order in active_orders:
        responsible = clean_text(order.get("mechanic") or order.get("advisor"), 120, "Не назначен") or "Не назначен"
        bucket = workload.setdefault(
            responsible,
            {
                "name": responsible,
                "orders_count": 0,
                "total": 0.0,
                "due": 0.0,
                "overdue_count": 0,
            },
        )
        bucket["orders_count"] += 1
        bucket["total"] += parse_float(order.get("total"))
        bucket["due"] += parse_float(order.get("due"))
        if int(order.get("id") or 0) in overdue_ids:
            bucket["overdue_count"] += 1
    workload_by_responsible = sorted(
        [
            {
                **bucket,
                "total": round(parse_float(bucket.get("total")), 2),
                "due": round(parse_float(bucket.get("due")), 2),
            }
            for bucket in workload.values()
        ],
        key=lambda item: (parse_int(item.get("overdue_count")), parse_int(item.get("orders_count")), parse_float(item.get("total"))),
        reverse=True,
    )[:8]

    service_sales: dict[str, float] = defaultdict(float)
    for order in orders:
        if order.get("status") == "cancelled":
            continue
        for item in order.get("items", []):
            if item.get("kind") == "service" and item_is_billable(item):
                service_sales[str(item.get("title"))] += parse_float(item.get("quantity")) * parse_float(item.get("unit_price"))
    top_services = sorted(
        [{"title": title, "total": round(total, 2)} for title, total in service_sales.items()],
        key=lambda x: x["total"],
        reverse=True,
    )[:5]

    retention_by_customer: dict[int, dict[str, Any]] = {}
    for order in orders:
        if order.get("status") == "cancelled" or not order.get("customer_id"):
            continue
        customer_id = int(order["customer_id"])
        bucket = retention_by_customer.setdefault(
            customer_id,
            {
                "customer_id": customer_id,
                "customer_name": order.get("customer_name"),
                "customer_phone": order.get("customer_phone"),
                "orders_count": 0,
                "revenue": 0.0,
                "last_order_at": "",
            },
        )
        bucket["orders_count"] += 1
        bucket["revenue"] += parse_float(order.get("total"))
        bucket["last_order_at"] = max(str(bucket.get("last_order_at") or ""), str(order.get("updated_at") or ""))
    vip_customers = sorted(
        [
            {
                **bucket,
                "revenue": round(parse_float(bucket.get("revenue")), 2),
            }
            for bucket in retention_by_customer.values()
            if parse_float(bucket.get("revenue")) > 0 and (bucket["orders_count"] >= 2 or parse_float(bucket.get("revenue")) >= 50_000)
        ],
        key=lambda item: (parse_float(item.get("revenue")), parse_int(item.get("orders_count"))),
        reverse=True,
    )[:8]

    crm_tasks_count = len(service_reminders) + len(followups_due) + len(authorizations_pending) + len(deferred_work) + len(inspection_alerts)
    risk_points = len(overdue_orders) * 9 + len(low_stock) * 4 + len(authorizations_pending) * 5 + len(inspection_alerts) * 5 + len(deferred_work) * 3
    business_health_score = max(0, min(100, 100 - risk_points))
    if business_health_score >= 85:
        business_health_label = "Отлично"
    elif business_health_score >= 70:
        business_health_label = "Контроль"
    else:
        business_health_label = "Риски"

    action_plan: list[dict[str, Any]] = []

    def add_action(
        kind: str,
        title: str,
        detail: str,
        priority: int,
        tone: str,
        route: str,
        action: str,
        record_id: Any = "",
        cta: str = "Открыть",
        customer_name: str = "",
        customer_phone: str = "",
        vehicle: str = "",
        amount: Any = 0,
        due_at: str = "",
    ) -> None:
        priority = max(0, min(100, parse_int(priority, 0)))
        if priority >= 90:
            priority_label = "Срочно"
        elif priority >= 72:
            priority_label = "Высокий"
        elif priority >= 55:
            priority_label = "Средний"
        else:
            priority_label = "Планово"
        action_plan.append(
            {
                "id": f"{kind}:{record_id or len(action_plan) + 1}:{len(action_plan) + 1}",
                "type": kind,
                "priority": priority,
                "priority_label": priority_label,
                "tone": tone,
                "title": clean_text(title, 180, "Действие CRM"),
                "detail": clean_text(detail, 260),
                "customer_name": clean_text(customer_name, 120),
                "customer_phone": clean_text(customer_phone, 80),
                "vehicle": clean_text(vehicle, 160),
                "amount": round(parse_float(amount), 2),
                "due_at": clean_text(due_at, 40),
                "route": clean_text(route, 40, "dashboard"),
                "action": clean_text(action, 60),
                "record_id": record_id or "",
                "cta": clean_text(cta, 80, "Открыть"),
            }
        )

    for order in overdue_orders[:10]:
        promised_dt = parse_local_datetime(order.get("promised_at"))
        overdue_hours = int(max((now - promised_dt).total_seconds() // 3600, 0)) if promised_dt else 0
        base_priority = {"urgent": 100, "high": 94, "normal": 88, "low": 82}.get(str(order.get("priority") or "normal"), 86)
        add_action(
            "overdue_order",
            f"Просрочен заказ-наряд {order.get('number') or 'без номера'}",
            f"Срок прошел {overdue_hours} ч назад · статус {ORDER_STATUSES.get(str(order.get('status') or ''), order.get('status') or 'не указан')} · к оплате {money(order.get('due'))}.",
            min(100, base_priority + (2 if parse_float(order.get("due")) else 0)),
            "danger",
            "orders",
            "edit-order",
            order.get("id"),
            "Открыть заказ",
            str(order.get("customer_name") or ""),
            str(order.get("customer_phone") or ""),
            orderVehicleText(order),
            order.get("due"),
            str(order.get("promised_at") or ""),
        )

    for item in inspection_alerts[:10]:
        condition = str(item.get("condition_status") or "attention")
        add_action(
            "inspection_alert",
            f"DVI: {INSPECTION_CONDITIONS.get(condition, condition).lower()} — {item.get('title') or 'пункт осмотра'}",
            f"{item.get('area') or 'Осмотр'} · рекомендация на {money(item.get('estimate'))} еще не согласована.",
            96 if condition == "critical" else 78,
            "danger" if condition == "critical" else "warning",
            "inspections",
            "edit-inspection",
            item.get("inspection_id"),
            "Открыть осмотр",
            str(item.get("customer_name") or ""),
            str(item.get("customer_phone") or ""),
            str(item.get("vehicle") or ""),
            item.get("estimate"),
            str(item.get("inspected_at") or ""),
        )

    for order in authorizations_pending[:8]:
        add_action(
            "authorization",
            f"Согласовать смету {order.get('number') or 'без номера'}",
            f"Клиент еще не подтвердил работы на {money(order.get('total'))}. Зафиксируйте ответственного и дату согласования.",
            86,
            "warning",
            "orders",
            "edit-order",
            order.get("id"),
            "Согласовать",
            str(order.get("customer_name") or ""),
            str(order.get("customer_phone") or ""),
            orderVehicleText(order),
            order.get("total"),
            str(order.get("updated_at") or ""),
        )

    for order in followups_due[:8]:
        add_action(
            "follow_up",
            f"Связаться после визита {order.get('number') or ''}".strip(),
            "Проверить удовлетворенность, закрыть возможные возражения и предложить следующий визит.",
            72,
            "info",
            "orders",
            "edit-order",
            order.get("id"),
            "Открыть клиента",
            str(order.get("customer_name") or ""),
            str(order.get("customer_phone") or ""),
            orderVehicleText(order),
            0,
            str(order.get("follow_up_at") or ""),
        )

    for vehicle in service_reminders[:8]:
        vehicle_text = " ".join(
            str(part)
            for part in [vehicle.get("make"), vehicle.get("model"), vehicle.get("year"), vehicle.get("plate")]
            if part
        )
        reminder_reasons = []
        if vehicle.get("due_by_date"):
            reminder_reasons.append("по дате")
        if vehicle.get("due_by_mileage"):
            reminder_reasons.append("по пробегу")
        add_action(
            "service_reminder",
            "Напомнить о плановом сервисе",
            f"Причина: {', '.join(reminder_reasons) or 'приближается регламент'} · канал {PREFERRED_CHANNELS.get(str(vehicle.get('customer_preferred_channel') or 'phone'), 'Телефон')}.",
            64,
            "info",
            "vehicles",
            "edit-vehicle",
            vehicle.get("id"),
            "Открыть авто",
            str(vehicle.get("customer_name") or ""),
            str(vehicle.get("customer_phone") or ""),
            vehicle_text,
            0,
            str(vehicle.get("next_service_at") or ""),
        )

    for item in deferred_work[:8]:
        approval_status = str(item.get("approval_status") or "deferred")
        add_action(
            "deferred_work",
            f"Вернуть в продажу: {item.get('title') or 'отложенная работа'}",
            f"Статус клиента: {ITEM_APPROVAL_STATUSES.get(approval_status, approval_status).lower()} · потенциально {money(item.get('amount'))}.",
            66 if approval_status == "declined" else 60,
            "warning",
            "orders",
            "edit-order",
            item.get("order_id"),
            "Открыть заказ",
            str(item.get("customer_name") or ""),
            str(item.get("customer_phone") or ""),
            str(item.get("vehicle") or ""),
            item.get("amount"),
        )

    for part in procurement_plan[:8]:
        add_action(
            "procurement",
            f"Заказать склад: {part.get('name') or 'позиция'}",
            f"Остаток {part.get('quantity')} {part.get('unit') or 'шт'} при минимуме {part.get('min_quantity')} · бюджет {money(part.get('budget'))}.",
            68 if part.get("urgency") == "critical" else 54,
            "danger" if part.get("urgency") == "critical" else "info",
            "inventory",
            "edit-inventory",
            part.get("id"),
            "Открыть склад",
            "",
            "",
            "",
            part.get("budget"),
        )

    for appointment in appointments_today[:6]:
        status = str(appointment.get("status") or "scheduled")
        appointment_vehicle = " ".join(
            str(part)
            for part in [appointment.get("vehicle_make"), appointment.get("vehicle_model"), appointment.get("vehicle_year"), appointment.get("vehicle_plate")]
            if part
        )
        add_action(
            "appointment_today",
            f"Приемка сегодня: {appointment.get('customer_name') or 'клиент'}",
            f"{APPOINTMENT_STATUSES.get(status, status)} · {appointment.get('reason') or 'причина не указана'}.",
            58 if status in {"scheduled", "confirmed"} else 50,
            "success" if status == "arrived" else "info",
            "appointments",
            "edit-appointment",
            appointment.get("id"),
            "Открыть запись",
            str(appointment.get("customer_name") or ""),
            str(appointment.get("customer_phone") or ""),
            appointment_vehicle,
            0,
            str(appointment.get("scheduled_at") or ""),
        )

    action_plan.sort(
        key=lambda item: (
            -parse_int(item.get("priority"), 0),
            str(item.get("due_at") or "9999-12-31T23:59"),
            str(item.get("title") or ""),
        )
    )
    action_plan_total = len(action_plan)
    action_plan = action_plan[:18]
    action_plan_by_tone: dict[str, int] = defaultdict(int)
    for item in action_plan:
        action_plan_by_tone[str(item.get("tone") or "info")] += 1

    return {
        "active_orders": len(active_orders),
        "revenue_month": round(revenue_month, 2),
        "gross_margin_month": round(gross_margin_month, 2),
        "margin_percent_month": round(margin_percent_month, 1),
        "conversion_rate": round(conversion_rate, 1),
        "inventory_value": round(inventory_value, 2),
        "pipeline_value": round(pipeline_value, 2),
        "pipeline_due": round(pipeline_due, 2),
        "business_health_score": business_health_score,
        "business_health_label": business_health_label,
        "due_total": round(due_total, 2),
        "avg_check": round(avg_check, 2),
        "low_stock_count": len(low_stock),
        "appointments_today_count": len(appointments_today),
        "inspections_count": len(inspections),
        "inspection_alerts_count": len(inspection_alerts),
        "overdue_orders_count": len(overdue_orders),
        "crm_tasks_count": crm_tasks_count,
        "action_plan": action_plan,
        "action_plan_total": action_plan_total,
        "action_plan_by_tone": dict(action_plan_by_tone),
        "promised_today": promised_today[:8],
        "overdue_orders": [summarize_order(order) for order in overdue_orders[:8]],
        "appointments_today": appointments_today[:8],
        "appointments_upcoming": appointments_upcoming,
        "appointment_load_7_days": appointment_load_7_days,
        "inspection_alerts": inspection_alerts[:8],
        "low_stock": low_stock[:8],
        "procurement_plan": procurement_plan[:8],
        "service_reminders": service_reminders[:8],
        "followups_due": followups_due[:8],
        "authorizations_pending": authorizations_pending[:8],
        "deferred_work": deferred_work[:8],
        "vip_customers": vip_customers,
        "workload_by_responsible": workload_by_responsible,
        "pipeline_by_status": pipeline_by_status,
        "status_counts": status_counts,
        "top_services": top_services,
    }


def orderVehicleText(order: dict[str, Any]) -> str:
    return " ".join(
        str(part)
        for part in [
            order.get("vehicle_make"),
            order.get("vehicle_model"),
            order.get("vehicle_year"),
            order.get("vehicle_plate"),
        ]
        if part
    )


def bootstrap_payload(q: str = "", status: str = "all") -> dict[str, Any]:
    status = clean_text(status, 40, "all") or "all"
    if status not in {"all", *ORDER_STATUSES}:
        raise ValueError("Некорректный статус заказа.")
    customers = list_customers(q)
    vehicles = list_vehicles(q)
    inventory = list_inventory(q)
    appointments = list_appointments(q)
    inspections = list_inspections(q)
    orders = list_orders(q, status)
    lookup_customers = list_customers("", LOOKUP_LIMIT)
    lookup_vehicles = list_vehicles("", LOOKUP_LIMIT)
    lookup_inventory = list_inventory("", LOOKUP_LIMIT)
    lookup_orders = list_orders("", "all", LOOKUP_LIMIT)
    all_orders = list_orders("", "all", None)
    all_inventory = list_inventory("", None)
    all_vehicles = list_vehicles("", None)
    all_appointments = list_appointments("", "all", None)
    all_inspections = list_inspections("", "all", None)
    lookup_appointments = all_appointments[:LOOKUP_LIMIT]
    lookup_inspections = all_inspections[:LOOKUP_LIMIT]
    reports = build_reports(
        all_orders, all_inventory, all_vehicles, all_appointments, all_inspections
    )
    return {
        "app": {
            "name": APP_NAME,
            "version": APP_VERSION,
            "db_path": RUNTIME.db_path.name,
            "db_directory": display_path(RUNTIME.db_path.parent),
            "csrf_token": RUNTIME.csrf_token,
            "repository": normalize_github_repository(),
            "repository_url": github_repository_url(),
            "releases_url": github_latest_release_url(),
            "can_install_update": is_frozen(),
        },
        "statuses": ORDER_STATUSES,
        "appointment_statuses": APPOINTMENT_STATUSES,
        "item_approval_statuses": ITEM_APPROVAL_STATUSES,
        "inspection_statuses": INSPECTION_STATUSES,
        "inspection_conditions": INSPECTION_CONDITIONS,
        "customers": customers,
        "vehicles": vehicles,
        "inventory": inventory,
        "appointments": appointments,
        "inspections": inspections,
        "orders": orders,
        "car_catalog": car_catalog_payload(),
        "lookups": {
            "customers": lookup_customers,
            "vehicles": lookup_vehicles,
            "inventory": lookup_inventory,
            "orders": lookup_orders,
            "appointments": lookup_appointments,
            "inspections": lookup_inspections,
        },
        "reports": reports,
        "preferred_channels": PREFERRED_CHANNELS,
        "priorities": ORDER_PRIORITIES,
    }


def csv_export(entity: str) -> tuple[str, str]:
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    if entity == "customers":
        rows = list_customers("", None)
        headers = ["id", "name", "phone", "email", "source", "preferred_channel", "reminder_consent", "vehicles_count", "orders_count", "notes"]
    elif entity == "vehicles":
        rows = list_vehicles("", None)
        headers = ["id", "customer_name", "make", "model", "year", "plate", "vin", "mileage", "next_service_at", "next_service_mileage", "notes"]
    elif entity == "inventory":
        rows = list_inventory("", None)
        headers = ["id", "sku", "name", "brand", "unit", "quantity", "min_quantity", "price", "cost", "supplier", "notes"]
    elif entity == "appointments":
        rows = list_appointments("", "all", None)
        headers = [
            "id", "scheduled_at", "duration_minutes", "status", "customer_name", "customer_phone",
            "vehicle_plate", "vehicle_make", "vehicle_model", "advisor", "reason", "notes",
        ]
    elif entity == "inspections":
        rows = []
        for inspection in list_inspections("", "all", None):
            for item in inspection.get("items", []):
                rows.append(
                    {
                        **{k: inspection.get(k, "") for k in [
                            "id", "inspected_at", "status", "customer_name", "customer_phone",
                            "vehicle_plate", "vehicle_make", "vehicle_model", "order_number", "inspector",
                        ]},
                        "area": item.get("area", ""),
                        "item_title": item.get("title", ""),
                        "condition_status": item.get("condition_status", ""),
                        "approval_status": item.get("approval_status", ""),
                        "recommendation": item.get("recommendation", ""),
                        "estimate": item.get("estimate", ""),
                    }
                )
        headers = [
            "id", "inspected_at", "status", "customer_name", "customer_phone", "vehicle_plate",
            "vehicle_make", "vehicle_model", "order_number", "inspector", "area", "item_title",
            "condition_status", "approval_status", "recommendation", "estimate",
        ]
    elif entity == "orders":
        rows = list_orders("", "all", None)
        headers = [
            "id", "number", "status", "customer_name", "vehicle_plate", "vehicle_make", "vehicle_model",
            "authorized_by", "authorized_at", "follow_up_at", "total", "paid", "due", "created_at", "updated_at",
        ]
    elif entity in {"catalog", "car_catalog"}:
        catalog = car_catalog_payload()
        rows = [
            {"make": make, "model": model}
            for make in catalog["makes"]
            for model in (catalog["models"].get(make) or [""])
        ]
        headers = ["make", "model"]
        entity = "car_catalog"
    else:
        raise KeyError("Неизвестный экспорт.")
    writer.writerow(headers)
    for row in rows:
        writer.writerow([csv_cell(row.get(header, "")) for header in headers])
    return f"{entity}.csv", "\ufeff" + output.getvalue()


def create_backup() -> dict[str, Any]:
    backup_dir = RUNTIME.db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"sto_crm_backup_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.sqlite3"
    try:
        with closing(connect()) as source, closing(sqlite3.connect(target, timeout=30)) as destination:
            destination.execute("PRAGMA busy_timeout = 30000")
            source.backup(destination)
    except sqlite3.Error as exc:
        raise RuntimeError(f"Не удалось создать резервную копию базы: {exc}") from exc
    return {"path": str(target), "size": target.stat().st_size}


def semantic_version_tuple(version: str) -> tuple[int, ...]:
    """Сравнимый кортеж для SemVer-подобных тегов GitHub Releases."""
    core = str(version or "").strip().lstrip("vV").split("-", 1)[0]
    numbers = [int(part) for part in re.findall(r"\d+", core)[:4]]
    return tuple(numbers or [0])


def is_newer_version(candidate: str, current: str = APP_VERSION) -> bool:
    left = semantic_version_tuple(candidate)
    right = semantic_version_tuple(current)
    width = max(len(left), len(right), 3)
    return left + (0,) * (width - len(left)) > right + (0,) * (width - len(right))


def release_asset_score(asset: dict[str, Any]) -> int:
    name = str(asset.get("name") or "")
    lowered = name.lower()
    score = 0
    if EXE_ASSET_RE.search(name):
        score += 100
    if lowered.endswith(".exe"):
        score += 40
    if "setup" in lowered or "installer" in lowered:
        score += 8
    if "portable" in lowered or "standalone" in lowered:
        score += 6
    if "sha" in lowered or "checksum" in lowered:
        score -= 80
    return score


def manifest_asset_score(asset: dict[str, Any]) -> int:
    name = str(asset.get("name") or "")
    lowered = name.lower()
    if name == GITHUB_RELEASE_MANIFEST_NAME:
        return 100
    if MANIFEST_ASSET_RE.search(name):
        return 80
    return 10 if lowered.endswith(".json") and "manifest" in lowered else 0


def select_release_asset(release: dict[str, Any], *, kind: str = "exe") -> dict[str, Any] | None:
    assets = [asset for asset in release.get("assets", []) if isinstance(asset, dict)]
    candidates = [asset for asset in assets if str(asset.get("browser_download_url") or "")]
    scorer = manifest_asset_score if kind == "manifest" else release_asset_score
    candidates = [asset for asset in candidates if scorer(asset) > 0]
    if not candidates:
        return None
    return max(candidates, key=scorer)


def github_headers(accept: str = "application/vnd.github+json") -> dict[str, str]:
    return {
        "Accept": accept,
        "User-Agent": f"STO-CRM/{APP_VERSION}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def validate_update_download_url(url: str) -> str:
    """Проверяет, что обновление скачивается только по доверенной HTTPS-ссылке GitHub."""
    cleaned = clean_text(url, 1000)
    if not cleaned:
        raise RuntimeError("В релизе нет ссылки на файл обновления.")
    try:
        parsed = urllib.parse.urlparse(cleaned)
    except ValueError as exc:
        raise RuntimeError("Manifest обновления содержит некорректную ссылку на файл.") from exc
    try:
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError("Manifest обновления содержит некорректную ссылку на файл.") from exc
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in TRUSTED_UPDATE_DOWNLOAD_HOSTS or port not in {None, 443} or parsed.username or parsed.password:
        raise RuntimeError("Manifest обновления содержит недоверенную ссылку на файл.")
    return cleaned


def validate_sha256(value: Any, *, required: bool = True) -> str:
    digest = clean_text(value, 80).lower()
    if not digest:
        if required:
            raise RuntimeError("В release-only manifest отсутствует SHA-256 файла обновления.")
        return ""
    if not SHA256_RE.fullmatch(digest):
        raise RuntimeError("В release-only manifest указан некорректный SHA-256 файла обновления.")
    return digest


def fetch_json(url: str, timeout: int = GITHUB_UPDATE_TIMEOUT, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers or github_headers())
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            payload = json.loads(response.read().decode(charset))
            if not isinstance(payload, dict):
                raise ValueError("GitHub вернул неожиданный ответ.")
            return payload
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError("Релиз GitHub не найден. Опубликуйте release-only билд STO_CRM.exe и latest.json.") from exc
        if exc.code in {401, 403}:
            raise RuntimeError(f"GitHub отклонил запрос ({exc.code}). Release-only репозиторий должен быть публичным.") from exc
        raise RuntimeError(f"GitHub недоступен: HTTP {exc.code}.") from exc
    except (OSError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"Не удалось получить информацию об обновлении: {exc}") from exc


def fetch_asset_json(asset: dict[str, Any]) -> dict[str, Any]:
    url = clean_text(asset.get("browser_download_url") or asset.get("download_url"), 1000)
    if not url:
        raise RuntimeError("В release-only билде нет ссылки на manifest latest.json.")
    return fetch_json(url, headers=github_headers("application/octet-stream"))


def normalize_release_asset(
    asset: dict[str, Any] | None,
    manifest_asset: dict[str, Any] | None = None,
    *,
    require_sha256: bool = False,
) -> dict[str, Any] | None:
    if not asset:
        return None
    name = clean_text(asset.get("name") or (manifest_asset or {}).get("name") or "STO_CRM.exe", 180)
    download_url = validate_update_download_url(
        asset.get("download_url") or asset.get("browser_download_url") or (manifest_asset or {}).get("browser_download_url")
    )
    return {
        "name": name,
        "size": parse_int(asset.get("size") or (manifest_asset or {}).get("size")),
        "sha256": validate_sha256(asset.get("sha256") or asset.get("hash") or "", required=require_sha256),
        "download_url": download_url,
    }


def release_info_from_manifest(release: dict[str, Any], manifest: dict[str, Any], manifest_asset: dict[str, Any]) -> dict[str, Any]:
    repository = normalize_github_repository()
    asset = normalize_release_asset(manifest.get("asset") if isinstance(manifest.get("asset"), dict) else None, require_sha256=True)
    version = clean_text(manifest.get("version") or manifest.get("tag") or release.get("tag_name") or "", 80).lstrip("vV")
    return {
        "repository": repository,
        "repository_url": github_repository_url(repository),
        "release_url": clean_text(manifest.get("release_url") or release.get("html_url") or github_latest_release_url(repository), 500),
        "tag": clean_text(manifest.get("tag") or release.get("tag_name") or "", 80),
        "name": clean_text(manifest.get("name") or release.get("name") or "", 120),
        "version": version,
        "published_at": clean_text(manifest.get("published_at") or release.get("published_at") or "", 40),
        "body": clean_multiline(manifest.get("notes") or release.get("body") or "", 3000),
        "prerelease": bool(release.get("prerelease")),
        "draft": bool(release.get("draft")),
        "manifest": {
            "name": clean_text(manifest_asset.get("name") or GITHUB_RELEASE_MANIFEST_NAME, 180),
            "size": parse_int(manifest_asset.get("size")),
        },
        "asset": asset,
    }


def latest_release_info() -> dict[str, Any]:
    repository = normalize_github_repository()
    release = fetch_json(github_latest_release_api_url(repository))
    manifest_asset = select_release_asset(release, kind="manifest")
    if manifest_asset:
        manifest = fetch_asset_json(manifest_asset)
        return release_info_from_manifest(release, manifest, manifest_asset)
    version = clean_text(release.get("tag_name") or release.get("name") or "", 80).lstrip("vV")
    asset = select_release_asset(release)
    return {
        "repository": repository,
        "repository_url": github_repository_url(repository),
        "release_url": clean_text(release.get("html_url") or github_latest_release_url(repository), 500),
        "tag": clean_text(release.get("tag_name") or "", 80),
        "name": clean_text(release.get("name") or "", 120),
        "version": version,
        "published_at": clean_text(release.get("published_at") or "", 40),
        "body": clean_multiline(release.get("body") or "", 3000),
        "prerelease": bool(release.get("prerelease")),
        "draft": bool(release.get("draft")),
        "manifest": None,
        "asset": normalize_release_asset(asset, require_sha256=False),
    }


def update_status() -> dict[str, Any]:
    repository = normalize_github_repository()
    app_path = app_executable_path()
    frozen = is_frozen()
    try:
        release = latest_release_info()
        release["is_newer"] = is_newer_version(release.get("version") or release.get("tag"), APP_VERSION)
        release["has_asset"] = bool(release.get("asset"))
        return {
            "ok": True,
            "current_version": APP_VERSION,
            "repository": repository,
            "repository_url": github_repository_url(repository),
            "releases_url": github_latest_release_url(repository),
            "can_install": frozen,
            "app_path": app_path.name,
            "log_path": display_path(updater_log_path()),
            "release": release,
        }
    except Exception as exc:
        return {
            "ok": False,
            "current_version": APP_VERSION,
            "repository": repository,
            "repository_url": github_repository_url(repository),
            "releases_url": github_latest_release_url(repository),
            "can_install": frozen,
            "app_path": app_path.name,
            "log_path": display_path(updater_log_path()),
            "error": str(exc),
        }


def append_updater_log(message: str) -> None:
    try:
        path = updater_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{now_iso()} {message}\n")
    except OSError:
        pass


def download_release_asset(asset: dict[str, Any], target: Path) -> dict[str, Any]:
    url = validate_update_download_url(asset.get("download_url"))
    expected_sha = validate_sha256(asset.get("sha256"), required=True)
    expected_size = parse_int(asset.get("size"))
    if expected_size > GITHUB_UPDATE_MAX_ASSET_BYTES:
        raise RuntimeError("Файл обновления слишком большой для безопасной автоматической установки.")
    request = urllib.request.Request(url, headers=github_headers("application/octet-stream"))
    sha256 = hashlib.sha256()
    total = 0
    tmp_target = target.with_name(f"{target.name}.tmp")
    try:
        tmp_target.unlink(missing_ok=True)
        with urllib.request.urlopen(request, timeout=GITHUB_UPDATE_TIMEOUT) as response, tmp_target.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > GITHUB_UPDATE_MAX_ASSET_BYTES:
                    raise RuntimeError("Файл обновления превышает безопасный лимит.")
                sha256.update(chunk)
                output.write(chunk)
        if expected_size and total != expected_size:
            raise RuntimeError("Размер скачанного обновления не совпадает с размером в GitHub Release.")
        if total <= 0:
            raise RuntimeError("GitHub вернул пустой файл обновления.")
        digest = sha256.hexdigest()
        if expected_sha != digest:
            raise RuntimeError("SHA-256 скачанного обновления не совпадает с release-only manifest.")
        tmp_target.replace(target)
    except urllib.error.HTTPError as exc:
        tmp_target.unlink(missing_ok=True)
        raise RuntimeError(f"Не удалось скачать обновление: HTTP {exc.code}.") from exc
    except (OSError, TimeoutError) as exc:
        tmp_target.unlink(missing_ok=True)
        raise RuntimeError(f"Не удалось скачать обновление: {exc}") from exc
    except Exception as exc:
        tmp_target.unlink(missing_ok=True)
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError(f"Не удалось скачать обновление: {exc}") from exc
    return {"size": total, "sha256": digest}


def ensure_downloaded_executable(path: Path) -> None:
    if path.suffix.lower() != ".exe":
        raise RuntimeError("Автообновление поддерживает только готовый Windows-файл .exe из GitHub Release.")
    with path.open("rb") as handle:
        if handle.read(2) != b"MZ":
            raise RuntimeError("Скачанный файл не похож на Windows .exe.")


def write_windows_update_script(script_path: Path, current_exe: Path, downloaded_exe: Path, backup_exe: Path, log_path: Path) -> None:
    ps = f"""
$ErrorActionPreference = 'Stop'
$Current = {json.dumps(str(current_exe))}
$Downloaded = {json.dumps(str(downloaded_exe))}
$Backup = {json.dumps(str(backup_exe))}
$Log = {json.dumps(str(log_path))}
function Write-UpdateLog([string]$Message) {{
    $dir = Split-Path -Parent $Log
    if ($dir) {{ New-Item -ItemType Directory -Force -Path $dir | Out-Null }}
    Add-Content -LiteralPath $Log -Encoding UTF8 -Value ((Get-Date).ToString('s') + ' ' + $Message)
}}
try {{
    Write-UpdateLog 'Ожидание завершения СТО CRM...'
    for ($i = 0; $i -lt 120; $i++) {{
        try {{
            $stream = [System.IO.File]::Open($Current, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
            $stream.Close()
            break
        }} catch {{ Start-Sleep -Milliseconds 500 }}
    }}
    if (Test-Path -LiteralPath $Backup) {{ Remove-Item -LiteralPath $Backup -Force }}
    Move-Item -LiteralPath $Current -Destination $Backup -Force
    Move-Item -LiteralPath $Downloaded -Destination $Current -Force
    Write-UpdateLog 'Файл приложения обновлен.'
    Start-Process -FilePath $Current
}} catch {{
    Write-UpdateLog ('Ошибка обновления: ' + $_.Exception.Message)
    try {{
        if ((Test-Path -LiteralPath $Backup) -and -not (Test-Path -LiteralPath $Current)) {{
            Move-Item -LiteralPath $Backup -Destination $Current -Force
        }}
    }} catch {{ Write-UpdateLog ('Ошибка отката: ' + $_.Exception.Message) }}
    throw
}}
""".strip()
    script_path.write_text(ps, encoding="utf-8")


def schedule_windows_update(downloaded_exe: Path) -> None:
    current_exe = app_executable_path()
    if not current_exe.exists():
        raise RuntimeError("Текущий исполняемый файл не найден.")
    if current_exe.suffix.lower() != ".exe":
        raise RuntimeError("Автоустановка доступна только для собранного STO_CRM.exe.")
    update_dir = user_data_dir() / "updates"
    update_dir.mkdir(parents=True, exist_ok=True)
    backup_exe = update_dir / f"{current_exe.stem}-{APP_VERSION}-{datetime.now().strftime('%Y%m%d%H%M%S')}.bak.exe"
    script_path = update_dir / "apply_update.ps1"
    write_windows_update_script(script_path, current_exe, downloaded_exe, backup_exe, updater_log_path())
    command = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
    ]
    subprocess.Popen(command, cwd=str(update_dir), close_fds=True)


def install_update_from_github() -> dict[str, Any]:
    if not is_frozen():
        raise RuntimeError("Автоустановка доступна в Windows-версии STO_CRM.exe. Для исходников используйте git pull.")
    release = latest_release_info()
    version = release.get("version") or release.get("tag")
    if not is_newer_version(version, APP_VERSION):
        return {"ok": True, "updated": False, "message": "Установлена актуальная версия.", "release": release}
    asset = release.get("asset")
    if not asset:
        raise RuntimeError("В последнем GitHub Release нет файла STO_CRM.exe для обновления.")
    validate_sha256(asset.get("sha256"), required=True)
    validate_update_download_url(asset.get("download_url"))
    update_dir = user_data_dir() / "updates"
    update_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", asset.get("name") or "STO_CRM.exe")
    downloaded = update_dir / f"download-{datetime.now().strftime('%Y%m%d%H%M%S')}-{safe_name}"
    details = download_release_asset(asset, downloaded)
    ensure_downloaded_executable(downloaded)
    append_updater_log(f"Скачано обновление {version}: {details['size']} байт, sha256={details['sha256']}.")
    schedule_windows_update(downloaded)
    return {
        "ok": True,
        "updated": True,
        "message": "Обновление скачано. CRM закроется, заменит exe и запустится снова.",
        "release": release,
        "download": details,
    }


class CRMHandler(BaseHTTPRequestHandler):
    server_version = f"STO-CRM/{APP_VERSION}"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        safe_log("%s - %s" % (self.log_date_time_string(), redact_sensitive_query(fmt % args)))

    def do_GET(self) -> None:
        self.handle_request("GET")

    def do_POST(self) -> None:
        self.handle_request("POST")

    def do_PUT(self) -> None:
        self.handle_request("PUT")

    def do_DELETE(self) -> None:
        self.handle_request("DELETE")

    def do_OPTIONS(self) -> None:
        try:
            self.validate_local_request_context()
            self.send_bytes(b"", "text/plain; charset=utf-8", status=204, headers={"Allow": "GET, POST, PUT, DELETE, OPTIONS"})
        except PermissionError as exc:
            self.send_error_json(403, str(exc))

    def handle_request(self, method: str) -> None:
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            query = urllib.parse.parse_qs(parsed.query)
            self.validate_mutating_request(method)

            if method == "GET" and path in {"/", "/app"}:
                self.send_html(INDEX_HTML)
                return
            if method == "GET" and path.startswith("/print/order/"):
                self.validate_local_request_context()
                token = (query.get("token") or [""])[0]
                if not token:
                    token = self.headers.get("X-CSRF-Token") or self.headers.get("X-CRM-CSRF-Token") or ""
                if not token or not secrets.compare_digest(token, RUNTIME.csrf_token):
                    raise PermissionError("Печатная форма доступна только из интерфейса CRM.")
                order_id = parse_int_field(path.rsplit("/", 1)[-1], "номер заказ-наряда")
                with db() as conn:
                    self.send_html(print_order_html(get_order(conn, order_id)))
                return
            if method == "GET" and path == "/api/health":
                self.send_json({"ok": True, "version": APP_VERSION, "uptime": round(time.time() - RUNTIME.start_time, 1)})
                return
            if method == "GET" and path == "/api/bootstrap":
                self.validate_local_request_context()
                q = clean_text((query.get("q") or [""])[0], 120)
                status = clean_text((query.get("status") or ["all"])[0], 40, "all")
                self.send_json(bootstrap_payload(q, status))
                return
            if method == "GET" and path in {"/api/catalog", "/api/car-catalog"}:
                self.validate_local_request_context()
                self.send_json(car_catalog_payload())
                return
            if method == "GET" and path == "/api/update/status":
                self.validate_local_request_context()
                self.send_json(update_status())
                return
            if method == "GET" and path.startswith("/api/export/"):
                self.validate_local_request_context()
                token = (query.get("token") or [""])[0]
                if not token:
                    token = self.headers.get("X-CSRF-Token") or self.headers.get("X-CRM-CSRF-Token") or ""
                if not secrets.compare_digest(token, RUNTIME.csrf_token):
                    raise PermissionError("Экспорт доступен только из интерфейса CRM.")
                entity = path.rsplit("/", 1)[-1].replace(".csv", "")
                filename, content = csv_export(entity)
                self.send_bytes(
                    content.encode("utf-8"),
                    "text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'},
                )
                return

            payload = self.read_json() if method in {"POST", "PUT"} else {}
            parts = [p for p in path.split("/") if p]
            if len(parts) < 2 or parts[0] != "api":
                self.send_error_json(404, "Маршрут не найден.")
                return
            entity = parts[1]
            record_id = parse_int_field(parts[2], "идентификатор записи") if len(parts) > 2 else 0

            if entity == "backup" and method == "POST":
                self.send_json(create_backup())
            elif entity == "update" and len(parts) > 2 and parts[2] == "install" and method == "POST":
                result = install_update_from_github()
                self.send_json(result)
                if result.get("updated"):
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
            elif entity == "shutdown" and method == "POST":
                self.send_json({"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            elif entity == "customers":
                self.route_entity(method, record_id, payload, create_customer, update_customer, delete_customer)
            elif entity == "vehicles":
                self.route_entity(method, record_id, payload, create_vehicle, update_vehicle, delete_vehicle)
            elif entity == "inventory":
                self.route_entity(method, record_id, payload, create_inventory, update_inventory, delete_inventory)
            elif entity == "appointments":
                self.route_entity(method, record_id, payload, create_appointment, update_appointment, delete_appointment)
            elif entity == "inspections":
                self.route_entity(method, record_id, payload, create_inspection, update_inspection, delete_inspection)
            elif entity == "orders":
                self.route_entity(method, record_id, payload, create_order, update_order, delete_order)
            else:
                self.send_error_json(404, "Маршрут не найден.")
        except ValueError as exc:
            self.send_error_json(400, str(exc))
        except PermissionError as exc:
            self.send_error_json(403, str(exc))
        except KeyError as exc:
            self.send_error_json(404, str(exc).strip("'"))
        except sqlite3.IntegrityError:
            self.send_error_json(409, "Запись конфликтует с существующими данными. Обновите страницу и повторите действие.")
        except BrokenPipeError:
            return
        except Exception:
            if getattr(sys, "stderr", None):
                traceback.print_exc()
            self.send_error_json(500, INTERNAL_ERROR_MESSAGE)

    def route_entity(
        self,
        method: str,
        record_id: int,
        payload: dict[str, Any],
        create_fn: Any,
        update_fn: Any,
        delete_fn: Any,
    ) -> None:
        if method == "POST":
            self.send_json(create_fn(payload), 201)
        elif method == "PUT" and record_id:
            self.send_json(update_fn(record_id, payload))
        elif method == "DELETE" and record_id:
            self.send_json(delete_fn(record_id))
        else:
            self.send_error_json(405, "Метод не поддерживается.")

    def validate_mutating_request(self, method: str) -> None:
        if method not in {"POST", "PUT", "DELETE"}:
            return
        self.validate_local_request_context()
        if method in {"POST", "PUT"}:
            raw_length = self.headers.get("Content-Length")
            try:
                length = int(raw_length or "0")
            except ValueError as exc:
                raise ValueError("Некорректная длина запроса.") from exc
            if length < 0:
                raise ValueError("Некорректная длина запроса.")
            if length == 0:
                raise ValueError("Пустое тело JSON-запроса.")
            if length > MAX_BODY_BYTES:
                raise ValueError("Слишком большой запрос.")
        self.require_csrf_token()
        if method in {"POST", "PUT"}:
            self.require_json_content_type()

    def validate_local_request_context(self) -> None:
        origin = self.headers.get("Origin")
        if origin and not self.is_allowed_origin(origin):
            raise PermissionError("Запрос отклонен: внешний источник не имеет доступа к локальной CRM.")
        fetch_site = (self.headers.get("Sec-Fetch-Site") or "").lower()
        if fetch_site and fetch_site not in {"same-origin", "same-site", "none"}:
            raise PermissionError("Запрос отклонен: внешний сайт не имеет доступа к локальной CRM.")

    def require_csrf_token(self) -> None:
        token = self.headers.get("X-CSRF-Token") or self.headers.get("X-CRM-CSRF-Token")
        if not token or not secrets.compare_digest(token, RUNTIME.csrf_token):
            raise PermissionError("Запрос отклонен: обновите страницу CRM и повторите действие.")

    def require_json_content_type(self) -> None:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise ValueError("Для изменений требуется Content-Type: application/json.")

    def is_allowed_origin(self, origin: str) -> bool:
        try:
            parsed = urllib.parse.urlparse(origin)
        except ValueError:
            return False
        if parsed.scheme != "http":
            return False
        host = (parsed.hostname or "").lower()
        if host not in {"127.0.0.1", "localhost", "::1"}:
            return False
        try:
            port = parsed.port or 80
        except ValueError:
            return False
        return port == self.server.server_port

    def read_json(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length or "0")
        except ValueError as exc:
            raise ValueError("Некорректная длина запроса.") from exc
        if length < 0:
            raise ValueError("Некорректная длина запроса.")
        if length > MAX_BODY_BYTES:
            raise ValueError("Слишком большой запрос.")
        if length == 0:
            raise ValueError("Пустое тело JSON-запроса.")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Некорректный JSON.") from exc
        if not isinstance(data, dict):
            raise ValueError("Ожидался JSON-объект.")
        return data

    def send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_bytes(body, "application/json; charset=utf-8", status=status)

    def send_html(self, content: str, status: int = 200) -> None:
        self.send_bytes(content.encode("utf-8"), "text/html; charset=utf-8", status=status)

    def send_error_json(self, status: int, message: str) -> None:
        self.send_json({"ok": False, "error": message}, status=status)

    def send_bytes(
        self,
        body: bytes,
        content_type: str,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "geolocation=(), camera=(), microphone=()")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
            "connect-src 'self' https://api.github.com https://github.com https://objects.githubusercontent.com; "
            "img-src 'self' data:; object-src 'none'; base-uri 'none'; "
            "form-action 'self'; frame-ancestors 'none'",
        )
        self.send_header("Connection", "close")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)


class CRMServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def print_order_html(order: dict[str, Any]) -> str:
    vehicle = " ".join(
        str(part)
        for part in [order.get("vehicle_make"), order.get("vehicle_model"), order.get("vehicle_year"), order.get("vehicle_plate")]
        if part
    )
    status_label = ORDER_STATUSES.get(str(order.get("status") or ""), str(order.get("status") or ""))
    printed_at = datetime.now().strftime("%d.%m.%Y %H:%M")
    rows = []
    for index, item in enumerate(order.get("items", []), start=1):
        total = parse_float(item.get("quantity")) * parse_float(item.get("unit_price")) if item_is_billable(item) else 0
        approval_key = str(item.get("approval_status") or "approved")
        approval_label = ITEM_APPROVAL_STATUSES.get(approval_key, approval_key)
        approval_class = "approved" if approval_key == "approved" else "deferred" if approval_key == "deferred" else "declined" if approval_key == "declined" else "neutral"
        rows.append(
            f"""
            <tr>
                <td class="row-index">{index}</td>
                <td><strong>{html.escape(str(item.get('title') or ''))}</strong></td>
                <td>{'Работа' if item.get('kind') == 'service' else 'Запчасть'}</td>
                <td><span class="line-badge {approval_class}">{html.escape(approval_label)}</span></td>
                <td class="num">{parse_float(item.get('quantity')):g}</td>
                <td class="num">{money(item.get('unit_price'))}</td>
                <td class="num total-cell">{money(total)}</td>
            </tr>
            """
        )
    rows_html = "".join(rows) or "<tr><td colspan=\"7\" class=\"empty-row\">В заказ-наряде нет позиций.</td></tr>"
    return f"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{html.escape(str(order.get("number")))} · заказ-наряд</title>
    <style>
        :root {{
            --ink: #0f172a;
            --muted: #64748b;
            --line: #dbe3ee;
            --line-strong: #cbd5e1;
            --surface: #ffffff;
            --surface-soft: #f8fafc;
            --accent: #0f766e;
            --accent-soft: #ccfbf1;
            --blue: #1d4ed8;
            --green: #047857;
            --amber: #b45309;
            --red: #b91c1c;
            --shadow: 0 24px 70px rgba(15,23,42,.14);
            color-scheme: light;
            font-family: 'Segoe UI', system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
        }}
        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            background:
                radial-gradient(circle at 8% -10%, rgba(15,118,110,.16), transparent 34vw),
                linear-gradient(135deg, #eef4fb, #f8fafc 46%, #eef7ff);
            color: var(--ink);
            font-size: 13px;
            line-height: 1.5;
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
        }}
        .print-toolbar {{
            position: sticky;
            top: 0;
            z-index: 3;
            display: flex;
            justify-content: flex-end;
            gap: 10px;
            padding: 14px clamp(14px, 3vw, 32px);
            background: rgba(255,255,255,.78);
            border-bottom: 1px solid rgba(203,213,225,.8);
            backdrop-filter: blur(14px);
        }}
        .print-button {{
            min-height: 40px;
            padding: 0 16px;
            border: 0;
            border-radius: 999px;
            background: linear-gradient(135deg, var(--accent), #14b8a6);
            color: #fff;
            font: inherit;
            font-weight: 800;
            cursor: pointer;
            box-shadow: 0 12px 30px rgba(15,118,110,.22);
        }}
        .document {{
            width: min(1080px, calc(100% - 32px));
            margin: 24px auto;
            padding: clamp(22px, 4vw, 42px);
            background: var(--surface);
            border: 1px solid rgba(203,213,225,.82);
            border-radius: 28px;
            box-shadow: var(--shadow);
        }}
        .doc-hero {{
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 24px;
            align-items: start;
            padding-bottom: 22px;
            border-bottom: 2px solid var(--ink);
        }}
        .brand-lockup {{ display: flex; align-items: center; gap: 14px; min-width: 0; }}
        .brand-mark {{
            width: 54px;
            height: 54px;
            border-radius: 18px;
            display: grid;
            place-items: center;
            background: linear-gradient(135deg, #0f172a, var(--accent));
            color: #fff;
            font-weight: 950;
            letter-spacing: -.05em;
            box-shadow: 0 18px 40px rgba(15,118,110,.24);
        }}
        h1 {{ margin: 0; font-size: clamp(25px, 4vw, 38px); line-height: 1; letter-spacing: -.06em; }}
        .eyebrow {{ color: var(--accent); font-weight: 900; text-transform: uppercase; letter-spacing: .08em; font-size: 11px; }}
        .muted {{ color: var(--muted); }}
        .doc-meta {{ display: grid; justify-items: end; gap: 8px; min-width: 220px; text-align: right; }}
        .status-chip {{
            display: inline-flex;
            align-items: center;
            min-height: 30px;
            padding: 0 12px;
            border-radius: 999px;
            background: var(--accent-soft);
            color: var(--accent);
            font-weight: 850;
        }}
        .summary-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin: 22px 0; }}
        .box {{
            min-width: 0;
            border: 1px solid var(--line);
            border-radius: 18px;
            padding: 16px;
            background: linear-gradient(180deg, #fff, var(--surface-soft));
        }}
        .box-title {{ display: block; margin-bottom: 8px; color: var(--muted); font-size: 11px; font-weight: 900; text-transform: uppercase; letter-spacing: .08em; }}
        .notes-grid {{ display: grid; gap: 12px; margin: 18px 0; }}
        .table-scroll {{ width:100%; overflow-x:auto; -webkit-overflow-scrolling:touch; border: 1px solid var(--line); border-radius: 18px; }}
        table {{ width:100%; border-collapse:collapse; min-width:760px; }}
        th, td {{ border-bottom:1px solid var(--line); padding:11px 12px; text-align:left; vertical-align: top; }}
        tr:last-child td {{ border-bottom: 0; }}
        th {{ background:#f1f5f9; color: #475569; font-size: 10px; text-transform: uppercase; letter-spacing: .06em; }}
        .row-index {{ width: 46px; color: var(--muted); font-weight: 800; }}
        .num {{ text-align:right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
        .total-cell {{ font-weight: 850; }}
        .line-badge {{ display: inline-flex; min-height: 24px; align-items: center; padding: 0 9px; border-radius: 999px; font-size: 11px; font-weight: 850; }}
        .line-badge.approved {{ background:#dcfce7; color: var(--green); }}
        .line-badge.deferred {{ background:#fef3c7; color: var(--amber); }}
        .line-badge.declined {{ background:#fee2e2; color: var(--red); }}
        .line-badge.neutral {{ background:#e2e8f0; color: #475569; }}
        .empty-row {{ text-align:center; color: var(--muted); padding: 24px; }}
        .totals {{
            margin: 18px 0 0 auto;
            width: min(380px, 100%);
            display: grid;
            gap: 0;
            overflow: hidden;
            border: 1px solid var(--line);
            border-radius: 18px;
            background: #fff;
        }}
        .totals div {{ display:flex; justify-content:space-between; gap:12px; padding:10px 14px; border-bottom: 1px solid var(--line); }}
        .totals div:last-child {{ border-bottom: 0; }}
        .totals .grand {{ background: #0f172a; color: #fff; font-size: 16px; font-weight: 900; }}
        .sign {{ display:grid; grid-template-columns:1fr 1fr; gap:40px; margin-top:58px; }}
        .line {{ border-top:1.5px solid var(--ink); padding-top:8px; color: var(--muted); }}
        @page {{ margin: 12mm; }}
        @media print {{
            body {{ background: #fff; font-size: 11px; }}
            .print-toolbar {{ display:none; }}
            .document {{ width: 100%; margin: 0; padding: 0; border: 0; border-radius: 0; box-shadow: none; }}
            .table-scroll {{ overflow: visible; }}
            table {{ min-width: 0; }}
            .box {{ break-inside: avoid; }}
            .totals, .sign {{ break-inside: avoid; }}
        }}
        @media (max-width: 720px) {{
            .document {{ width: min(100% - 20px, 1080px); margin: 10px auto; border-radius: 18px; }}
            .doc-hero, .summary-grid, .sign {{ grid-template-columns: 1fr; }}
            .doc-meta {{ justify-items: start; text-align: left; min-width: 0; }}
            table {{ font-size: 12px; }}
        }}
    </style>
</head>
<body>
    <div class="print-toolbar"><button type="button" class="print-button" id="printButton" aria-label="Печать заказ-наряда">⎙ Печать</button></div>
    <noscript>Для кнопки печати включите JavaScript или используйте Ctrl+P.</noscript>
    <main class="document" aria-label="Печатная форма заказ-наряда">
        <header class="doc-hero">
            <div class="brand-lockup">
                <div class="brand-mark" aria-hidden="true">CRM</div>
                <div>
                    <div class="eyebrow">СТО CRM · заказ-наряд</div>
                    <h1>{html.escape(str(order.get("number") or ""))}</h1>
                    <div class="muted">Сформировано: {printed_at}</div>
                </div>
            </div>
            <div class="doc-meta">
                <span class="status-chip">{html.escape(status_label)}</span>
                <div><strong>Мастер:</strong> {html.escape(str(order.get("mechanic") or order.get("advisor") or "—"))}</div>
                <div><strong>Согласовал:</strong> {html.escape(str(order.get("authorized_by") or "—"))}</div>
            </div>
        </header>
        <section class="summary-grid" aria-label="Клиент и автомобиль">
            <div class="box">
                <span class="box-title">Клиент</span>
                <strong>{html.escape(str(order.get("customer_name") or ""))}</strong><br>
                {html.escape(str(order.get("customer_phone") or ""))}<br>
                {html.escape(str(order.get("customer_email") or ""))}
            </div>
            <div class="box">
                <span class="box-title">Автомобиль</span>
                <strong>{html.escape(vehicle or "Автомобиль не выбран")}</strong><br>
                VIN: {html.escape(str(order.get("vehicle_vin") or "—"))}<br>
                Пробег: {parse_int(order.get("odometer"))} км
            </div>
        </section>
        <section class="notes-grid" aria-label="Описание работ">
            <div class="box"><span class="box-title">Жалоба клиента</span>{html.escape(str(order.get("complaint") or "—"))}</div>
            <div class="box"><span class="box-title">Диагностика</span>{html.escape(str(order.get("diagnosis") or "—"))}</div>
            <div class="box"><span class="box-title">Рекомендации</span>{html.escape(str(order.get("recommendations") or "—"))}</div>
        </section>
        <div class="table-scroll" role="region" aria-label="Позиции заказ-наряда" tabindex="0">
            <table>
                <thead><tr><th scope="col">№</th><th scope="col">Наименование</th><th scope="col">Тип</th><th scope="col">Согласование</th><th scope="col">Кол-во</th><th scope="col">Цена</th><th scope="col">Сумма</th></tr></thead>
                <tbody>{rows_html}</tbody>
            </table>
        </div>
        <section class="totals" aria-label="Итоги заказ-наряда">
            <div><span>Работы</span><strong>{money(order.get("service_total"))}</strong></div>
            <div><span>Запчасти</span><strong>{money(order.get("parts_total"))}</strong></div>
            <div><span>Скидка</span><strong>{money(order.get("discount"))}</strong></div>
            <div><span>Налог</span><strong>{money(order.get("tax"))}</strong></div>
            <div><span>Итого</span><strong>{money(order.get("total"))}</strong></div>
            <div><span>Оплачено</span><strong>{money(order.get("paid"))}</strong></div>
            <div class="grand"><span>К оплате</span><strong>{money(order.get("due"))}</strong></div>
        </section>
        <section class="sign" aria-label="Подписи сторон">
            <div class="line">Представитель сервиса</div>
            <div class="line">Клиент</div>
        </section>
    </main>
    <script>document.getElementById("printButton").addEventListener("click", () => window.print());</script>
</body>
</html>"""


INDEX_HTML = r"""<!doctype html>
<html lang="ru">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="color-scheme" content="light dark">
    <title>СТО CRM</title>
    <style>
:root {
            --bg: #eef4fb;
            --page-gradient: linear-gradient(135deg, #fbfdff 0%, #eef4fb 48%, #e8f7ff 100%);
            --surface: #ffffff;
            --surface-soft: #f8fafc;
            --surface-strong: #eef2f6;
            --surface-raised: #ffffff;
            --surface-glass: rgba(255,255,255,.82);
            --surface-tint: rgba(13, 148, 136, .07);
            --ink: #0b1220;
            --muted: #64748b;
            --muted-strong: #475569;
            --line: #e2e8f0;
            --line-strong: #cbd5e1;
            --accent: #0d9488;
            --accent-strong: #0f766e;
            --accent-soft: #ccfbf1;
            --accent-glow: rgba(13, 148, 136, 0.18);
            --blue: #2563eb;
            --blue-soft: #dbeafe;
            --amber: #d97706;
            --amber-soft: #fef3c7;
            --red: #dc2626;
            --red-soft: #fee2e2;
            --green: #059669;
            --green-soft: #d1fae5;
            --violet: #7c3aed;
            --violet-soft: #ede9fe;
            --brand-start: #0f172a;
            --brand-end: #134e4a;
            --brand-contrast: #ecfeff;
            --sidebar: #0b1220;
            --sidebar-soft: rgba(255,255,255,.08);
            --sidebar-strong: rgba(255,255,255,.14);
            --shadow-sm: 0 1px 2px rgba(15, 23, 42, .06);
            --shadow: 0 10px 30px rgba(15, 23, 42, .08), 0 1px 3px rgba(15, 23, 42, .05);
            --shadow-lg: 0 22px 70px rgba(15, 23, 42, .14);
            --shadow-xl: 0 30px 90px rgba(15, 23, 42, .18);
            --focus: 0 0 0 3px rgba(13, 148, 136, .22);
            --radius: 16px;
            --radius-sm: 10px;
            --radius-lg: 24px;
            --transition: 180ms cubic-bezier(.2, .8, .2, 1);
            --font-ui: 'Inter', 'Segoe UI', system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
            --font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
            --content-max: 1680px;
            font-family: var(--font-ui);
        }
        body.dark {
            --bg: #0f172a;
            --page-gradient: linear-gradient(135deg, #0b1120 0%, #0f172a 55%, #102235 100%);
            --surface: #1e293b;
            --surface-soft: #1a2332;
            --surface-strong: #243044;
            --surface-raised: #243044;
            --surface-glass: rgba(30, 41, 59, .82);
            --surface-tint: rgba(20, 184, 166, .09);
            --ink: #e2e8f0;
            --muted: #94a3b8;
            --muted-strong: #cbd5e1;
            --line: #2d3a4d;
            --line-strong: #3b4d63;
            --brand-start: #020617;
            --brand-end: #0f766e;
            --brand-contrast: #ccfbf1;
        }
        body.dark .topbar { background: rgba(15, 23, 42, .78); }
        body.dark .search input { background: rgba(15, 23, 42, .74); }
        body.dark .search input:focus { background: #1e293b; }
        body.dark .search-clear:hover,
        body.dark .search-clear:focus-visible { background: #2d3a4d; color: var(--ink); }
        body.dark .btn { background: #2d3a4d; color: var(--ink); }
        body.dark .btn:hover { background: #3b4d63; }
        body.dark .btn.ghost { background: rgba(30, 41, 59, .72); border-color: var(--line); }
        body.dark .btn.ghost:hover { background: #2d3a4d; }
        body.dark .segmented { background: rgba(15, 23, 42, .72); }
        body.dark .table-wrap { background: var(--surface); }
        body.dark th { background: var(--surface-strong); color: #94a3b8; }
        body.dark tr:hover td { background: #243044; }
        body.dark .plate { background: #1a2332; border-color: var(--line-strong); }
        body.dark .model-pill { background: #1a2332; border-color: var(--line); color: #cbd5e1; }
        body.dark .model-pill:hover { background: #0f766e20; }
        body.dark .notice { background: #1a2332; border-color: var(--line); color: #94a3b8; }
        body.dark .modal-head, body.dark .modal-foot { background: #1a2332; }
        body.dark .catalog-make-head { background: #1a2332; }
        body.dark input, body.dark select, body.dark textarea { background: #1a2332; color: var(--ink); border-color: var(--line-strong); }
        body.dark .stat-chip { background: rgba(20, 184, 166, .16); color: #5eead4; }
        body.dark .count-pill { background: rgba(45, 58, 77, .86); color: #cbd5e1; }
        body.dark .metric { background: linear-gradient(180deg, rgba(30, 41, 59, .92), rgba(30, 41, 59, .74)); border-color: var(--line); }
        body.dark .bar-track { background: #2d3a4d; }
        body.dark .panel-head { background: rgba(26, 35, 50, .94); }
        body.dark label { color: #94a3b8; }
        body.dark .check-field { color: #94a3b8; }
        body.dark .loading-skeleton { background: #2d3a4d; }
        body.dark .items-table { border-color: var(--line); }
        body.dark .items-table input, body.dark .items-table select { background: #1a2332; }
        body.dark .s-closed { background: #243044; color: #94a3b8; }
        body.dark .a-done { background: #243044; color: #94a3b8; }
        body.dark .inspection-archived { background: #243044; color: #94a3b8; }
        body.dark .model-pill.muted-pill { background: #1a2332; }
        body.dark .toast { background: #334155; color: #e2e8f0; }
        body.dark .update-release { background: #1a2332; border-color: var(--line); }
        body.dark .update-card { background: linear-gradient(135deg, rgba(13, 148, 136, .14), rgba(59, 130, 246, .10)); }
        body.dark .command-palette { border-color: var(--line); }
        body.dark .deal-card { background: #1a2332; }
        body.dark .timeline-day { background: #1a2332; }
        body.dark .page-hero, body.dark .section-card.hero-card { background: linear-gradient(135deg, rgba(20, 184, 166, .16), rgba(37, 99, 235, .14)); }
        body.dark .context-pill,
        body.dark .hero-stat,
        body.dark .insight-card { background: linear-gradient(180deg, rgba(30,41,59,.92), rgba(26,35,50,.78)); border-color: var(--line); }
        body.dark .metric-icon,
        body.dark .insight-icon { background: rgba(20,184,166,.14); color: #5eead4; }
        @media (prefers-color-scheme: dark) {
            body:not(.light) {
                --bg: #0f172a;
                --surface: #1e293b;
                --surface-soft: #1a2332;
                --surface-strong: #243044;
                --surface-glass: rgba(30, 41, 59, .82);
                --ink: #e2e8f0;
                --muted: #94a3b8;
                --line: #2d3a4d;
                --line-strong: #3b4d63;
            }
        }
        * { box-sizing: border-box; }
        html { scroll-behavior: smooth; }
        html, body { height: 100%; }
        body {
            margin: 0;
            background:
                radial-gradient(circle at 16% -8%, rgba(13, 148, 136, .16), transparent 31vw),
                radial-gradient(circle at 84% 2%, rgba(37, 99, 235, .14), transparent 33vw),
                radial-gradient(circle at 55% 100%, rgba(124, 58, 237, .08), transparent 34vw),
                var(--page-gradient, var(--bg));
            color: var(--ink);
            font-size: 14px;
            line-height: 1.5;
            letter-spacing: -.01em;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
            display: flex;
            flex-direction: column;
        }
        body::before {
            content: "";
            position: fixed;
            inset: 0;
            pointer-events: none;
            z-index: -1;
            background-image:
                linear-gradient(rgba(15, 23, 42, .035) 1px, transparent 1px),
                linear-gradient(90deg, rgba(15, 23, 42, .035) 1px, transparent 1px);
            background-size: 42px 42px;
            mask-image: linear-gradient(to bottom, rgba(0,0,0,.72), transparent 78%);
        }
        body.dark::before { background-image: linear-gradient(rgba(255,255,255,.035) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.035) 1px, transparent 1px); }
        ::selection { background: var(--accent-soft); color: var(--accent-strong); }
        body.dark ::selection { background: rgba(20, 184, 166, .35); color: #ecfeff; }
        button, input, select, textarea { font: inherit; }
        button { border: 0; cursor: pointer; transition: background-color var(--transition), color var(--transition), border-color var(--transition), box-shadow var(--transition), transform var(--transition), opacity var(--transition); }
        button:focus-visible, a:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible {
            outline: none;
            box-shadow: var(--focus);
        }
        @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after {
                scroll-behavior: auto !important;
                animation: none !important;
                transition: none !important;
            }
        }
        a { color: inherit; text-decoration: none; }
        .skip-link {
            position: fixed;
            top: 14px;
            left: 14px;
            z-index: 100;
            transform: translateY(-150%);
            padding: 10px 14px;
            border-radius: 999px;
            background: var(--sidebar);
            color: #fff;
            box-shadow: var(--shadow-lg);
            font-weight: 800;
            transition: transform var(--transition);
        }
        .skip-link:focus-visible { transform: translateY(0); }
        .app { min-width: 0; min-height: 100%; display: grid; grid-template-columns: 292px minmax(0, 1fr); }
        .sidebar {
            min-width: 0;
            position: sticky;
            top: 0;
            height: 100vh;
            overflow-y: auto;
            background:
                radial-gradient(circle at 18% 4%, rgba(20, 184, 166, .22), transparent 34%),
                radial-gradient(circle at 86% 16%, rgba(37, 99, 235, .18), transparent 30%),
                linear-gradient(160deg, var(--brand-start), var(--brand-end));
            color: #fff;
            padding: 22px 16px;
            display: flex;
            flex-direction: column;
            gap: 20px;
            box-shadow: 14px 0 44px rgba(15, 23, 42, .14);
            z-index: 6;
            isolation: isolate;
        }
        .sidebar::after {
            content: "";
            position: absolute;
            inset: 12px;
            border: 1px solid rgba(255,255,255,.08);
            border-radius: 22px;
            pointer-events: none;
            z-index: -1;
        }
        .brand {
            min-height: 66px;
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 4px 8px 18px;
            border-bottom: 1px solid rgba(255,255,255,.12);
        }
        .brand-mark {
            width: 48px;
            height: 48px;
            border-radius: 16px;
            background:
                linear-gradient(135deg, rgba(255,255,255,.22), rgba(255,255,255,.04)),
                linear-gradient(135deg, var(--accent), #14b8a6);
            color: #fff;
            display: grid;
            place-items: center;
            font-weight: 900;
            font-size: 15px;
            letter-spacing: -.04em;
            box-shadow: 0 16px 36px rgba(20, 184, 166, .28);
        }
        .brand-title { font-size: 18px; font-weight: 850; letter-spacing: -.03em; }
        .brand-subtitle { font-size: 12px; color: rgba(255,255,255,.62); margin-top: 3px; }
        .nav { display: grid; gap: 6px; }
        .nav button {
            min-height: 46px;
            color: rgba(255,255,255,.76);
            background: transparent;
            text-align: left;
            padding: 10px 12px;
            border-radius: 14px;
            display: flex;
            align-items: center;
            gap: 11px;
            font-weight: 650;
            letter-spacing: -.015em;
            border: 1px solid transparent;
            transition: background-color var(--transition), color var(--transition), border-color var(--transition), box-shadow var(--transition), transform var(--transition);
        }
        .nav button:hover { color: #fff; background: var(--sidebar-soft); border-color: rgba(255,255,255,.08); }
        @media (hover: hover) {
            .nav button:hover { transform: translateX(3px); }
        }
        .nav button.active {
            color: #fff;
            background: linear-gradient(135deg, var(--sidebar-strong), rgba(20, 184, 166, .20));
            border-color: rgba(255,255,255,.13);
            font-weight: 800;
            box-shadow: inset 3px 0 0 #5eead4, 0 14px 30px rgba(0,0,0,.12);
        }
        .nav button:focus-visible { box-shadow: inset 3px 0 0 #5eead4, 0 0 0 3px rgba(20, 184, 166, .35); }
        .nav .icon {
            width: 28px;
            height: 28px;
            border-radius: 9px;
            display: grid;
            place-items: center;
            color: #bae6fd;
            background: rgba(255,255,255,.08);
            font-weight: 850;
            font-size: 13px;
            flex: 0 0 auto;
        }
        .nav-label { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
        .nav-badge {
            margin-left: auto;
            min-width: 24px;
            height: 24px;
            padding: 0 8px;
            border-radius: 999px;
            display: inline-grid;
            place-items: center;
            color: #ccfbf1;
            background: rgba(20,184,166,.16);
            border: 1px solid rgba(153,246,228,.22);
            font-size: 11px;
            font-weight: 900;
            font-variant-numeric: tabular-nums;
        }
        .nav-badge[hidden] { display: none; }
        .nav button.active .icon { color: #042f2e; background: #99f6e4; }
        .nav button.active .nav-badge { color: #042f2e; background: #ccfbf1; border-color: transparent; }
        .db-path {
            margin-top: auto;
            padding: 14px 10px 0;
            color: rgba(255,255,255,.56);
            font-size: 11px;
            overflow-wrap: anywhere;
            border-top: 1px solid rgba(255,255,255,.12);
        }
        .main { min-width: 0; display: flex; flex-direction: column; }
        .topbar {
            min-width: 0;
            min-height: 76px;
            background: rgba(255,255,255,.76);
            border-bottom: 1px solid rgba(203,213,225,.72);
            display: flex;
            align-items: center;
            gap: 16px;
            padding: 13px 28px;
            position: sticky;
            top: 0;
            z-index: 5;
            backdrop-filter: blur(18px) saturate(150%);
            -webkit-backdrop-filter: blur(18px) saturate(150%);
        }
        .title-block { min-width: 220px; display: grid; gap: 4px; }
        .topbar h1 { font-size: clamp(21px, 2vw, 26px); line-height: 1.15; margin: 0; font-weight: 850; letter-spacing: -.035em; }
        .view-subtitle { color: var(--muted); font-size: 12px; font-weight: 600; }
        .search { flex: 1; min-width: 240px; position: relative; }
        .search input {
            width: 100%;
            height: 44px;
            border: 1.5px solid rgba(203, 213, 225, .82);
            border-radius: 999px;
            padding: 0 46px 0 42px;
            background: rgba(255,255,255,.78);
            box-shadow: var(--shadow-sm);
            transition: background-color var(--transition), color var(--transition), border-color var(--transition), box-shadow var(--transition), transform var(--transition);
        }
        .search input:focus { border-color: var(--accent); box-shadow: var(--focus), var(--shadow); background: #fff; }
        .search span { position: absolute; left: 16px; top: 11px; color: var(--muted); font-size: 16px; }
        .search-clear {
            position: absolute;
            right: 8px;
            top: 6px;
            width: 30px;
            height: 30px;
            border: 0;
            border-radius: 999px;
            background: transparent;
            color: var(--muted);
            font-size: 20px;
            line-height: 1;
            cursor: pointer;
        }
        .search-clear:hover,
        .search-clear:focus-visible { background: #e2e8f0; color: var(--ink); outline: none; box-shadow: var(--focus); }
        .top-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
        .content { min-width: 0; width: min(100%, var(--content-max)); margin: 0 auto; padding: 28px clamp(18px, 3vw, 40px) 44px; display: grid; gap: 22px; }
        .context-strip {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 12px;
        }
        .context-pill {
            min-width: 0;
            position: relative;
            overflow: hidden;
            display: grid;
            gap: 3px;
            padding: 14px 16px 14px 18px;
            border: 1.5px solid rgba(203,213,225,.74);
            border-radius: 18px;
            background: linear-gradient(180deg, rgba(255,255,255,.82), rgba(255,255,255,.64));
            box-shadow: var(--shadow-sm);
        }
        .context-pill::before {
            content: "";
            position: absolute;
            inset: 0 auto 0 0;
            width: 4px;
            background: var(--accent);
        }
        .context-pill.warning::before { background: var(--amber); }
        .context-pill.danger::before { background: var(--red); }
        .context-pill.info::before { background: var(--blue); }
        .context-pill strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 15px; letter-spacing: -.025em; }
        .context-pill span { color: var(--muted); font-size: 12px; font-weight: 700; }
        .context-label { display: inline-flex; align-items: center; gap: 7px; color: var(--muted); font-size: 11px; font-weight: 900; text-transform: uppercase; letter-spacing: .06em; }
        .live-dot { width: 8px; height: 8px; border-radius: 999px; background: var(--green); box-shadow: 0 0 0 5px rgba(5,150,105,.13); }
        .app.offline .live-dot { background: var(--red); box-shadow: 0 0 0 5px rgba(220,38,38,.13); }
        .toolbar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            flex-wrap: wrap;
        }
        .toolbar-left, .toolbar-right { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
        .btn {
            min-height: 40px;
            padding: 0 15px;
            border-radius: 999px;
            background: rgba(241,245,249,.92);
            color: var(--ink);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 7px;
            white-space: nowrap;
            border: 1.5px solid rgba(203,213,225,.78);
            font-weight: 700;
            letter-spacing: -.015em;
            box-shadow: var(--shadow-sm);
            transition: background-color var(--transition), color var(--transition), border-color var(--transition), box-shadow var(--transition), transform var(--transition);
        }
        .btn:hover { background: #e2e8f0; border-color: var(--line-strong); box-shadow: var(--shadow); }
        @media (hover: hover) {
            .btn:hover { transform: translateY(-1px); }
        }
        .btn:focus-visible { border-color: var(--accent); }
        .btn:active { transform: translateY(0); }
        .btn.primary {
            background: linear-gradient(135deg, var(--accent), #14b8a6);
            color: #fff;
            border-color: transparent;
            box-shadow: 0 12px 26px var(--accent-glow);
        }
        .btn.primary:hover { background: linear-gradient(135deg, var(--accent-strong), var(--accent)); box-shadow: 0 16px 34px var(--accent-glow); }
        .btn.danger { background: #fef2f2; color: var(--red); border-color: #fecaca; box-shadow: none; }
        .btn.danger:hover { background: #fee2e2; }
        .btn.ghost { background: rgba(255,255,255,.78); border-color: rgba(203,213,225,.78); }
        .btn.ghost:hover { border-color: var(--line-strong); background: #fff; }
        .btn.icon { width: 40px; padding: 0; font-weight: 850; font-size: 16px; }
        .segmented {
            display: inline-flex;
            border: 1.5px solid var(--line);
            background: #f8fafc;
            border-radius: var(--radius-sm);
            padding: 4px;
            gap: 2px;
            overflow-x: auto;
            max-width: 100%;
        }
        .segmented button {
            min-height: 32px;
            padding: 0 12px;
            border-radius: 6px;
            background: transparent;
            color: var(--muted);
            flex: 0 0 auto;
            font-weight: 550;
        }
        .segmented button.active { background: var(--sidebar); color: #fff; box-shadow: var(--shadow-sm); }
        .kpi-grid { display: grid; grid-template-columns: repeat(4, minmax(190px, 1fr)); gap: 16px; }
        .ops-grid { display: grid; grid-template-columns: minmax(320px, 1.3fr) repeat(4, minmax(170px, .6fr)); gap: 16px; }
        .ops-card {
            min-width: 0;
            min-height: 118px;
            background: linear-gradient(180deg, var(--surface-glass), var(--surface));
            border: 1.5px solid rgba(203,213,225,.72);
            border-radius: var(--radius);
            padding: 18px;
            display: grid;
            align-content: space-between;
            gap: 12px;
            box-shadow: var(--shadow-sm);
            transition: box-shadow var(--transition), transform var(--transition), border-color var(--transition);
        }
        .ops-card:hover { box-shadow: var(--shadow); transform: translateY(-2px); border-color: var(--line-strong); }
        .ops-card strong { display: block; min-width: 0; font-size: 24px; line-height: 1.15; white-space: normal; word-break: break-word; font-weight: 850; letter-spacing: -.035em; }
        .ops-card strong, .metric strong, .panel-head h2, .catalog-make-head strong {
            overflow-wrap: anywhere;
        }
        .ops-card small { color: var(--muted); font-weight: 700; text-transform: uppercase; font-size: 11px; letter-spacing: .04em; }
        .ops-card.accent {
            position: relative;
            overflow: hidden;
            background:
                radial-gradient(circle at 88% 12%, rgba(255,255,255,.22), transparent 28%),
                linear-gradient(135deg, #134e4a, #0f766e 52%, #0f172a);
            color: #fff;
            border-color: rgba(20, 184, 166, .34);
            box-shadow: 0 18px 46px rgba(15, 118, 110, .24);
        }
        .ops-card.accent::after {
            content: "";
            position: absolute;
            width: 160px;
            height: 160px;
            right: -62px;
            bottom: -76px;
            border-radius: 999px;
            background: rgba(255,255,255,.14);
            pointer-events: none;
        }
        .ops-card.accent small { color: rgba(255,255,255,.65); }
        .ops-actions { display: flex; gap: 8px; flex-wrap: wrap; }
        .ops-card.accent .btn { background: rgba(255,255,255,.1); color: #fff; border-color: rgba(255,255,255,.15); }
        .ops-card.accent .btn:hover { background: rgba(255,255,255,.18); }
        .ops-card.accent .btn.primary { background: #fff; color: #134e4a; font-weight: 650; }
        .stat-chip {
            display: inline-flex;
            align-items: center;
            min-height: 28px;
            width: fit-content;
            padding: 0 10px;
            border-radius: 999px;
            background: #ccfbf1;
            color: var(--accent-strong);
            font-weight: 750;
            font-size: 12px;
        }
        .count-pill {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-height: 26px;
            min-width: 34px;
            padding: 0 10px;
            border-radius: 999px;
            background: #f1f5f9;
            color: #334155;
            font-weight: 750;
            font-size: 12px;
        }
        .catalog-summary {
            display: grid;
            grid-template-columns: minmax(240px, 1fr) repeat(3, minmax(150px, .35fr));
            gap: 14px;
        }
        .catalog-search {
            min-width: 280px;
            width: min(440px, 100%);
            position: relative;
        }
        .catalog-search input { padding-left: 36px; }
        .catalog-search span { position: absolute; left: 13px; top: 10px; color: var(--muted); font-size: 16px; }
        .catalog-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 14px;
        }
        .catalog-make {
            min-width: 0;
            background: var(--surface);
            border: 1.5px solid var(--line);
            border-radius: var(--radius);
            min-height: 120px;
            overflow: hidden;
            box-shadow: var(--shadow-sm);
            transition: box-shadow var(--transition);
        }
        .catalog-make:hover { box-shadow: var(--shadow); }
        .catalog-make-head {
            min-height: 50px;
            padding: 14px 15px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            background: var(--surface-soft);
            border-bottom: 1px solid var(--line);
        }
        .catalog-make-head strong {
            min-width: 0;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            font-weight: 700;
        }
        .model-list {
            padding: 14px;
            display: flex;
            align-content: flex-start;
            gap: 7px;
            flex-wrap: wrap;
        }
        .model-pill {
            display: inline-flex;
            align-items: center;
            min-height: 28px;
            max-width: 100%;
            padding: 0 10px;
            border-radius: 6px;
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            color: #334155;
            font-size: 12px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            transition: background-color var(--transition), color var(--transition), border-color var(--transition), box-shadow var(--transition), transform var(--transition);
        }
        .model-pill:hover { border-color: var(--accent); background: #f0fdfa; }
        .model-pill.muted-pill {
            color: var(--muted);
            background: #fff;
            border-style: dashed;
        }
        .metric {
            min-width: 0;
            position: relative;
            isolation: isolate;
            overflow: hidden;
            background: linear-gradient(180deg, var(--surface-glass), var(--surface));
            border: 1.5px solid rgba(203,213,225,.76);
            border-left: 4px solid var(--accent);
            border-radius: var(--radius);
            padding: 18px 18px 16px;
            min-height: 116px;
            box-shadow: var(--shadow-sm);
            transition: box-shadow var(--transition), transform var(--transition), border-color var(--transition);
        }
        .metric::after {
            content: "";
            position: absolute;
            width: 92px;
            height: 92px;
            right: -46px;
            top: -42px;
            border-radius: 999px;
            background: var(--surface-tint);
            z-index: -1;
        }
        .metric:hover { box-shadow: var(--shadow); transform: translateY(-2px); border-color: var(--line-strong); }
        .metric:nth-child(2), .metric.tone-blue { border-left-color: var(--blue); }
        .metric:nth-child(3), .metric.tone-warning { border-left-color: var(--amber); }
        .metric:nth-child(4), .metric.tone-danger { border-left-color: var(--red); }
        .metric.tone-success { border-left-color: var(--green); }
        .metric-top {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 10px;
            margin-bottom: 11px;
        }
        .metric small {
            color: var(--muted);
            display: block;
            margin: 0;
            font-weight: 800;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: .055em;
        }
        .metric-icon,
        .insight-icon {
            width: 34px;
            height: 34px;
            border-radius: 12px;
            display: grid;
            place-items: center;
            flex: 0 0 auto;
            background: var(--accent-soft);
            color: var(--accent-strong);
            font-size: 13px;
            font-weight: 900;
            box-shadow: inset 0 0 0 1px rgba(13,148,136,.12);
        }
        .metric { min-width: 0; }
        .metric strong { font-size: clamp(27px, 2.4vw, 34px); line-height: 1.05; display: block; font-weight: 850; letter-spacing: -.045em; }
        .metric .trend { margin-top: 11px; color: var(--muted); font-size: 12px; font-weight: 600; }
        body.compact .content { gap: 16px; }
        body.compact .metric { min-height: 94px; padding: 14px; }
        body.compact .metric strong { font-size: 26px; }
        body.compact .ops-card { min-height: 96px; padding: 14px; }
        body.compact .panel-body { padding: 14px; }
        body.compact .panel-head { min-height: 48px; padding: 12px 14px; }
        body.compact th, body.compact td { padding: 9px 11px; }
        body.compact .section-card.hero-card { padding: 22px; }
        .section-card {
            min-width: 0;
            background: linear-gradient(135deg, var(--surface-glass), var(--surface));
            border: 1.5px solid rgba(203,213,225,.74);
            border-radius: var(--radius);
            padding: 20px;
            box-shadow: var(--shadow-sm);
        }
        .section-card.compact { padding: 14px 16px; }
        .section-card.hero-card {
            position: relative;
            overflow: hidden;
            isolation: isolate;
            padding: clamp(22px, 3vw, 34px);
            border-radius: var(--radius-lg);
            background:
                radial-gradient(circle at 86% 12%, rgba(20, 184, 166, .18), transparent 26%),
                linear-gradient(135deg, rgba(255,255,255,.94), rgba(240,253,250,.86) 48%, rgba(239,246,255,.9));
            box-shadow: var(--shadow);
        }
        .section-card.hero-card::after {
            content: "";
            position: absolute;
            width: 260px;
            height: 260px;
            right: -92px;
            bottom: -130px;
            border-radius: 999px;
            background: linear-gradient(135deg, rgba(13,148,136,.16), rgba(37,99,235,.12));
            z-index: -1;
        }
        .hero-layout { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 24px; align-items: center; }
        .hero-eyebrow { display: inline-flex; align-items: center; width: fit-content; gap: 8px; margin-bottom: 10px; padding: 5px 10px; border-radius: 999px; background: var(--accent-soft); color: var(--accent-strong); font-size: 11px; font-weight: 850; text-transform: uppercase; letter-spacing: .08em; }
        .hero-eyebrow::before { content: ""; width: 7px; height: 7px; border-radius: 999px; background: currentColor; box-shadow: 0 0 0 4px rgba(13,148,136,.14); }
        .section-card h3 {
            margin: 0 0 4px;
            font-size: 16px;
            line-height: 1.25;
        }
        .section-card.hero-card h3 { font-size: clamp(28px, 4vw, 44px); line-height: .98; letter-spacing: -.06em; margin-bottom: 10px; max-width: 780px; }
        .section-card p { margin: 0; color: var(--muted); }
        .section-card.hero-card p { max-width: 760px; font-size: 15px; color: var(--muted-strong); }
        .hero-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }
        .hero-stat-stack { display: grid; grid-template-columns: repeat(2, minmax(128px, 1fr)); gap: 10px; min-width: min(360px, 100%); }
        .hero-stat { padding: 14px; border-radius: 16px; background: rgba(255,255,255,.72); border: 1px solid rgba(203,213,225,.75); box-shadow: var(--shadow-sm); }
        .hero-stat strong { display: block; font-size: 24px; line-height: 1.05; letter-spacing: -.045em; }
        .hero-stat span { display: block; margin-top: 5px; color: var(--muted); font-size: 12px; font-weight: 700; }
        .view-heading {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            flex-wrap: wrap;
            padding: 18px 20px;
            border: 1.5px solid rgba(203,213,225,.74);
            border-radius: var(--radius);
            background: linear-gradient(135deg, var(--surface-glass), rgba(255,255,255,.68));
            box-shadow: var(--shadow-sm);
        }
        body.dark .view-heading { background: linear-gradient(135deg, rgba(30,41,59,.92), rgba(30,41,59,.62)); }
        .view-heading h2 { margin: 0; font-size: clamp(20px, 2vw, 28px); line-height: 1.08; letter-spacing: -.045em; }
        .view-heading p { margin: 6px 0 0; max-width: 760px; color: var(--muted); font-weight: 600; }
        .view-meta { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
        .view-heading-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
        .insight-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 16px; }
        .insight-card {
            min-width: 0;
            display: grid;
            gap: 8px;
            padding: 16px;
            border: 1.5px solid rgba(203,213,225,.72);
            border-radius: var(--radius);
            background: linear-gradient(180deg, var(--surface-glass), var(--surface));
            box-shadow: var(--shadow-sm);
            transition: box-shadow var(--transition), transform var(--transition), border-color var(--transition);
        }
        .insight-card:hover { transform: translateY(-2px); box-shadow: var(--shadow); border-color: var(--line-strong); }
        .insight-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
        .insight-card strong { font-size: 18px; letter-spacing: -.025em; }
        .insight-card small { color: var(--muted); font-weight: 800; text-transform: uppercase; letter-spacing: .055em; font-size: 11px; }
        .grid-2 { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(360px, .6fr); gap: 18px; align-items: start; }
        .panel {
            min-width: 0;
            background: var(--surface);
            border: 1.5px solid rgba(203,213,225,.74);
            border-radius: var(--radius);
            overflow: hidden;
            box-shadow: var(--shadow-sm);
        }
        .panel-head {
            min-height: 56px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            padding: 15px 18px;
            border-bottom: 1px solid var(--line);
            background: linear-gradient(180deg, var(--surface-soft), rgba(248,250,252,.78));
        }
        .panel-head h2 { font-size: 16px; margin: 0; font-weight: 850; letter-spacing: -.025em; }
        .panel-body { padding: 18px; }
        .table-wrap {
            min-width: 0;
            overflow: auto;
            position: relative;
            background: var(--surface);
            border: 1.5px solid rgba(203,213,225,.74);
            border-radius: var(--radius);
            box-shadow: var(--shadow-sm);
        }
        .scroll-hint {
            display: none;
            position: sticky;
            right: 0;
            bottom: 0;
            width: max-content;
            margin-left: auto;
            padding: 4px 9px;
            border-top-left-radius: 8px;
            background: linear-gradient(90deg, rgba(255,255,255,.65), var(--surface));
            color: var(--muted);
            font-size: 11px;
            font-weight: 700;
            pointer-events: none;
        }
        .has-horizontal-overflow > .scroll-hint { display: block; }
        body.dark .scroll-hint {
            background: linear-gradient(90deg, rgba(30,41,59,.65), var(--surface));
        }
        .panel > .table-wrap { border: 0; border-radius: 0; box-shadow: none; }
        table { width: 100%; border-collapse: collapse; min-width: 790px; }
        table.compact-table { min-width: 620px; }
        th, td {
            padding: 12px 14px;
            border-bottom: 1px solid var(--line);
            text-align: left;
            vertical-align: top;
        }
        th {
            background: var(--surface-strong);
            color: #475569;
            font-size: 11px;
            text-transform: uppercase;
            font-weight: 750;
            letter-spacing: .05em;
            position: sticky;
            top: 0;
            z-index: 1;
        }
        tbody tr:last-child td { border-bottom: 0; }
        tbody tr { transition: background var(--transition); }
        tr:hover td { background: #f8fafc; }
        td.money, th.money { text-align: right; font-variant-numeric: tabular-nums; }
        .cell-title { display: grid; gap: 3px; }
        .cell-title strong { letter-spacing: -.02em; }
        .plate {
            display: inline-flex;
            align-items: center;
            min-height: 28px;
            width: fit-content;
            padding: 0 10px;
            border: 1.5px solid #cbd5e1;
            border-radius: 6px;
            background: #fff;
            font-weight: 750;
            font-variant-numeric: tabular-nums;
        }
        .muted { color: var(--muted); }
        .notice {
            border: 1.5px solid #e2e8f0;
            background: #f8fafc;
            color: #475569;
            border-radius: var(--radius-sm);
            padding: 16px;
        }
        .status {
            display: inline-flex;
            align-items: center;
            min-height: 26px;
            padding: 0 10px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 750;
        }
        .s-new { background: var(--blue-soft); color: #1d4ed8; }
        .s-diagnostics, .s-estimate { background: var(--amber-soft); color: #92400e; }
        .s-approved, .s-in_progress { background: var(--green-soft); color: #065f46; }
        .s-done { background: #cffafe; color: #0e7490; }
        .s-closed { background: #f1f5f9; color: #475569; }
        .s-cancelled { background: var(--red-soft); color: var(--red); }
        .a-scheduled { background: var(--blue-soft); color: #1d4ed8; }
        .a-confirmed, .a-arrived { background: var(--green-soft); color: #065f46; }
        .a-done { background: #f1f5f9; color: #475569; }
        .a-no_show, .a-cancelled { background: var(--red-soft); color: var(--red); }
        .item-approved { background: var(--green-soft); color: #065f46; }
        .item-deferred { background: var(--amber-soft); color: #92400e; }
        .item-declined { background: var(--red-soft); color: var(--red); }
        .inspection-draft { background: var(--blue-soft); color: #1d4ed8; }
        .inspection-ready, .inspection-sent { background: var(--green-soft); color: #065f46; }
        .inspection-archived { background: #f1f5f9; color: #475569; }
        .condition-ok { background: var(--green-soft); color: #065f46; }
        .condition-attention { background: var(--amber-soft); color: #92400e; }
        .condition-critical { background: var(--red-soft); color: var(--red); }
        .priority { color: var(--muted); font-size: 12px; margin-top: 2px; }
        .priority.high, .priority.urgent { color: var(--red); font-weight: 750; }
        .stack { display: grid; gap: 10px; }
        .row-actions { display: flex; gap: 6px; justify-content: flex-end; }
        .modal-foot .btn.danger { margin-right: auto; }
        .btn:disabled { opacity: .5; cursor: not-allowed; transform: none !important; }
        .empty {
            padding: 32px;
            text-align: center;
            color: var(--muted);
            place-items: center;
            gap: 8px;
        }
        div.empty { display: grid; }
        td.empty { text-align: center; }
        .empty::before {
            content: "";
            width: 34px;
            height: 34px;
            border-radius: 10px;
            background: linear-gradient(135deg, rgba(13, 148, 136, .16), rgba(59, 130, 246, .12));
            border: 1px solid var(--line);
        }
        td.empty::before { display: none; }
        .empty strong { display: block; color: var(--ink); font-size: 15px; }
        .empty span { display: block; margin-top: 4px; }
        .loading-state {
            min-height: 220px;
            display: grid;
            place-items: center;
            gap: 14px;
            color: var(--muted);
        }
        .loading-mark {
            width: 44px;
            height: 44px;
            border-radius: 14px;
            background: linear-gradient(135deg, var(--accent), #14b8a6);
            box-shadow: 0 10px 30px var(--accent-glow);
            animation: breathe 1.4s ease-in-out infinite;
        }
        @keyframes breathe { 0%, 100% { transform: scale(.96); opacity: .82; } 50% { transform: scale(1); opacity: 1; } }
        .bars { display: grid; gap: 12px; }
        .bar { display: grid; grid-template-columns: 140px 1fr minmax(50px, auto); gap: 12px; align-items: center; }
        .bar-track { height: 12px; border-radius: 999px; background: #e2e8f0; overflow: hidden; }
        .bar-fill { height: 100%; background: linear-gradient(90deg, var(--accent), #14b8a6); border-radius: 999px; transition: width 400ms ease; }
        .modal-backdrop {
            position: fixed;
            inset: 0;
            background: rgba(15, 23, 42, .5);
            display: none;
            align-items: center;
            justify-content: center;
            padding: 20px;
            z-index: 20;
            backdrop-filter: blur(4px);
            -webkit-backdrop-filter: blur(4px);
        }
        .modal-backdrop.open { display: flex; animation: fadeIn 180ms ease; }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        .modal {
            width: min(1040px, 100%);
            max-height: calc(100vh - 40px);
            background: var(--surface);
            border-radius: var(--radius);
            box-shadow: var(--shadow-lg);
            display: flex;
            flex-direction: column;
            overflow: hidden;
            animation: slideUp 220ms ease;
        }
        @keyframes slideUp { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: translateY(0); } }
        .modal.small { width: min(680px, 100%); }
        .modal.wide { width: min(1180px, 100%); }
        .modal-head {
            min-height: 60px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            padding: 0 18px;
            border-bottom: 1px solid var(--line);
            background: var(--surface-soft);
        }
        .modal-title { font-size: 17px; font-weight: 750; }
        .modal-body { padding: 18px; overflow: auto; }
        .modal-foot {
            display: flex;
            justify-content: flex-end;
            gap: 8px;
            padding: 14px 18px;
            border-top: 1px solid var(--line);
            background: var(--surface-soft);
        }
        .form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
        .form-grid.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
        .field { display: grid; gap: 5px; }
        label { color: #475569; font-size: 12px; font-weight: 700; }
        .check-field {
            min-height: 40px;
            display: flex;
            align-items: center;
            gap: 8px;
            padding-top: 18px;
            color: #475569;
        }
        .check-field input { width: 17px; height: 17px; accent-color: var(--accent); }
        input, select, textarea {
            width: 100%;
            border: 1.5px solid var(--line-strong);
            border-radius: var(--radius-sm);
            background: #fff;
            color: var(--ink);
            padding: 9px 11px;
            min-height: 40px;
            transition: border-color var(--transition), box-shadow var(--transition);
        }
        textarea { resize: vertical; min-height: 80px; line-height: 1.4; }
        input:focus, select:focus, textarea:focus {
            outline: none;
            box-shadow: var(--focus);
            border-color: var(--accent);
        }
        .span-2 { grid-column: span 2; }
        .span-3 { grid-column: span 3; }
        .items-table { border: 1.5px solid var(--line); border-radius: var(--radius-sm); overflow: auto; position: relative; }
        .items-table table { min-width: 1280px; }
        .inspection-items table { min-width: 1180px; }
        .items-table input, .items-table select { min-height: 36px; padding: 6px 8px; }
        .source-select { min-width: 220px; }
        .source-note { color: var(--muted); font-size: 12px; line-height: 1.35; margin-top: 4px; max-width: 240px; }
        .totals { margin-top: 14px; margin-left: auto; width: min(390px, 100%); display: grid; gap: 8px; }
        .totals div { display: flex; justify-content: space-between; gap: 12px; }
        .totals .grand { border-top: 1.5px solid var(--line); padding-top: 10px; font-size: 17px; font-weight: 700; }
        .toast {
            position: fixed;
            right: 20px;
            bottom: 20px;
            background: #0f172a;
            color: #fff;
            padding: 13px 18px;
            border-radius: var(--radius-sm);
            display: none;
            z-index: 30;
            max-width: 440px;
            box-shadow: 0 16px 40px rgba(0,0,0,.25);
            font-weight: 550;
            animation: slideUp 200ms ease;
        }
        .toast.show { display: block; }
        .toast.error { background: var(--red); color: #fff; }
        .command-palette-backdrop {
            position: fixed;
            inset: 0;
            z-index: 40;
            display: none;
            align-items: flex-start;
            justify-content: center;
            padding: 9vh 18px 18px;
            background: rgba(15, 23, 42, .42);
            backdrop-filter: blur(6px);
            -webkit-backdrop-filter: blur(6px);
        }
        .command-palette-backdrop.open { display: flex; animation: fadeIn 160ms ease; }
        .command-palette {
            width: min(720px, 100%);
            border: 1.5px solid rgba(255,255,255,.18);
            border-radius: 16px;
            background: var(--surface);
            box-shadow: var(--shadow-lg);
            overflow: hidden;
        }
        .command-palette-head {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 12px 14px;
            border-bottom: 1px solid var(--line);
            background: var(--surface-soft);
        }
        .command-palette-head input {
            border: 0;
            box-shadow: none !important;
            background: transparent !important;
            padding: 8px 0;
            min-height: 38px;
            font-size: 16px;
        }
        .command-palette-list { max-height: 420px; overflow: auto; padding: 8px; }
        .command-item {
            width: 100%;
            min-height: 54px;
            border-radius: 10px;
            background: transparent;
            color: var(--ink);
            display: grid;
            grid-template-columns: 32px 1fr auto;
            align-items: center;
            gap: 12px;
            padding: 10px;
            text-align: left;
        }
        .command-item:hover,
        .command-item.active { background: var(--surface-soft); }
        .command-item kbd {
            border: 1px solid var(--line);
            border-bottom-width: 2px;
            border-radius: 6px;
            padding: 2px 6px;
            color: var(--muted);
            background: var(--surface);
            font: 700 11px/1.4 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        }
        .pipeline-board {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
            gap: 14px;
        }
        .pipeline-column {
            min-width: 0;
            border: 1.5px solid rgba(203,213,225,.74);
            border-radius: var(--radius);
            background: linear-gradient(180deg, var(--surface-glass), var(--surface));
            box-shadow: var(--shadow-sm);
            overflow: hidden;
        }
        .pipeline-head {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            padding: 13px 15px;
            border-bottom: 1px solid var(--line);
            background: var(--surface-soft);
        }
        .pipeline-head strong { letter-spacing: -.02em; }
        .pipeline-body { padding: 14px; display: grid; gap: 11px; }
        .deal-card {
            border: 1px solid rgba(203,213,225,.72);
            border-radius: 14px;
            padding: 12px;
            background: linear-gradient(180deg, var(--surface-glass), var(--surface));
            display: grid;
            gap: 7px;
            box-shadow: var(--shadow-sm);
        }
        .deal-card.overdue { border-color: #fecaca; box-shadow: inset 3px 0 0 var(--red), var(--shadow-sm); }
        .deal-card button { justify-self: start; }
        .action-center .panel-body { padding: 0; }
        .action-stream { display: grid; gap: 0; }
        .action-card {
            min-width: 0;
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 14px;
            padding: 16px 18px;
            border-bottom: 1px solid var(--line);
            background: linear-gradient(90deg, rgba(13,148,136,.08), transparent 48%);
        }
        .action-card:last-child { border-bottom: 0; }
        .action-card strong { display: block; font-size: 14px; line-height: 1.3; }
        .action-card p { margin: 5px 0 0; color: var(--muted); }
        .action-meta { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; margin-top: 9px; }
        .action-priority {
            display: inline-flex;
            align-items: center;
            min-height: 24px;
            padding: 0 9px;
            border-radius: 999px;
            font-size: 11px;
            font-weight: 850;
            text-transform: uppercase;
            letter-spacing: .04em;
            background: #ecfeff;
            color: #0e7490;
        }
        .action-card.danger { box-shadow: inset 4px 0 0 var(--red); background: linear-gradient(90deg, rgba(220,38,38,.08), transparent 45%); }
        .action-card.warning { box-shadow: inset 4px 0 0 var(--amber); background: linear-gradient(90deg, rgba(217,119,6,.08), transparent 45%); }
        .action-card.success { box-shadow: inset 4px 0 0 var(--green); background: linear-gradient(90deg, rgba(5,150,105,.08), transparent 45%); }
        .action-card.info { box-shadow: inset 4px 0 0 var(--blue); }
        .action-card.danger .action-priority { background: #fee2e2; color: var(--red); }
        .action-card.warning .action-priority { background: #fef3c7; color: #92400e; }
        .action-card.success .action-priority { background: #d1fae5; color: #065f46; }
        .action-side { display: grid; justify-items: end; align-content: center; gap: 8px; min-width: 136px; }
        .action-score { color: var(--muted); font-size: 12px; font-weight: 750; font-variant-numeric: tabular-nums; }
        body.dark .action-card { background: linear-gradient(90deg, rgba(20,184,166,.08), transparent 45%); }
        body.dark .action-card.danger { background: linear-gradient(90deg, rgba(248,113,113,.12), transparent 45%); }
        body.dark .action-card.warning { background: linear-gradient(90deg, rgba(251,191,36,.12), transparent 45%); }
        body.dark .action-card.success { background: linear-gradient(90deg, rgba(52,211,153,.10), transparent 45%); }
        .timeline {
            display: grid;
            grid-template-columns: repeat(7, minmax(96px, 1fr));
            gap: 10px;
        }
        .timeline-day {
            min-width: 0;
            border: 1.5px solid rgba(203,213,225,.74);
            border-radius: var(--radius);
            background: linear-gradient(180deg, var(--surface-glass), var(--surface));
            padding: 13px;
            display: grid;
            gap: 10px;
            box-shadow: var(--shadow-sm);
        }
        .timeline-day.today { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-glow); }
        .timeline-day strong { display: flex; justify-content: space-between; gap: 8px; }
        .timeline-list { display: grid; gap: 6px; font-size: 12px; }
        .health-card {
            position: relative;
            overflow: hidden;
            isolation: isolate;
            background: linear-gradient(135deg, #0f766e, #1d4ed8);
            color: #fff;
        }
        .health-card::after {
            content: "";
            position: absolute;
            width: 180px;
            height: 180px;
            border-radius: 999px;
            right: -60px;
            top: -70px;
            background: rgba(255,255,255,.14);
            z-index: -1;
        }
        .health-card small,
        .health-card .trend { color: rgba(255,255,255,.72); }
        .health-card .metric-icon { background: rgba(255,255,255,.16); color: #fff; box-shadow: inset 0 0 0 1px rgba(255,255,255,.16); }
        .health-card strong { display: flex; align-items: baseline; gap: 6px; }
        .health-score { font-size: 34px; }
        .app.offline .topbar { border-bottom-color: var(--red); }
        .modal-backdrop.saving { cursor: progress; }
        .modal-backdrop.saving .modal { opacity: .88; }
        .modal-backdrop.saving .modal-body { pointer-events: none; }
        .modal-backdrop.saving .modal-foot { pointer-events: auto; }
        .field-error {
            color: var(--red);
            font-size: 12px;
            font-weight: 700;
            margin-top: 2px;
        }
        input.invalid, select.invalid, textarea.invalid { border-color: var(--red); }
        input.invalid:focus, select.invalid:focus, textarea.invalid:focus { box-shadow: 0 0 0 3px rgba(220, 38, 38, .18); }
        .row-warning {
            color: var(--amber);
            font-size: 12px;
            margin-top: 4px;
            font-weight: 650;
        }
        .modal-section {
            border: 1.5px solid var(--line);
            border-radius: var(--radius-sm);
            padding: 14px;
            background: var(--surface-soft);
        }
        .modal-section-title {
            margin: 0 0 10px;
            font-size: 13px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: .04em;
            color: var(--muted);
        }
        .update-card {
            display: grid;
            gap: 14px;
            border: 1.5px solid var(--line);
            border-radius: var(--radius);
            padding: 18px;
            background: linear-gradient(135deg, rgba(13, 148, 136, .10), rgba(59, 130, 246, .08));
        }
        .update-card h3 { margin: 0; font-size: 18px; }
        .update-card p { margin: 0; color: var(--muted); }
        .update-meta { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
        .update-release {
            border: 1.5px solid var(--line);
            border-radius: var(--radius-sm);
            background: #fff;
            padding: 14px;
            display: grid;
            gap: 10px;
        }
        .update-release h4 { margin: 0; font-size: 15px; }
        .update-release pre {
            margin: 0;
            max-height: 220px;
            overflow: auto;
            white-space: pre-wrap;
            color: var(--muted);
            font: inherit;
            line-height: 1.45;
        }
        .offline-banner,
        .error-banner {
            border: 1.5px solid #fecaca;
            color: #991b1b;
            background: #fef2f2;
            border-radius: var(--radius-sm);
            padding: 10px 12px;
            font-weight: 650;
        }
        .offline-banner { display: none; }
        .error-banner { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
        .error-banner span { min-width: min(100%, 260px); color: #7f1d1d; font-weight: 500; }
        .app.offline .offline-banner { display: block; }
        body.dark .offline-banner,
        body.dark .error-banner { background: rgba(127, 29, 29, .28); color: #fecaca; border-color: rgba(248, 113, 113, .45); }
        body.dark .error-banner span { color: #fecaca; }
        .shutdown-state {
            min-height: 100vh;
            display: grid;
            place-items: center;
            padding: 32px;
            background: var(--bg);
            color: var(--ink);
        }
        .shutdown-card {
            width: min(440px, 100%);
            background: var(--surface);
            border: 1.5px solid var(--line);
            border-radius: var(--radius);
            padding: 28px;
            box-shadow: var(--shadow-lg);
            text-align: center;
        }
        .shutdown-card h1 { margin: 0 0 8px; font-size: 24px; }
        .shutdown-card p { margin: 0; color: var(--muted); }
        .danger-text { color: var(--red); font-weight: 750; }
        .nowrap { white-space: nowrap; }
        .sr-only {
            position: absolute;
            width: 1px;
            height: 1px;
            padding: 0;
            margin: -1px;
            overflow: hidden;
            clip: rect(0, 0, 0, 0);
            white-space: nowrap;
            border: 0;
        }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .5; } }
        .loading-skeleton { animation: pulse 1.6s ease-in-out infinite; background: #e2e8f0; border-radius: var(--radius-sm); min-height: 24px; }
        @media (max-width: 1120px) {
            .app { grid-template-columns: 1fr; }
            .sidebar { position: sticky; top: 0; height: auto; max-height: 64px; z-index: 7; padding: 10px; overflow: hidden; }
            .sidebar::after { display: none; }
            .brand, .db-path { display: none; }
            .nav { display: flex; overflow: auto; scrollbar-width: thin; }
            .nav button { flex: 0 0 auto; }
            .topbar { top: 64px; min-height: 0; padding: 12px; flex-wrap: wrap; }
            .title-block { width: 100%; }
            .content { padding: 18px; width: 100%; }
            .context-strip, .kpi-grid, .grid-2, .ops-grid, .catalog-summary, .catalog-grid, .insight-grid { grid-template-columns: 1fr; }
            .hero-layout { grid-template-columns: 1fr; }
            .hero-stat-stack { min-width: 0; width: 100%; }
            .top-actions { width: 100%; justify-content: flex-start; }
        }
        @media (max-width: 680px) {
            .app, .sidebar, .main, .topbar, .content { width: 100%; max-width: 100vw; }
            .content { padding: 14px 12px 28px; }
            .search { min-width: 100%; }
            .catalog-search { min-width: 100%; }
            .btn { min-height: 44px; }
            .btn.icon { width: 44px; }
            .context-pill, .metric, .ops-card, .panel, .table-wrap { width: 100%; max-width: calc(100vw - 24px); }
            .hero-stat-stack { grid-template-columns: 1fr; }
            .section-card.hero-card h3 { font-size: 30px; }
            .ops-card strong { max-width: min(100%, 300px); font-size: 19px; }
            .ops-actions { display: grid; grid-template-columns: 1fr; }
            .ops-actions .btn { width: 100%; min-width: 0; }
            .kpi-grid { grid-template-columns: 1fr; }
            .form-grid, .form-grid.three { grid-template-columns: 1fr; }
            .span-2, .span-3 { grid-column: auto; }
            .bar { grid-template-columns: 1fr; gap: 6px; }
            .timeline { grid-template-columns: minmax(0, 1fr); }
            .action-card { grid-template-columns: 1fr; }
            .action-side { justify-items: start; min-width: 0; }
            .command-palette-backdrop { padding: 12px; align-items: stretch; }
            .command-palette-list { max-height: calc(100vh - 130px); }
            .modal-foot { justify-content: stretch; flex-wrap: wrap; }
            .modal-foot .btn { flex: 1 1 auto; }
            .table-wrap { -webkit-overflow-scrolling: touch; scroll-snap-type: x mandatory; }
            .items-table { max-width: calc(100vw - 36px); -webkit-overflow-scrolling: touch; }
            .items-table table { min-width: 1180px; }
            .inspection-items table { min-width: 1080px; }
            .row-actions { flex-wrap: wrap; }
        }
    </style>
</head>
<body>
<a class="skip-link" href="#content">К основному содержанию</a>
<div class="app">
    <aside class="sidebar">
        <div class="brand">
            <div class="brand-mark">CRM</div>
            <div>
                <div class="brand-title">СТО CRM</div>
                <div class="brand-subtitle">Автосервис</div>
            </div>
        </div>
        <nav class="nav" id="nav" aria-label="Основные разделы CRM">
            <button type="button" data-route="dashboard" class="active" aria-current="page"><span class="icon" aria-hidden="true">⌂</span><span class="nav-label">Панель</span><span class="nav-badge" data-nav-badge="dashboard" hidden></span></button>
            <button type="button" data-route="appointments"><span class="icon" aria-hidden="true">📅</span><span class="nav-label">Запись</span><span class="nav-badge" data-nav-badge="appointments" hidden></span></button>
            <button type="button" data-route="inspections"><span class="icon" aria-hidden="true">✓</span><span class="nav-label">Осмотры</span><span class="nav-badge" data-nav-badge="inspections" hidden></span></button>
            <button type="button" data-route="orders"><span class="icon" aria-hidden="true">№</span><span class="nav-label">Заказы</span><span class="nav-badge" data-nav-badge="orders" hidden></span></button>
            <button type="button" data-route="customers"><span class="icon" aria-hidden="true">👤</span><span class="nav-label">Клиенты</span></button>
            <button type="button" data-route="vehicles"><span class="icon" aria-hidden="true">🚘</span><span class="nav-label">Авто</span></button>
            <button type="button" data-route="catalog"><span class="icon" aria-hidden="true">◎</span><span class="nav-label">Каталог авто</span></button>
            <button type="button" data-route="inventory"><span class="icon" aria-hidden="true">▦</span><span class="nav-label">Склад</span><span class="nav-badge" data-nav-badge="inventory" hidden></span></button>
            <button type="button" data-route="reports"><span class="icon" aria-hidden="true">↗</span><span class="nav-label">Отчеты</span></button>
            <button type="button" data-route="updates"><span class="icon" aria-hidden="true">⬢</span><span class="nav-label">Обновления</span><span class="nav-badge" data-nav-badge="updates" hidden></span></button>
        </nav>
        <div class="db-path" id="dbPath"></div>
    </aside>
    <main class="main">
        <header class="topbar">
            <div class="title-block">
                <h1 id="viewTitle">Панель</h1>
                <div class="view-subtitle" id="viewSubtitle">Оперативная сводка автосервиса</div>
            </div>
            <div class="search">
                <span aria-hidden="true">⌕</span>
                <label class="sr-only" for="globalSearch">Поиск по клиентам, автомобилям, заказам и складу</label>
                <input id="globalSearch" placeholder="Поиск по клиентам, авто, заказам и складу" autocomplete="off" aria-label="Поиск по клиентам, автомобилям, заказам и складу">
                <button class="search-clear" id="clearSearch" type="button" aria-label="Очистить поиск" title="Очистить поиск" hidden>×</button>
            </div>
            <div class="top-actions">
                <button type="button" class="btn ghost" id="commandBtn" title="Командная палитра Ctrl+K" aria-label="Открыть командную палитру">⌘K</button>
                <button type="button" class="btn ghost" id="themeToggle" title="Тёмная/светлая тема" aria-label="Переключить тёмную или светлую тему" aria-pressed="false">◐</button>
                <button type="button" class="btn ghost" id="densityToggle" title="Плотность интерфейса" aria-label="Переключить плотность интерфейса" aria-pressed="false">↕</button>
                <button type="button" class="btn ghost" id="backupBtn" title="Создать резервную копию"><span aria-hidden="true">⇩</span>Резерв</button>
                <button type="button" class="btn icon" id="refreshBtn" title="Обновить" aria-label="Обновить данные">↻</button>
                <button type="button" class="btn danger" id="shutdownBtn" title="Остановить локальную CRM">Остановить</button>
            </div>
        </header>
        <section class="content" id="content">
            <div class="offline-banner" id="offlineBanner" role="alert">Нет связи с локальным сервером. Проверьте, что СТО CRM запущена, или нажмите «Обновить».</div>
            <div class="loading-state" role="status" aria-label="Загрузка данных CRM">
                <div class="loading-mark" aria-hidden="true"></div>
                <strong>Загружаем данные CRM...</strong>
                <span class="muted">Готовим рабочее пространство смены</span>
            </div>
        </section>
    </main>
</div>

<div class="modal-backdrop" id="modalBackdrop" role="presentation">
    <div class="modal" id="modal" role="dialog" aria-modal="true" aria-labelledby="modalTitle" tabindex="-1">
        <div class="modal-head">
            <div class="modal-title" id="modalTitle"></div>
            <button type="button" class="btn icon" id="modalClose" title="Закрыть" aria-label="Закрыть окно">×</button>
        </div>
        <div class="modal-body" id="modalBody"></div>
        <div class="modal-foot" id="modalFoot"></div>
    </div>
</div>
<div class="command-palette-backdrop" id="commandPalette" role="presentation">
    <div class="command-palette" role="dialog" aria-modal="true" aria-labelledby="commandPaletteTitle">
        <div class="command-palette-head">
            <span aria-hidden="true">⌘</span>
            <label class="sr-only" id="commandPaletteTitle" for="commandSearch">Командная палитра CRM</label>
            <input id="commandSearch" autocomplete="off" placeholder="Команда, раздел или действие…" aria-label="Командная палитра CRM">
            <button type="button" class="btn icon" id="commandClose" aria-label="Закрыть командную палитру">×</button>
        </div>
        <div class="command-palette-list" id="commandList" role="listbox" aria-label="Доступные команды CRM"></div>
    </div>
</div>
<div class="toast" id="toast" role="status" aria-live="polite" aria-atomic="true"></div>
<div class="sr-only" id="appStatus" role="status" aria-live="polite" aria-atomic="true"></div>

<script>
const state = {
    route: "dashboard",
    q: "",
    status: "all",
    catalogQ: "",
    data: null,
    updateStatus: null,
    updateLoading: false,
    updateInstalling: false,
    loadSeq: 0,
    lastError: "",
    orderDraftItems: [],
    inspectionDraftItems: [],
    modalDirty: false,
    saving: false,
    loading: false,
    lastLoadedAt: "",
    compactMode: false
};

const routes = {
    dashboard: "Панель",
    appointments: "Запись",
    inspections: "Осмотры",
    orders: "Заказы",
    customers: "Клиенты",
    vehicles: "Автомобили",
    catalog: "Каталог авто",
    inventory: "Склад",
    reports: "Отчеты",
    updates: "Обновления"
};

const routeSubtitles = {
    dashboard: "Оперативная сводка автосервиса",
    appointments: "Календарь приемки, подтверждения и неявки",
    inspections: "Цифровые мульти-точечные осмотры и рекомендации",
    orders: "Заказ-наряды, сроки и оплаты",
    customers: "Клиентская база и история обращений",
    vehicles: "Автомобили клиентов, VIN и пробеги",
    catalog: "Полный справочник производителей и моделей",
    inventory: "Остатки, цены и себестоимость",
    reports: "Финансы, загрузка и складские риски",
    updates: "Безопасная проверка и установка релизов GitHub"
};

const requestedRoute = new URLSearchParams(location.search).get("route") || location.hash.replace("#", "");
if (requestedRoute && routes[requestedRoute]) {
    state.route = requestedRoute;
}

const priorityLabels = { low: "Низкий", normal: "Обычный", high: "Высокий", urgent: "Срочно" };
const channelLabels = { phone: "Телефон", sms: "SMS", email: "Email", messenger: "Мессенджер", none: "Не писать" };
function channelLabel(key) {
    return (state.data?.preferred_channels || channelLabels)[key] || channelLabels[key] || key;
}
const appointmentStatusFallback = { scheduled: "Запланирована", confirmed: "Подтверждена", arrived: "Клиент приехал", done: "Завершена", no_show: "Не приехал", cancelled: "Отменена" };
const itemApprovalFallback = { approved: "Согласовано", deferred: "Отложено", declined: "Отказ" };
const inspectionStatusFallback = { draft: "Черновик", ready: "Готов", sent: "Отправлен клиенту", archived: "Архив" };
const inspectionConditionFallback = { ok: "Норма", attention: "Внимание", critical: "Критично" };

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, ch => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    }[ch]));
}

function money(value) {
    return new Intl.NumberFormat("ru-RU", { style: "currency", currency: "RUB", minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(value || 0));
}

function bytesText(value) {
    const bytes = Number(value || 0);
    if (!Number.isFinite(bytes) || bytes <= 0) return "—";
    const units = ["Б", "КБ", "МБ", "ГБ"];
    let size = bytes;
    let index = 0;
    while (size >= 1024 && index < units.length - 1) {
        size /= 1024;
        index += 1;
    }
    return `${size >= 10 || index === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[index]}`;
}

function exportUrl(entity) {
    return `/api/export/${encodeURIComponent(entity)}.csv`;
}

async function downloadCsv(entity) {
    const response = await fetch(exportUrl(entity), {
        headers: state.data?.app?.csrf_token ? { "X-CSRF-Token": state.data.app.csrf_token } : {},
        cache: "no-store"
    });
    if (!response.ok) {
        const contentType = response.headers.get("Content-Type") || "";
        const payload = contentType.includes("application/json") ? await response.json() : await response.text();
        const error = new Error(payload?.error || payload || "Не удалось экспортировать CSV");
        error.status = response.status;
        throw error;
    }
    const blob = await response.blob();
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^";]+)"?/i);
    const filename = match ? match[1] : `${entity}.csv`;
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast("CSV экспортирован");
}

function qty(value) {
    const number = num(value);
    return Number.isInteger(number) ? String(number) : number.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
}

function num(value, fallback = 0) {
    if (value === null || value === undefined || value === "") return fallback;
    const parsed = Number(String(value).replace(/\s+/g, "").replace(",", "."));
    return Number.isFinite(parsed) ? parsed : fallback;
}

function dateShort(value) {
    if (!value) return "";
    const parsed = new Date(String(value).replace(" ", "T"));
    if (Number.isNaN(parsed.getTime())) return String(value).slice(0, 16);
    return parsed.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function inputDateValue(value) {
    if (!value) return "";
    return String(value).replace(" ", "T").slice(0, 16);
}

function vehicleName(vehicle) {
    if (!vehicle) return "";
    return [vehicle.make, vehicle.model, vehicle.year, vehicle.plate].filter(Boolean).join(" ");
}

function orderVehicle(order) {
    return [order.vehicle_make, order.vehicle_model, order.vehicle_year, order.vehicle_plate].filter(Boolean).join(" ");
}

function inspectionVehicle(inspection) {
    return [inspection.vehicle_make, inspection.vehicle_model, inspection.vehicle_year, inspection.vehicle_plate].filter(Boolean).join(" ");
}

function appointmentVehicle(appointment) {
    return [appointment.vehicle_make, appointment.vehicle_model, appointment.vehicle_year, appointment.vehicle_plate].filter(Boolean).join(" ");
}

function classToken(value) {
    return String(value ?? "").toLowerCase().replace(/[^a-z0-9_-]+/g, "-") || "unknown";
}

function formatClockTime(value) {
    const parsed = value ? new Date(value) : new Date();
    if (Number.isNaN(parsed.getTime())) return "—";
    return parsed.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}

function contextPill(label, value, hint, tone = "") {
    const toneClass = tone ? ` ${classToken(tone)}` : "";
    return `<article class="context-pill${toneClass}" aria-label="${esc(`${label}: ${value}. ${hint}`)}"><div class="context-label"><span class="live-dot" aria-hidden="true"></span>${esc(label)}</div><strong>${esc(value)}</strong><span>${esc(hint)}</span></article>`;
}

function contextStripHtml() {
    if (!state.data) return "";
    const r = state.data.reports || {};
    const riskCount = Number(r.overdue_orders_count || 0) + Number(r.inspection_alerts_count || 0) + Number(r.low_stock_count || 0);
    const riskTone = riskCount > 0 ? (riskCount > 3 ? "danger" : "warning") : "success";
    return `<section class="context-strip" aria-label="Операционный статус CRM">
        ${contextPill("Смена", `${Math.max(0, Math.min(100, Number(r.business_health_score || 0)))}/100 · ${r.business_health_label || "Контроль"}`, "Индекс здоровья сервиса", riskTone)}
        ${contextPill("Воронка", money(r.pipeline_value || 0), `${r.active_orders || 0} активных заказов`, "info")}
        ${contextPill("К оплате", money(r.due_total || 0), "Дебиторская задолженность", Number(r.due_total || 0) > 0 ? "warning" : "success")}
        ${contextPill("Обновлено", formatClockTime(state.lastLoadedAt), `Онлайн · ${state.data.app?.version || ""}`, "success")}
    </section>`;
}

function statusBadge(status) {
    const label = state.data?.statuses?.[status] || status;
    return `<span class="status s-${classToken(status)}">${esc(label)}</span>`;
}

function appointmentStatusBadge(status) {
    const label = state.data?.appointment_statuses?.[status] || appointmentStatusFallback[status] || status;
    return `<span class="status a-${classToken(status)}">${esc(label)}</span>`;
}

function itemApprovalBadge(status) {
    const label = state.data?.item_approval_statuses?.[status] || itemApprovalFallback[status] || status;
    return `<span class="status item-${classToken(status)}">${esc(label)}</span>`;
}

function inspectionStatusBadge(status) {
    const label = state.data?.inspection_statuses?.[status] || inspectionStatusFallback[status] || status;
    return `<span class="status inspection-${classToken(status)}">${esc(label)}</span>`;
}

function inspectionConditionBadge(status) {
    const label = state.data?.inspection_conditions?.[status] || inspectionConditionFallback[status] || status;
    return `<span class="status condition-${classToken(status)}">${esc(label)}</span>`;
}

function announce(message, urgent = false) {
    const status = $("#appStatus");
    if (!status) return;
    status.setAttribute("aria-live", urgent ? "assertive" : "polite");
    status.textContent = "";
    requestAnimationFrame(() => { status.textContent = message; });
}

function toast(message, type = "info") {
    const node = $("#toast");
    const isError = type === "error";
    node.textContent = message;
    node.classList.toggle("error", isError);
    node.setAttribute("role", isError ? "alert" : "status");
    node.setAttribute("aria-live", isError ? "assertive" : "polite");
    node.classList.add("show");
    announce(message, isError);
    clearTimeout(node.timer);
    node.timer = setTimeout(() => node.classList.remove("show"), isError ? 5200 : 3200);
}

function clearAllFormErrors(form) {
    if (!form) return;
    $$(".invalid", form).forEach(clearFormError);
    $$(".field-error", form).forEach(node => node.remove());
}

function applyFormError(error) {
    const form = $("#entityForm") || $("#orderForm") || $("#inspectionForm");
    if (!form) return;
    clearAllFormErrors(form);
    const message = error?.message || String(error || "");
    let target = null;
    let matchedName = "";
    const lower = message.toLocaleLowerCase("ru-RU");
    const hints = [
        ["email", ["email", "почт"]],
        ["vin", ["vin"]],
        ["year", ["год"]],
        ["scheduled_at", ["дата", "время", "запис"]],
        ["promised_at", ["срок"]],
        ["customer_id", ["клиент"]],
        ["vehicle_id", ["автомоб"]],
        ["inventory_id", ["склад", "позици"]],
        ["title", ["наименование", "запчаст"]],
        ["quantity", ["количество"]],
        ["unit_price", ["цена"]],
        ["name", ["имя", "название"]]
    ];
    for (const [name, tokens] of hints) {
        if (tokens.some(token => lower.includes(token))) {
            matchedName = name;
            target = form.elements[name] || form.querySelector(`[data-item="${name}"], [data-inspection-item="${name}"]`);
            break;
        }
    }
    if (window.RadioNodeList && target instanceof RadioNodeList) target = target[0];
    if (!(target instanceof HTMLElement) && matchedName) target = form.querySelector(`[data-item="${matchedName}"], [data-inspection-item="${matchedName}"]`);
    if (!(target instanceof HTMLElement)) target = form.querySelector("input, select, textarea");
    if (!target) return;
    target.classList.add("invalid");
    target.setAttribute("aria-invalid", "true");
    const id = `${target.name || target.id || "field"}-error`;
    const previous = (target.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean).filter(token => token !== id);
    target.dataset.errorDescribedby = id;
    target.setAttribute("aria-describedby", [...previous, id].join(" "));
    const errorNode = document.createElement("div");
    errorNode.className = "field-error";
    errorNode.id = id;
    errorNode.textContent = message;
    (target.closest(".field") || target.parentElement)?.append(errorNode);
    target.focus({ preventScroll: false });
}

function clearFormError(target) {
    if (!target) return;
    target.classList.remove("invalid");
    target.removeAttribute("aria-invalid");
    const errorId = target.dataset.errorDescribedby;
    if (errorId) document.getElementById(errorId)?.remove();
    const describedBy = (target.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean).filter(token => token !== errorId);
    if (describedBy.length) target.setAttribute("aria-describedby", describedBy.join(" "));
    else target.removeAttribute("aria-describedby");
    delete target.dataset.errorDescribedby;
}

async function api(path, options = {}, retries = null) {
    const method = String(options.method || "GET").toUpperCase();
    const maxRetries = retries ?? (method === "GET" ? 2 : 0);
    for (let attempt = 0; attempt <= maxRetries; attempt++) {
        try {
            const headers = { ...(options.headers || {}) };
            if (method !== "GET") {
                headers["Content-Type"] = headers["Content-Type"] || "application/json";
                if (state.data?.app?.csrf_token) headers["X-CSRF-Token"] = state.data.app.csrf_token;
            }
            const response = await fetch(path, {
                ...options,
                headers
            });
            const contentType = response.headers.get("Content-Type") || "";
            const data = contentType.includes("application/json") ? await response.json() : await response.text();
            if (!response.ok) {
                const error = new Error(data?.error || data || "Ошибка запроса");
                error.status = response.status;
                error.retryable = response.status >= 500;
                throw error;
            }
            return data;
        } catch (error) {
            const retryable = error?.retryable === true || !Number(error?.status || 0);
            if (attempt === maxRetries || !retryable) throw error;
            await new Promise(r => setTimeout(r, 400 * (attempt + 1)));
        }
    }
}

function setLoadingState(isLoading) {
    state.loading = isLoading;
    const content = $("#content");
    if (content) content.setAttribute("aria-busy", String(isLoading));
    $("#refreshBtn")?.toggleAttribute("disabled", isLoading);
}

async function loadData() {
    const seq = ++state.loadSeq;
    setLoadingState(true);
    const params = new URLSearchParams({ q: state.q, status: state.status });
    try {
        const data = await api(`/api/bootstrap?${params}`);
        if (seq !== state.loadSeq) return;
        state.data = data;
        state.lastLoadedAt = new Date().toISOString();
        state.lastError = "";
        setOnlineState(true);
        $("#dbPath").textContent = `База: ${state.data.app.db_path}`;
        $("#dbPath").title = state.data.app.db_directory ? `Папка базы: ${state.data.app.db_directory}` : "";
        render();
        updateSearchClear();
        announce(`Данные обновлены. Раздел: ${routes[state.route]}.`);
    } finally {
        if (seq === state.loadSeq) setLoadingState(false);
    }
}

function setRoute(route, updateUrl = true) {
    if (!routes[route]) return;
    const previousRoute = state.route;
    state.route = route;
    if (route === "updates" && !state.updateStatus && !state.updateLoading) {
        window.setTimeout(() => checkForUpdates(false).catch(showError), 0);
    }
    if (updateUrl) {
        const url = new URL(location.href);
        url.searchParams.set("route", route);
        url.hash = "";
        history.pushState({ route }, "", url);
    }
    $("#viewTitle").textContent = routes[route];
    $("#viewSubtitle").textContent = routeSubtitles[route] || "";
    $$("#nav button").forEach(button => {
        const active = button.dataset.route === route;
        button.classList.toggle("active", active);
        if (active) button.setAttribute("aria-current", "page");
        else button.removeAttribute("aria-current");
    });
    render();
    if (previousRoute !== route) {
        const prefersReducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        $("#content")?.scrollIntoView({ behavior: prefersReducedMotion ? "auto" : "smooth", block: "start" });
        announce(`Открыт раздел ${routes[route]}.`);
    }
}

function routeFromLocation() {
    const params = new URLSearchParams(location.search);
    const requested = params.get("route") || location.hash.replace("#", "");
    return routes[requested] ? requested : "dashboard";
}

function render() {
    if (!state.data) return;
    const content = $("#content");
    const renderers = {
        dashboard: renderDashboard,
        appointments: renderAppointments,
        inspections: renderInspections,
        orders: renderOrders,
        customers: renderCustomers,
        vehicles: renderVehicles,
        catalog: renderCatalog,
        inventory: renderInventory,
        reports: renderReports,
        updates: renderUpdates
    };
    const busy = content.getAttribute("aria-busy") || "false";
    content.innerHTML = `${offlineBannerHtml()}${errorBannerHtml()}${contextStripHtml()}${renderers[state.route]()}`;
    content.setAttribute("aria-busy", busy);
    bindViewActions(content);
    bindCatalogFilter(content);
    updateScrollHints(content);
    updateNavigationBadges();
}

function updateScrollHints(root = document) {
    const refresh = () => {
        $$(".table-wrap, .items-table", root).forEach(container => {
            if (!container.querySelector(":scope > .scroll-hint")) {
                const hint = document.createElement("div");
                hint.className = "scroll-hint";
                hint.setAttribute("aria-hidden", "true");
                hint.textContent = "Прокрутите вправо →";
                container.append(hint);
            }
            let srHint = container.querySelector(":scope > .scroll-hint-sr");
            if (!srHint) {
                srHint = document.createElement("div");
                srHint.className = "sr-only scroll-hint-sr";
                srHint.id = `scrollHint${Math.random().toString(36).slice(2)}`;
                srHint.textContent = "Таблица прокручивается горизонтально. Используйте Shift и колесо мыши, тач-жест или горизонтальную прокрутку клавиатурой.";
                container.append(srHint);
            }
            const hasOverflow = container.scrollWidth > container.clientWidth + 1;
            container.classList.toggle("has-horizontal-overflow", hasOverflow);
            if (hasOverflow) {
                container.setAttribute("tabindex", container.getAttribute("tabindex") || "0");
                const describedBy = new Set((container.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean));
                describedBy.add(srHint.id);
                container.setAttribute("aria-describedby", [...describedBy].join(" "));
            } else {
                const describedBy = (container.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean).filter(id => id !== srHint.id);
                if (describedBy.length) container.setAttribute("aria-describedby", describedBy.join(" "));
                else container.removeAttribute("aria-describedby");
                if (container.getAttribute("tabindex") === "0") container.removeAttribute("tabindex");
            }
        });
    };
    refresh();
    requestAnimationFrame(refresh);
}

function offlineBannerHtml() {
    return `<div class="offline-banner" role="alert">Нет связи с локальным сервером. Проверьте, что СТО CRM запущена, или нажмите «Обновить».</div>`;
}

function errorBannerHtml() {
    if (!state.lastError) return "";
    return `<div class="error-banner" role="alert"><strong>Последнее действие не выполнено.</strong><span>${esc(state.lastError)}</span><button class="btn ghost" type="button" data-action="dismiss-error">Скрыть</button></div>`;
}

function setOnlineState(isOnline) {
    const app = $(".app");
    if (app) app.classList.toggle("offline", !isOnline);
}

function updateNavigationBadges() {
    const r = state.data?.reports || {};
    const badgeValues = {
        dashboard: r.action_plan_total || 0,
        appointments: r.appointments_today_count || 0,
        inspections: r.inspection_alerts_count || 0,
        orders: r.active_orders || 0,
        inventory: r.low_stock_count || 0,
        updates: state.updateStatus?.ok && state.updateStatus.release?.is_newer ? "!" : 0
    };
    $$('[data-nav-badge]').forEach(badge => {
        const value = badgeValues[badge.dataset.navBadge] || 0;
        const visible = value === "!" || Number(value) > 0;
        badge.hidden = !visible;
        badge.textContent = visible ? String(value) : "";
        badge.setAttribute("aria-label", value === "!" ? "Доступно обновление" : `${value} требует внимания`);
    });
}

function updateSearchClear() {
    const clearButton = $("#clearSearch");
    if (clearButton) clearButton.hidden = !state.q;
}

function clearGlobalSearch() {
    const input = $("#globalSearch");
    state.q = "";
    if (input) {
        input.value = "";
        input.focus({ preventScroll: true });
    }
    updateSearchClear();
    clearTimeout(state.searchTimer);
    loadData().catch(showError);
}

function commandItems() {
    return [
        { icon: "⌂", title: "Панель управления", hint: "Executive cockpit и риски", keys: "G P", run: () => setRoute("dashboard") },
        { icon: "📅", title: "Новая запись", hint: "Поставить клиента в календарь", keys: "N A", run: () => openAppointmentModal() },
        { icon: "✓", title: "Новый осмотр DVI", hint: "Цифровой мульти-точечный осмотр", keys: "N D", run: () => openInspectionModal() },
        { icon: "№", title: "Новый заказ-наряд", hint: "Работы, запчасти и оплаты", keys: "N O", run: () => openOrderModal() },
        { icon: "👤", title: "Новый клиент", hint: "Добавить клиента в CRM", keys: "N C", run: () => openCustomerModal() },
        { icon: "🚘", title: "Новый автомобиль", hint: "Карточка авто и сервисный план", keys: "N V", run: () => openVehicleModal() },
        { icon: "▦", title: "Новая позиция склада", hint: "Остатки, цена и себестоимость", keys: "N S", run: () => openInventoryModal() },
        { icon: "↗", title: "Отчеты", hint: "Финансы, маржа и закупки", keys: "G R", run: () => setRoute("reports") },
        { icon: "◎", title: "Каталог авто", hint: "Марки и модели", keys: "G C", run: () => setRoute("catalog") },
        { icon: "↻", title: "Обновить данные", hint: "Перезагрузить bootstrap", keys: "R", run: () => loadData().then(() => toast("Обновлено")).catch(showError) },
        { icon: "↕", title: "Плотность интерфейса", hint: "Компактный или комфортный режим", keys: "D", run: () => toggleDensity() },
        { icon: "⇩", title: "Резервная копия", hint: "Создать консистентный backup SQLite", keys: "B", run: () => createBackupFromUi() },
        { icon: "⬢", title: "Проверить обновления", hint: "GitHub release-only", keys: "U", run: () => { setRoute("updates"); checkForUpdates(true).catch(showError); } }
    ];
}

function filteredCommandItems() {
    const needle = String($("#commandSearch")?.value || "").trim().toLocaleLowerCase("ru-RU");
    if (!needle) return commandItems();
    return commandItems().filter(item => `${item.title} ${item.hint} ${item.keys}`.toLocaleLowerCase("ru-RU").includes(needle));
}

function renderCommandPalette() {
    const list = $("#commandList");
    if (!list) return;
    const items = filteredCommandItems();
    list.innerHTML = items.map((item, index) => `
        <button class="command-item ${index === 0 ? "active" : ""}" type="button" role="option" data-command-index="${index}" aria-selected="${index === 0 ? "true" : "false"}">
            <span aria-hidden="true">${esc(item.icon)}</span>
            <span><strong>${esc(item.title)}</strong><div class="muted">${esc(item.hint)}</div></span>
            <kbd>${esc(item.keys)}</kbd>
        </button>`).join("") || `<div class="empty"><strong>Команда не найдена</strong><span>Попробуйте другой запрос.</span></div>`;
}

function openCommandPalette() {
    if (!state.data) return;
    $("#commandPalette")?.classList.add("open");
    const input = $("#commandSearch");
    if (input) {
        input.value = "";
        renderCommandPalette();
        requestAnimationFrame(() => input.focus({ preventScroll: true }));
    }
}

function closeCommandPalette() {
    $("#commandPalette")?.classList.remove("open");
}

function runCommand(index = 0) {
    const item = filteredCommandItems()[index];
    if (!item) return;
    closeCommandPalette();
    item.run();
}

async function createBackupFromUi() {
    try {
        const result = await api("/api/backup", { method: "POST", body: "{}" });
        toast(`Резервная копия: ${result.path}`);
    } catch (error) {
        showError(error);
    }
}

function sectionIntro(title, text, options = {}) {
    const className = options.hero ? "section-card hero-card" : "section-card";
    const eyebrow = options.eyebrow ? `<div class="hero-eyebrow">${esc(options.eyebrow)}</div>` : "";
    const actions = (options.actions || []).length
        ? `<div class="hero-actions">${options.actions.map(action => action.action === "export-csv"
            ? `<button class="btn ghost" type="button" data-action="export-csv" data-export="${esc(action.export || "")}">${esc(action.label || "CSV")}</button>`
            : `<button class="btn ${esc(action.className || "")}" type="button" data-action="${esc(action.action || "")}">${esc(action.label || "Открыть")}</button>`).join("")}</div>`
        : "";
    const stats = (options.stats || []).length
        ? `<div class="hero-stat-stack">${options.stats.map(item => `<div class="hero-stat"><strong>${esc(item.value)}</strong><span>${esc(item.label)}</span></div>`).join("")}</div>`
        : "";
    if (options.hero) {
        return `<section class="${className}"><div class="hero-layout"><div>${eyebrow}<h3>${esc(title)}</h3><p>${esc(text)}</p>${actions}</div>${stats}</div></section>`;
    }
    return `<section class="${className}"><h3>${esc(title)}</h3><p>${esc(text)}</p></section>`;
}

function emptyState(title, text, action = "") {
    return `<div class="empty"><strong>${esc(title)}</strong><span>${esc(text)}</span>${action}</div>`;
}

function insightCard(label, value, hint, options = {}) {
    const icon = options.icon || String(label || "").trim().slice(0, 1).toLocaleUpperCase("ru-RU") || "•";
    return `<article class="insight-card" aria-label="${esc(`${label}: ${value}`)}"><div class="insight-head"><small>${esc(label)}</small><span class="insight-icon" aria-hidden="true">${esc(icon)}</span></div><strong>${esc(value)}</strong><span class="muted">${esc(hint)}</span></article>`;
}

function viewHeading(title, text, meta = [], actions = []) {
    const metaHtml = meta.length ? `<div class="view-meta">${meta.map(item => `<span class="count-pill">${esc(item)}</span>`).join("")}</div>` : "";
    const actionsHtml = actions.length ? `<div class="view-heading-actions">${actions.map(action => action.action === "export-csv"
        ? `<button class="btn ghost" type="button" data-action="export-csv" data-export="${esc(action.export || "")}">${esc(action.label || "CSV")}</button>`
        : `<button class="btn ${esc(action.className || "")}" type="button" data-action="${esc(action.action || "")}"${action.export ? ` data-export="${esc(action.export)}"` : ""}>${esc(action.label || "Открыть")}</button>`).join("")}</div>` : "";
    return `<section class="view-heading"><div><h2>${esc(title)}</h2><p>${esc(text)}</p>${metaHtml}</div>${actionsHtml}</section>`;
}

function tableHead(labels) {
    return `<tr>${labels.map(label => {
        if (typeof label === "string") {
            const text = label || "Действия";
            const content = label ? esc(label) : `<span class="sr-only">${esc(text)}</span>`;
            return `<th scope="col">${content}</th>`;
        }
        const text = label.text || "Действия";
        const className = label.className ? ` class="${esc(label.className)}"` : "";
        const content = label.text ? esc(label.text) : `<span class="sr-only">${esc(text)}</span>`;
        return `<th scope="col"${className}>${content}</th>`;
    }).join("")}</tr>`;
}

function labeledField(id, label, controlHtml, span = "") {
    return `<div class="field ${esc(span)}"><label for="${esc(id)}">${esc(label)}</label>${controlHtml}</div>`;
}

function fieldId(formScope, name) {
    return `${formScope}_${name}`.replace(/[^a-zA-Z0-9_-]/g, "_");
}

function inputField(formScope, name, label, attributes = "", span = "") {
    const id = fieldId(formScope, name);
    return labeledField(id, label, `<input id="${id}" name="${esc(name)}" ${attributes}>`, span);
}

function selectField(formScope, name, label, optionsHtml, attributes = "", span = "") {
    const id = fieldId(formScope, name);
    return labeledField(id, label, `<select id="${id}" name="${esc(name)}" ${attributes}>${optionsHtml}</select>`, span);
}

function textareaField(formScope, name, label, value = "", attributes = "", span = "") {
    const id = fieldId(formScope, name);
    return labeledField(id, label, `<textarea id="${id}" name="${esc(name)}" ${attributes}>${esc(value)}</textarea>`, span);
}

function renderDashboard() {
    const r = state.data.reports;
    const recent = [...state.data.orders].slice(0, 6);
    const catalog = state.data.car_catalog?.stats || { makes: 0, models: 0 };
    return `
        ${sectionIntro("Управляйте сменой автосервиса без хаоса", "Executive cockpit объединяет деньги, загрузку, DVI-риски, склад и приоритетный план действий мастера-приемщика.", {
            hero: true,
            eyebrow: "Premium workspace",
            actions: [
                { label: "Новый заказ", action: "new-order", className: "primary" },
                { label: "Записать клиента", action: "new-appointment", className: "ghost" },
                { label: "План смены", action: "open-action-plan", className: "ghost" } // data-action="open-action-plan"
            ],
            stats: [
                { label: "Индекс смены", value: `${Math.max(0, Math.min(100, Number(r.business_health_score || 0)))}/100` },
                { label: "Активная воронка", value: money(r.pipeline_value || 0) },
                { label: "Записей сегодня", value: r.appointments_today_count || 0 },
                { label: "Задач в плане", value: r.action_plan_total || 0 }
            ]
        })}
        <section class="kpi-grid">
            ${healthMetric(r)}
            ${metric("Открытые заказ-наряды", r.active_orders, `${money(r.pipeline_value || 0)} в активной воронке`)}
            ${metric("Выручка месяца", money(r.revenue_month), "По закрытым заказам")}
            ${metric("CRM задачи", r.crm_tasks_count, `${r.overdue_orders_count || 0} просрочено · ${r.inspection_alerts_count || 0} DVI рисков`)}
        </section>
        <section class="insight-grid">
            ${insightCard("К оплате", money(r.due_total), "Дебиторская задолженность")}
            ${insightCard("Маржа месяца", money(r.gross_margin_month || 0), `${num(r.margin_percent_month).toFixed(1)}% валовой маржи`)}
            ${insightCard("Конверсия смет", `${num(r.conversion_rate).toFixed(1)}%`, "Согласование → работа")}
            ${insightCard("Активная воронка", money(r.pipeline_value || 0), `${money(r.pipeline_due || 0)} ожидает оплаты`)}
            ${insightCard("Стоимость склада", money(r.inventory_value || 0), "По себестоимости активных остатков")}
            ${insightCard("Закупка", money((r.procurement_plan || []).reduce((sum, item) => sum + num(item.budget), 0)), `${(r.procurement_plan || []).length} позиций к заказу`)}
        </section>
        <section class="grid-2">
            <div class="panel">
                <div class="panel-head"><h2>Воронка заказ-нарядов</h2><button class="btn" type="button" data-action="open-orders">Все заказы</button></div>
                <div class="panel-body">${pipelineBoard(r.pipeline_by_status || [])}</div>
            </div>
            <div class="panel">
                <div class="panel-head"><h2>Загрузка на 7 дней</h2><button class="btn" type="button" data-action="open-appointments">Календарь</button></div>
                <div class="panel-body">${appointmentTimeline(r.appointment_load_7_days || [])}</div>
            </div>
        </section>
        <section class="ops-grid">
            <div class="ops-card accent">
                <small>Быстрые действия</small>
                <strong>Приемка, клиент, авто и склад в один клик</strong>
                <div class="ops-actions">
                    <button class="btn primary" type="button" data-action="new-appointment" title="Создать запись клиента">Запись</button>
                    <button class="btn" type="button" data-action="new-inspection" title="Создать цифровой осмотр">Осмотр</button>
                    <button class="btn primary" type="button" data-action="new-order" title="Оформить заказ-наряд">Заказ</button>
                    <button class="btn" type="button" data-action="new-customer" title="Добавить клиента">Клиент</button>
                    <button class="btn" type="button" data-action="new-vehicle" title="Добавить автомобиль">Авто</button>
                    <button class="btn" type="button" data-action="open-catalog" title="Открыть каталог марок и моделей">Каталог</button>
                    <button class="btn" type="button" data-action="new-inventory" title="Добавить складскую позицию">Склад</button>
                </div>
            </div>
            <div class="ops-card">
                <small>Запись сегодня</small>
                <strong>${r.appointments_today_count || 0}</strong>
                <span class="stat-chip">приемка и подтверждения</span>
            </div>
            <div class="ops-card">
                <small>Клиенты</small>
                <strong>${state.data.lookups.customers.length}</strong>
                <span class="stat-chip">активная база</span>
            </div>
            <div class="ops-card">
                <small>Автомобили</small>
                <strong>${state.data.lookups.vehicles.length}</strong>
                <span class="stat-chip">${catalog.makes} марок</span>
            </div>
            <div class="ops-card">
                <small>Справочник</small>
                <strong>${catalog.models}</strong>
                <span class="stat-chip">моделей авто</span>
            </div>
        </section>
        <section class="grid-2">
            <div class="panel">
                <div class="panel-head"><h2>Последние заказ-наряды</h2><button class="btn primary" type="button" data-action="new-order">Новый заказ</button></div>
                ${ordersTable(recent, true)}
            </div>
            <div class="stack">
                <div class="panel">
                    <div class="panel-head"><h2>Просроченные сроки</h2><button class="btn" type="button" data-action="open-orders">Открыть заказы</button></div>
                    <div class="panel-body">${overdueOrderList(r.overdue_orders || [])}</div>
                </div>
                <div class="panel action-center">
                    <div class="panel-head"><h2>План смены</h2><span class="count-pill">${r.action_plan_total || 0}</span></div>
                    <div class="panel-body">${actionPlanList(r.action_plan || [])}</div>
                </div>
                <div class="panel">
                    <div class="panel-head"><h2>CRM задачи</h2></div>
                    <div class="panel-body">${crmTaskList(r)}</div>
                </div>
                <div class="panel">
                    <div class="panel-head"><h2>VIP и удержание</h2></div>
                    <div class="panel-body">${vipCustomerList(r.vip_customers)}</div>
                </div>
                <div class="panel">
                    <div class="panel-head"><h2>Осмотры DVI</h2><button class="btn" type="button" data-action="new-inspection">Новый осмотр</button></div>
                    <div class="panel-body">${inspectionAlertList(r.inspection_alerts)}</div>
                </div>
                <div class="panel">
                    <div class="panel-head"><h2>Запись сегодня</h2><button class="btn" type="button" data-action="new-appointment">Новая запись</button></div>
                    <div class="panel-body">${appointmentList(r.appointments_today)}</div>
                </div>
                <div class="panel">
                    <div class="panel-head"><h2>На сегодня</h2></div>
                    <div class="panel-body">${smallOrderList(r.promised_today)}</div>
                </div>
                <div class="panel">
                    <div class="panel-head"><h2>Склад ниже минимума</h2><button class="btn" type="button" data-action="open-inventory">Склад</button></div>
                    <div class="panel-body">${lowStockList(r.low_stock)}</div>
                </div>
                <div class="panel">
                    <div class="panel-head"><h2>План закупки</h2></div>
                    <div class="panel-body">${procurementList(r.procurement_plan || [])}</div>
                </div>
                <div class="panel">
                    <div class="panel-head"><h2>Загрузка мастеров</h2></div>
                    <div class="panel-body">${workloadList(r.workload_by_responsible || [])}</div>
                </div>
            </div>
        </section>
    `;
}

function metric(label, value, hint, options = {}) {
    const toneClass = options.tone ? ` tone-${classToken(options.tone)}` : "";
    const icon = options.icon || String(label || "").trim().slice(0, 1).toLocaleUpperCase("ru-RU") || "•";
    return `<article class="metric${toneClass}" aria-label="${esc(`${label}: ${value}`)}"><div class="metric-top"><small>${esc(label)}</small><span class="metric-icon" aria-hidden="true">${esc(icon)}</span></div><strong>${esc(value)}</strong><div class="trend">${esc(hint)}</div></article>`;
}

function healthMetric(report) {
    const score = Math.max(0, Math.min(100, Number(report.business_health_score || 0)));
    return `<article class="metric health-card" aria-label="Индекс смены: ${score} из 100"><div class="metric-top"><small>Индекс смены</small><span class="metric-icon" aria-hidden="true">↗</span></div><strong><span class="health-score">${score}</span><span>/100</span></strong><div class="trend">${esc(report.business_health_label || "Контроль")} · просрочки, склад и DVI</div></article>`;
}

function pipelineBoard(statuses = []) {
    const active = statuses.filter(column => !["cancelled"].includes(column.status));
    if (!active.length) return `<div class="muted">Воронка пока пуста.</div>`;
    return `<div class="pipeline-board">${active.map(column => `
        <article class="pipeline-column">
            <div class="pipeline-head"><strong>${esc(column.label)}</strong><span class="count-pill">${column.count}</span></div>
            <div class="pipeline-body">
                <div class="muted">${money(column.total)} · долг ${money(column.due)}</div>
                ${(column.orders || []).slice(0, 3).map(order => {
                    const overdue = (state.data?.reports?.overdue_orders || []).some(item => Number(item.id) === Number(order.id));
                    return `
                    <div class="deal-card ${overdue ? "overdue" : ""}">
                        <strong>${esc(order.number || "Без номера")}</strong>
                        <div class="muted">${esc(order.customer_name || "")} · ${esc(order.vehicle || "Авто не выбрано")}</div>
                        <div>${money(order.total)} · ${esc(priorityLabels[order.priority] || order.priority || "")}</div>
                        <button class="btn ghost" type="button" data-action="edit-order" data-id="${order.id}">Открыть</button>
                    </div>`;
                }).join("") || `<div class="muted">Нет заказов в статусе.</div>`}
            </div>
        </article>`).join("")}</div>`;
}

function appointmentTimeline(days = []) {
    if (!days.length) return `<div class="muted">Нет данных календаря.</div>`;
    const todayKey = new Date().toISOString().slice(0, 10);
    const maxCount = Math.max(...days.map(day => Number(day.count || 0)), 1);
    return `<div class="timeline">${days.map(day => {
        const width = Number(day.count || 0) ? Math.max(8, Math.round(Number(day.count || 0) / maxCount * 100)) : 0;
        return `
        <article class="timeline-day ${day.date === todayKey ? "today" : ""}">
            <strong><span>${esc(day.label)}</span><span class="count-pill">${day.count}</span></strong>
            <div class="bar-track" aria-label="Загрузка ${esc(day.label)}: ${day.count}"><div class="bar-fill" style="width:${width}%"></div></div>
            <div class="timeline-list">${(day.appointments || []).slice(0, 2).map(item => `<span>${dateShort(item.scheduled_at)} · ${esc(item.customer_name || "")}</span>`).join("") || `<span class="muted">Свободно</span>`}</div>
        </article>`;
    }).join("")}</div>`;
}

function overdueOrderList(orders = []) {
    if (!orders.length) return `<div class="muted">Просроченных заказ-нарядов нет.</div>`;
    return `<div class="stack">${orders.map(order => `
        <div class="deal-card overdue">
            <strong>${esc(order.number)} · ${money(order.total)}</strong>
            <div class="muted">${esc(order.customer_name || "")} · ${esc(order.vehicle || "")} · срок ${dateShort(order.promised_at)}</div>
            <button class="btn ghost" type="button" data-action="edit-order" data-id="${order.id}">Открыть</button>
        </div>`).join("")}</div>`;
}

function procurementList(items = []) {
    if (!items.length) return `<div class="muted">Склад в нормативе.</div>`;
    return `<div class="stack">${items.map(item => `
        <div>
            <strong>${esc(item.name)} ${item.urgency === "critical" ? `<span class="danger-text">критично</span>` : ""}</strong>
            <div class="muted">${esc(item.sku || "без артикула")} · заказать ${qty(item.reorder_quantity)} ${esc(item.unit || "шт")} · бюджет ${money(item.budget)}</div>
        </div>`).join("")}</div>`;
}

function workloadList(items = []) {
    if (!items.length) return `<div class="muted">Ответственные пока не назначены.</div>`;
    return `<div class="stack">${items.map(item => `
        <div>
            <strong>${esc(item.name)}</strong>
            <div class="muted">${item.orders_count} заказов · ${money(item.total)} в работе · ${item.overdue_count} просрочено</div>
        </div>`).join("")}</div>`;
}

function actionPlanList(items = []) {
    if (!items.length) {
        return `<div class="empty"><strong>План смены чист</strong><span>Нет просрочек, критичных DVI, срочных закупок и задач follow-up.</span></div>`;
    }
    return `<div class="action-stream">${items.map(item => {
        const meta = [
            item.customer_name,
            item.customer_phone,
            item.vehicle,
            item.due_at ? dateShort(item.due_at) : "",
            Number(item.amount || 0) ? money(item.amount) : ""
        ].filter(Boolean);
        return `<article class="action-card ${esc(classToken(item.tone || "info"))}">
            <div>
                <strong>${esc(item.title)}</strong>
                <p>${esc(item.detail || "")}</p>
                <div class="action-meta">
                    <span class="action-priority">${esc(item.priority_label || "Планово")}</span>
                    ${meta.map(value => `<span class="count-pill">${esc(value)}</span>`).join("")}
                </div>
            </div>
            <div class="action-side">
                <span class="action-score">${Number(item.priority || 0)}/100</span>
                <button class="btn primary" type="button" data-action="${esc(item.action || "")}" data-id="${esc(item.record_id || "")}" data-route-target="${esc(item.route || "dashboard")}">${esc(item.cta || "Открыть")}</button>
            </div>
        </article>`;
    }).join("")}</div>`;
}

function renderAppointments() {
    const rows = state.data.appointments || [];
    const upcoming = state.data.reports?.appointments_upcoming || [];
    return `
        ${viewHeading("Календарь приемки", "Планируйте визиты, подтверждения, прибытия и неявки в одном аккуратном рабочем списке.", [
            `${rows.length} записей`,
            `${upcoming.length} ближайших`,
            `${state.data.reports.appointments_today_count || 0} сегодня`
        ], [
            { label: "CSV", action: "export-csv", export: "appointments", className: "ghost" },
            { label: "Новая запись", action: "new-appointment", className: "primary" }
        ])}
        <section class="kpi-grid">
            ${metric("Записей сегодня", state.data.reports.appointments_today_count || 0, "Подтверждения, приемка и прибытия")}
            ${metric("Ближайшие записи", upcoming.length, "Активные записи в календаре")}
            ${metric("Клиентов в базе", state.data.lookups.customers.length, "Можно быстро поставить в календарь")}
            ${metric("CRM задачи", state.data.reports.crm_tasks_count, "Напоминания, follow-up и отложенные работы")}
        </section>
        <div class="table-wrap">
            <table aria-label="Таблица записей клиентов">
                <thead>${tableHead(["Дата и время", "Клиент и авто", "Статус", "Длительность", "Мастер", "Причина", ""])}</thead>
                <tbody>
                    ${rows.map(appointment => `
                        <tr>
                            <td class="nowrap">${dateShort(appointment.scheduled_at)}</td>
                            <td><div class="cell-title"><strong>${esc(appointment.customer_name)}</strong><div class="muted">${esc(appointment.customer_phone)} · ${esc(appointmentVehicle(appointment) || "Авто не выбрано")}</div></div></td>
                            <td>${appointmentStatusBadge(appointment.status)}</td>
                            <td>${Number(appointment.duration_minutes || 0)} мин</td>
                            <td>${esc(appointment.advisor || "")}</td>
                            <td><div class="cell-title"><strong>${esc(appointment.reason || "")}</strong><div class="muted">${esc(appointment.notes || "")}</div></div></td>
                            <td><div class="row-actions"><button class="btn" type="button" data-action="edit-appointment" data-id="${appointment.id}">Открыть</button></div></td>
                        </tr>`).join("") || `<tr><td colspan="7" class="empty"><strong>Записей не найдено</strong><span>Создайте запись клиента в календаре.</span></td></tr>`}
                </tbody>
            </table>
        </div>
    `;
}

function renderInspections() {
    const rows = state.data.inspections || [];
    return `
        ${viewHeading("Digital Vehicle Inspection", "Фиксируйте состояние автомобиля, критичные пункты, рекомендации и согласования клиента в профессиональном DVI-процессе.", [
            `${rows.length} осмотров`,
            `${state.data.reports.inspection_alerts_count || 0} рисков DVI`,
            `${state.data.reports.crm_tasks_count || 0} CRM задач`
        ], [
            { label: "CSV", action: "export-csv", export: "inspections", className: "ghost" },
            { label: "Новый осмотр", action: "new-inspection", className: "primary" }
        ])}
        <section class="kpi-grid">
            ${metric("Осмотров", state.data.reports.inspections_count || 0, "История DVI по клиентам и авто")}
            ${metric("Риски DVI", state.data.reports.inspection_alerts_count || 0, "Требуют согласования и follow-up")}
            ${metric("Каталог авто", state.data.car_catalog?.stats?.models || 0, "Моделей для точной карточки авто")}
            ${metric("CRM задачи", state.data.reports.crm_tasks_count, "Осмотры, follow-up и сервисные напоминания")}
        </section>
        <div class="table-wrap">
            <table aria-label="Таблица цифровых осмотров">
                <thead>${tableHead(["Дата", "Клиент и авто", "Статус", "Пункты", "Риски", {text: "Рекомендации", className: "money"}, ""])}</thead>
                <tbody>
                    ${rows.map(inspection => `
                        <tr>
                            <td class="nowrap">${dateShort(inspection.inspected_at)}</td>
                            <td><div class="cell-title"><strong>${esc(inspection.customer_name)}</strong><div class="muted">${esc(inspectionVehicle(inspection) || "Авто не выбрано")} ${inspection.order_number ? `· ${esc(inspection.order_number)}` : ""}</div></div></td>
                            <td>${inspectionStatusBadge(inspection.status)}</td>
                            <td>${Number(inspection.items_count || 0)}</td>
                            <td><div class="cell-title"><strong>${Number(inspection.critical_count || 0)} крит.</strong><div class="muted">${Number(inspection.attention_count || 0)} требует внимания</div></div></td>
                            <td class="money">${money(inspection.recommended_total)}</td>
                            <td><div class="row-actions"><button class="btn" type="button" data-action="edit-inspection" data-id="${inspection.id}">Открыть</button></div></td>
                        </tr>`).join("") || `<tr><td colspan="7" class="empty"><strong>Осмотров не найдено</strong><span>Создайте цифровой осмотр DVI.</span></td></tr>`}
                </tbody>
            </table>
        </div>
    `;
}

function smallOrderList(orders) {
    if (!orders.length) return `<div class="muted">Нет запланированных выдач.</div>`;
    return `<div class="stack">${orders.map(order => `
        <div>
            <strong>${esc(order.number)}</strong> · ${statusBadge(order.status)}
            <div class="muted">${esc(order.customer_name)} · ${esc(orderVehicle(order))} · ${dateShort(order.promised_at)}</div>
        </div>`).join("")}</div>`;
}

function appointmentList(appointments) {
    if (!appointments?.length) return `<div class="muted">Записей на сегодня нет.</div>`;
    return `<div class="stack">${appointments.map(appointment => `
        <div>
            <strong>${dateShort(appointment.scheduled_at)} · ${esc(appointment.customer_name)}</strong> ${appointmentStatusBadge(appointment.status)}
            <div class="muted">${esc(appointmentVehicle(appointment) || "Авто не выбрано")} · ${esc(appointment.reason || "")}</div>
        </div>`).join("")}</div>`;
}

function inspectionAlertList(items) {
    if (!items?.length) return `<div class="muted">Критичных пунктов осмотра нет.</div>`;
    return `<div class="stack">${items.map(item => `
        <div>
            <strong>${esc(item.title)}</strong> ${inspectionConditionBadge(item.condition_status)}
            <div class="muted">${esc(item.customer_name)} · ${esc(item.vehicle || "")} · ${money(item.estimate)}</div>
        </div>`).join("")}</div>`;
}

function lowStockList(parts) {
    if (!parts.length) return `<div class="muted">Критичных остатков нет.</div>`;
    return `<div class="stack">${parts.map(part => `
        <div>
            <strong>${esc(part.name)}</strong>
            <div class="muted">${esc(part.sku)} · остаток ${qty(part.quantity)} ${esc(part.unit)} · минимум ${qty(part.min_quantity)}</div>
        </div>`).join("")}</div>`;
}

function vipCustomerList(customers = []) {
    if (!customers.length) return `<div class="muted">Недостаточно истории для VIP-сегмента.</div>`;
    return `<div class="stack">${customers.map(customer => `
        <div>
            <strong>${esc(customer.customer_name)}</strong>
            <div class="muted">${esc(customer.customer_phone || "без телефона")} · ${customer.orders_count} заказов · ${money(customer.revenue)}</div>
        </div>`).join("")}</div>`;
}

function renderOrders() {
    return `
        ${viewHeading("Заказ-наряды", "Контролируйте статусы ремонта, сроки, оплаты, согласование строк и повторные продажи.", [
            `${state.data.orders.length} найдено`,
            `${state.data.reports.active_orders || 0} активных`,
            `${money(state.data.reports.pipeline_value || 0)} в работе`
        ], [
            { label: "CSV", action: "export-csv", export: "orders", className: "ghost" },
            { label: "Новый заказ", action: "new-order", className: "primary" }
        ])}
        <div class="toolbar">
            <div class="toolbar-left">
                <div class="segmented" role="group" aria-label="Фильтр заказов по статусу">
                    ${["all", "new", "diagnostics", "estimate", "approved", "in_progress", "done", "closed"].map(status => `
                        <button type="button" data-action="filter-status" data-status="${status}" class="${state.status === status ? "active" : ""}" aria-pressed="${state.status === status ? "true" : "false"}">
                            ${status === "all" ? "Все" : esc(state.data.statuses[status])}
                        </button>`).join("")}
                </div>
            </div>
        </div>
        ${ordersTable(state.data.orders, false)}
    `;
}

function ordersTable(orders, compact) {
    if (!orders.length) return emptyState("Заказ-нарядов не найдено", "Создайте первый заказ или измените поиск/фильтр.", `<button class="btn primary" type="button" data-action="new-order">Новый заказ</button>`);
    if (compact) {
        return `<div class="table-wrap">
            <table class="compact-table" aria-label="Таблица последних заказ-нарядов">
                <thead>${tableHead(["Номер", "Клиент и авто", "Статус", {text: "Итого", className: "money"}, ""])}</thead>
                <tbody>
                    ${orders.map(order => `
                        <tr>
                            <td><div class="cell-title"><strong>${esc(order.number)}</strong><div class="priority ${esc(order.priority)}">${esc(priorityLabels[order.priority] || order.priority)}</div></div></td>
                            <td><div class="cell-title"><strong>${esc(order.customer_name)}</strong><div class="muted">${esc(orderVehicle(order) || "Авто не выбрано")}</div></div></td>
                            <td>${statusBadge(order.status)}</td>
                            <td class="money">${money(order.total)}</td>
                            <td>
                                <div class="row-actions">
                                    <button class="btn icon" type="button" title="Печать" aria-label="Печать заказ-наряда ${esc(order.number)}" data-action="print-order" data-id="${order.id}"><span aria-hidden="true">⎙</span></button>
                                    <button class="btn" type="button" data-action="edit-order" data-id="${order.id}">Открыть</button>
                                    <button class="btn ghost" type="button" data-action="duplicate-order" data-id="${order.id}" title="Создать новый заказ на основе текущего">Повторить</button>
                                </div>
                            </td>
                        </tr>
                    `).join("")}
                </tbody>
            </table>
        </div>`;
    }
    return `<div class="table-wrap">
        <table aria-label="Таблица заказ-нарядов">
            <thead>${tableHead(["Номер", "Клиент и авто", "Статус", "Срок", "Мастер", {text: "Итого", className: "money"}, {text: "К оплате", className: "money"}, ""])}</thead>
            <tbody>
                ${orders.map(order => `
                    <tr>
                        <td><div class="cell-title"><strong>${esc(order.number)}</strong><div class="priority ${esc(order.priority)}">${esc(priorityLabels[order.priority] || order.priority)}</div></div></td>
                        <td><div class="cell-title"><strong>${esc(order.customer_name)}</strong><div class="muted">${esc(orderVehicle(order) || "Авто не выбрано")}</div></div></td>
                        <td>${statusBadge(order.status)}</td>
                        <td class="nowrap">${dateShort(order.promised_at)}</td>
                        <td>${esc(order.mechanic || order.advisor || "")}</td>
                        <td class="money">${money(order.total)}</td>
                        <td class="money">${money(order.due)}</td>
                        <td>
                            <div class="row-actions">
                                <button class="btn icon" type="button" title="Печать" aria-label="Печать заказ-наряда ${esc(order.number)}" data-action="print-order" data-id="${order.id}"><span aria-hidden="true">⎙</span></button>
                                <button class="btn" type="button" data-action="edit-order" data-id="${order.id}">Открыть</button>
                                <button class="btn ghost" type="button" data-action="duplicate-order" data-id="${order.id}" title="Создать новый заказ на основе текущего">Повторить</button>
                            </div>
                        </td>
                    </tr>
                `).join("")}
            </tbody>
        </table>
    </div>`;
}

function renderCustomers() {
    const rows = state.data.customers;
    return `
        ${viewHeading("Клиенты", "Единая клиентская база с каналами связи, согласием на напоминания, автомобилями и историей заказов.", [
            `${rows.length} найдено`,
            `${state.data.lookups.customers.length} всего`,
            `${state.data.reports.vip_customers?.length || 0} VIP`
        ], [
            { label: "CSV", action: "export-csv", export: "customers", className: "ghost" },
            { label: "Новый клиент", action: "new-customer", className: "primary" }
        ])}
        <div class="table-wrap">
            <table aria-label="Таблица клиентов">
                <thead>${tableHead(["Клиент", "Телефон", "Email", "Канал", "Источник", "Авто", "Заказы", ""])}</thead>
                <tbody>
                    ${rows.map(c => `
                        <tr>
                            <td><div class="cell-title"><strong>${esc(c.name)}</strong><div class="muted">${esc(c.notes)}</div></div></td>
                            <td>${esc(c.phone)}</td>
                            <td>${esc(c.email)}</td>
                            <td>${esc(channelLabel(c.preferred_channel))}${Number(c.reminder_consent) ? "" : `<div class="danger-text">без напоминаний</div>`}</td>
                            <td>${esc(c.source)}</td>
                            <td>${c.vehicles_count}</td>
                            <td><div class="cell-title"><strong>${c.orders_count}</strong><div class="muted">${c.last_order_at ? `посл. ${dateShort(c.last_order_at)}` : "нет заказов"}</div></div></td>
                            <td><div class="row-actions"><button class="btn" type="button" data-action="edit-customer" data-id="${c.id}">Открыть</button></div></td>
                        </tr>`).join("") || `<tr><td colspan="8" class="empty"><strong>Клиентов не найдено</strong><span>Добавьте клиента или измените поиск.</span></td></tr>`}
                </tbody>
            </table>
        </div>
    `;
}

function renderVehicles() {
    const rows = state.data.vehicles;
    const catalog = state.data.car_catalog?.stats || { makes: 0, models: 0 };
    return `
        ${viewHeading("Автомобили", "Паспорт автомобиля, VIN, пробег, сервисный план и быстрый доступ к офлайн-каталогу марок и моделей.", [
            `${rows.length} авто`,
            `${catalog.makes} марок`,
            `${state.data.reports.service_reminders?.length || 0} напоминаний`
        ], [
            { label: "Каталог", action: "open-catalog", className: "ghost" },
            { label: "CSV", action: "export-csv", export: "vehicles", className: "ghost" },
            { label: "Новый автомобиль", action: "new-vehicle", className: "primary" }
        ])}
        <div class="table-wrap">
            <table aria-label="Таблица автомобилей">
                <thead>${tableHead(["Автомобиль", "Госномер", "VIN", "Клиент", "Пробег", "Следующий сервис", ""])}</thead>
                <tbody>
                    ${rows.map(v => `
                        <tr>
                            <td><div class="cell-title"><strong>${esc(vehicleName(v))}</strong><div class="muted">${esc(v.notes)}</div></div></td>
                            <td>${v.plate ? `<span class="plate">${esc(v.plate)}</span>` : ""}</td>
                            <td>${esc(v.vin)}</td>
                            <td><div class="cell-title">${esc(v.customer_name)}<div class="muted">${esc(v.customer_phone)}</div></div></td>
                            <td>${Number(v.mileage || 0).toLocaleString("ru-RU")} км</td>
                            <td><div class="cell-title">${esc(v.next_service_at || "")}<div class="muted">${v.next_service_mileage ? `${Number(v.next_service_mileage).toLocaleString("ru-RU")} км` : ""}</div></div></td>
                            <td><div class="row-actions"><button class="btn" type="button" data-action="edit-vehicle" data-id="${v.id}">Открыть</button></div></td>
                        </tr>`).join("") || `<tr><td colspan="7" class="empty"><strong>Автомобилей не найдено</strong><span>Добавьте автомобиль клиента.</span></td></tr>`}
                </tbody>
            </table>
        </div>
    `;
}

function crmTaskList(report) {
    const blocks = [];
    if (report.authorizations_pending?.length) {
        blocks.push(...report.authorizations_pending.map(order => `
            <div>
                <strong>Согласовать смету ${esc(order.number)}</strong>
                <div class="muted">${esc(order.customer_name)} · ${esc(orderVehicle(order))} · ${money(order.total)}</div>
            </div>`));
    }
    if (report.followups_due?.length) {
        blocks.push(...report.followups_due.map(order => `
            <div>
                <strong>Связаться после визита ${esc(order.number)}</strong>
                <div class="muted">${esc(order.customer_name)} · ${dateShort(order.follow_up_at)}</div>
            </div>`));
    }
    if (report.service_reminders?.length) {
        blocks.push(...report.service_reminders.map(vehicle => `
            <div>
                <strong>Напомнить о сервисе</strong>
                <div class="muted">${esc(vehicle.customer_name)} · ${esc(vehicleName(vehicle))} · ${esc(channelLabels[vehicle.customer_preferred_channel] || "Телефон")}</div>
            </div>`));
    }
    if (report.deferred_work?.length) {
        blocks.push(...report.deferred_work.map(item => `
            <div>
                <strong>Вернуть ${esc(itemApprovalFallback[item.approval_status] || item.approval_status)}: ${esc(item.title)}</strong>
                <div class="muted">${esc(item.customer_name)} · ${esc(item.vehicle || "")} · ${money(item.amount)}</div>
            </div>`));
    }
    if (report.inspection_alerts?.length) {
        blocks.push(...report.inspection_alerts.map(item => `
            <div>
                <strong>DVI: ${esc(item.title)}</strong>
                <div class="muted">${esc(item.customer_name)} · ${esc(item.vehicle || "")} · ${esc(inspectionConditionFallback[item.condition_status] || item.condition_status)} · ${money(item.estimate)}</div>
            </div>`));
    }
    return blocks.length ? `<div class="stack">${blocks.slice(0, 8).join("")}</div>` : `<div class="muted">Нет срочных CRM задач.</div>`;
}

function renderCatalog() {
    const catalog = state.data.car_catalog || { makes: [], models: {}, stats: { makes: 0, models: 0, empty_makes: 0 } };
    const stats = catalog.stats || { makes: 0, models: 0, empty_makes: 0 };
    const entries = filteredCatalogEntries();
    return `
        ${viewHeading("Каталог автомобилей", "Офлайн-справочник производителей и моделей помогает быстро и единообразно заполнять карточки автомобилей.", [
            `${stats.makes} производителей`,
            `${stats.models} моделей`,
            `${entries.length} в подборке`
        ], [
            { label: "CSV каталога", action: "export-csv", export: "catalog", className: "ghost" },
            { label: "Новый автомобиль", action: "new-vehicle", className: "primary" }
        ])}
        <section class="catalog-summary">
            <article class="metric"><small>Производители</small><strong>${stats.makes}</strong><div class="trend">Полный офлайн-справочник марок</div></article>
            <article class="metric"><small>Модели</small><strong>${stats.models}</strong><div class="trend">Доступны в карточке авто</div></article>
            <article class="metric"><small>Без моделей</small><strong>${stats.empty_makes || 0}</strong><div class="trend">Редкие производители из официального списка</div></article>
            <article class="metric"><small>В подборке</small><strong>${entries.length}</strong><div class="trend">Найдено по фильтру</div></article>
        </section>
        <div class="toolbar">
            <div class="toolbar-left">
                <div class="catalog-search">
                    <span aria-hidden="true">⌕</span>
                    <label class="sr-only" for="catalogFilter">Фильтр по марке или модели</label>
                    <input id="catalogFilter" value="${esc(state.catalogQ)}" placeholder="Фильтр по марке или модели" autocomplete="off" aria-label="Фильтр по марке или модели">
                </div>
            </div>

        </div>
        <section class="catalog-grid">
            ${entries.map(entry => catalogMakeHtml(entry.make, entry.models)).join("") || `<div class="empty">В каталоге ничего не найдено.</div>`}
        </section>
    `;
}

function filteredCatalogEntries() {
    const catalog = state.data.car_catalog || { makes: [], models: {} };
    const needle = String(state.catalogQ || "").trim().toLocaleLowerCase("ru-RU");
    return (catalog.makes || []).map(make => ({
        make,
        models: catalog.models?.[make] || []
    })).filter(entry => {
        if (!needle) return true;
        return entry.make.toLocaleLowerCase("ru-RU").includes(needle)
            || entry.models.some(model => model.toLocaleLowerCase("ru-RU").includes(needle));
    });
}

function catalogMakeHtml(make, models) {
    const list = models.length
        ? models.map(model => `<span class="model-pill" title="${esc(make)} ${esc(model)}">${esc(model)}</span>`).join("")
        : `<span class="model-pill muted-pill">модели не указаны</span>`;
    return `<article class="catalog-make">
        <div class="catalog-make-head">
            <strong title="${esc(make)}">${esc(make)}</strong>
            <span class="count-pill">${models.length}</span>
        </div>
        <div class="model-list">${list}</div>
    </article>`;
}

function bindCatalogFilter(root) {
    const input = $("#catalogFilter", root);
    if (!input) return;
    let catalogTimer;
    input.addEventListener("input", event => {
        state.catalogQ = event.target.value;
        clearTimeout(catalogTimer);
        const selectionStart = input.selectionStart;
        const selectionEnd = input.selectionEnd;
        const wasFocused = document.activeElement === input;
        catalogTimer = setTimeout(() => {
            render();
            const next = $("#catalogFilter");
            if (wasFocused && next) {
                next.focus({ preventScroll: true });
                if (typeof next.setSelectionRange === "function" && selectionStart !== null && selectionEnd !== null) {
                    next.setSelectionRange(selectionStart, selectionEnd);
                }
            }
        }, 180);
    });
}

function renderInventory() {
    const rows = state.data.inventory;
    const lowCount = rows.filter(part => Number(part.is_low)).length;
    return `
        ${viewHeading("Склад", "Следите за остатками, себестоимостью, поставщиками и закупкой до остановки ремонта.", [
            `${rows.length} позиций`,
            `${lowCount} ниже минимума`,
            `${money(state.data.reports.inventory_value || 0)} себестоимость`
        ], [
            { label: "CSV", action: "export-csv", export: "inventory", className: "ghost" },
            { label: "Новая позиция", action: "new-inventory", className: "primary" }
        ])}
        <section class="insight-grid">
            ${insightCard("Активных позиций", rows.length, "Складские остатки в базе")}
            ${insightCard("Ниже минимума", lowCount, "Позиции для закупки")}
            ${insightCard("Стоимость склада", money(state.data.reports.inventory_value || 0), "По себестоимости остатков")}
        </section>
        <div class="table-wrap">
            <table aria-label="Таблица складских позиций">
                <thead>${tableHead(["Позиция", "Артикул", "Бренд", "Остаток", {text: "Цена", className: "money"}, {text: "Себестоимость", className: "money"}, "Поставщик", ""])}</thead>
                <tbody>
                    ${rows.map(p => `
                        <tr>
                            <td><div class="cell-title"><strong>${esc(p.name)}</strong>${Number(p.is_low) ? `<div class="danger-text">Ниже минимума</div>` : ""}</div></td>
                            <td>${esc(p.sku)}</td>
                            <td>${esc(p.brand)}</td>
                            <td>${qty(p.quantity)} ${esc(p.unit)}<div class="muted">мин. ${qty(p.min_quantity)}</div></td>
                            <td class="money">${money(p.price)}</td>
                            <td class="money">${money(p.cost)}</td>
                            <td>${esc(p.supplier)}</td>
                            <td><div class="row-actions"><button class="btn" type="button" data-action="edit-inventory" data-id="${p.id}">Открыть</button></div></td>
                        </tr>`).join("") || `<tr><td colspan="8" class="empty"><strong>Складских позиций не найдено</strong><span>Добавьте первую позицию склада.</span></td></tr>`}
                </tbody>
            </table>
        </div>
    `;
}

function renderReports() {
    const r = state.data.reports;
    const maxStatus = Math.max(...Object.values(r.status_counts), 1);
    const maxService = Math.max(...r.top_services.map(x => x.total), 1);
    return `
        ${viewHeading("Отчеты и аналитика", "Финансы, маржа, загрузка, закупки и удержание клиентов для управленческих решений.", [
            `${money(r.revenue_month)} выручка`,
            `${num(r.margin_percent_month).toFixed(1)}% маржа`,
            `${r.low_stock_count || 0} складских рисков`
        ], [
            { label: "Открыть заказы", action: "open-orders", className: "ghost" },
            { label: "Склад", action: "open-inventory", className: "ghost" }
        ])}
        <section class="kpi-grid">
            ${healthMetric(r)}
            ${metric("Средний чек", money(r.avg_check), "Закрытые заказы текущего месяца")}
            ${metric("Выручка месяца", money(r.revenue_month), "Факт по закрытым")}
            ${metric("Низкий склад", r.low_stock_count, "Требуют закупки")}
        </section>
        <section class="insight-grid">
            ${insightCard("К оплате", money(r.due_total), "Все незакрытые долги")}
            ${insightCard("Маржа месяца", money(r.gross_margin_month || 0), `${num(r.margin_percent_month).toFixed(1)}% валовой маржи`)}
            ${insightCard("Конверсия смет", `${num(r.conversion_rate).toFixed(1)}%`, "Согласование → работа")}
            ${insightCard("Активная воронка", money(r.pipeline_value || 0), `${money(r.pipeline_due || 0)} ожидает оплаты`)}
            ${insightCard("Стоимость склада", money(r.inventory_value || 0), "Себестоимость остатков")}
            ${insightCard("Просрочено", r.overdue_orders_count || 0, "Заказы со сроком раньше текущего времени")}
        </section>
        <section class="grid-2">
            <div class="panel">
                <div class="panel-head"><h2>Статусы заказов</h2></div>
                <div class="panel-body bars">
                    ${Object.entries(state.data.statuses).map(([key, label]) => `
                        <div class="bar">
                            <span>${esc(label)}</span>
                            <div class="bar-track" role="img" aria-label="${esc(label)}: ${r.status_counts[key] || 0}"><div class="bar-fill" style="width:${Math.round((r.status_counts[key] || 0) / maxStatus * 100)}%"></div></div>
                            <strong>${r.status_counts[key] || 0}</strong>
                        </div>`).join("")}
                </div>
            </div>
            <div class="panel">
                <div class="panel-head"><h2>Топ работ</h2></div>
                <div class="panel-body bars">
                    ${r.top_services.map(item => `
                        <div class="bar">
                            <span>${esc(item.title)}</span>
                            <div class="bar-track" role="img" aria-label="${esc(item.title)}: ${money(item.total)}"><div class="bar-fill" style="width:${Math.round(item.total / maxService * 100)}%"></div></div>
                            <strong>${money(item.total)}</strong>
                        </div>`).join("") || `<div class="muted">Нет данных по работам.</div>`}
                </div>
            </div>
        </section>
        <section class="grid-2">
            <div class="panel">
                <div class="panel-head"><h2>План закупки</h2><button class="btn" type="button" data-action="open-inventory">Склад</button></div>
                <div class="panel-body">${procurementList(r.procurement_plan || [])}</div>
            </div>
            <div class="panel">
                <div class="panel-head"><h2>Загрузка ответственных</h2></div>
                <div class="panel-body">${workloadList(r.workload_by_responsible || [])}</div>
            </div>
        </section>
        <section class="panel">
            <div class="panel-head"><h2>VIP и удержание клиентов</h2></div>
            <div class="panel-body">${vipCustomerList(r.vip_customers)}</div>
        </section>
    `;
}

function updateStatusBadge(status) {
    if (!status) return `<span class="status s-new">Не проверено</span>`;
    if (!status.ok) return `<span class="status s-cancelled">Ошибка проверки</span>`;
    if (status.release?.is_newer) return `<span class="status s-approved">Доступна версия ${esc(status.release.version || status.release.tag)}</span>`;
    return `<span class="status s-closed">Актуальная версия</span>`;
}

function updateReleaseHtml(status) {
    if (!status) return `<div class="notice">Нажмите «Проверить обновления», чтобы получить последний релиз GitHub.</div>`;
    if (!status.ok) {
        return `<div class="notice" role="alert"><strong>Не удалось проверить обновления.</strong><p>${esc(status.error || "Проверьте интернет или доступ к GitHub.")}</p></div>`;
    }
    const release = status.release || {};
    const asset = release.asset || {};
    return `
        <div class="update-release">
            <h4>${release.is_newer ? "Новый релиз найден" : "Последний релиз GitHub"}</h4>
            <div class="update-meta">
                <span class="status ${release.is_newer ? "s-approved" : "s-closed"}">${esc(release.tag || release.version || "без тега")}</span>
                ${release.prerelease ? `<span class="status s-estimate">pre-release</span>` : ""}
                <span class="count-pill">${asset.name ? esc(asset.name) : "нет .exe в релизе"}</span>
                <span class="count-pill">${bytesText(asset.size)}</span>
            </div>
            <div class="muted">Опубликовано: ${esc(release.published_at || "—")}</div>
            ${release.body ? `<pre>${esc(release.body)}</pre>` : `<div class="muted">Описание релиза не заполнено.</div>`}
            <div class="row-actions" style="justify-content:flex-start">
                <a class="btn ghost" href="${esc(release.release_url || status.releases_url)}" target="_blank" rel="noreferrer">Открыть релиз</a>
            </div>
        </div>`;
}

function renderUpdates() {
    const app = state.data.app;
    const status = state.updateStatus;
    const canInstall = Boolean(status?.ok && status.release?.is_newer && status.release?.has_asset && status.can_install);
    const installDisabled = !canInstall || state.updateInstalling;
    const installTitle = !status?.ok
        ? "Сначала выполните успешную проверку обновлений"
        : !status.release?.is_newer
            ? "Установлена последняя версия"
            : !status.release?.has_asset
                ? "В релизе нет файла STO_CRM.exe"
                : !status.can_install
                    ? "Автоустановка доступна только в собранном Windows .exe"
                    : "Скачать и установить обновление";
    return `
        <section class="update-card">
            <div class="toolbar">
                <div class="toolbar-left">
                    <h3>Обновление с GitHub</h3>
                    ${updateStatusBadge(status)}
                </div>
                <div class="toolbar-right">
                    <button class="btn ghost" type="button" data-action="check-update" ${state.updateLoading ? "disabled" : ""}>${state.updateLoading ? "Проверяем..." : "Проверить обновления"}</button>
                    <button class="btn primary" type="button" data-action="install-update" title="${esc(installTitle)}" ${installDisabled ? "disabled" : ""}>${state.updateInstalling ? "Устанавливаем..." : "Установить"}</button>
                </div>
            </div>
            <p>CRM проверяет release-only репозиторий: в GitHub хранится только готовый <strong>STO_CRM.exe</strong>, checksum и <strong>latest.json</strong>. Исходный код туда не загружается. Обновление скачивается с контролем размера и SHA-256, делает резерв текущего exe и перезапускает приложение.</p>
            <div class="update-meta">
                <span class="count-pill">Текущая версия: ${esc(app.version)}</span>
                <a class="count-pill" href="${esc(app.repository_url)}" target="_blank" rel="noreferrer">${esc(app.repository)}</a>
                <span class="count-pill">База не переносится: ${esc(app.db_path)}</span>
            </div>
            ${app.can_install_update ? "" : `<div class="notice"><strong>Вы запустили исходник Python.</strong><p>Автоустановка включается в Windows-сборке STO_CRM.exe. Для исходников обновляйте проект командой <code>git pull --ff-only</code> и перезапускайте Python.</p></div>`}
            ${updateReleaseHtml(status)}
        </section>
    `;
}

async function checkForUpdates(showToast = true) {
    state.updateLoading = true;
    render();
    try {
        state.updateStatus = await api("/api/update/status", {}, 0);
        if (showToast) {
            if (state.updateStatus.ok && state.updateStatus.release?.is_newer) toast(`Доступна версия ${state.updateStatus.release.version || state.updateStatus.release.tag}`);
            else if (state.updateStatus.ok) toast("Установлена актуальная версия");
            else toast(state.updateStatus.error || "Не удалось проверить обновления", "error");
        }
    } finally {
        state.updateLoading = false;
        render();
    }
}

async function installUpdate() {
    if (!state.updateStatus?.release?.is_newer) {
        toast("Новых обновлений нет");
        return;
    }
    if (!confirm("Скачать обновление, закрыть CRM и перезапустить новую версию? Перед установкой будет создана резервная копия текущего exe.")) return;
    state.updateInstalling = true;
    render();
    try {
        const result = await api("/api/update/install", { method: "POST", body: "{}" }, 0);
        toast(result.message || "Обновление запущено");
        document.body.innerHTML = '<main class="shutdown-state"><section class="shutdown-card"><h1>СТО CRM обновляется</h1><p>Приложение закроется, заменит exe и запустится снова. Базу данных обновление не трогает.</p></section></main>';
    } catch (error) {
        state.updateInstalling = false;
        render();
        throw error;
    }
}

function bindViewActions(root) {
    root.querySelectorAll("[data-action]").forEach(button => {
        button.addEventListener("click", event => {
            const action = event.currentTarget.dataset.action;
            const id = Number(event.currentTarget.dataset.id || 0);
            const routeTarget = event.currentTarget.dataset.routeTarget;
            if (routeTarget && routes[routeTarget] && routeTarget !== state.route) {
                setRoute(routeTarget);
            }
            if (action === "retry-load") loadData().catch(showError);
            else if (action === "dismiss-error") {
                state.lastError = "";
                render();
            }
            else if (action === "export-csv") {
                event.preventDefault();
                downloadCsv(event.currentTarget.dataset.export).catch(showError);
            }
            else if (action === "filter-status") {
                state.status = event.currentTarget.dataset.status;
                loadData().catch(showError);
            } else if (action === "new-appointment") openAppointmentModal();
            else if (action === "edit-appointment") openAppointmentModal(findAppointmentById(id));
            else if (action === "new-inspection") openInspectionModal();
            else if (action === "edit-inspection") openInspectionModal(findInspectionById(id));
            else if (action === "new-customer") openCustomerModal();
            else if (action === "edit-customer") openCustomerModal(findCustomerById(id));
            else if (action === "new-vehicle") openVehicleModal();
            else if (action === "edit-vehicle") openVehicleModal(findVehicleById(id));
            else if (action === "open-catalog") setRoute("catalog");
            else if (action === "open-orders") setRoute("orders");
            else if (action === "open-appointments") setRoute("appointments");
            else if (action === "open-inventory") setRoute("inventory");
            else if (action === "open-action-plan") document.querySelector(".action-center")?.scrollIntoView({ behavior: "smooth", block: "start" });
            else if (action === "new-inventory") openInventoryModal();
            else if (action === "edit-inventory") openInventoryModal(findInventoryById(id));
            else if (action === "new-order") openOrderModal();
            else if (action === "edit-order") openOrderModal(findOrderById(id));
            else if (action === "duplicate-order") openOrderModal(orderDuplicateDraft(findOrderById(id)));
            else if (action === "print-order") openPrintOrder(id).catch(showError);
            else if (action === "check-update") checkForUpdates(true).catch(showError);
            else if (action === "install-update") installUpdate().catch(showError);
        });
    });
}

function findById(list, id) {
    return list.find(item => Number(item.id) === Number(id));
}

function findCustomerById(id) {
    return findById(state.data?.customers || [], id) || findById(state.data?.lookups?.customers || [], id) || null;
}

function findVehicleById(id) {
    return findById(state.data?.vehicles || [], id) || findById(state.data?.lookups?.vehicles || [], id) || null;
}

function findInventoryById(id) {
    return findById(state.data?.inventory || [], id) || findById(state.data?.lookups?.inventory || [], id) || null;
}

function findOrderById(id) {
    return findById(state.data?.orders || [], id) || findById(state.data?.lookups?.orders || [], id) || null;
}

function findAppointmentById(id) {
    return findById(state.data?.appointments || [], id) || findById(state.data?.lookups?.appointments || [], id) || null;
}

function findInspectionById(id) {
    return findById(state.data?.inspections || [], id) || findById(state.data?.lookups?.inspections || [], id) || null;
}

function orderDuplicateDraft(order = {}) {
    return {
        ...order,
        id: "",
        number: "",
        status: "new",
        paid: 0,
        closed_at: "",
        authorized_at: "",
        follow_up_at: "",
        items: (order.items || []).map(item => ({ ...item, id: "" }))
    };
}

let lastFocusedElement = null;
let appTabbableSnapshot = [];

function modalFocusableElements() {
    const modal = $("#modal");
    return $$('a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])', modal)
        .filter(element => !element.closest('[hidden], [aria-hidden="true"]') && (element.getClientRects().length > 0 || element === document.activeElement));
}

function shouldKeepModalForEscape(event) {
    if (event.defaultPrevented) return true;
    const target = event.target;
    if (!(target instanceof HTMLElement)) return false;
    if (target.isContentEditable) return true;
    if (target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return true;
    if (target instanceof HTMLInputElement) return Boolean(target.getAttribute("list"));
    return false;
}

function focusModalStart() {
    const preferred = $("#modalBody input:not([type='hidden']), #modalBody select, #modalBody textarea, #modalFoot .btn.primary, #modalClose");
    if (preferred instanceof HTMLElement) preferred.focus({ preventScroll: true });
    else $("#modal")?.focus({ preventScroll: true });
}

function setAppInert(isInert) {
    const app = $(".app");
    if (!app) return;
    if (isInert) {
        app.setAttribute("aria-hidden", "true");
        if ("inert" in app) {
            app.inert = true;
            return;
        }
        appTabbableSnapshot = $$('a[href], button, textarea, input, select, [tabindex]', app).map(element => ({
            element,
            tabindex: element.getAttribute("tabindex")
        }));
        appTabbableSnapshot.forEach(({ element }) => element.setAttribute("tabindex", "-1"));
    } else {
        app.removeAttribute("aria-hidden");
        if ("inert" in app) app.inert = false;
        appTabbableSnapshot.forEach(({ element, tabindex }) => {
            if (!document.contains(element)) return;
            if (tabindex === null) element.removeAttribute("tabindex");
            else element.setAttribute("tabindex", tabindex);
        });
        appTabbableSnapshot = [];
    }
}

function openModal(title, body, foot, size = "") {
    lastFocusedElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const allowedSizes = new Set(["", "small", "wide"]);
    const modalSize = allowedSizes.has(size) ? size : "";
    $("#modalTitle").textContent = title;
    $("#modalBody").innerHTML = body;
    $("#modalFoot").innerHTML = foot;
    $("#modal").className = modalSize ? `modal ${modalSize}` : "modal";
    $("#modalBackdrop").classList.add("open");
    state.modalDirty = false;
    setAppInert(true);
    bindModalSubmitHandlers();
    requestAnimationFrame(focusModalStart);
}

function closeModal(force = false) {
    if (state.saving && !force) return false;
    if (!force && state.modalDirty && !confirm("Закрыть окно без сохранения изменений?")) return false;
    $("#modalBackdrop").classList.remove("open");
    setAppInert(false);
    $("#modalBody").innerHTML = "";
    $("#modalFoot").innerHTML = "";
    if (lastFocusedElement && document.contains(lastFocusedElement)) {
        lastFocusedElement.focus();
    }
    lastFocusedElement = null;
    state.modalDirty = false;
    return true;
}

function handleModalKeydown(event) {
    if ((event.ctrlKey || event.metaKey) && event.key.toLocaleLowerCase("ru-RU") === "k") {
        event.preventDefault();
        openCommandPalette();
        return;
    }
    if ($("#commandPalette")?.classList.contains("open")) {
        if (event.key === "Escape") {
            event.preventDefault();
            closeCommandPalette();
        }
        return;
    }
    const backdrop = $("#modalBackdrop");
    if (!backdrop.classList.contains("open")) return;
    if (event.key === "Escape") {
        if (shouldKeepModalForEscape(event)) return;
        event.preventDefault();
        closeModal();
        return;
    }
    if (event.key !== "Tab") return;
    const modal = $("#modal");
    const focusable = modalFocusableElements();
    if (!focusable.length) {
        event.preventDefault();
        modal.focus();
        return;
    }
    if (!modal.contains(document.activeElement)) {
        event.preventDefault();
        focusable[0].focus();
        return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
    }
}

function bindModalSubmitHandlers() {
    const modal = $("#modal");
    $$("form", modal).forEach(form => {
        form.addEventListener("input", event => {
            markModalDirty();
            clearFormError(event.target);
        });
        form.addEventListener("change", event => {
            markModalDirty();
            clearFormError(event.target);
        });
        form.addEventListener("submit", event => {
            event.preventDefault();
            $("#modalFoot [data-save]:not([data-save='cancel']):not([data-save^='delete']):not([data-save='print-order'])")?.click();
        });
    });
}

async function openPrintOrder(id) {
    const printWindow = window.open("", "_blank");
    if (!printWindow) {
        toast("Разрешите всплывающие окна, чтобы открыть печатную форму.", "error");
        return;
    }
    printWindow.opener = null;
    printWindow.document.write("<p>Загрузка печатной формы...</p>");
    try {
        const response = await fetch(`/print/order/${encodeURIComponent(id)}`, {
            headers: state.data?.app?.csrf_token ? { "X-CSRF-Token": state.data.app.csrf_token } : {},
            cache: "no-store"
        });
        const html = await response.text();
        if (!response.ok) throw new Error(html || "Не удалось открыть печатную форму");
        printWindow.document.open();
        printWindow.document.write(html);
        printWindow.document.close();
    } catch (error) {
        printWindow.close();
        throw error;
    }
}

function markModalDirty() {
    state.modalDirty = true;
}

function setSaveButtonsBusy(isBusy) {
    state.saving = isBusy;
    $("#modalBackdrop")?.classList.toggle("saving", isBusy);
    $$("[data-save]").forEach(button => {
        button.disabled = isBusy;
        button.setAttribute("aria-busy", String(isBusy));
    });
    $("#modalClose")?.toggleAttribute("disabled", isBusy);
}

function collectForm(form) {
    const data = Object.fromEntries(new FormData(form).entries());
    $$('input[type="checkbox"][name]', form).forEach(input => {
        data[input.name] = input.checked ? (input.value || "1") : "0";
    });
    return data;
}

function customerOptions(selected) {
    const customers = state.data.lookups?.customers || state.data.customers;
    const placeholder = customers.length ? "" : `<option value="">Нет клиентов</option>`;
    return placeholder + customers.map(c => `<option value="${c.id}" ${Number(selected) === Number(c.id) ? "selected" : ""}>${esc(c.name)} · ${esc(c.phone)}</option>`).join("");
}

function vehicleOptions(customerId, selected) {
    const allVehicles = state.data.lookups?.vehicles || state.data.vehicles;
    const vehicles = allVehicles.filter(v => !customerId || Number(v.customer_id) === Number(customerId));
    return `<option value="">Не выбран</option>` + vehicles.map(v => `<option value="${v.id}" ${Number(selected) === Number(v.id) ? "selected" : ""}>${esc(vehicleName(v))}</option>`).join("");
}

function catalogModels(make) {
    const models = state.data?.car_catalog?.models || {};
    if (models[make]) return models[make];
    const normalized = String(make || "").toLocaleLowerCase("ru-RU");
    const found = Object.keys(models).find(key => key.toLocaleLowerCase("ru-RU") === normalized);
    return found ? models[found] : [];
}

function datalistOptions(values, selected = "") {
    const unique = [];
    [...(values || []), selected].forEach(value => {
        const normalized = String(value || "").trim();
        if (normalized && !unique.includes(normalized)) unique.push(normalized);
    });
    return unique.map(value => `<option value="${esc(value)}"></option>`).join("");
}

function partAvailability(partId) {
    const inventory = state.data.lookups?.inventory || state.data.inventory;
    const part = findById(inventory, Number(partId));
    return part ? `${qty(part.quantity)} ${esc(part.unit)}` : "неизвестно";
}

function partSourceOptions(item = {}) {
    const inventory = state.data.lookups?.inventory || state.data.inventory;
    const selected = Number(item.inventory_id || 0);
    const outsideSelected = item.kind === "part" && !selected;
    return `<option value="" ${outsideSelected ? "selected" : ""}>Вне склада / заказная</option>` + inventory.map(part => {
        const selectedAttr = selected === Number(part.id) ? "selected" : "";
        return `<option value="${part.id}" ${selectedAttr}>${esc(part.name)} · ${qty(part.quantity)} ${esc(part.unit)} · ${money(part.price)}</option>`;
    }).join("");
}

function partSourceHint(item = {}) {
    if (item.kind !== "part") return "";
    if (item.inventory_id) return `<div class="source-note">Складская: спишется при закрытии. Доступно: ${partAvailability(item.inventory_id)}</div>`;
    return `<div class="source-note">Вне склада: не влияет на остатки, но попадает в сумму, печать и отчеты.</div>`;
}

function channelOptions(selected = "phone") {
    return Object.entries(channelLabels)
        .map(([key, label]) => `<option value="${key}" ${(selected || "phone") === key ? "selected" : ""}>${esc(label)}</option>`)
        .join("");
}

function appointmentStatusOptions(selected = "scheduled") {
    const statuses = state.data?.appointment_statuses || appointmentStatusFallback;
    return Object.entries(statuses)
        .map(([key, label]) => `<option value="${key}" ${(selected || "scheduled") === key ? "selected" : ""}>${esc(label)}</option>`)
        .join("");
}

function inspectionStatusOptions(selected = "draft") {
    const statuses = state.data?.inspection_statuses || inspectionStatusFallback;
    return Object.entries(statuses)
        .map(([key, label]) => `<option value="${key}" ${(selected || "draft") === key ? "selected" : ""}>${esc(label)}</option>`)
        .join("");
}

function inspectionConditionOptions(selected = "ok") {
    const statuses = state.data?.inspection_conditions || inspectionConditionFallback;
    return Object.entries(statuses)
        .map(([key, label]) => `<option value="${key}" ${(selected || "ok") === key ? "selected" : ""}>${esc(label)}</option>`)
        .join("");
}

function itemApprovalOptions(selected = "approved") {
    const statuses = state.data?.item_approval_statuses || itemApprovalFallback;
    return Object.entries(statuses)
        .map(([key, label]) => `<option value="${key}" ${(selected || "approved") === key ? "selected" : ""}>${esc(label)}</option>`)
        .join("");
}

function orderOptions(customerId, vehicleId, selected) {
    const allOrders = state.data.lookups?.orders || state.data.orders || [];
    const orders = allOrders.filter(order => {
        if (customerId && Number(order.customer_id) !== Number(customerId)) return false;
        if (vehicleId && order.vehicle_id && Number(order.vehicle_id) !== Number(vehicleId)) return false;
        return true;
    });
    return `<option value="">Не выбран</option>` + orders.map(order => `<option value="${order.id}" ${Number(selected) === Number(order.id) ? "selected" : ""}>${esc(order.number)} · ${esc(orderVehicle(order) || order.customer_name)}</option>`).join("");
}

function openAppointmentModal(appointment = {}) {
    const lookupCustomers = state.data.lookups?.customers || state.data.customers;
    if (!lookupCustomers.length) {
        openModal(
            "Новая запись",
            `<div class="notice">В базе нет клиентов для записи.</div>`,
            `<button class="btn" type="button" data-save="cancel">Закрыть</button>`,
            "small"
        );
        return;
    }
    const selectedCustomer = appointment.customer_id || lookupCustomers[0]?.id || "";
    openModal(
        appointment.id ? "Запись клиента" : "Новая запись",
        `<form id="entityForm" class="form-grid">
            ${selectField("appointment", "customer_id", "Клиент", customerOptions(selectedCustomer), "required", "span-2")}
            ${selectField("appointment", "vehicle_id", "Автомобиль", vehicleOptions(selectedCustomer, appointment.vehicle_id), "", "span-2")}
            ${inputField("appointment", "scheduled_at", "Дата и время", `type="datetime-local" value="${inputDateValue(appointment.scheduled_at)}" required`)}
            ${inputField("appointment", "duration_minutes", "Длительность, мин", `type="number" min="15" step="15" value="${esc(appointment.duration_minutes || 60)}"`)}
            ${selectField("appointment", "status", "Статус", appointmentStatusOptions(appointment.status))}
            ${inputField("appointment", "advisor", "Мастер-приемщик", `value="${esc(appointment.advisor || "Администратор")}"`)}
            ${inputField("appointment", "reason", "Причина визита", `value="${esc(appointment.reason)}" placeholder="ТО, диагностика, замена шин"`, "span-2")}
            ${textareaField("appointment", "notes", "Заметки", appointment.notes, "", "span-2")}
        </form>`,
        `${appointment.id ? `<button class="btn danger" type="button" data-save="delete-appointment" data-id="${appointment.id}">Удалить</button>` : ""}
         <button class="btn" type="button" data-save="cancel">Отмена</button>
         <button class="btn primary" type="button" data-save="appointment" data-id="${appointment.id || ""}">Сохранить</button>`,
        "small"
    );
    $("#appointment_customer_id").addEventListener("change", event => {
        $("#appointment_vehicle_id").innerHTML = vehicleOptions(event.target.value, "");
    });
}

const standardInspectionTemplate = [
    { area: "Тормоза", title: "Тормозные колодки и диски", condition_status: "ok", approval_status: "approved", recommendation: "", estimate: 0 },
    { area: "Шины", title: "Протектор и давление шин", condition_status: "ok", approval_status: "approved", recommendation: "", estimate: 0 },
    { area: "Жидкости", title: "Моторное масло, ОЖ, тормозная жидкость", condition_status: "ok", approval_status: "approved", recommendation: "", estimate: 0 },
    { area: "Подвеска", title: "Люфты, сайлентблоки, амортизаторы", condition_status: "ok", approval_status: "approved", recommendation: "", estimate: 0 },
    { area: "Свет", title: "Наружное освещение", condition_status: "ok", approval_status: "approved", recommendation: "", estimate: 0 },
    { area: "АКБ", title: "Состояние аккумулятора", condition_status: "ok", approval_status: "approved", recommendation: "", estimate: 0 }
];

function openInspectionModal(inspection = {}) {
    const lookupCustomers = state.data.lookups?.customers || state.data.customers;
    if (!lookupCustomers.length) {
        openModal(
            "Новый осмотр",
            `<div class="notice">В базе нет клиентов для цифрового осмотра.</div>`,
            `<button class="btn" type="button" data-save="cancel">Закрыть</button>`,
            "small"
        );
        return;
    }
    state.inspectionDraftItems = (inspection.items || standardInspectionTemplate).map(item => ({ ...item }));
    const selectedCustomer = inspection.customer_id || lookupCustomers[0]?.id || "";
    const selectedVehicle = inspection.vehicle_id || "";
    openModal(
        inspection.id ? "Цифровой осмотр DVI" : "Новый цифровой осмотр",
        `<form id="inspectionForm" class="stack">
            <div class="form-grid three">
                ${selectField("inspection", "customer_id", "Клиент", customerOptions(selectedCustomer), "required")}
                ${selectField("inspection", "vehicle_id", "Автомобиль", vehicleOptions(selectedCustomer, selectedVehicle))}
                ${selectField("inspection", "order_id", "Заказ-наряд", orderOptions(selectedCustomer, selectedVehicle, inspection.order_id))}
                ${selectField("inspection", "status", "Статус", inspectionStatusOptions(inspection.status))}
                ${inputField("inspection", "inspector", "Механик", `value="${esc(inspection.inspector || "Механик")}"`)}
                ${inputField("inspection", "inspected_at", "Дата осмотра", `type="datetime-local" value="${inputDateValue(inspection.inspected_at)}"`)}
                ${textareaField("inspection", "summary", "Итог осмотра", inspection.summary, "", "span-3")}
            </div>
            <div class="toolbar">
                <div class="toolbar-left"><strong>Чек-лист DVI</strong></div>
                <div class="toolbar-right">
                    <button class="btn" type="button" id="useInspectionTemplate">Шаблон</button>
                    <button class="btn" type="button" id="addInspectionItem">+ Пункт</button>
                </div>
            </div>
            <div id="inspectionItemsHost"></div>
        </form>`,
        `${inspection.id ? `<button class="btn danger" type="button" data-save="delete-inspection" data-id="${inspection.id}">Удалить</button>` : ""}
         <button class="btn" type="button" data-save="cancel">Отмена</button>
         <button class="btn primary" type="button" data-save="inspection" data-id="${inspection.id || ""}">Сохранить</button>`
    );
    renderInspectionItems();
    $("#inspection_customer_id").addEventListener("change", event => {
        $("#inspection_vehicle_id").innerHTML = vehicleOptions(event.target.value, "");
        $("#inspection_order_id").innerHTML = orderOptions(event.target.value, "", "");
    });
    $("#inspection_vehicle_id").addEventListener("change", event => {
        $("#inspection_order_id").innerHTML = orderOptions($("#inspection_customer_id").value, event.target.value, "");
    });
    $("#addInspectionItem").addEventListener("click", () => {
        state.inspectionDraftItems.push({ area: "", title: "", condition_status: "ok", approval_status: "approved", recommendation: "", estimate: 0 });
        renderInspectionItems();
    });
    $("#useInspectionTemplate").addEventListener("click", () => {
        state.inspectionDraftItems = standardInspectionTemplate.map(item => ({ ...item }));
        renderInspectionItems();
    });
}

function renderInspectionItems() {
    const host = $("#inspectionItemsHost");
    host.innerHTML = `<div class="items-table inspection-items">
        <table aria-label="Пункты цифрового осмотра">
            <thead>${tableHead(["Зона", "Пункт", "Состояние", "Согласование", "Рекомендация", {text: "Оценка", className: "money"}, ""])}</thead>
            <tbody>
                ${state.inspectionDraftItems.map((item, index) => `
                    <tr data-inspection-index="${index}">
                        <td><input data-inspection-item="area" aria-label="Зона осмотра" value="${esc(item.area)}" required></td>
                        <td><input data-inspection-item="title" aria-label="Пункт осмотра" value="${esc(item.title)}" required></td>
                        <td><select data-inspection-item="condition_status" aria-label="Состояние пункта осмотра">${inspectionConditionOptions(item.condition_status)}</select></td>
                        <td><select data-inspection-item="approval_status" aria-label="Статус согласования пункта осмотра">${itemApprovalOptions(item.approval_status)}</select></td>
                        <td><input data-inspection-item="recommendation" aria-label="Рекомендация" value="${esc(item.recommendation)}"></td>
                        <td><input data-inspection-item="estimate" aria-label="Оценка работ" class="money" type="number" inputmode="decimal" step="0.01" min="0" value="${esc(item.estimate || 0)}"></td>
                        <td><button class="btn icon" type="button" data-remove-inspection-item="${index}" title="Удалить" aria-label="Удалить пункт осмотра">×</button></td>
                    </tr>`).join("")}
            </tbody>
        </table>
    </div>`;
    $$("[data-inspection-item]", host).forEach(input => {
        input.addEventListener("input", syncInspectionItemStateOnly);
        input.addEventListener("change", syncInspectionItemStateOnly);
    });
    $$("[data-remove-inspection-item]", host).forEach(button => {
        button.addEventListener("click", event => {
            state.inspectionDraftItems.splice(Number(event.currentTarget.dataset.removeInspectionItem), 1);
            if (!state.inspectionDraftItems.length) state.inspectionDraftItems.push({ area: "", title: "", condition_status: "ok", approval_status: "approved", recommendation: "", estimate: 0 });
            renderInspectionItems();
        });
    });
}

function openCustomerModal(customer = {}) {
    openModal(
        customer.id ? "Клиент" : "Новый клиент",
        `<form id="entityForm" class="form-grid">
            ${inputField("customer", "name", "Имя", `value="${esc(customer.name)}" required`)}
            ${inputField("customer", "phone", "Телефон", `type="tel" value="${esc(customer.phone)}" inputmode="tel" autocomplete="tel" placeholder="+7 900 000-00-00"`)}
            ${inputField("customer", "email", "Email", `type="email" value="${esc(customer.email)}" inputmode="email" autocomplete="email"`)}
            ${inputField("customer", "source", "Источник", `value="${esc(customer.source)}"`)}
            ${selectField("customer", "preferred_channel", "Канал связи", channelOptions(customer.preferred_channel))}
            <label class="check-field" for="customer_reminder_consent"><input id="customer_reminder_consent" type="checkbox" name="reminder_consent" value="1" ${customer.reminder_consent === 0 ? "" : "checked"}> Сервисные напоминания</label>
            ${textareaField("customer", "notes", "Заметки", customer.notes, "", "span-2")}
        </form>`,
        `${customer.id ? `<button class="btn danger" type="button" data-save="delete-customer" data-id="${customer.id}">Удалить</button>` : ""}
         <button class="btn" type="button" data-save="cancel">Отмена</button>
         <button class="btn primary" type="button" data-save="customer" data-id="${customer.id || ""}">Сохранить</button>`,
        "small"
    );
}

function openVehicleModal(vehicle = {}) {
    const makes = state.data?.car_catalog?.makes || [];
    const customers = state.data.lookups?.customers || state.data.customers;
    const hasCustomers = customers.length > 0;
    openModal(
        vehicle.id ? "Автомобиль" : "Новый автомобиль",
        `<form id="entityForm" class="form-grid">
            ${hasCustomers ? "" : `<div class="notice span-2">В базе нет клиентов для привязки автомобиля.</div>`}
            ${selectField("vehicle", "customer_id", "Клиент", customerOptions(vehicle.customer_id), "required", "span-2")}
            ${labeledField("vehicleMake", "Марка", `<input name="make" id="vehicleMake" list="vehicleMakeList" value="${esc(vehicle.make)}"><datalist id="vehicleMakeList">${datalistOptions(makes, vehicle.make)}</datalist>`)}
            ${labeledField("vehicleModel", "Модель", `<input name="model" id="vehicleModel" list="vehicleModelList" value="${esc(vehicle.model)}"><datalist id="vehicleModelList">${datalistOptions(catalogModels(vehicle.make), vehicle.model)}</datalist>`)}
            ${inputField("vehicle", "year", "Год", `type="number" min="1900" max="${new Date().getFullYear() + 1}" value="${esc(vehicle.year || "")}"`)}
            ${inputField("vehicle", "plate", "Госномер", `value="${esc(vehicle.plate)}" autocomplete="off" maxlength="40" autocapitalize="characters" spellcheck="false"`)}
            ${inputField("vehicle", "vin", "VIN", `value="${esc(vehicle.vin)}" maxlength="17" minlength="17" pattern="[A-HJ-NPR-Za-hj-npr-z0-9]{17}" title="VIN должен содержать 17 символов без I, O и Q" autocomplete="off" autocapitalize="characters" spellcheck="false"`)}
            ${inputField("vehicle", "mileage", "Пробег, км", `type="number" inputmode="numeric" step="1" min="0" value="${esc(vehicle.mileage || "")}"`)}
            ${inputField("vehicle", "next_service_at", "Следующий сервис", `type="date" value="${esc(String(vehicle.next_service_at || "").slice(0, 10))}"`)}
            ${inputField("vehicle", "next_service_mileage", "Сервисный пробег", `type="number" inputmode="numeric" step="1" min="0" value="${esc(vehicle.next_service_mileage || "")}"`)}
            ${textareaField("vehicle", "notes", "Заметки", vehicle.notes, "", "span-2")}
        </form>`,
        `${vehicle.id ? `<button class="btn danger" type="button" data-save="delete-vehicle" data-id="${vehicle.id}">Удалить</button>` : ""}
         <button class="btn" type="button" data-save="cancel">Отмена</button>
         <button class="btn primary" type="button" data-save="vehicle" data-id="${vehicle.id || ""}" ${hasCustomers ? "" : "disabled"}>Сохранить</button>`,
        "small"
    );
    bindVehicleCatalog();
}

function bindVehicleCatalog() {
    const makeInput = $("#vehicleMake");
    const modelInput = $("#vehicleModel");
    const modelList = $("#vehicleModelList");
    if (!makeInput || !modelInput || !modelList) return;
    const refreshModels = () => {
        modelList.innerHTML = datalistOptions(catalogModels(makeInput.value), modelInput.value);
    };
    makeInput.addEventListener("input", refreshModels);
    const uppercaseInput = event => { event.target.value = String(event.target.value || "").toUpperCase(); };
    $("#vehicle_vin")?.addEventListener("input", uppercaseInput);
    $("#vehicle_plate")?.addEventListener("input", uppercaseInput);
    refreshModels();
}

function openInventoryModal(part = {}) {
    openModal(
        part.id ? "Складская позиция" : "Новая складская позиция",
        `<form id="entityForm" class="form-grid">
            ${inputField("inventory", "name", "Название", `value="${esc(part.name)}" required`)}
            ${inputField("inventory", "sku", "Артикул", `value="${esc(part.sku)}"`)}
            ${inputField("inventory", "brand", "Бренд", `value="${esc(part.brand)}"`)}
            ${inputField("inventory", "unit", "Ед.", `value="${esc(part.unit || "шт")}"`)}
            ${inputField("inventory", "quantity", "Остаток", `type="number" inputmode="decimal" step="0.01" min="0" value="${esc(part.quantity || 0)}"`)}
            ${inputField("inventory", "min_quantity", "Минимум", `type="number" inputmode="decimal" step="0.01" min="0" value="${esc(part.min_quantity || 0)}"`)}
            ${inputField("inventory", "price", "Цена", `type="number" inputmode="decimal" step="0.01" min="0" value="${esc(part.price || 0)}"`)}
            ${inputField("inventory", "cost", "Себестоимость", `type="number" inputmode="decimal" step="0.01" min="0" value="${esc(part.cost || 0)}"`)}
            ${inputField("inventory", "supplier", "Поставщик", `value="${esc(part.supplier)}"`, "span-2")}
            ${textareaField("inventory", "notes", "Заметки", part.notes, "", "span-2")}
        </form>`,
        `${part.id ? `<button class="btn danger" type="button" data-save="delete-inventory" data-id="${part.id}">Удалить</button>` : ""}
         <button class="btn" type="button" data-save="cancel">Отмена</button>
         <button class="btn primary" type="button" data-save="inventory" data-id="${part.id || ""}">Сохранить</button>`,
        "small"
    );
}

function openOrderModal(order = {}) {
    if (!order) {
        toast("Заказ не найден в текущей выборке. Очистите поиск или обновите данные.", "error");
        return;
    }
    state.orderDraftItems = (order.items || [{ kind: "service", title: "", approval_status: "approved", quantity: 1, unit_price: 0, unit_cost: 0 }])
        .map(item => ({ approval_status: "approved", inventory_id: "", ...item }));
    const lookupCustomers = state.data.lookups?.customers || state.data.customers;
    if (!lookupCustomers.length) {
        openModal(
            "Новый заказ-наряд",
            `<div class="notice">В базе нет клиентов для оформления заказ-наряда.</div>`,
            `<button class="btn" type="button" data-save="cancel">Закрыть</button>`,
            "small"
        );
        return;
    }
    const selectedCustomer = order.customer_id || lookupCustomers[0]?.id || "";
    openModal(
        order.id ? `Заказ-наряд ${order.number}` : "Новый заказ-наряд",
        `<form id="orderForm" class="stack">
            <div class="form-grid three">
                ${selectField("order", "customer_id", "Клиент", customerOptions(selectedCustomer), "required")}
                ${selectField("order", "vehicle_id", "Автомобиль", vehicleOptions(selectedCustomer, order.vehicle_id))}
                ${selectField("order", "status", "Статус", Object.entries(state.data.statuses).map(([key, label]) => `<option value="${key}" ${order.status === key ? "selected" : ""}>${esc(label)}</option>`).join(""))}
                ${selectField("order", "priority", "Приоритет", Object.entries(state.data.priorities || priorityLabels).map(([key, label]) => `<option value="${key}" ${(order.priority || "normal") === key ? "selected" : ""}>${esc(label)}</option>`).join(""))}
                ${inputField("order", "advisor", "Мастер-приемщик", `value="${esc(order.advisor || "Администратор")}"`)}
                ${inputField("order", "mechanic", "Механик", `value="${esc(order.mechanic)}"`)}
                ${inputField("order", "promised_at", "Срок", `type="datetime-local" value="${inputDateValue(order.promised_at)}"`)}
                ${inputField("order", "odometer", "Пробег", `type="number" inputmode="numeric" step="1" min="0" value="${esc(order.odometer || "")}"`)}
                ${inputField("order", "paid", "Оплачено", `type="number" inputmode="decimal" step="0.01" min="0" value="${esc(order.paid || 0)}"`)}
                ${inputField("order", "discount", "Скидка", `type="number" inputmode="decimal" step="0.01" min="0" value="${esc(order.discount || 0)}"`)}
                ${inputField("order", "tax_rate", "Налог, %", `type="number" inputmode="decimal" step="0.01" min="0" max="100" value="${esc(order.tax_rate || 0)}"`)}
                ${inputField("order", "payment_method", "Оплата", `value="${esc(order.payment_method)}"`)}
                ${inputField("order", "authorized_by", "Согласовал", `value="${esc(order.authorized_by)}"`)}
                ${inputField("order", "authorized_at", "Дата согласования", `type="datetime-local" value="${inputDateValue(order.authorized_at)}"`)}
                ${inputField("order", "follow_up_at", "Follow-up", `type="datetime-local" value="${inputDateValue(order.follow_up_at)}"`)}
                ${textareaField("order", "complaint", "Жалоба клиента", order.complaint, "", "span-3")}
                ${textareaField("order", "diagnosis", "Диагностика", order.diagnosis, "", "span-3")}
                ${textareaField("order", "recommendations", "Рекомендации", order.recommendations, "", "span-3")}
            </div>
            <div class="toolbar">
                <div class="toolbar-left"><strong>Работы и запчасти</strong></div>
                <div class="toolbar-right">
                    <button class="btn" type="button" id="addService">+ Работа</button>
                    <button class="btn" type="button" id="addPart">+ Запчасть</button>
                </div>
            </div>
            <div class="notice">Запчасть можно выбрать со склада или указать вручную как «вне склада» — такие позиции не списывают остатки, но учитываются в сумме заказ-наряда.</div>
            <div id="itemsHost"></div>
        </form>`,
        `${order.id ? `<button class="btn danger" type="button" data-save="delete-order" data-id="${order.id}">Удалить</button>` : ""}
         ${order.id ? `<button class="btn ghost" type="button" data-save="print-order" data-id="${order.id}">Печать</button>` : ""}
         <button class="btn" type="button" data-save="cancel">Отмена</button>
         <button class="btn primary" type="button" data-save="order" data-id="${order.id || ""}">Сохранить</button>`
    );
    renderOrderItems();
    $("#order_customer_id").addEventListener("change", event => {
        $("#order_vehicle_id").innerHTML = vehicleOptions(event.target.value, "");
    });
    $("#addService").addEventListener("click", () => {
        state.orderDraftItems.push({ kind: "service", title: "", approval_status: "approved", quantity: 1, unit_price: 0, unit_cost: 0 });
        renderOrderItems();
    });
    $("#addPart").addEventListener("click", () => {
        state.orderDraftItems.push({ kind: "part", inventory_id: "", title: "", approval_status: "approved", quantity: 1, unit_price: 0, unit_cost: 0 });
        renderOrderItems();
    });
    ['discount', 'tax_rate', 'paid'].forEach(name => {
        const input = document.querySelector(`[name="${name}"]`);
        if (input) input.addEventListener("input", () => {
            const totals = $("#orderTotals");
            if (totals) totals.outerHTML = orderTotalsHtml();
        });
    });
}

function renderOrderItems() {
    const host = $("#itemsHost");
    host.innerHTML = `<div class="items-table">
        <table aria-label="Позиции заказ-наряда">
            <thead>${tableHead(["Тип", "Источник запчасти", "Наименование", "Согласование", "Кол-во", "Цена", "Себест.", {text: "Сумма", className: "money"}, ""])}</thead>
            <tbody>
                ${state.orderDraftItems.map((item, index) => `
                    <tr data-index="${index}">
                        <td><select data-item="kind" aria-label="Тип позиции">
                            <option value="service" ${item.kind === "service" ? "selected" : ""}>Работа</option>
                            <option value="part" ${item.kind === "part" ? "selected" : ""}>Запчасть</option>
                        </select></td>
                        <td><select class="source-select" data-item="inventory_id" aria-label="Источник запчасти" ${item.kind !== "part" ? "disabled" : ""}>${partSourceOptions(item)}</select>${partSourceHint(item)}</td>
                        <td><input data-item="title" aria-label="Наименование позиции" value="${esc(item.title)}" required></td>
                        <td><select data-item="approval_status" aria-label="Статус согласования позиции">${itemApprovalOptions(item.approval_status)}</select></td>
                        <td><input data-item="quantity" aria-label="Количество" type="number" inputmode="decimal" step="0.01" min="0" value="${esc(item.quantity || 1)}"></td>
                        <td><input data-item="unit_price" aria-label="Цена" type="number" inputmode="decimal" step="0.01" min="0" value="${esc(item.unit_price || 0)}"></td>
                        <td><input data-item="unit_cost" aria-label="Себестоимость" type="number" inputmode="decimal" step="0.01" min="0" value="${esc(item.unit_cost || 0)}"></td>
                        <td class="money" data-row-total>${money((item.approval_status || "approved") === "approved" ? num(item.quantity) * num(item.unit_price) : 0)}</td>
                        <td><button class="btn icon" type="button" data-remove-item="${index}" title="Удалить" aria-label="Удалить позицию заказ-наряда">×</button></td>
                    </tr>`).join("")}
            </tbody>
        </table>
    </div>${orderTotalsHtml()}`;
    $$("[data-item]", host).forEach(input => {
        input.addEventListener("change", syncOrderItemsFromDom);
        input.addEventListener("input", syncOrderItemStateOnly);
    });
    $$("[data-remove-item]", host).forEach(button => {
        button.addEventListener("click", event => {
            state.orderDraftItems.splice(Number(event.currentTarget.dataset.removeItem), 1);
            if (!state.orderDraftItems.length) state.orderDraftItems.push({ kind: "service", title: "", approval_status: "approved", quantity: 1, unit_price: 0, unit_cost: 0 });
            renderOrderItems();
        });
    });
}

function syncOrderItemsFromDom(event) {
    const row = event.target.closest("tr[data-index]");
    if (!row) return;
    const index = Number(row.dataset.index);
    const item = state.orderDraftItems[index];
    $$("[data-item]", row).forEach(input => {
        item[input.dataset.item] = input.value;
    });
    if (event.target.dataset.item === "kind") {
        if (item.kind === "service") item.inventory_id = "";
        if (item.kind === "part") item.inventory_id = item.inventory_id || "";
    }
    if (event.target.dataset.item === "inventory_id") {
        if (item.inventory_id) {
            const inventory = state.data.lookups?.inventory || state.data.inventory;
            const part = findById(inventory, Number(item.inventory_id));
            if (part) {
                item.title = part.name;
                item.unit_price = part.price;
                item.unit_cost = part.cost;
            }
        } else if (item.kind === "part") {
            item.title = item.title || "";
            item.unit_price = num(item.unit_price, 0);
            item.unit_cost = num(item.unit_cost, 0);
        }
    }
    renderOrderItems();
}

function orderTotalsHtml() {
    const approved = state.orderDraftItems.filter(i => (i.approval_status || "approved") === "approved");
    const service = approved.filter(i => i.kind === "service").reduce((sum, i) => sum + num(i.quantity) * num(i.unit_price), 0);
    const parts = approved.filter(i => i.kind === "part").reduce((sum, i) => sum + num(i.quantity) * num(i.unit_price), 0);
    const deferred = state.orderDraftItems.filter(i => (i.approval_status || "approved") !== "approved")
        .reduce((sum, i) => sum + num(i.quantity) * num(i.unit_price), 0);
    const subtotal = service + parts;
    const discountPreview = Math.min(num(document.querySelector('[name="discount"]')?.value, 0), subtotal);
    const taxPreview = Math.max(0, subtotal - discountPreview) * Math.min(Math.max(num(document.querySelector('[name="tax_rate"]')?.value, 0), 0), 100) / 100;
    const paidPreview = Math.min(num(document.querySelector('[name="paid"]')?.value, 0), Math.max(0, subtotal - discountPreview) + taxPreview);
    const duePreview = Math.max(0, subtotal - discountPreview + taxPreview - paidPreview);
    return `<div class="totals" id="orderTotals">
        <div><span>Работы</span><strong>${money(service)}</strong></div>
        <div><span>Запчасти</span><strong>${money(parts)}</strong></div>
        <div><span>Отложено/отказ</span><strong>${money(deferred)}</strong></div>
        <div><span>Скидка</span><strong>${money(discountPreview)}</strong></div>
        <div><span>Налог</span><strong>${money(taxPreview)}</strong></div>
        <div><span>Оплачено</span><strong>${money(paidPreview)}</strong></div>
        <div class="grand"><span>К оплате</span><strong>${money(duePreview)}</strong></div>
    </div>`;
}

async function saveEntity(kind, id) {
    const form = $("#entityForm");
    if (form && !form.reportValidity()) return;
    const data = collectForm(form);
    const path = id ? `/api/${kind}/${id}` : `/api/${kind}`;
    const method = id ? "PUT" : "POST";
    setSaveButtonsBusy(true);
    try {
        await api(path, { method, body: JSON.stringify(data) });
        setSaveButtonsBusy(false);
        closeModal(true);
        await loadData();
        toast("Сохранено");
    } finally {
        if (state.saving) setSaveButtonsBusy(false);
    }
}

async function saveOrder(id) {
    const form = $("#orderForm");
    if (form && !form.reportValidity()) return;
    const data = collectForm(form);
    syncAllOrderItems();
    data.items = state.orderDraftItems.map(item => ({
        kind: item.kind,
        inventory_id: item.kind === "part" && num(item.inventory_id, 0) > 0 ? num(item.inventory_id, 0) : null,
        title: item.title,
        approval_status: item.approval_status || "approved",
        quantity: num(item.quantity, 0),
        unit_price: num(item.unit_price, 0),
        unit_cost: num(item.unit_cost, 0)
    }));
    const path = id ? `/api/orders/${id}` : "/api/orders";
    const method = id ? "PUT" : "POST";
    setSaveButtonsBusy(true);
    try {
        await api(path, { method, body: JSON.stringify(data) });
        setSaveButtonsBusy(false);
        closeModal(true);
        await loadData();
        toast("Заказ-наряд сохранен");
    } finally {
        if (state.saving) setSaveButtonsBusy(false);
    }
}

async function saveInspection(id) {
    const form = $("#inspectionForm");
    if (form && !form.reportValidity()) return;
    const data = collectForm(form);
    syncAllInspectionItems();
    data.items = state.inspectionDraftItems.map(item => ({
        area: item.area,
        title: item.title,
        condition_status: item.condition_status || "ok",
        approval_status: item.approval_status || ((item.condition_status || "ok") === "ok" ? "approved" : "deferred"),
        recommendation: item.recommendation,
        estimate: num(item.estimate, 0)
    }));
    const path = id ? `/api/inspections/${id}` : "/api/inspections";
    const method = id ? "PUT" : "POST";
    setSaveButtonsBusy(true);
    try {
        await api(path, { method, body: JSON.stringify(data) });
        setSaveButtonsBusy(false);
        closeModal(true);
        await loadData();
        toast("Осмотр сохранен");
    } finally {
        if (state.saving) setSaveButtonsBusy(false);
    }
}

function syncAllOrderItems() {
    $$("#itemsHost tr[data-index]").forEach(row => {
        const index = Number(row.dataset.index);
        const item = state.orderDraftItems[index];
        $$("[data-item]", row).forEach(input => {
            item[input.dataset.item] = input.value;
        });
    });
}

function syncAllInspectionItems() {
    $$("#inspectionItemsHost tr[data-inspection-index]").forEach(row => {
        const index = Number(row.dataset.inspectionIndex);
        const item = state.inspectionDraftItems[index];
        $$("[data-inspection-item]", row).forEach(input => {
            item[input.dataset.inspectionItem] = input.value;
        });
    });
}

function syncInspectionItemStateOnly(event) {
    const row = event.target.closest("tr[data-inspection-index]");
    if (!row) return;
    const index = Number(row.dataset.inspectionIndex);
    const item = state.inspectionDraftItems[index];
    $$("[data-inspection-item]", row).forEach(input => {
        item[input.dataset.inspectionItem] = input.value;
    });
    if (event.target.dataset.inspectionItem === "condition_status") {
        if (item.condition_status === "ok") {
            item.approval_status = "approved";
        }
        renderInspectionItems();
    }
}

function syncOrderItemStateOnly(event) {
    const row = event.target.closest("tr[data-index]");
    if (!row) return;
    const index = Number(row.dataset.index);
    const item = state.orderDraftItems[index];
    $$("[data-item]", row).forEach(input => {
        item[input.dataset.item] = input.value;
    });
    const totalCell = $("[data-row-total]", row);
    if (totalCell) totalCell.textContent = money((item.approval_status || "approved") === "approved" ? num(item.quantity) * num(item.unit_price) : 0);
    const totals = $("#orderTotals");
    if (totals) totals.outerHTML = orderTotalsHtml();
}

async function deleteEntity(kind, id) {
    if (state.saving) return;
    if (!confirm("Удалить запись? Это действие скроет запись из активной базы CRM.")) return;
    setSaveButtonsBusy(true);
    try {
        await api(`/api/${kind}/${id}`, { method: "DELETE" });
        setSaveButtonsBusy(false);
        closeModal(true);
        await loadData();
        toast("Удалено");
    } finally {
        if (state.saving) setSaveButtonsBusy(false);
    }
}

function showError(error) {
    const status = Number(error?.status || 0);
    if (!status || status >= 500) setOnlineState(false);
    const message = error.message || String(error);
    state.lastError = message;
    applyFormError(error);
    const modalOpen = $("#modalBackdrop")?.classList.contains("open");
    if (!state.data) {
        const content = $("#content");
        content.innerHTML = `${offlineBannerHtml()}<div class="notice" role="alert"><strong>Не удалось загрузить данные.</strong><p>${esc(message)}</p><button class="btn primary" type="button" data-action="retry-load">Повторить</button></div>`;
        bindViewActions(content);
    } else if (!modalOpen) {
        render();
    }
    toast(message, "error");
}

document.addEventListener("click", event => {
    const navButton = event.target.closest("#nav button[data-route]");
    if (navButton) setRoute(navButton.dataset.route);

    const saveButton = event.target.closest("[data-save]");
    if (!saveButton) return;
    const action = saveButton.dataset.save;
    const id = Number(saveButton.dataset.id || 0);
    if (state.saving) return;
    if (action === "cancel") closeModal();
    else if (action === "appointment") saveEntity("appointments", id).catch(showError);
    else if (action === "inspection") saveInspection(id).catch(showError);
    else if (action === "customer") saveEntity("customers", id).catch(showError);
    else if (action === "vehicle") saveEntity("vehicles", id).catch(showError);
    else if (action === "inventory") saveEntity("inventory", id).catch(showError);
    else if (action === "order") saveOrder(id).catch(showError);
    else if (action === "delete-customer") deleteEntity("customers", id).catch(showError);
    else if (action === "delete-vehicle") deleteEntity("vehicles", id).catch(showError);
    else if (action === "delete-inventory") deleteEntity("inventory", id).catch(showError);
    else if (action === "delete-appointment") deleteEntity("appointments", id).catch(showError);
    else if (action === "delete-inspection") deleteEntity("inspections", id).catch(showError);
    else if (action === "delete-order") deleteEntity("orders", id).catch(showError);
    else if (action === "print-order") openPrintOrder(id).catch(showError);
});

const modalCloseButton = $("#modalClose");
modalCloseButton.addEventListener("click", () => closeModal());
document.addEventListener("keydown", handleModalKeydown);
$("#modalBackdrop").addEventListener("click", event => {
    if (event.target.id === "modalBackdrop") closeModal();
});
$("#globalSearch").addEventListener("input", event => {
    state.q = event.target.value;
    updateSearchClear();
    clearTimeout(state.searchTimer);
    state.searchTimer = setTimeout(() => loadData().catch(showError), 260);
});
$("#globalSearch").addEventListener("keydown", event => {
    if (event.key === "Escape" && state.q) {
        event.preventDefault();
        clearGlobalSearch();
    }
});
$("#clearSearch").addEventListener("click", clearGlobalSearch);
$("#refreshBtn").addEventListener("click", () => loadData().then(() => toast("Обновлено")).catch(showError));
$("#backupBtn").addEventListener("click", createBackupFromUi);
$("#commandBtn")?.addEventListener("click", openCommandPalette);
$("#commandClose")?.addEventListener("click", closeCommandPalette);
$("#commandPalette")?.addEventListener("click", event => {
    if (event.target.id === "commandPalette") closeCommandPalette();
    const commandButton = event.target.closest("[data-command-index]");
    if (commandButton) runCommand(Number(commandButton.dataset.commandIndex || 0));
});
$("#commandSearch")?.addEventListener("input", renderCommandPalette);
$("#commandSearch")?.addEventListener("keydown", event => {
    const buttons = $$("[data-command-index]", $("#commandList"));
    const activeIndex = Math.max(0, buttons.findIndex(button => button.classList.contains("active")));
    if (event.key === "Escape") {
        event.preventDefault();
        closeCommandPalette();
    } else if (event.key === "Enter") {
        event.preventDefault();
        runCommand(activeIndex);
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        if (!buttons.length) return;
        const nextIndex = event.key === "ArrowDown"
            ? (activeIndex + 1) % buttons.length
            : (activeIndex - 1 + buttons.length) % buttons.length;
        buttons.forEach((button, index) => {
            const active = index === nextIndex;
            button.classList.toggle("active", active);
            button.setAttribute("aria-selected", active ? "true" : "false");
        });
        buttons[nextIndex].scrollIntoView({ block: "nearest" });
    }
});
async function shutdownApp() {
    if (!confirm("Остановить локальное приложение СТО CRM?")) return;
    try {
        await api("/api/shutdown", { method: "POST", body: "{}" });
        document.body.innerHTML = '<main class="shutdown-state"><section class="shutdown-card"><h1>СТО CRM остановлена</h1><p>Локальный сервер завершает работу. Окно можно закрыть.</p></section></main>';
    } catch (error) {
        toast(error.message || String(error), "error");
    }
}
$("#shutdownBtn").addEventListener("click", () => shutdownApp());

// init theme
function systemPrefersDark() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function resolveTheme(theme) {
    return theme === "dark" || theme === "light" ? theme : (systemPrefersDark() ? "dark" : "light");
}

function applyTheme(theme) {
    const requested = theme === "dark" || theme === "light" ? theme : "auto";
    const resolved = resolveTheme(requested);
    const isDark = resolved === "dark";
    document.body.classList.toggle("dark", isDark);
    document.body.classList.toggle("light", !isDark);
    document.body.dataset.theme = requested;
    const themeButton = $("#themeToggle");
    if (themeButton) {
        const label = requested === "auto" ? `Тема: авто (${isDark ? "тёмная" : "светлая"})` : `Тема: ${isDark ? "тёмная" : "светлая"}`;
        themeButton.textContent = requested === "auto" ? "◐" : (isDark ? "◑" : "☼");
        themeButton.setAttribute("aria-pressed", requested === "auto" ? "false" : "true");
        themeButton.setAttribute("aria-label", `${label}. Нажмите, чтобы переключить.`);
        themeButton.title = `${label}. Цикл: авто → светлая → тёмная.`;
    }
}

function applyDensity(compact) {
    state.compactMode = Boolean(compact);
    document.body.classList.toggle("compact", state.compactMode);
    const densityButton = $("#densityToggle");
    if (densityButton) {
        densityButton.textContent = state.compactMode ? "↧" : "↕";
        densityButton.setAttribute("aria-pressed", state.compactMode ? "true" : "false");
        densityButton.setAttribute("aria-label", state.compactMode ? "Компактный режим включен. Нажмите для комфортного режима." : "Комфортный режим включен. Нажмите для компактного режима.");
        densityButton.title = state.compactMode ? "Компактный режим" : "Комфортный режим";
    }
}

function toggleDensity() {
    applyDensity(!state.compactMode);
    safeStorageSet("sto-crm-density", state.compactMode ? "compact" : null);
    toast(state.compactMode ? "Компактная плотность включена" : "Комфортная плотность включена");
}

function safeStorageGet(key) {
    try { return window.localStorage ? localStorage.getItem(key) : null; }
    catch (_error) { return null; }
}

function safeStorageSet(key, value) {
    try {
        if (!window.localStorage) return;
        if (value === null || value === "") localStorage.removeItem(key);
        else localStorage.setItem(key, value);
    }
    catch (_error) { /* storage can be disabled in private or locked-down modes */ }
}

function nextThemePreference(current) {
    const normalized = current === "dark" || current === "light" ? current : "auto";
    if (normalized === "auto") return "light";
    if (normalized === "light") return "dark";
    return "auto";
}

applyTheme(safeStorageGet("sto-crm-theme") || "auto");
applyDensity(safeStorageGet("sto-crm-density") === "compact");
const densityToggle = $("#densityToggle");
if (densityToggle) {
    densityToggle.addEventListener("click", toggleDensity);
}
const themeToggle = $("#themeToggle");
if (themeToggle) {
    themeToggle.addEventListener("click", () => {
        const currentTheme = safeStorageGet("sto-crm-theme") || "auto";
        const nextTheme = nextThemePreference(currentTheme);
        safeStorageSet("sto-crm-theme", nextTheme === "auto" ? null : nextTheme);
        applyTheme(nextTheme);
    });
}
if (window.matchMedia) {
    const colorSchemeQuery = window.matchMedia("(prefers-color-scheme: dark)");
    const onSystemThemeChange = () => {
        if (!safeStorageGet("sto-crm-theme")) applyTheme("auto");
    };
    if (colorSchemeQuery.addEventListener) colorSchemeQuery.addEventListener("change", onSystemThemeChange);
    else if (colorSchemeQuery.addListener) colorSchemeQuery.addListener(onSystemThemeChange);
}

window.addEventListener("popstate", () => setRoute(routeFromLocation(), false));
window.addEventListener("hashchange", () => setRoute(routeFromLocation(), false));
setRoute(state.route, false);
loadData().catch(showError);
</script>
</body>
</html>"""


def candidate_ports(preferred: int, attempts: int = 50) -> Iterator[int]:
    """Генерирует предпочтительные порты и безопасный fallback на порт ОС."""
    start = min(max(parse_int(preferred, DEFAULT_PORT), 0), 65_535)
    if start > 0:
        yield from range(start, min(start + max(attempts, 1), 65_536))
    yield 0


def find_free_port(preferred: int) -> int:
    """Возвращает ближайший свободный порт для обратной совместимости тестов и CLI."""
    for port in candidate_ports(preferred):
        try:
            with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("127.0.0.1", port))
                return int(sock.getsockname()[1])
        except OSError:
            continue
    raise OSError("Не удалось найти свободный локальный порт.")


def normalize_bind_host(host: str | None) -> str:
    value = clean_text(host, 255, "127.0.0.1").lower()
    aliases = {"", "localhost", "127.0.0.1", "::1"}
    if value not in aliases:
        raise ValueError("СТО CRM можно запускать только на локальном loopback-адресе: 127.0.0.1, localhost или ::1.")
    return "::1" if value == "::1" else "127.0.0.1"


def create_server(preferred_port: int, host: str = "127.0.0.1") -> CRMServer:
    """Создаёт сервер сразу на локальном loopback-адресе, без race между проверкой и bind."""
    bind_host = normalize_bind_host(host)
    last_error: OSError | None = None
    for port in candidate_ports(preferred_port):
        try:
            return CRMServer((bind_host, port), CRMHandler)
        except OSError as exc:
            last_error = exc
            continue
    raise OSError("Не удалось запустить локальный сервер CRM.") from last_error


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Локальная CRM для автосервиса")
    parser.add_argument("--host", default="127.0.0.1", help="локальный адрес сервера: 127.0.0.1, localhost или ::1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="порт локального сервера")
    parser.add_argument("--db", type=Path, default=None, help="путь к SQLite базе")
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер автоматически")
    parser.add_argument("--demo", action="store_true", help="заполнить новую базу демонстрационными данными")
    args = parser.parse_args(argv)
    if args.port < 0 or args.port > 65_535:
        parser.error("Порт должен быть в диапазоне 0..65535, где 0 означает автоматический выбор свободного порта.")
    try:
        args.host = normalize_bind_host(args.host)
    except ValueError as exc:
        parser.error(str(exc))
    return args


def main(argv: list[str] | None = None) -> int:
    global RUNTIME
    args = parse_args(argv or sys.argv[1:])
    db_path = args.db.resolve() if args.db else default_db_path()
    RUNTIME = Runtime(db_path=db_path, start_time=time.time(), csrf_token=secrets.token_urlsafe(32))
    init_db(seed_demo=args.demo)
    server = create_server(args.port, args.host)
    host = server.server_address[0]
    port = server.server_port
    url_host = "[::1]" if host == "::1" else "127.0.0.1"
    url = f"http://{url_host}:{port}"

    def shutdown(*_: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, shutdown)

    safe_log(f"{APP_NAME} запущена: {url}")
    safe_log(f"База данных: {RUNTIME.db_path}")
    if not args.no_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

