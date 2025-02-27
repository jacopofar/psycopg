"""
psycopg -- PostgreSQL database adapter for Python -- C optimization package
"""

# Copyright (C) 2020-2021 The Psycopg Team

import sys

# This package shouldn't be imported before psycopg itself, or weird things
# will happen
if "psycopg" not in sys.modules:
    raise ImportError(
        "the psycopg package should be imported before psycopg_c"
    )

from .version import __version__  # noqa
