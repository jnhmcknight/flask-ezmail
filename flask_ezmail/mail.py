from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from .connection import Connection, _recordings
from .message import Message

if TYPE_CHECKING:
    from flask import Flask

#: ``app.config`` key prefix read by :meth:`Mail.init_app`.
CONFIG_PREFIX = 'FLASK_MAIL_'


class _MailMixin:

    server: str | None
    username: str | None
    password: str | None
    port: int | None
    use_tls: bool | None
    use_ssl: bool | None
    default_sender: str | None
    debug: bool | int | None
    max_emails: int | None
    suppress: bool | None

    @contextmanager
    def record_messages(self) -> Iterator[list[Message]]:
        """Records all messages. Use in unit tests for example::

            with mail.record_messages() as outbox:
                response = app.test_client.get("/email-sending-view/")
                assert len(outbox) == 1
                assert outbox[0].subject == "testing"

        While recording, nothing sent through this mail object is actually
        delivered. Recording is scoped to the current thread / async task:
        messages sent from other threads are neither captured nor
        suppressed, and ``self.suppress`` is never modified.

        :versionadded: 0.4
        """

        outbox: list[Message] = []
        token = _recordings.set(_recordings.get() + ((self, outbox),))
        try:
            yield outbox
        finally:
            _recordings.reset(token)

    def send(self, message: Message) -> None:
        """Sends a single message instance. If suppressed (e.g. when the app
        is in testing mode) the message will not actually be sent.

        :param message: a Message instance.
        """

        with self.connect() as connection:
            message.send(connection)

    def send_message(self, *args: Any, **kwargs: Any) -> None:
        """Shortcut for send(msg).

        Takes same arguments as Message constructor.

        :versionadded: 0.3.5
        """

        self.send(Message(*args, **kwargs))

    def connect(self) -> Connection:
        """Opens a connection to the mail host."""

        return Connection(self)


class Mail(_MailMixin):
    """Mail settings and sender.

    Any argument left as ``None`` can be filled in later by :meth:`init_app`
    from the Flask config. Arguments passed explicitly always win over the
    config, including ``False`` values such as ``use_tls=False``.
    """

    def __init__(
        self,
        server: str | None = None,
        username: str | None = None,
        password: str | None = None,
        port: int | None = None,
        use_tls: bool | None = None,
        use_ssl: bool | None = None,
        default_sender: str | None = None,
        debug: bool | int | None = None,
        max_emails: int | None = None,
        suppress: bool | None = None,
    ) -> None:

        self.server = server
        self.username = username
        self.password = password
        self.port = port
        self.use_tls = use_tls
        self.use_ssl = use_ssl
        self.default_sender = default_sender
        self.debug = debug
        self.max_emails = max_emails
        self.suppress = suppress

    def init_app(self, flask_app: Flask) -> None:
        """Fill any setting that was not passed explicitly from the Flask app
        config (``FLASK_MAIL_*`` keys), then register the extension as
        ``app.extensions['ezmail']``.

        ``FLASK_MAIL_SUPPRESS`` defaults to ``app.testing`` and
        ``FLASK_MAIL_DEBUG`` defaults to ``app.debug``.
        """

        config = flask_app.config

        def fill(attr: str, default: Any = None) -> None:
            if getattr(self, attr, None) is None:
                setattr(self, attr, config.get(CONFIG_PREFIX + attr.upper(), default))

        fill('server')
        if not self.server:
            raise ValueError('Missing FLASK_MAIL_SERVER. Cannot proceed')

        fill('username')
        fill('password')
        fill('port')
        fill('use_tls', False)
        fill('use_ssl', False)
        fill('default_sender')
        fill('max_emails')
        fill('suppress', flask_app.testing)
        fill('debug', flask_app.debug)

        flask_app.extensions['ezmail'] = self
