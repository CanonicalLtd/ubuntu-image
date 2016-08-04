# Copyright (C) 2016 Barry Warsaw
#
# This project is licensed under the terms of the Apache 2.0 License.

"""nose2 test infrastructure."""

import os
import re
import shutil
import doctest

from contextlib import ExitStack
from hashlib import sha256
from nose2.events import Plugin
from pkg_resources import resource_filename
from tempfile import TemporaryDirectory
from ubuntu_image.helpers import as_bool, weld
from unittest.mock import patch


FLAGS = doctest.ELLIPSIS | doctest.NORMALIZE_WHITESPACE | doctest.REPORT_NDIFF
TOPDIR = os.path.dirname(resource_filename('ubuntu_image', '__init__.py'))


def setup(testobj):
    """Global doctest setup."""


def teardown(testobj):
    """Global doctest teardown."""


class WeldMock:
    def __init__(self, tmpdir):
        self._tmpdir = tmpdir
        self._patcher = patch('ubuntu_image.builder.weld', self.run)

    def run(self, model_assertion, root_dir, unpack_dir, channel=None):
        # Hash the contents of the model.assertion file + the channel name and
        # use that in the cache directory name.  This is more accurate than
        # using the model.assertion basename.
        with open(model_assertion, 'rb') as fp:
            checksum = sha256(fp.read())
        checksum.update(
            ('default' if channel is None else channel).encode('utf-8'))
        run_tmp = os.path.join(self._tmpdir, checksum.hexdigest())
        tmp_root = os.path.join(run_tmp, 'root')
        tmp_unpack = os.path.join(run_tmp, 'unpack')
        if not os.path.isdir(run_tmp):
            os.makedirs(tmp_root)
            os.makedirs(tmp_unpack)
            weld(model_assertion, tmp_root, tmp_unpack, channel)
        # copytree() requires that the destination directories do not exist.
        # Since this code only ever executes during the test suite, and even
        # though only when mocking `snap` for speed, this is always safe.
        shutil.rmtree(root_dir, ignore_errors=True)
        shutil.rmtree(unpack_dir, ignore_errors=True)
        shutil.copytree(tmp_root, root_dir)
        shutil.copytree(tmp_unpack, unpack_dir)

    def __enter__(self):
        self._patcher.start()

    def __exit__(self, *args):
        self._patcher.stop()
        return False


class NosePlugin(Plugin):
    configSection = 'ubuntu-image'

    def __init__(self):
        super().__init__()
        self.patterns = []
        self.addArgument(self.patterns, 'P', 'pattern',
                         'Add a test matching pattern')

    def getTestCaseNames(self, event):
        if len(self.patterns) == 0:
            # No filter patterns, so everything should be tested.
            return
        # Does the pattern match the fully qualified class name?
        for pattern in self.patterns:
            full_class_name = '{}.{}'.format(
                event.testCase.__module__, event.testCase.__name__)
            if re.search(pattern, full_class_name):
                # Don't suppress this test class.
                return
        names = filter(event.isTestMethod, dir(event.testCase))
        for name in names:
            full_test_name = '{}.{}.{}'.format(
                event.testCase.__module__,
                event.testCase.__name__,
                name)
            for pattern in self.patterns:
                if re.search(pattern, full_test_name):
                    break
            else:
                event.excludedNames.append(name)

    def handleFile(self, event):
        path = event.path[len(TOPDIR)+1:]
        if len(self.patterns) > 0:
            for pattern in self.patterns:
                if re.search(pattern, path):
                    break
            else:
                # Skip this doctest.
                return
        base, ext = os.path.splitext(path)
        if ext != '.rst':
            return
        test = doctest.DocFileTest(
            path, package='ubuntu_image',
            optionflags=FLAGS,
            setUp=setup,
            tearDown=teardown)
        # Suppress the extra "Doctest: ..." line.
        test.shortDescription = lambda: None
        event.extraTests.append(test)

    def startTestRun(self, event):
        # Create a mock for the `sudo snap weld` command.  This is an
        # expensive command which hits the actual snap store.  We want this to
        # run at least once so we know our tests are valid.  We can cache the
        # results in a test-suite-wide temporary directory and simulate future
        # calls by just recursively copying the contents to the specified
        # directories.
        #
        # It's a bit more complicated than that though, because it's possible
        # that the channel and model.assertion will be different, so we need
        # to make the cache dependent on those values.
        #
        # Finally, to enable full end-to-end tests, check an environment
        # variable to see if the mocking should even be done.  This way, we
        # can make our Travis-CI job do at least one real end-to-end test.
        self.resources = ExitStack()
        # How should we mock `snap weld`?  For now, it's a binary choice, but
        # I was thinking it might be useful to have another level where we'd
        # mock `snap weld` entirely and just use sample data.
        should_we_mock = as_bool(
            os.environ.get('UBUNTUIMAGE_MOCK_SNAP', 'yes'))
        if should_we_mock:
            tmpdir = self.resources.enter_context(TemporaryDirectory())
            self.resources.enter_context(WeldMock(tmpdir))

    def stopTestRun(self, event):
        self.resources.close()

    # def startTest(self, event):
    #     import sys; print('vvvvv', event.test, file=sys.stderr)

    # def stopTest(self, event):
    #     import sys; print('^^^^^', event.test, file=sys.stderr)
