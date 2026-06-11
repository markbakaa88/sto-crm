import pytest
from sto_crm.validation import item_is_billable, require_non_negative_float

def test_item_is_billable_edge():
    assert item_is_billable({})
    assert item_is_billable({"approval_status": "approved"})
    assert not item_is_billable({"approval_status": "declined"})

def test_require_non_negative_float_edge():
    with pytest.raises(ValueError):
        require_non_negative_float(-1, "test")
