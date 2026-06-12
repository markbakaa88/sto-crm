import re

with open("/home/zxc/CRM/sto_crm/services.py", "r", encoding="utf-8") as f:
    text = f.read()

# Let's replace simple `raise ValueError("error")` with more structured exceptions or logging.
text = text.replace('raise ValueError("Дубликат телефона.")', 
                    'raise ValueError("Клиент с таким телефоном уже существует.")')

# And add logging! We already have logger from sto_crm.logging_config
text = re.sub(r'def update_order\(record_id: int, payload: dict\[str, Any\]\) -> dict\[str, Any\]:', 
              r'def update_order(record_id: int, payload: dict[str, Any]) -> dict[str, Any]:\n    logger.info(f"Updating order {record_id}")', 
              text)

text = re.sub(r'def create_order_tx\(conn: sqlite3.Connection, payload: dict\[str, Any\]\) -> int:', 
              r'def create_order_tx(conn: sqlite3.Connection, payload: dict[str, Any]) -> int:\n    logger.info(f"Creating new order transaction")', 
              text)

text = re.sub(r'def delete_order\(record_id: int\) -> dict\[str, Any\]:', 
              r'def delete_order(record_id: int) -> dict[str, Any]:\n    logger.info(f"Deleting order {record_id}")', 
              text)

with open("/home/zxc/CRM/sto_crm/services.py", "w", encoding="utf-8") as f:
    f.write(text)

print("Python services.py augmented with logging")
