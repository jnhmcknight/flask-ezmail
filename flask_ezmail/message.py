from __future__ import annotations

import mimetypes
import re
import unicodedata
from collections.abc import Iterable, Mapping
from email.encoders import encode_base64
from email.message import Message as EmailMessage
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from typing import TYPE_CHECKING, Any, Union

from inscriptis import get_text

from flask_ezmail.utils import (
    Address,
    _has_newline,
    force_text,
    message_policy,
    sanitize_address,
    sanitize_addresses,
    sanitize_subject,
)

if TYPE_CHECKING:
    from flask_ezmail.connection import Connection

DEFAULT_CONTENT_TYPE = 'application/octet-stream'

_SPACES = re.compile(r'[\s]+', re.UNICODE)


def guess_content_type(filename: str | None) -> str:
    """Guess a MIME type from ``filename``, falling back to
    ``application/octet-stream``."""
    if filename:
        guessed, _ = mimetypes.guess_type(filename)
        if guessed:
            return guessed
    return DEFAULT_CONTENT_TYPE


class Attachment:
    """Encapsulates file attachment information.

    :versionadded: 0.3.5

    :param filename: filename of attachment
    :param content_type: file mimetype; guessed from ``filename`` when omitted
    :param data: the raw file data
    :param disposition: content-disposition (if any)
    :param headers: extra MIME headers for this attachment part
    """

    def __init__(
        self,
        filename: str | None = None,
        content_type: str | None = None,
        data: bytes | str | None = None,
        disposition: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.filename = filename
        self.content_type = content_type or guess_content_type(filename)
        self.data = data
        self.disposition = disposition or 'attachment'
        self.headers: dict[str, str] = dict(headers or {})


AltsType = Union[Mapping[str, str], Iterable[tuple[str, str]]]


class Message:
    """Encapsulates an email message.

    :param subject: email subject header
    :param recipients: list of email addresses
    :param body: plain text message; derived from ``html`` when omitted
    :param html: HTML message
    :param alts: A dict or an iterable to go through dict() that contains
        multipart alternatives
    :param sender: email sender address, or the mail's ``default_sender``
    :param cc: CC list
    :param bcc: BCC list
    :param attachments: list of Attachment instances
    :param reply_to: reply-to address
    :param date: send date
    :param charset: message character set
    :param extra_headers: A dictionary of additional headers for the message
    :param mail_options: A list of ESMTP options to be used in MAIL FROM
        command
    :param rcpt_options:  A list of ESMTP options to be used in RCPT commands
    :param ascii_attachments: force attachment filenames to ASCII
    """

    _body: str | None = None

    def __init__(
        self,
        subject: str = '',
        recipients: list[Address] | None = None,
        body: str | None = None,
        html: str | None = None,
        alts: AltsType | None = None,
        sender: Address | None = None,
        cc: list[Address] | None = None,
        bcc: list[Address] | None = None,
        attachments: list[Attachment] | None = None,
        reply_to: Address | None = None,
        date: float | None = None,
        charset: str | None = None,
        extra_headers: Mapping[str, str] | None = None,
        mail_options: list[str] | None = None,
        rcpt_options: list[str] | None = None,
        ascii_attachments: bool = False,
    ) -> None:
        if isinstance(sender, tuple):
            sender = "%s <%s>" % sender

        self.recipients: list[Address] = recipients or []
        self.subject = subject
        self.sender: str | None = sender
        self.reply_to = reply_to
        self.cc: list[Address] = cc or []
        self.bcc: list[Address] = bcc or []
        self.body = body
        self.alts: dict[str, str] = dict(alts or {})
        if html is not None:
            self.html = html
        self.date = date
        self.msgId = make_msgid()
        self.charset = charset
        self.extra_headers = extra_headers
        self.mail_options: list[str] = mail_options or []
        self.rcpt_options: list[str] = rcpt_options or []
        self.attachments: list[Attachment] = attachments or []
        self.ascii_attachments = ascii_attachments

    @property
    def send_to(self) -> set[Address]:
        return set(self.recipients) | set(self.bcc or ()) | set(self.cc or ())

    @property
    def html(self) -> str | None:
        return self.alts.get('html')

    @html.setter
    def html(self, value: str | None) -> None:
        if value is None:
            self.alts.pop('html', None)
        else:
            self.alts['html'] = value

    @property
    def body(self) -> str | None:
        if not self._body and self.html:
            return str(get_text(self.html))
        return self._body

    @body.setter
    def body(self, value: str | None) -> None:
        self._body = value

    def _mimetext(self, text: str | None, subtype: str = 'plain') -> MIMEText:
        """Creates a MIMEText object with the given subtype (default: 'plain')
        If the text is unicode, the utf-8 charset is used.
        """
        charset = self.charset or 'utf-8'
        return MIMEText(text or '', _subtype=subtype, _charset=charset)

    def _message(self) -> EmailMessage:
        """Creates the email"""
        ascii_attachments = self.ascii_attachments
        encoding = self.charset or 'utf-8'

        attachments = self.attachments or []

        msg: EmailMessage
        if len(attachments) == 0 and not self.alts:
            # No html content and zero attachments means plain text
            msg = self._mimetext(self.body)
        elif len(attachments) > 0 and not self.alts:
            # No html and at least one attachment means multipart
            msg = MIMEMultipart()
            msg.attach(self._mimetext(self.body))
        else:
            # Anything else
            msg = MIMEMultipart()
            alternative = MIMEMultipart('alternative')
            alternative.attach(self._mimetext(self.body, 'plain'))
            for mimetype, content in self.alts.items():
                alternative.attach(self._mimetext(content, mimetype))
            msg.attach(alternative)

        if self.subject:
            msg['Subject'] = sanitize_subject(force_text(self.subject), encoding)

        if self.sender:
            msg['From'] = sanitize_address(self.sender, encoding)
        msg['To'] = ', '.join(
            dict.fromkeys(sanitize_addresses(self.recipients, encoding))
        )

        msg['Date'] = formatdate(self.date, localtime=True)
        # see RFC 5322 section 3.6.4.
        msg['Message-ID'] = self.msgId

        if self.cc:
            msg['Cc'] = ', '.join(dict.fromkeys(sanitize_addresses(self.cc, encoding)))

        if self.reply_to:
            msg['Reply-To'] = sanitize_address(self.reply_to, encoding)

        if self.extra_headers:
            for k, v in self.extra_headers.items():
                msg[k] = v

        for attachment in attachments:
            content_type = attachment.content_type or guess_content_type(
                attachment.filename
            )
            maintype, _, subtype = content_type.partition('/')
            f = MIMEBase(maintype, subtype or 'octet-stream')
            f.set_payload(attachment.data if attachment.data is not None else b'')
            encode_base64(f)

            filename: Any = attachment.filename
            if filename and ascii_attachments:
                # force filename to ascii
                filename = unicodedata.normalize('NFKD', filename)
                filename = filename.encode('ascii', 'ignore').decode('ascii')
                filename = _SPACES.sub(' ', filename).strip()

            try:
                filename and filename.encode('ascii')
            except UnicodeEncodeError:
                filename = ('UTF8', '', filename)

            f.add_header('Content-Disposition', attachment.disposition, filename=filename)

            for key, value in attachment.headers.items():
                f.add_header(key, value)

            msg.attach(f)

        msg.policy = message_policy

        return msg

    def as_string(self) -> str:
        return self._message().as_string()

    def as_bytes(self) -> bytes:
        return self._message().as_bytes()

    def __str__(self) -> str:
        return self.as_string()

    def __bytes__(self) -> bytes:
        return self.as_bytes()

    def has_bad_headers(self) -> bool:
        """Checks for bad headers i.e. newlines in subject, sender or recipients.
        RFC5322: Allows multiline CRLF with trailing whitespace (FWS) in header
        """

        headers = [self.sender, self.reply_to] + self.recipients
        for header in headers:
            if _has_newline(header):
                return True

        if self.subject:
            if _has_newline(self.subject):
                for linenum, line in enumerate(self.subject.split('\r\n')):
                    if not line:
                        return True
                    if linenum > 0 and line[0] not in '\t ':
                        return True
                    if _has_newline(line):
                        return True
                    if len(line.strip()) == 0:
                        return True
        return False

    def is_bad_headers(self) -> bool:
        from warnings import warn

        msg = '''is_bad_headers is deprecated, use the new
        has_bad_headers method instead.'''
        warn(DeprecationWarning(msg), stacklevel=1)
        return self.has_bad_headers()

    def send(self, connection: Connection) -> None:
        """Verifies and sends the message."""

        if not self.sender and connection.mail.default_sender:
            self.sender = connection.mail.default_sender

        connection.send(self)

    def add_recipient(self, recipient: Address) -> None:
        """Adds another recipient to the message.

        :param recipient: email address of recipient.
        """

        self.recipients.append(recipient)

    def attach(
        self,
        filename: str | None = None,
        content_type: str | None = None,
        data: bytes | str | None = None,
        disposition: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        """Adds an attachment to the message.

        :param filename: filename of attachment
        :param content_type: file mimetype; guessed from ``filename`` when
            omitted
        :param data: the raw file data
        :param disposition: content-disposition (if any)
        :param headers: extra MIME headers for this attachment part
        """
        self.attachments.append(
            Attachment(filename, content_type, data, disposition, headers)
        )
