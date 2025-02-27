"""
Support for range types adaptation.
"""

# Copyright (C) 2020-2021 The Psycopg Team

import re
from typing import Any, Dict, Generic, Optional, TypeVar, Type, Union
from typing import cast
from decimal import Decimal
from datetime import date, datetime

from .. import postgres
from ..pq import Format
from ..abc import AdaptContext, Buffer, Dumper, DumperKey
from ..adapt import RecursiveDumper, RecursiveLoader, PyFormat
from .._struct import pack_len, unpack_len
from ..postgres import INVALID_OID, TEXT_OID
from .._typeinfo import RangeInfo as RangeInfo  # exported here
from .composite import SequenceDumper, BaseCompositeLoader

RANGE_EMPTY = 0x01  # range is empty
RANGE_LB_INC = 0x02  # lower bound is inclusive
RANGE_UB_INC = 0x04  # upper bound is inclusive
RANGE_LB_INF = 0x08  # lower bound is -infinity
RANGE_UB_INF = 0x10  # upper bound is +infinity

_EMPTY_HEAD = bytes([RANGE_EMPTY])

T = TypeVar("T")


class Range(Generic[T]):
    """Python representation for a PostgreSQL range type.

    :param lower: lower bound for the range. `!None` means unbound
    :param upper: upper bound for the range. `!None` means unbound
    :param bounds: one of the literal strings ``()``, ``[)``, ``(]``, ``[]``,
        representing whether the lower or upper bounds are included
    :param empty: if `!True`, the range is empty

    """

    __slots__ = ("_lower", "_upper", "_bounds")

    def __init__(
        self,
        lower: Optional[T] = None,
        upper: Optional[T] = None,
        bounds: str = "[)",
        empty: bool = False,
    ):
        if not empty:
            if bounds not in ("[)", "(]", "()", "[]"):
                raise ValueError("bound flags not valid: %r" % bounds)

            self._lower = lower
            self._upper = upper
            self._bounds = bounds
        else:
            self._lower = self._upper = None
            self._bounds = ""

    def __repr__(self) -> str:
        if self._bounds:
            args = f"{self._lower!r}, {self._upper!r}, {self._bounds!r}"
        else:
            args = "empty=True"

        return f"{self.__class__.__name__}({args})"

    def __str__(self) -> str:
        if not self._bounds:
            return "empty"

        items = [
            self._bounds[0],
            str(self._lower),
            ", ",
            str(self._upper),
            self._bounds[1],
        ]
        return "".join(items)

    @property
    def lower(self) -> Optional[T]:
        """The lower bound of the range. `!None` if empty or unbound."""
        return self._lower

    @property
    def upper(self) -> Optional[T]:
        """The upper bound of the range. `!None` if empty or unbound."""
        return self._upper

    @property
    def bounds(self) -> str:
        """The bounds string (two characters from '[', '(', ']', ')')."""
        return self._bounds

    @property
    def isempty(self) -> bool:
        """`!True` if the range is empty."""
        return not self._bounds

    @property
    def lower_inf(self) -> bool:
        """`!True` if the range doesn't have a lower bound."""
        if not self._bounds:
            return False
        return self._lower is None

    @property
    def upper_inf(self) -> bool:
        """`!True` if the range doesn't have an upper bound."""
        if not self._bounds:
            return False
        return self._upper is None

    @property
    def lower_inc(self) -> bool:
        """`!True` if the lower bound is included in the range."""
        if not self._bounds or self._lower is None:
            return False
        return self._bounds[0] == "["

    @property
    def upper_inc(self) -> bool:
        """`!True` if the upper bound is included in the range."""
        if not self._bounds or self._upper is None:
            return False
        return self._bounds[1] == "]"

    def __contains__(self, x: T) -> bool:
        if not self._bounds:
            return False

        if self._lower is not None:
            if self._bounds[0] == "[":
                # It doesn't seem that Python has an ABC for ordered types.
                if x < self._lower:  # type: ignore[operator]
                    return False
            else:
                if x <= self._lower:  # type: ignore[operator]
                    return False

        if self._upper is not None:
            if self._bounds[1] == "]":
                if x > self._upper:  # type: ignore[operator]
                    return False
            else:
                if x >= self._upper:  # type: ignore[operator]
                    return False

        return True

    def __bool__(self) -> bool:
        return bool(self._bounds)

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Range):
            return False
        return (
            self._lower == other._lower
            and self._upper == other._upper
            and self._bounds == other._bounds
        )

    def __ne__(self, other: Any) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return hash((self._lower, self._upper, self._bounds))

    # as the postgres docs describe for the server-side stuff,
    # ordering is rather arbitrary, but will remain stable
    # and consistent.

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, Range):
            return NotImplemented
        for attr in ("_lower", "_upper", "_bounds"):
            self_value = getattr(self, attr)
            other_value = getattr(other, attr)
            if self_value == other_value:
                pass
            elif self_value is None:
                return True
            elif other_value is None:
                return False
            else:
                return cast(bool, self_value < other_value)
        return False

    def __le__(self, other: Any) -> bool:
        if self == other:
            return True
        else:
            return self.__lt__(other)

    def __gt__(self, other: Any) -> bool:
        if isinstance(other, Range):
            return other.__lt__(self)
        else:
            return NotImplemented

    def __ge__(self, other: Any) -> bool:
        if self == other:
            return True
        else:
            return self.__gt__(other)

    def __getstate__(self) -> Dict[str, Any]:
        return {
            slot: getattr(self, slot)
            for slot in self.__slots__
            if hasattr(self, slot)
        }

    def __setstate__(self, state: Dict[str, Any]) -> None:
        for slot, value in state.items():
            setattr(self, slot, value)


