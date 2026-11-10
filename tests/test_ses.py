from __future__ import annotations

import smtplib

import boto3
import pytest
from botocore.stub import ANY, Stubber
from flask import Flask

from flask_ezmail import Mail, Message
from flask_ezmail.providers.ses import (
    CONFIGURATION_SET_KEY,
    PROFILE_KEY,
    REGION_KEY,
    SESConnection,
    SESFakeSMTP,
    SESSendError,
)


@pytest.fixture
def ses_client():
    client = boto3.client(
        'sesv2',
        region_name='us-east-1',
        aws_access_key_id='testing',
        aws_secret_access_key='testing',
    )
    with Stubber(client) as stubber:
        yield client, stubber
        stubber.assert_no_pending_responses()


def test_defaults_without_app_context():
    host = SESFakeSMTP()
    assert host.region_name is None
    assert host.profile_name is None
    assert host.configuration_set is None


def test_settings_from_app_config():
    app = Flask(__name__)
    app.config.update({
        REGION_KEY: 'ca-central-1',
        PROFILE_KEY: 'mail',
        CONFIGURATION_SET_KEY: 'tracking',
    })
    with app.app_context():
        host = SESFakeSMTP()
    assert host.region_name == 'ca-central-1'
    assert host.profile_name == 'mail'
    assert host.configuration_set == 'tracking'


def test_explicit_args_override_config():
    app = Flask(__name__)
    app.config[REGION_KEY] = 'ca-central-1'
    with app.app_context():
        assert SESFakeSMTP(region_name='eu-west-1').region_name == 'eu-west-1'


def test_client_is_lazy_and_uses_region(monkeypatch):
    monkeypatch.setenv('AWS_ACCESS_KEY_ID', 'testing')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY', 'testing')
    host = SESFakeSMTP(region_name='eu-west-1')
    assert host._client is None
    client = host.client
    assert client is host.client
    assert client.meta.service_model.service_name == 'sesv2'
    assert client.meta.region_name == 'eu-west-1'
    host.quit()
    assert host._client is None


def test_sendmail_uses_raw_content_and_envelope(ses_client):
    client, stubber = ses_client
    stubber.add_response(
        'send_email',
        {'MessageId': 'abc-123'},
        {
            'FromEmailAddress': 'a@x.com',
            'Destination': {'ToAddresses': ['b@x.com', 'hidden@x.com']},
            'Content': {'Raw': {'Data': b'raw-mime'}},
        },
    )
    host = SESFakeSMTP(client=client)
    assert host.sendmail('a@x.com', ['b@x.com', 'hidden@x.com'], b'raw-mime') == {}
    assert host.last_message_id == 'abc-123'


def test_sendmail_includes_configuration_set(ses_client):
    client, stubber = ses_client
    stubber.add_response(
        'send_email',
        {'MessageId': 'id'},
        {
            'FromEmailAddress': 'a@x.com',
            'Destination': {'ToAddresses': ['b@x.com']},
            'Content': {'Raw': {'Data': b'm'}},
            'ConfigurationSetName': 'tracking',
        },
    )
    SESFakeSMTP(client=client, configuration_set='tracking').sendmail('a@x.com', ['b@x.com'], b'm')


def test_sendmail_wraps_client_errors(ses_client):
    client, stubber = ses_client
    stubber.add_client_error(
        'send_email',
        service_error_code='MessageRejected',
        service_message='Email address is not verified.',
        http_status_code=400,
    )
    host = SESFakeSMTP(client=client)
    with pytest.raises(SESSendError, match='MessageRejected') as info:
        host.sendmail('a@x.com', ['b@x.com'], b'm')
    assert isinstance(info.value, smtplib.SMTPException)
    assert info.value.code == 'MessageRejected'
    assert info.value.message == 'Email address is not verified.'
    assert info.value.__cause__ is not None


def test_debug_output(ses_client, capsys):
    client, stubber = ses_client
    stubber.add_response('send_email', {'MessageId': 'dbg'}, None)
    host = SESFakeSMTP(client=client)
    host.set_debuglevel(1)
    host.sendmail('a@x.com', ['b@x.com'], b'm')
    assert 'dbg' in capsys.readouterr().err


def test_connection_sends_message_with_bcc(ses_client, monkeypatch):
    client, stubber = ses_client
    stubber.add_response(
        'send_email',
        {'MessageId': 'm-1'},
        {
            'FromEmailAddress': 'a@x.com',
            'Destination': {'ToAddresses': ANY},
            'Content': {'Raw': {'Data': ANY}},
        },
    )
    monkeypatch.setattr(
        SESConnection, 'configure_host', lambda self: SESFakeSMTP(client=client)
    )

    sent = []
    original = SESFakeSMTP.sendmail

    def spy(self, from_addr, to_addrs, msg, *args):
        sent.append((from_addr, sorted(to_addrs), msg))
        return original(self, from_addr, to_addrs, msg, *args)

    monkeypatch.setattr(SESFakeSMTP, 'sendmail', spy)

    mail = Mail(default_sender='a@x.com')
    msg = Message('Hi', recipients=['b@x.com'], bcc=['hidden@x.com'], body='hello')
    with Flask(__name__).app_context(), SESConnection(mail) as conn:
        msg.send(conn)
        assert conn.host.last_message_id == 'm-1'

    from_addr, to_addrs, raw = sent[0]
    assert from_addr == 'a@x.com'
    assert to_addrs == ['b@x.com', 'hidden@x.com']
    assert b'Subject: Hi' in raw
    assert b'hidden@x.com' not in raw


def test_connection_configures_host():
    mail = Mail(debug=True, default_sender='a@x.com')
    app = Flask(__name__)
    app.config[REGION_KEY] = 'us-west-2'
    with app.app_context(), SESConnection(mail) as conn:
        assert isinstance(conn.host, SESFakeSMTP)
        assert conn.host.debuglevel == 1
        assert conn.host.region_name == 'us-west-2'


def test_suppressed_connection_has_no_host():
    mail = Mail(suppress=True, default_sender='a@x.com')
    with SESConnection(mail) as conn:
        assert conn.host is None
