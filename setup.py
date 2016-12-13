#!/usr/bin/env python3

import sys

try:
    from debian.changelog import Changelog
except ImportError:
    Changelog = None
from setuptools import find_packages, setup


def require_python(minimum):
    """Require at least a minimum Python version.

    The version number is expressed in terms of `sys.hexversion`.  E.g. to
    require a minimum of Python 2.6, use::

    >>> require_python(0x206000f0)

    :param minimum: Minimum Python version supported.
    :type minimum: integer
    """
    if sys.hexversion < minimum:
        hversion = hex(minimum)[2:]
        if len(hversion) % 2 != 0:
            hversion = '0' + hversion
        split = list(hversion)
        parts = []
        while split:
            parts.append(int(''.join((split.pop(0), split.pop(0))), 16))
        major, minor, micro, release = parts
        if release == 0xf0:
            print('Python {}.{}.{} or better is required'.format(
                major, minor, micro))
        else:
            print('Python {}.{}.{} ({}) or better is required'.format(
                major, minor, micro, hex(release)[2:]))
        sys.exit(1)

require_python(0x30500f0)


if Changelog is None:
    __version__ = 'dev'
else:
    with open('debian/changelog', encoding='utf-8') as infp:
        __version__ = str(Changelog(infp).get_version())
        # Write the version out to the package directory so `ubuntu-image
        # --version` can display it.
        with open('ubuntu_image/version.txt', 'w', encoding='utf-8') as outfp:
            print(__version__, file=outfp)


setup(
    name='ubuntu-image',
    version=__version__,
    description='Construct snappy images out of a model assertion',
    author_email='snapcraft@lists.ubuntu.com',
    url='https://github.com/CanonicalLtd/ubuntu-image',
    packages=find_packages(),
    install_requires=[
        'attrs',
        'pyyaml',
        'voluptuous',
        ],
    include_package_data=True,
    scripts=['ubuntu-image'],
    license='GPLv3',
    classifiers=(
        'Development Status :: 3 - Alpha',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Natural Language :: English',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
        'Topic :: Software Development :: Build Tools',
        'Topic :: System :: Software Distribution',
        ),
    )