# Subclasses to specify a specific subtype. Usually not needed: only needed
# in binary copy, where switching to text is not an option.


class Int4Range(Range[int]):
    pass


class Int8Range(Range[int]):
    pass


class NumericRange(Range[Decimal]):
    pass


class DateRange(Range[date]):
    pass


class TimestampRange(Range[datetime]):
    pass


class TimestamptzRange(Range[datetime]):
    pass


class BaseRangeDumper(RecursiveDumper):
    def __init__(self, cls: type, context: Optional[AdaptContext] = None):
        super().__init__(cls, context)
        self.sub_dumper: Optional[Dumper] = None
        self._adapt_format = PyFormat.from_pq(self.format)

    def get_key(self, obj: Range[Any], format: PyFormat) -> DumperKey:
        # If we are a subclass whose oid is specified we don't need upgrade
        if self.cls is not Range:
            return self.cls

        item = self._get_item(obj)
        if item is not None:
            sd = self._tx.get_dumper(item, self._adapt_format)
            return (self.cls, sd.get_key(item, format))  # type: ignore
        else:
            return (self.cls,)

    def upgrade(self, obj: Range[Any], format: PyFormat) -> "BaseRangeDumper":
        # If we are a subclass whose oid is specified we don't need upgrade
        if self.cls is not Range:
            return self

        item = self._get_item(obj)
        if item is None:
            return RangeDumper(self.cls)

        dumper: BaseRangeDumper
        if type(item) is int:
            # postgres won't cast int4range -> int8range so we must use
            # text format and unknown oid here
            sd = self._tx.get_dumper(item, PyFormat.TEXT)
            dumper = RangeDumper(self.cls, self._tx)
            dumper.sub_dumper = sd
            dumper.oid = INVALID_OID
            return dumper

        sd = self._tx.get_dumper(item, format)
        dumper = type(self)(self.cls, self._tx)
        dumper.sub_dumper = sd
        if sd.oid == INVALID_OID and isinstance(item, str):
            # Work around the normal mapping where text is dumped as unknown
            dumper.oid = self._get_range_oid(TEXT_OID)
        else:
            dumper.oid = self._get_range_oid(sd.oid)

        return dumper

    def _get_item(self, obj: Range[Any]) -> Any:
        """
        Return a member representative of the range
        """
        rv = obj.lower
        return rv if rv is not None else obj.upper

    def _get_range_oid(self, sub_oid: int) -> int:
        """
        Return the oid of the range from the oid of its elements.

        Raise InterfaceError if not found.
        """
        info = self._tx.adapters.types.get_range(sub_oid)
        return info.oid if info else INVALID_OID


class RangeDumper(BaseRangeDumper, SequenceDumper):
    """
    Dumper for range types.

    The dumper can upgrade to one specific for a different range type.
    """

    def dump(self, obj: Range[Any]) -> bytes:
        if not obj:
            return b"empty"
        else:
            return self._dump_sequence(
                (obj.lower, obj.upper),
                b"[" if obj.lower_inc else b"(",
                b"]" if obj.upper_inc else b")",
                b",",
            )

    _re_needs_quotes = re.compile(br'[",\\\s()\[\]]')


