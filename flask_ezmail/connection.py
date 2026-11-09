from __future__ import annotations

import smtplib
import time
from contextvars import ContextVar
from types import TracebackType
from typing import TYPE_CHECKING, Any, Protocol, cast

import blinker
from flask import current_app, has_app_context

from flask_ezmail.message import Message
from flask_ezmail.utils import sanitize_address, sanitize_addresses

if TYPE_CHECKING:
    from flask import Flask

    from flask_ezmail.mail import _MailMixin

signals = blinker.Namespace()

email_dispatched = signals.signal("email-dispatched", doc="""
Signal sent when an email is dispatched. This signal will also be sent
in testing mode, even though the email will not actually be sent.

Receivers are called with the message as the sender and an ``app`` keyword
argument holding the current Flask app (or ``None`` outside an app context),
matching Flask-Mail::

    @email_dispatched.connect
    def on_sent(message, app):
        ...
""")

#: Active :meth:`~flask_ezmail.mail._MailMixin.record_messages` blocks for the
#: current thread / async task, as ``(mail, outbox)`` pairs. Using a context
#: variable keeps recordings isolated between threads and never mutates the
#: shared ``mail.suppress`` attribute.
_recordings: ContextVar[tuple[tuple[Any, list[Message]], ...]] = ContextVar(
    'flask_ezmail_recordings', default=()
)


def _outboxes_for(mail: Any) -> list[list[Message]]:
    return [outbox for recording_mail, outbox in _recordings.get() if recording_mail is mail]


def _current_app() -> Flask | None:
    if has_app_context():
        return cast('Flask', current_app._get_current_object())  # type: ignore[attr-defined]
    return None


class SMTPHost(Protocol):
    """The subset of :class:`smtplib.SMTP` that :class:`Connection` uses."""

    def set_debuglevel(self, debuglevel: int) -> None: ...

    def sendmail(
        self,
        from_addr: str,
        to_addrs: list[str],
        msg: bytes,
        mail_options: list[str] = ...,
        rcpt_options: list[str] = ...,
    ) -> Any: ...

    def quit(self) -> Any: ...


class Connection:
    """Handles connection to host."""

    host: SMTPHost | None

    def __init__(self, mail: _MailMixin) -> None:
        self.mail = mail
        self.host = None
        self.num_emails = 0

    @property
    def suppressed(self) -> bool:
        """True when nothing should actually be sent: either the mail is
        configured to suppress sending, or a ``record_messages`` block for
        this mail is active in the current context."""
        return bool(self.mail.suppress) or bool(_outboxes_for(self.mail))

    def __enter__(self) -> Connection:
        if self.suppressed:
            self.host = None
        else:
            self.host = self.configure_host()

        self.num_emails = 0

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self.host:
            self.host.quit()

    def configure_host(self) -> SMTPHost:
        host: smtplib.SMTP
        if self.mail.use_ssl:
            host = smtplib.SMTP_SSL(self.mail.server or '', self.mail.port or 0)
        else:
            host = smtplib.SMTP(self.mail.server or '', self.mail.port or 0)

        host.set_debuglevel(int(bool(self.mail.debug)))

        if self.mail.use_tls:
            host.starttls()

        if self.mail.username and self.mail.password:
            host.login(self.mail.username, self.mail.password)

        return host

    def send(self, message: Message, envelope_from: str | None = None) -> None:
        """Verifies and sends message.

        :param message: Message instance.
        :param envelope_from: Email address to be used in MAIL FROM command.
        """
        assert message.send_to, "No recipients have been added"

        assert message.sender, (
            "The message does not specify a sender and a default sender "
            "has not been configured")

        if message.has_bad_headers():
            raise BadHeaderError

        if message.date is None:
            message.date = time.time()

        if self.host:
            self.host.sendmail(
                sanitize_address(envelope_from or message.sender),
                list(sanitize_addresses(message.send_to)),
                message.as_bytes(),
                message.mail_options,
                message.rcpt_options,
            )

        for outbox in _outboxes_for(self.mail):
            outbox.append(message)

        email_dispatched.send(message, app=_current_app())

        self.num_emails += 1

        if self.num_emails == self.mail.max_emails:
            self.num_emails = 0
            if self.host:
                self.host.quit()
                self.host = self.configure_host()

    def send_message(self, *args: Any, **kwargs: Any) -> None:
        """Shortcut for send(msg).

        Takes same arguments as Message constructor.

        :versionadded: 0.3.5
        """

        Message(*args, **kwargs).send(self)


class BadHeaderError(Exception):
    pass
