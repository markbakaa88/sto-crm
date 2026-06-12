import re

with open("/home/zxc/CRM/sto_crm/services.py", "r", encoding="utf-8") as f:
    text = f.read()

# I apparently overwrote my initial `logging_config` import from my very first pass when I ran tests or cleanup? 
# Ah, I see: I used sed before. Let's do it safely.
if "import logging" not in text:
    text = "import logging\nlogger = logging.getLogger('sto_crm')\n" + text

with open("/home/zxc/CRM/sto_crm/services.py", "w", encoding="utf-8") as f:
    f.write(text)

print("Logger imported")
