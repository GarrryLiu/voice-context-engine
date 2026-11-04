"""Launcher configuration and isolation checks; never call providers."""
import importlib.util
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('quickstart', ROOT / 'run.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class QuickstartTests(unittest.TestCase):
    def test_busy_port_is_not_reused(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            with self.assertRaisesRegex(ValueError, 'Port unavailable'):
                launcher.choose_port(listener.getsockname()[1])

    def test_demo_does_not_load_credentials(self):
        with patch.dict(os.environ, {'LLM_API_KEY': 'private-placeholder'}):
            self.assertEqual(launcher.choose_mode('demo', '/missing'), 'demo')

    def test_auto_empty_config_and_partial_config(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / '.env'
            path.write_text('')
            self.assertEqual(launcher.choose_mode('auto', path), 'demo')
            path.write_text('LLM_API_KEY=private-placeholder\n')
            with self.assertRaises(ValueError) as error:
                launcher.choose_mode('auto', path)
            self.assertNotIn('private-placeholder', str(error.exception))

    def test_connected_requires_valid_official_configuration(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / '.env'
            path.write_text('LLM_API_KEY=placeholder\nLLM_MODEL=example\n')
            self.assertEqual(launcher.choose_mode('auto', path), 'connected')
            path.write_text(path.read_text() + 'LLM_BASE_URL=https://example.com\n')
            with self.assertRaises(ValueError):
                launcher.choose_mode('connected', path)
