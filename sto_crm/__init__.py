"""Public compatibility facade for STO CRM.

Historically the project exposed almost everything from one `sto_crm.py` module.
The implementation is now split by responsibility, while this package keeps the
old `import sto_crm` API stable for tests, scripts and local integrations.
"""

from __future__ import annotations

import argparse as argparse
import base64 as base64
import csv as csv
import hashlib as hashlib
import html as html
import io as io
import json as json
import math as math
import os as os
import re as re
import secrets as secrets
import signal as signal
import socket as socket
import sqlite3 as sqlite3
import subprocess as subprocess
import sys as sys
import threading as threading
import time as time
import traceback as traceback
import types
import urllib as urllib
import webbrowser as webbrowser
import zlib as zlib
from collections import defaultdict as defaultdict
from contextlib import closing as closing, contextmanager as contextmanager
from dataclasses import dataclass as dataclass
from datetime import datetime as datetime, timedelta as timedelta
from pathlib import Path as Path
from typing import Any as Any, Iterator as Iterator
from http.server import BaseHTTPRequestHandler as BaseHTTPRequestHandler, ThreadingHTTPServer as ThreadingHTTPServer

from . import catalog as catalog
from . import cli as cli
from . import config as config
from . import database as database
from . import export as export
from . import http_server as http_server
from . import printing as printing
from . import queries as queries
from . import reports as reports
from . import runtime as runtime
from . import seed as seed
from . import services as services
from . import updates as updates
from . import validation as validation
from . import web as web

_IMPLEMENTATION_MODULES = [
    config,
    runtime,
    catalog,
    database,
    validation,
    services,
    queries,
    reports,
    export,
    updates,
    printing,
    web,
    http_server,
    cli,
    seed,
]


def _publish_module_symbols() -> None:
    for module in _IMPLEMENTATION_MODULES:
        for name, value in vars(module).items():
            if name.startswith("_"):
                continue
            globals()[name] = value


_publish_module_symbols()


class _StoCrmFacade(types.ModuleType):
    """Module type that keeps legacy monkeypatching semantics intact."""

    def __getattribute__(self, name: str):
        if name == "RUNTIME":
            return runtime.RUNTIME
        return super().__getattribute__(name)

    def __setattr__(self, name: str, value) -> None:
        if name == "RUNTIME":
            runtime.RUNTIME = value
        for module in _IMPLEMENTATION_MODULES:
            if hasattr(module, name):
                setattr(module, name, value)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _StoCrmFacade

__all__ = sorted(name for name in globals() if not name.startswith("_"))