class RangeBinaryDumper(BaseRangeDumper):

    format = Format.BINARY

    def dump(self, obj: Range[Any]) -> Union[bytes, bytearray]:
        if not obj:
            return _EMPTY_HEAD

        out = bytearray([0])  # will replace the head later

        head = 0
        if obj.lower_inc:
            head |= RANGE_LB_INC
        if obj.upper_inc:
            head |= RANGE_UB_INC

        item = self._get_item(obj)
        if item is not None:
            dump = self._tx.get_dumper(item, self._adapt_format).dump

        if obj.lower is not None:
            data = dump(obj.lower)
            out += pack_len(len(data))
            out += data
        else:
            head |= RANGE_LB_INF

        if obj.upper is not None:
            data = dump(obj.upper)
            out += pack_len(len(data))
            out += data
        else:
            head |= RANGE_UB_INF

        out[0] = head
        return out


class RangeLoader(BaseCompositeLoader, Generic[T]):
    """Generic loader for a range.

    Subclasses shoud specify the oid of the subtype and the class to load.
    """

    subtype_oid: int

    def load(self, data: Buffer) -> Range[T]:
        if data == b"empty":
            return Range(empty=True)

        cast = self._tx.get_loader(self.subtype_oid, format=Format.TEXT).load
        bounds = _int2parens[data[0]] + _int2parens[data[-1]]
        min, max = (
            cast(token) if token is not None else None
            for token in self._parse_record(data[1:-1])
        )
        return Range(min, max, bounds)


class RangeBinaryLoader(RecursiveLoader, Generic[T]):

    format = Format.BINARY
    subtype_oid: int

    def load(self, data: Buffer) -> Range[T]:
        head = data[0]
        if head & RANGE_EMPTY:
            return Range(empty=True)

        load = self._tx.get_loader(self.subtype_oid, format=Format.BINARY).load
        lb = "[" if head & RANGE_LB_INC else "("
        ub = "]" if head & RANGE_UB_INC else ")"

        pos = 1  # after the head
        if head & RANGE_LB_INF:
            min = None
        else:
            length = unpack_len(data, pos)[0]
            pos += 4
            min = load(data[pos : pos + length])
            pos += length

        if head & RANGE_UB_INF:
            max = None
        else:
            length = unpack_len(data, pos)[0]
            pos += 4
            max = load(data[pos : pos + length])

        return Range(min, max, lb + ub)


_int2parens = {ord(c): c for c in "[]()"}


def register_range(
    info: RangeInfo, context: Optional[AdaptContext] = None
) -> None:
    """Register the adapters to load and dump a range type.

    :param info: The object with the information about the range to register.
    :param context: The context where to register the adapters. If `!None`,
        register it globally.

    Register loaders so that loading data of this type will result in a `Range`
    with bounds parsed as the right subtype.
    """

    # Register arrays and type info
    info.register(context)

    adapters = context.adapters if context else postgres.adapters

    # generate and register a customized text loader
    loader: Type[RangeLoader[Any]] = type(
        f"{info.name.title()}Loader",
        (RangeLoader,),
        {"subtype_oid": info.subtype_oid},
    )
    adapters.register_loader(info.oid, loader)

    # generate and register a customized binary loader
    bloader: Type[RangeBinaryLoader[Any]] = type(
        f"{info.name.title()}BinaryLoader",
        (RangeBinaryLoader,),
        {"subtype_oid": info.subtype_oid},
    )
    adapters.register_loader(info.oid, bloader)


# Text dumpers for builtin range types wrappers
# These are registered on specific subtypes so that the upgrade mechanism
# doesn't kick in.


class Int4RangeDumper(RangeDumper):
    oid = postgres.types["int4range"].oid


class Int8RangeDumper(RangeDumper):
    oid = postgres.types["int8range"].oid


class NumericRangeDumper(RangeDumper):
    oid = postgres.types["numrange"].oid


class DateRangeDumper(RangeDumper):
    oid = postgres.types["daterange"].oid


class TimestampRangeDumper(RangeDumper):
    oid = postgres.types["tsrange"].oid


class TimestamptzRangeDumper(RangeDumper):
    oid = postgres.types["tstzrange"].oid


