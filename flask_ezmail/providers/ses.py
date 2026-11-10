"""Amazon SES provider (SES v2 API).

Sends mail through the SES v2 ``SendEmail`` API using boto3 instead of
SMTP, so credentials come from the standard AWS credential chain (IAM
instance profiles, ECS task roles, EKS pod identity / IRSA, Lambda roles,
``AWS_PROFILE`` / SSO, environment variables, ...) rather than static SMTP
passwords.

Requires the ``ses`` extra (``boto3``).

Optional Flask config:

``FLASK_MAIL_SES_REGION``
    AWS region of the SES endpoint. Defaults to boto3's normal region
    resolution (``AWS_REGION`` / ``AWS_DEFAULT_REGION`` / profile config).
``FLASK_MAIL_SES_PROFILE``
    Named AWS profile to use. Defaults to the standard credential chain.
``FLASK_MAIL_SES_CONFIGURATION_SET``
    SES configuration set to attach to every message.
"""

from __future__ import annotations

import smtplib
import sys
from typing import Any

from flask import current_app, has_app_context

from ..connection import Connection

REGION_KEY = 'FLASK_MAIL_SES_REGION'
PROFILE_KEY = 'FLASK_MAIL_SES_PROFILE'
CONFIGURATION_SET_KEY = 'FLASK_MAIL_SES_CONFIGURATION_SET'


class SESSendError(smtplib.SMTPException):
    """Raised when SES rejects a send.

    Subclasses :class:`smtplib.SMTPException` so code written against the
    SMTP connection keeps working. The original botocore ``ClientError`` is
    available as ``__cause__``.
    """

    def __init__(self, code: str, message: str, response: dict[str, Any] | None = None) -> None:
        super().__init__(f'{code}: {message}')
        self.code = code
        self.message = message
        self.response = response or {}


def _config(key: str) -> Any:
    if has_app_context():
        return current_app.config.get(key)
    return None


class SESFakeSMTP:
    """Mimics the parts of :class:`smtplib.SMTP` used by ``Connection``,
    backed by the SES v2 API."""

    def __init__(
        self,
        region_name: str | None = None,
        profile_name: str | None = None,
        configuration_set: str | None = None,
        client: Any = None,
    ) -> None:
        self.region_name = region_name or _config(REGION_KEY)
        self.profile_name = profile_name or _config(PROFILE_KEY)
        self.configuration_set = configuration_set or _config(CONFIGURATION_SET_KEY)
        self.debuglevel = 0
        self.last_message_id: str | None = None
        self._client: Any = client

    @property
    def client(self) -> Any:
        """Lazily-created ``sesv2`` boto3 client (requires the ``ses``
        extra)."""
        if self._client is None:
            import boto3

            session = boto3.session.Session(profile_name=self.profile_name)
            self._client = session.client('sesv2', region_name=self.region_name)
        return self._client

    def set_debuglevel(self, debuglevel: int) -> None:
        self.debuglevel = debuglevel

    def sendmail(
        self,
        from_addr: str,
        to_addrs: list[str],
        msg: bytes,
        mail_options: list[str] = (),  # type: ignore[assignment]
        rcpt_options: list[str] = (),  # type: ignore[assignment]
    ) -> dict[str, tuple[int, bytes]]:
        """Send a fully-rendered MIME message.

        ``to_addrs`` is passed as the envelope destination so Bcc recipients
        (which are not in the message headers) are delivered. ESMTP
        ``mail_options`` / ``rcpt_options`` have no SES equivalent and are
        ignored.
        """
        from botocore.exceptions import ClientError

        kwargs: dict[str, Any] = {
            'FromEmailAddress': from_addr,
            'Destination': {'ToAddresses': list(to_addrs)},
            'Content': {'Raw': {'Data': msg}},
        }
        if self.configuration_set:
            kwargs['ConfigurationSetName'] = self.configuration_set

        try:
            response = self.client.send_email(**kwargs)
        except ClientError as exc:
            error = exc.response.get('Error', {})
            raise SESSendError(
                error.get('Code', 'Unknown'),
                error.get('Message', str(exc)),
                exc.response,
            ) from exc

        self.last_message_id = response.get('MessageId')
        if self.debuglevel:
            print(f'SES sent message {self.last_message_id} to {to_addrs}', file=sys.stderr)

        # SES accepts or rejects the message as a whole; there are never
        # per-recipient refusals to report.
        return {}

    def quit(self) -> None:
        self._client = None


class SESConnection(Connection):

    requires_server = False

    def configure_host(self) -> SESFakeSMTP:
        host = SESFakeSMTP()
        host.set_debuglevel(int(bool(self.mail.debug)))
        return host
