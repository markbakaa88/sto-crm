with open("/home/zxc/CRM/sto_crm/services.py", "r", encoding="utf-8") as f:
    text = f.read()

text = text.replace(
'''from __future__ import annotations

import logging
logger = logging.getLogger("sto_crm")

import sqlite3''',
'''from __future__ import annotations

import logging
import sqlite3''')

# Oh it wasn't replaced probably because of exactly mapping whitespace, let's fix
with open("/home/zxc/CRM/sto_crm/services.py", "w", encoding="utf-8") as f:
    f.write(text)
