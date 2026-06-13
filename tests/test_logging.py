import logging
import sys
import unittest

from sto_crm.logging_config import setup_logger


class TestLoggingConfig(unittest.TestCase):
    def test_setup_logger_new(self):
        # Должен возвращаться логгер с хендлером
        logger = setup_logger("test_logging_unique")
        self.assertEqual(logger.level, logging.INFO)
        self.assertTrue(len(logger.handlers) > 0)
        handler = logger.handlers[0]
        self.assertIsInstance(handler, logging.StreamHandler)
        self.assertEqual(getattr(handler, "stream", None), sys.stdout)

    def test_setup_logger_existing(self):
        # Если хендлер уже есть, setup_logger не должен добавлять второй
        logger = setup_logger("test_logging_existing")
        initial_handlers_len = len(logger.handlers)
        setup_logger("test_logging_existing")
        self.assertEqual(len(logger.handlers), initial_handlers_len)

    def test_redacting_formatter_exception_fallback(self):
        from unittest.mock import patch

        from sto_crm.logging_config import RedactingFormatter

        formatter = RedactingFormatter("%(message)s")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="User request: csrf_token=abcdef",
            args=(),
            exc_info=None,
        )

        with patch("sto_crm.runtime.redact_sensitive_query", side_effect=Exception("mocked error")):
            formatted = formatter.format(record)
            self.assertEqual(formatted, "User request: csrf_token=abcdef")
