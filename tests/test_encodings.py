import codecs
import pytest

import psycopg
from psycopg import encodings


def test_names_normalised():
    for name in encodings._py_codecs.values():
        assert codecs.lookup(name).name == name


@pytest.mark.parametrize(
    "pyenc, pgenc",
    [
        ("ascii", "SQL_ASCII"),
        ("utf8", "UTF8"),
        ("utf-8", "UTF8"),
        ("uTf-8", "UTF8"),
        ("latin9", "LATIN9"),
        ("iso8859-15", "LATIN9"),
    ],
)
def test_py2pg(pyenc, pgenc):
    assert encodings.py2pg(pyenc) == pgenc.encode()


@pytest.mark.parametrize(
    "pyenc, pgenc",
    [
        ("ascii", "SQL_ASCII"),
        ("utf-8", "UTF8"),
        ("iso8859-15", "LATIN9"),
    ],
)
def test_pg2py(pyenc, pgenc):
    assert encodings.pg2py(pgenc.encode()) == pyenc


@pytest.mark.parametrize("pgenc", ["MULE_INTERNAL", "EUC_TW"])
def test_pg2py_missing(pgenc):
    with pytest.raises(psycopg.NotSupportedError):
        encodings.pg2py(pgenc.encode())
