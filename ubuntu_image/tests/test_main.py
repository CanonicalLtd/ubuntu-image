"""Test main execution."""

import logging

from contextlib import ExitStack
from io import StringIO
from ubuntu_image.__main__ import main
from unittest import TestCase
from unittest.mock import patch


class TestMain(TestCase):
    def setUp(self):
        super().setUp()
        self._resources = ExitStack()
        self.addCleanup(self._resources.close)
        # Capture builtin print() output.
        self._stdout = StringIO()
        self._stderr = StringIO()
        self._resources.enter_context(
            patch('argparse._sys.stdout', self._stdout))
        # Capture stderr since this is where argparse will spew to.
        self._resources.enter_context(
            patch('argparse._sys.stderr', self._stderr))

    def test_help(self):
        with self.assertRaises(SystemExit) as cm:
            main(('--help',))
        self.assertEqual(cm.exception.code, 0)
        lines = self._stdout.getvalue().splitlines()
        self.assertTrue(lines[0].startswith('usage: ubuntu-image'),
                        lines[0])

    def test_debug(self):
        with ExitStack() as resources:
            mock = resources.enter_context(
                patch('ubuntu_image.__main__.logging.basicConfig'))
            code = main(('--debug',))
        self.assertEqual(code, 0)
        mock.assert_called_once_with(level=logging.DEBUG)

    def test_no_debug(self):
        with ExitStack() as resources:
            mock = resources.enter_context(
                patch('ubuntu_image.__main__.logging.basicConfig'))
            code = main(())
        self.assertEqual(code, 0)
        mock.assert_not_called()
