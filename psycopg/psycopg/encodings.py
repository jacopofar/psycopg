"""
Mappings between PostgreSQL and Python encodings.
"""

# Copyright (C) 2020-2021 The Psycopg Team

import codecs
from typing import Dict, Union

from .errors import NotSupportedError

_py_codecs = {
    "BIG5": "big5",
    "EUC_CN": "gb2312",
    "EUC_JIS_2004": "euc_jis_2004",
    "EUC_JP": "euc_jp",
    "EUC_KR": "euc_kr",
    # "EUC_TW": not available in Python
    "GB18030": "gb18030",
    "GBK": "gbk",
    "ISO_8859_5": "iso8859-5",
    "ISO_8859_6": "iso8859-6",
    "ISO_8859_7": "iso8859-7",
    "ISO_8859_8": "iso8859-8",
    "JOHAB": "johab",
    "KOI8R": "koi8-r",
    "KOI8U": "koi8-u",
    "LATIN1": "iso8859-1",
    "LATIN10": "iso8859-16",
    "LATIN2": "iso8859-2",
    "LATIN3": "iso8859-3",
    "LATIN4": "iso8859-4",
    "LATIN5": "iso8859-9",
    "LATIN6": "iso8859-10",
    "LATIN7": "iso8859-13",
    "LATIN8": "iso8859-14",
    "LATIN9": "iso8859-15",
    # "MULE_INTERNAL": not available in Python
    "SHIFT_JIS_2004": "shift_jis_2004",
    "SJIS": "shift_jis",
    # this actually means no encoding, see PostgreSQL docs
    # it is special-cased by the text loader.
    "SQL_ASCII": "ascii",
    "UHC": "cp949",
    "UTF8": "utf-8",
    "WIN1250": "cp1250",
    "WIN1251": "cp1251",
    "WIN1252": "cp1252",
    "WIN1253": "cp1253",
    "WIN1254": "cp1254",
    "WIN1255": "cp1255",
    "WIN1256": "cp1256",
    "WIN1257": "cp1257",
    "WIN1258": "cp1258",
    "WIN866": "cp866",
    "WIN874": "cp874",
}

py_codecs: Dict[Union[bytes, str], str] = {}
py_codecs.update((k, v) for k, v in _py_codecs.items())
py_codecs.update((k.encode(), v) for k, v in _py_codecs.items())

pg_codecs = {v: k.encode() for k, v in _py_codecs.items()}


def py2pg(name: str) -> bytes:
    """Convert a Python encoding name to PostgreSQL encoding name.

    Raise LookupError if the Python encoding is unknown.
    """
    return pg_codecs[codecs.lookup(name).name]


def pg2py(name: Union[bytes, str]) -> str:
    """Convert a Python encoding name to PostgreSQL encoding name.

    Raise NotSupportedError if the PostgreSQL encoding is not supported by
    Python.
    """
    try:
        return py_codecs[name]
    except KeyError:
        raise NotSupportedError("codec not available in Python: {name!r}")
