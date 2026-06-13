import unittest
import os
from unittest.mock import patch
from sto_crm.config import _get_env_int

class TestConfigEnv(unittest.TestCase):
    def test_get_env_int_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_get_env_int("NONEXISTENT_ENV_VAR", 42), 42)

    def test_get_env_int_invalid_value(self):
        with patch.dict(os.environ, {"INVALID_ENV_VAR": "not_an_int"}):
            self.assertEqual(_get_env_int("INVALID_ENV_VAR", 100), 100)

    def test_get_env_int_negative_value(self):
        with patch.dict(os.environ, {"NEGATIVE_ENV_VAR": "-50"}):
            self.assertEqual(_get_env_int("NEGATIVE_ENV_VAR", 200), 200)

    def test_get_env_int_success(self):
        with patch.dict(os.environ, {"SUCCESS_ENV_VAR": "15"}):
            self.assertEqual(_get_env_int("SUCCESS_ENV_VAR", 5), 15)
