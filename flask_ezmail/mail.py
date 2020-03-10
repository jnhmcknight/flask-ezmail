
from contextlib import contextmanager

try:
    from babel import _
except ImportError:
    def _(string):
        return string

from .connection import Connection
from .message import Message


class _MailMixin(object):

    @contextmanager
    def record_messages(self):
        """Records all messages. Use in unit tests for example::

            with mail.record_messages() as outbox:
                response = app.test_client.get("/email-sending-view/")
                assert len(outbox) == 1
                assert outbox[0].subject == "testing"

        You must have blinker installed in order to use this feature.
        :versionadded: 0.4
        """

        if not email_dispatched:
            raise RuntimeError(_("blinker must be installed"))

        outbox = []

        def _record(message, app):
            outbox.append(message)

        email_dispatched.connect(_record)

        try:
            yield outbox
        finally:
            email_dispatched.disconnect(_record)

    def send(self, message):
        """Sends a single message instance. If TESTING is True the message will
        not actually be sent.

        :param message: a Message instance.
        """

        with self.connect() as connection:
            message.send(connection)

    def send_message(self, *args, **kwargs):
        """Shortcut for send(msg).

        Takes same arguments as Message constructor.

        :versionadded: 0.3.5
        """

        self.send(Message(*args, **kwargs))

    def connect(self):
        """Opens a connection to the mail host."""
        return Connection(self)


class Mail(_MailMixin):

    def __init__(
        self,
        server=None,
        username=None,
        password=None,
        port=None,
        use_tls=False,
        use_ssl=False,
        default_sender=None,
        debug=False,
        max_emails=None,
        suppress=False,
    ):

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

    def init_app(self, flask_app):
        """Initialize this extension with values from the flask app config"""

        if not self.server:
            if not flask_app.config.get('FLASK_MAIL_SERVER'):
                raise ValueError(_('Missing FLASK_MAIL_SERVER. Cannot proceed'))

        if not self.username:
            self.username = flask_app.config.get('FLASK_MAIL_USERNAME')

        if not self.password:
            self.password = flask_app.config.get('FLASK_MAIL_PASSWORD')

        if not self.port:
            self.port = flask_app.config.get('FLASK_MAIL_PORT')

        if not self.use_tls:
            self.use_tls = flask_app.config.get('FLASK_MAIL_USE_TLS')

        if not self.use_ssl:
            self.use_ssl = flask_app.config.get('FLASK_MAIL_USE_SSL')

        if not self.default_sender:
            self.default_sender = flask_app.config.get('FLASK_MAIL_DEFAULT_SENDER')

        if not self.max_emails:
            self.max_emails = flask_app.config.get('FLASK_MAIL_MAX_EMAILS')

        if not self.suppress:
            self.suppress = flask_app.config.get('FLASK_MAIL_SUPPRESS')

        if not self.debug:
            self.debug = flask_app.config.get('FLASK_MAIL_DEBUG', flask_app.debug)
