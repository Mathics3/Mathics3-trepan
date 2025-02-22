#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os.path as osp
import platform
import sys

from setuptools import find_namespace_packages, setup

# Ensure user has the correct Python version
if sys.version_info < (3, 8):
    print("Mathics support Python 3.8 and above; you have %d.%d" % sys.version_info[:2])
    sys.exit(-1)


def get_srcdir():
    filename = osp.normcase(osp.dirname(osp.abspath(__file__)))
    return osp.realpath(filename)


def read(*rnames):
    return open(osp.join(get_srcdir(), *rnames)).read()


# Get/set VERSION and long_description from files
long_description = read("README.rst") + "\n"

__version__ = "0.0.0"  # overwritten by exec below

# stores __version__ in the current namespace
exec(compile(open("pymathics/trepan/version.py").read(), "version.py", "exec"))

is_PyPy = platform.python_implementation() == "PyPy"

# Install a wordlist.
# Environment variables "lang", "WORDLIST_SIZE", and "SPACY_DOWNLOAD" override defaults.

setup(
    name="Mathics3-trepan",
    version=__version__,
    packages=find_namespace_packages(include=["pymathics.*"]),
    install_requires=[
        "Mathics3>=8.0.0",
        "trepan3k>=1.3.1",
        "mathics-pygments",
    ],
    zip_safe=False,
    maintainer="Mathics3 Group",
    maintainer_email="rb@dustyfeet.com",
    long_description=long_description,
    long_description_content_type="text/x-rst",
    # metadata for upload to PyPI
    classifiers=[
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python :: Implementation :: PyPy",
        "Topic :: Scientific/Engineering",
        "Topic :: Scientific/Engineering :: Mathematics",
        "Topic :: Software Development :: Interpreters",
        "Topic :: Software Development :: Debuggers",
    ],
)
