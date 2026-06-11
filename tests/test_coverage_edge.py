import pytest
import sto_crm
from sto_crm.validation import item_is_billable, require_non_negative_float
from sto_crm.http_server import CRMServer, CRMHandler
import urllib.request
import threading
import json
import time

def test_item_is_billable_edge():
    assert item_is_billable({}) == True
    assert item_is_billable({"approval_status": "approved"}) == True
    assert item_is_billable({"approval_status": "declined"}) == False

def test_require_non_negative_float_edge():
    with pytest.raises(ValueError):
        require_non_negative_float(-1, "test")