# Binary dumpers for builtin range types wrappers
# These are registered on specific subtypes so that the upgrade mechanism
# doesn't kick in.


class Int4RangeBinaryDumper(RangeBinaryDumper):
    oid = postgres.types["int4range"].oid


class Int8RangeBinaryDumper(RangeBinaryDumper):
    oid = postgres.types["int8range"].oid


class NumericRangeBinaryDumper(RangeBinaryDumper):
    oid = postgres.types["numrange"].oid


class DateRangeBinaryDumper(RangeBinaryDumper):
    oid = postgres.types["daterange"].oid


class TimestampRangeBinaryDumper(RangeBinaryDumper):
    oid = postgres.types["tsrange"].oid


class TimestamptzRangeBinaryDumper(RangeBinaryDumper):
    oid = postgres.types["tstzrange"].oid


# Text loaders for builtin range types


class Int4RangeLoader(RangeLoader[int]):
    subtype_oid = postgres.types["int4"].oid


class Int8RangeLoader(RangeLoader[int]):
    subtype_oid = postgres.types["int8"].oid


class NumericRangeLoader(RangeLoader[Decimal]):
    subtype_oid = postgres.types["numeric"].oid


class DateRangeLoader(RangeLoader[date]):
    subtype_oid = postgres.types["date"].oid


class TimestampRangeLoader(RangeLoader[datetime]):
    subtype_oid = postgres.types["timestamp"].oid


class TimestampTZRangeLoader(RangeLoader[datetime]):
    subtype_oid = postgres.types["timestamptz"].oid


# Binary loaders for builtin range types


class Int4RangeBinaryLoader(RangeBinaryLoader[int]):
    subtype_oid = postgres.types["int4"].oid


class Int8RangeBinaryLoader(RangeBinaryLoader[int]):
    subtype_oid = postgres.types["int8"].oid


class NumericRangeBinaryLoader(RangeBinaryLoader[Decimal]):
    subtype_oid = postgres.types["numeric"].oid


class DateRangeBinaryLoader(RangeBinaryLoader[date]):
    subtype_oid = postgres.types["date"].oid


class TimestampRangeBinaryLoader(RangeBinaryLoader[datetime]):
    subtype_oid = postgres.types["timestamp"].oid


class TimestampTZRangeBinaryLoader(RangeBinaryLoader[datetime]):
    subtype_oid = postgres.types["timestamptz"].oid


def register_default_adapters(context: AdaptContext) -> None:
    adapters = context.adapters
    adapters.register_dumper(Range, RangeBinaryDumper)
    adapters.register_dumper(Range, RangeDumper)
    adapters.register_dumper(Int4Range, Int4RangeDumper)
    adapters.register_dumper(Int8Range, Int8RangeDumper)
    adapters.register_dumper(NumericRange, NumericRangeDumper)
    adapters.register_dumper(DateRange, DateRangeDumper)
    adapters.register_dumper(TimestampRange, TimestampRangeDumper)
    adapters.register_dumper(TimestamptzRange, TimestamptzRangeDumper)
    adapters.register_dumper(Int4Range, Int4RangeBinaryDumper)
    adapters.register_dumper(Int8Range, Int8RangeBinaryDumper)
    adapters.register_dumper(NumericRange, NumericRangeBinaryDumper)
    adapters.register_dumper(DateRange, DateRangeBinaryDumper)
    adapters.register_dumper(TimestampRange, TimestampRangeBinaryDumper)
    adapters.register_dumper(TimestamptzRange, TimestamptzRangeBinaryDumper)
    adapters.register_loader("int4range", Int4RangeLoader)
    adapters.register_loader("int8range", Int8RangeLoader)
    adapters.register_loader("numrange", NumericRangeLoader)
    adapters.register_loader("daterange", DateRangeLoader)
    adapters.register_loader("tsrange", TimestampRangeLoader)
    adapters.register_loader("tstzrange", TimestampTZRangeLoader)
    adapters.register_loader("int4range", Int4RangeBinaryLoader)
    adapters.register_loader("int8range", Int8RangeBinaryLoader)
    adapters.register_loader("numrange", NumericRangeBinaryLoader)
    adapters.register_loader("daterange", DateRangeBinaryLoader)
    adapters.register_loader("tsrange", TimestampRangeBinaryLoader)
    adapters.register_loader("tstzrange", TimestampTZRangeBinaryLoader)
