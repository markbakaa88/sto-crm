import sys
import types
import pytest

@pytest.fixture(autouse=True)
def ensure_main_module():
    if "__main__" not in sys.modules:
        main_module = types.ModuleType("__main__")
        main_module.__file__ = "<string>"
        sys.modules["__main__"] = main_module
    yield
