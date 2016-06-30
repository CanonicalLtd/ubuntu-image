"""Test the helpers."""


from ubuntu_image.helpers import GiB, MiB, as_size, transform
from unittest import TestCase


class TestHelpers(TestCase):
    def test_m(self):
        self.assertEqual(as_size('25M'), MiB(25))

    def test_g(self):
        self.assertEqual(as_size('30G'), GiB(30))

    def test_bytes(self):
        self.assertEqual(as_size('801'), 801)

    def test_transform(self):
        @transform(ZeroDivisionError, RuntimeError)
        def oops():
            1/0
        self.assertRaises(RuntimeError, oops)
