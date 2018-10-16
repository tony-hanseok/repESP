"""Fundamental types used to describe molecules in space"""

from ._util import elements, get_symbol, get_atomic_number
from .util import angstrom_per_bohr

from dataclasses import dataclass
from typing import Any, Generic, List, Tuple, TypeVar


class Dist(float):
    # NewType had many limitations: not supported in sphinx, not possible to
    # override __repr__, and requirement for standalone helper constructors, like:
    # https://github.com/python/typing/issues/415#issuecomment-297401553

    """Distance [bohr]"""

    __slots__ = ()

    def __new__(cls, x: Any):
        return super().__new__(cls, float(x))  # type: ignore # (Too many arguments for "__new__" of "object")

    @classmethod
    def from_angstrom(cls, value: Any):
        return cls(float(value)/angstrom_per_bohr)

    def angstrom(self) -> float:
        return angstrom_per_bohr*self

    def __repr__(self) -> str:
        return f"Dist({super().__repr__()})"

    def __str__(self) -> str:

        def get_decimals_in_str(str_: str) -> int:
            return len(str_) - str_.find(".") - 1

        # Angstroms are displayed with the same decimal precision as a.u. value
        angstrom_format = f"{{:.{get_decimals_in_str(super().__str__())}f}}"
        str_ = f"{super().__str__()} a₀ ({angstrom_format} Å)"
        return str_.format(self.angstrom())


class Coords(tuple):

    __slots__ = ()

    # A constructor from individual distances would be more convenient but that
    # was causing issues due to libraries and built-ins assuming the same
    # interface as `tuple`.
    def __new__(cls, t: Tuple[Any, Any, Any]):
        # To allow generators (required by `dataclasses.astuple`)
        t = tuple(t)  # type: ignore # (t is now a variadic-size tuple)
        return super().__new__(cls, tuple((Dist(t[0]), Dist(t[1]), Dist(t[2]))))


@dataclass
class Atom:
    atomic_number: int

    def __post_init__(self):
        if self.atomic_number < 1 or self.atomic_number >= len(elements):
            raise ValueError("Atomic number is not within expected bounds.")

    @property
    def symbol(self) -> str:
        return get_symbol(self.atomic_number)

    @classmethod
    def from_symbol(cls, symbol: str, *args, **kwargs):
        # Generic type annotations as per:
        # https://github.com/python/typing/issues/58#issuecomment-326240794)
        # don't seem to be working for a dataclass, and that's even before
        # getting them to work with args and kwargs.
        return cls(get_atomic_number(symbol), *args, **kwargs)  # type: ignore # (args, kwargs)


@dataclass
class AtomWithCoords(Atom):
    coords: Coords


GenericAtom = TypeVar('GenericAtom', bound=Atom)

@dataclass
class Molecule(Generic[GenericAtom]):
    atoms: List[GenericAtom]
