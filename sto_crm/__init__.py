"""CRM package — public API re-exports.

The sto_crm/ package shadows sto_crm.py, so we load the module
via importlib and then replace this package module with the loaded
implementation module. That keeps attribute writes like
`sto_crm.RUNTIME = ...` affecting the real runtime state.
"""

import importlib.util
import sys
from pathlib import Path

_parent = Path(__file__).resolve().parent.parent
_module_path = _parent / "sto_crm.py"

_spec = importlib.util.spec_from_file_location("_sto_crm_module", _module_path)
_sto_crm = importlib.util.module_from_spec(_spec)
sys.modules["_sto_crm_module"] = _sto_crm
_spec.loader.exec_module(_sto_crm)

_sto_crm.__name__ = __name__
_sto_crm.__package__ = __name__
sys.modules[__name__] = _sto_crm
