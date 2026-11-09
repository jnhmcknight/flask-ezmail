from __future__ import annotations

import pytest
from flask import Flask

from flask_ezmail import BadHeaderError, Mail, Message, email_dispatched


def make_msg(**kwargs) -> Message:
    kwargs.setdefault('subject', 'Hi')
    kwargs.setdefault('recipients', ['b@x.com'])
    kwargs.setdefault('body', 'hello')
    return Message(**kwargs)


class TestConfigureHost:
    def test_plain_smtp(self, smtp, mail):
        mail.send(make_msg())
        (host,) = smtp.instances
        assert (host.host, host.port, host.ssl) == ('smtp.example.com', 2525, False)
        assert host.debuglevel == 0
        assert not host.started_tls
        assert host.login_args is None
        assert host.quit_called

    def test_ssl(self, smtp):
        Mail(server='s', port=465, use_ssl=True, default_sender='a@x.com').send(make_msg())
        assert smtp.instances[0].ssl

    def test_tls_and_login(self, smtp):
        Mail(
            server='s', username='u', password='p', use_tls=True, default_sender='a@x.com'
        ).send(make_msg())
        host = smtp.instances[0]
        assert host.started_tls
        assert host.login_args == ('u', 'p')

    def test_login_requires_both_credentials(self, smtp):
        Mail(server='s', username='u', default_sender='a@x.com').send(make_msg())
        assert smtp.instances[0].login_args is None

    def test_debug_level(self, smtp):
        Mail(server='s', debug=True, default_sender='a@x.com').send(make_msg())
        assert smtp.instances[0].debuglevel == 1

    def test_missing_port_uses_smtplib_default(self, smtp):
        Mail(server='s', default_sender='a@x.com').send(make_msg())
        assert smtp.instances[0].port == 0


class TestSend:
    def test_sendmail_arguments(self, smtp, mail):
        msg = make_msg(
            cc=['c@x.com'], bcc=['d@x.com'], mail_options=['SMTPUTF8'], rcpt_options=['NOTIFY=NEVER']
        )
        mail.send(msg)
        from_addr, to_addrs, raw, mail_opts, rcpt_opts = smtp.instances[0].sent[0]
        assert from_addr == 'sender@example.com'
        assert sorted(to_addrs) == ['b@x.com', 'c@x.com', 'd@x.com']
        assert isinstance(raw, bytes) and b'hello' in raw
        assert mail_opts == ['SMTPUTF8']
        assert rcpt_opts == ['NOTIFY=NEVER']

    def test_default_sender_applied(self, smtp, mail):
        msg = make_msg()
        mail.send(msg)
        assert msg.sender == 'sender@example.com'

    def test_explicit_sender_kept(self, smtp, mail):
        msg = make_msg(sender='me@x.com')
        mail.send(msg)
        assert smtp.instances[0].sent[0][0] == 'me@x.com'

    def test_envelope_from(self, smtp, mail):
        with mail.connect() as conn:
            conn.send(make_msg(sender='me@x.com'), envelope_from='bounce@x.com')
        assert smtp.instances[0].sent[0][0] == 'bounce@x.com'

    def test_date_set_on_send(self, smtp, mail):
        msg = make_msg()
        assert msg.date is None
        mail.send(msg)
        assert isinstance(msg.date, float)

    def test_no_recipients(self, smtp, mail):
        with pytest.raises(AssertionError, match='No recipients'):
            mail.send(make_msg(recipients=[]))

    def test_no_sender(self, smtp):
        with pytest.raises(AssertionError, match='sender'):
            Mail(server='s').send(make_msg())

    def test_bad_headers(self, smtp, mail):
        with pytest.raises(BadHeaderError):
            mail.send(make_msg(subject='bad\nsubject'))
        assert smtp.instances[0].sent == []

    def test_send_message_shortcut(self, smtp, mail):
        mail.send_message('Hi', recipients=['b@x.com'], body='x')
        assert len(smtp.instances[0].sent) == 1

    def test_connection_send_message_applies_default_sender(self, smtp, mail):
        with mail.connect() as conn:
            conn.send_message('Hi', recipients=['b@x.com'], body='x')
        assert smtp.instances[0].sent[0][0] == 'sender@example.com'

    def test_bulk_single_connection(self, smtp, mail):
        with mail.connect() as conn:
            for i in range(3):
                conn.send(make_msg(sender='a@x.com', subject=str(i)))
        assert len(smtp.instances) == 1
        assert len(smtp.instances[0].sent) == 3

    def test_max_emails_reconnects(self, smtp):
        mail = Mail(server='s', max_emails=2, default_sender='a@x.com')
        with mail.connect() as conn:
            for _ in range(5):
                make_msg().send(conn)
        assert [len(h.sent) for h in smtp.instances] == [2, 2, 1]
        assert all(h.quit_called for h in smtp.instances)


class TestSuppress:
    def test_suppressed_never_connects(self, smtp):
        Mail(server='s', suppress=True, default_sender='a@x.com').send(make_msg())
        assert smtp.instances == []

    def test_suppressed_still_validates(self, smtp):
        with pytest.raises(BadHeaderError):
            Mail(server='s', suppress=True, default_sender='a@x.com').send(
                make_msg(subject='x\ny')
            )


class TestSignal:
    def test_signal_without_app_context(self, smtp, mail):
        received = []

        def receiver(message, app):
            received.append((message, app))

        msg = make_msg()
        with email_dispatched.connected_to(receiver):
            mail.send(msg)
        assert received == [(msg, None)]

    def test_signal_with_app_context(self, smtp, mail):
        app = Flask(__name__)
        received = []

        def receiver(message, app):
            received.append(app)

        with app.app_context(), email_dispatched.connected_to(receiver):
            mail.send(make_msg())
        assert received == [app]

    def test_signal_sent_when_suppressed(self, smtp):
        received = []
        mail = Mail(server='s', suppress=True, default_sender='a@x.com')
        with email_dispatched.connected_to(lambda m, app: received.append(m)):
            mail.send(make_msg())
        assert len(received) == 1

    def test_flask_mail_style_receiver_signature(self, smtp, mail):
        # Flask-Mail receivers are written as f(message, app); a receiver with
        # that exact signature must not raise.
        calls = []

        @email_dispatched.connect
        def strict(message, app):
            calls.append(1)

        try:
            mail.send(make_msg())
        finally:
            email_dispatched.disconnect(strict)
        assert calls == [1]
