import re

with open("/home/zxc/CRM/sto_crm/services.py", "r", encoding="utf-8") as f:
    text = f.read()

text = text.replace("import logging\nlogger = logging.getLogger('sto_crm')\n", "")

text = re.sub(
    r'(from __future__ import annotations\n)',
    r'\1\nimport logging\nlogger = logging.getLogger("sto_crm")\n',
    text
)

with open("/home/zxc/CRM/sto_crm/services.py", "w", encoding="utf-8") as f:
    f.write(text)

print("Future import fixed")
