from __future__ import annotations

from collections.abc import Iterable, Iterator
from email import charset, policy
from email.header import Header
from email.utils import formataddr, parseaddr
from typing import Any, Union

#: An address may be a plain string (``"Name <addr@example.com>"``) or a
#: ``(name, address)`` tuple.
Address = Union[str, tuple[str, str]]

message_policy = policy.SMTP

charset.add_charset('utf-8', charset.SHORTEST, None, 'utf-8')


class FlaskMailUnicodeDecodeError(UnicodeDecodeError):
    def __init__(self, obj: Any, *args: Any) -> None:
        self.obj = obj
        UnicodeDecodeError.__init__(self, *args)

    def __str__(self) -> str:
        original = UnicodeDecodeError.__str__(self)
        return '%s. You passed in %r (%s)' % (original, self.obj, type(self.obj))


def force_text(s: Any, encoding: str = 'utf-8', errors: str = 'strict') -> str:
    """Coerce ``s`` to ``str``.

    ``bytes`` are decoded with ``encoding``; anything else (including lazy
    translation strings and exceptions) is converted with ``str()``.
    """
    if isinstance(s, str):
        return s

    if isinstance(s, (bytes, bytearray)):
        try:
            return bytes(s).decode(encoding, errors)
        except UnicodeDecodeError as e:
            raise FlaskMailUnicodeDecodeError(s, *e.args) from e

    return str(s)


def sanitize_subject(subject: str, encoding: str = 'utf-8') -> str:
    try:
        subject.encode('ascii')
    except UnicodeEncodeError:
        try:
            subject = Header(subject, encoding).encode()
        except UnicodeEncodeError:
            subject = Header(subject, 'utf-8').encode()
    return subject


def sanitize_address(addr: Address, encoding: str = 'utf-8') -> str:
    if isinstance(addr, str):
        nm, addr = parseaddr(force_text(addr))
    else:
        nm, addr = addr

    try:
        nm = Header(nm, encoding).encode()
    except UnicodeEncodeError:
        nm = Header(nm, 'utf-8').encode()
    try:
        addr.encode('ascii')
    except UnicodeEncodeError:  # IDN
        if '@' in addr:
            localpart, domain = addr.split('@', 1)
            localpart = str(Header(localpart, encoding))
            domain = domain.encode('idna').decode('ascii')
            addr = '@'.join([localpart, domain])
        else:
            addr = Header(addr, encoding).encode()
    return formataddr((nm, addr))


def sanitize_addresses(
    addresses: Iterable[Address], encoding: str = 'utf-8'
) -> Iterator[str]:
    return (sanitize_address(e, encoding) for e in addresses)


def _has_newline(line: Any) -> bool:
    """Used by has_bad_header to check for \\r or \\n.

    ``(name, address)`` tuples are checked element by element.
    """
    if isinstance(line, tuple):
        return any(_has_newline(part) for part in line)
    if line and isinstance(line, str) and ('\r' in line or '\n' in line):
        return True
    return False
