.. currentmodule:: psycopg

.. index::
    single: Adaptation
    pair: Objects; Adaptation
    single: Data types; Adaptation

.. _extra-adaptation:

Adapting other PostgreSQL types
===============================

PostgreSQL offers other data types which don't map to native Python types.
Psycopg offers wrappers and conversion functions to allow their use.


.. index::
    pair: Composite types; Data types
    pair: tuple; Adaptation
    pair: namedtuple; Adaptation

.. _adapt-composite:

Composite types casting
-----------------------

Psycopg can adapt PostgreSQL composite types (either created with the |CREATE
TYPE|_ command or implicitly defined after a table row type) to and from
Python tuples or `~collections.namedtuple`.

.. |CREATE TYPE| replace:: :sql:`CREATE TYPE`
.. _CREATE TYPE: https://www.postgresql.org/docs/current/static/sql-createtype.html

Before using a composite type it is necessary to get information about it
using the `~psycopg.types.composite.CompositeInfo` class and to register it
using `~psycopg.types.composite.register_composite()`.

.. autoclass:: psycopg.types.composite.CompositeInfo

   `!CompositeInfo` is a `~psycopg.types.TypeInfo` subclass: check its
   documentation for generic details.

   .. attribute:: python_type

       After `register_composite()` is called, it will contain the python type
       mapping to the registered composite.

.. autofunction:: psycopg.types.composite.register_composite

   After registering, fetching data of the registered composite will invoke
   *factory* to create corresponding Python objects.

   If no factory is specified, a `~collection.namedtuple` is created and used
   to return data.

   If the *factory* is a type (and not a generic callable), then dumpers for
   that type are created and registered too, so that passing objects of that
   type to a query will adapt them to the registered type.

Example::

    >>> from psycopg.types.composite import CompositeInfo, register_composite

    >>> conn.execute("CREATE TYPE card AS (value int, suit text)")

    >>> info = TypeInfo.fetch(conn, "card")
    >>> register_composite(info, conn)

    >>> my_card = info.python_type(8, "hearts")
    >>> my_card
    card(value=8, suit='hearts')

    >>> conn.execute(
    ...     "SELECT pg_typeof(%(card)s), (%(card)s).suit", {"card": my_card}
    ...     ).fetchone()
    ('card', 'hearts')

    >>> conn.execute("SELECT (%s, %s)::card", [1, "spades"]).fetchone()[0]
    card(value=1, suit='spades')


Nested composite types are handled as expected, provided that the type of the
composite components are registered as well::

    >>> conn.execute("CREATE TYPE card_back AS (face card, back text)")

    >>> info2 = CompositeInfo.fetch(conn, "card_back")
    >>> register_composite(info2, conn)

    >>> conn.execute("SELECT ((8, 'hearts'), 'blue')::card_back").fetchone()[0]


.. index::
    pair: range; Data types

.. _adapt-range:

Range adaptation
----------------

PostgreSQL `range types`__ are a family of data types representing a range of
value between two elements. The type of the element is called the range
*subtype*. PostgreSQL offers a few built-in range types and allows the
definition of custom ones.

.. __: https://www.postgresql.org/docs/current/rangetypes.html

All the PostgreSQL range types are loaded as the `~psycopg.types.range.Range`
Python type, which is a `~typing.Generic` type and can hold bounds of
different types.

.. autoclass:: psycopg.types.range.Range

    This Python type is only used to pass and retrieve range values to and
    from PostgreSQL and doesn't attempt to replicate the PostgreSQL range
    features: it doesn't perform normalization and doesn't implement all the
    operators__ supported by the database.

    .. __: https://www.postgresql.org/docs/current/static/functions-range.html#RANGE-OPERATORS-TABLE

    `!Range` objects are immutable, hashable, and support the ``in`` operator
    (checking if an element is within the range). They can be tested for
    equivalence. Empty ranges evaluate to `!False` in boolean context,
    nonempty evaluate to `!True`.

    `!Range` objects have the following attributes:

    .. autoattribute:: isempty
    .. autoattribute:: lower
    .. autoattribute:: upper
    .. autoattribute:: lower_inc
    .. autoattribute:: upper_inc
    .. autoattribute:: lower_inf
    .. autoattribute:: upper_inf

The built-in range objects are adapted automatically: if a `!Range` objects
contains `~datetime.date` bounds, it is dumped using the :sql:`daterange` OID,
and of course :sql:`daterange` values are loaded back as `!Range[date]`.

If you create your own range type you can use `~psycopg.types.range.RangeInfo`
and `~psycopg.types.range.register_range()` to associate the range type with
its subtype and make it work like the builtin ones.

.. autoclass:: psycopg.types.range.RangeInfo

   `!RangeInfo` is a `~psycopg.types.TypeInfo` subclass: check its
   documentation for generic details.

.. autofunction:: psycopg.types.range.register_range

Example::

    >>> from psycopg.types.range import Range, RangeInfo, register_range
    >>> conn.execute("create type strrange as range (subtype = text)")

    >>> info = RangeInfo.fetch(conn, "strrange")
    >>> register_range(info, conn)

    >>> conn.execute("SELECT pg_typeof(%s)", [Range("a", "z")]).fetchone()[0]
    'strrange'

    >>> conn.execute("SELECT '[a,z]'::strrange").fetchone()[0]
    Range('a', 'z', '[]')


.. index::
    pair: hstore; Data types
    pair: dict; Adaptation

.. _adapt-hstore:

Hstore adaptation
-----------------

The |hstore|_ data type is a key-value store embedded in PostgreSQL. It
supports GiST or GIN indexes allowing search by keys or key/value pairs as
well as regular BTree indexes for equality, uniqueness etc.

.. |hstore| replace:: :sql:`hstore`
.. _hstore: https://www.postgresql.org/docs/current/static/hstore.html

Psycopg can convert Python `!dict` objects to and from |hstore| structures.
Only dictionaries with string keys and values are supported. `!None` is also
allowed as value but not as a key.

In order to use the |hstore| data type it is necessary to load it in a
database using 

.. code:: none

    =# CREATE EXTENSION hstore;

Because |hstore| is distributed as a contrib module, its oid is not well
known, so it is necessary to use `~psycopg.types.TypeInfo` to query the
database and get its oid. After that you can use
`~psycopg.types.hstore.register_hstore()` to allow dumping `!dict` to |hstore|
and parsing |hstore| back to `!dict` in the context where it is registered.

.. autofunction:: psycopg.types.hstore.register_hstore

Example::

    >>> from psycopg.types import TypeInfo
    >>> from psycopg.types.hstore import register_hstore

    >>> info = TypeInfo.fetch(conn, "hstore")
    >>> register_hstore(info, conn)

    >>> conn.execute("SELECT pg_typeof(%s)", [{"a": "b"}]).fetchone()[0]
    'hstore'

    >>> conn.execute("SELECT 'foo => bar'::hstore").fetchone()[0]
    {'foo': 'bar'}
