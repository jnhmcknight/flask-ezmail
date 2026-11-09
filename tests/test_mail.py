from __future__ import annotations

import asyncio
import pickle
import threading

import pytest
from flask import Flask

from flask_ezmail import Mail, Message


def make_msg(**kwargs) -> Message:
    kwargs.setdefault('recipients', ['b@x.com'])
    kwargs.setdefault('body', 'hello')
    kwargs.setdefault('subject', 'Hi')
    return Message(**kwargs)


class TestInitApp:
    def test_reads_config(self):
        app = Flask(__name__)
        app.config.update(
            FLASK_MAIL_SERVER='smtp.cfg',
            FLASK_MAIL_USERNAME='user',
            FLASK_MAIL_PASSWORD='pw',
            FLASK_MAIL_PORT=587,
            FLASK_MAIL_USE_TLS=True,
            FLASK_MAIL_USE_SSL=False,
            FLASK_MAIL_DEFAULT_SENDER='cfg@x.com',
            FLASK_MAIL_MAX_EMAILS=10,
            FLASK_MAIL_SUPPRESS=True,
            FLASK_MAIL_DEBUG=True,
        )
        mail = Mail()
        mail.init_app(app)
        assert mail.server == 'smtp.cfg'
        assert mail.username == 'user'
        assert mail.password == 'pw'
        assert mail.port == 587
        assert mail.use_tls is True
        assert mail.use_ssl is False
        assert mail.default_sender == 'cfg@x.com'
        assert mail.max_emails == 10
        assert mail.suppress is True
        assert mail.debug is True

    def test_defaults(self, app):
        mail = Mail()
        mail.init_app(app)
        assert mail.use_tls is False
        assert mail.use_ssl is False
        assert mail.suppress is False
        assert mail.debug is False
        assert mail.port is None
        assert mail.max_emails is None

    def test_missing_server_raises(self):
        with pytest.raises(ValueError, match='FLASK_MAIL_SERVER'):
            Mail().init_app(Flask(__name__))

    def test_explicit_server_without_config(self):
        mail = Mail(server='explicit')
        mail.init_app(Flask(__name__))
        assert mail.server == 'explicit'

    def test_registers_extension(self, app):
        mail = Mail()
        mail.init_app(app)
        assert app.extensions['ezmail'] is mail

    def test_does_not_store_app(self, app):
        mail = Mail()
        mail.init_app(app)
        assert not hasattr(mail, 'flask_app')

    def test_picklable_after_init_app(self, app):
        mail = Mail()
        mail.init_app(app)
        clone = pickle.loads(pickle.dumps(mail))
        assert clone.server == 'smtp.example.com'


class TestExplicitArgsWin:
    @pytest.fixture
    def app(self) -> Flask:
        app = Flask(__name__)
        app.debug = True
        app.testing = True
        app.config.update(
            FLASK_MAIL_SERVER='smtp.cfg',
            FLASK_MAIL_USERNAME='cfg-user',
            FLASK_MAIL_PASSWORD='cfg-pw',
            FLASK_MAIL_PORT=587,
            FLASK_MAIL_USE_TLS=True,
            FLASK_MAIL_USE_SSL=True,
            FLASK_MAIL_DEFAULT_SENDER='cfg@x.com',
            FLASK_MAIL_MAX_EMAILS=10,
            FLASK_MAIL_SUPPRESS=True,
            FLASK_MAIL_DEBUG=True,
        )
        return app

    def test_truthy_explicit_values(self, app):
        mail = Mail(
            server='smtp.arg',
            username='arg-user',
            password='arg-pw',
            port=2525,
            default_sender='arg@x.com',
            max_emails=3,
        )
        mail.init_app(app)
        assert mail.server == 'smtp.arg'
        assert mail.username == 'arg-user'
        assert mail.password == 'arg-pw'
        assert mail.port == 2525
        assert mail.default_sender == 'arg@x.com'
        assert mail.max_emails == 3

    @pytest.mark.parametrize('attr', ['use_tls', 'use_ssl', 'suppress', 'debug'])
    def test_explicit_false_not_overridden(self, app, attr):
        mail = Mail(**{attr: False})
        mail.init_app(app)
        assert getattr(mail, attr) is False

    def test_explicit_debug_zero(self, app):
        mail = Mail(debug=0)
        mail.init_app(app)
        assert mail.debug == 0

    def test_unset_values_still_filled(self, app):
        mail = Mail(use_tls=False)
        mail.init_app(app)
        assert mail.use_ssl is True
        assert mail.suppress is True

    def test_attribute_set_before_init_app(self, app):
        # Mimics a SQLAlchemy model row loaded without calling __init__.
        mail = Mail.__new__(Mail)
        mail.server = 'db.server'
        mail.use_tls = False
        mail.init_app(app)
        assert mail.server == 'db.server'
        assert mail.use_tls is False
        assert mail.port == 587


class TestSuppressionConfig:
    def test_testing_app_suppresses_by_default(self, app, smtp):
        app.testing = True
        mail = Mail()
        mail.init_app(app)
        assert mail.suppress is True
        mail.send(make_msg())
        assert smtp.instances == []

    def test_config_suppress_without_testing(self, app, smtp):
        app.config['FLASK_MAIL_SUPPRESS'] = True
        mail = Mail()
        mail.init_app(app)
        assert mail.suppress is True
        mail.send(make_msg())
        assert smtp.instances == []

    def test_config_false_overrides_testing(self, app, smtp):
        app.testing = True
        app.config['FLASK_MAIL_SUPPRESS'] = False
        mail = Mail()
        mail.init_app(app)
        assert mail.suppress is False
        mail.send(make_msg())
        assert len(smtp.instances) == 1

    def test_not_testing_not_suppressed(self, app, smtp):
        mail = Mail()
        mail.init_app(app)
        assert mail.suppress is False
        mail.send(make_msg())
        assert len(smtp.instances) == 1

    def test_debug_follows_app_debug(self, app):
        app.debug = True
        mail = Mail()
        mail.init_app(app)
        assert mail.debug is True


class TestRecordMessages:
    def test_records_and_suppresses(self, smtp, mail):
        with mail.record_messages() as outbox:
            mail.send(make_msg())
            mail.send_message('Other', recipients=['c@x.com'], body='y')
        assert [m.subject for m in outbox] == ['Hi', 'Other']
        assert smtp.instances == []

    def test_does_not_touch_suppress_attribute(self, smtp, mail):
        assert mail.suppress is None
        with mail.record_messages():
            assert mail.suppress is None
        assert mail.suppress is None

    def test_sends_again_after_block(self, smtp, mail):
        with mail.record_messages():
            mail.send(make_msg())
        mail.send(make_msg())
        assert len(smtp.instances) == 1

    def test_restored_after_exception(self, smtp, mail):
        with pytest.raises(RuntimeError):
            with mail.record_messages():
                raise RuntimeError
        mail.send(make_msg())
        assert len(smtp.instances) == 1

    def test_nested(self, smtp, mail):
        with mail.record_messages() as outer:
            mail.send(make_msg())
            with mail.record_messages() as inner:
                mail.send(make_msg())
            mail.send(make_msg())
        assert len(outer) == 3
        assert len(inner) == 1
        assert smtp.instances == []

    def test_only_records_own_mail(self, smtp, mail):
        other = Mail(server='other', default_sender='o@x.com')
        with mail.record_messages() as outbox:
            other.send(make_msg())
        assert outbox == []
        assert len(smtp.instances) == 1

    def test_through_flask_view(self, smtp, app):
        mail = Mail()
        mail.init_app(app)

        @app.route('/send')
        def send():
            mail.send_message('From view', recipients=['b@x.com'], body='x')
            return 'ok'

        with mail.record_messages() as outbox:
            assert app.test_client().get('/send').data == b'ok'
        assert [m.subject for m in outbox] == ['From view']
        assert smtp.instances == []

    def test_async_tasks_inherit_recording(self, smtp, mail):
        async def main():
            with mail.record_messages() as outbox:
                await asyncio.gather(
                    asyncio.to_thread(mail.send, make_msg()),
                    asyncio.create_task(asyncio.sleep(0, mail.send(make_msg()))),
                )
            return outbox

        assert len(asyncio.run(main())) == 2
        assert smtp.instances == []

    def test_thread_isolation(self, smtp, mail):
        """A recording in one thread must neither suppress nor capture sends
        in another thread, and concurrent recordings must not clobber each
        other (the old implementation toggled the shared ``self.suppress``)."""
        n = 8
        barrier = threading.Barrier(n + 1)
        outboxes: dict[int, list[Message]] = {}
        errors: list[BaseException] = []

        def recorder(i: int) -> None:
            try:
                with mail.record_messages() as outbox:
                    barrier.wait()  # every recorder is inside its block
                    mail.send(make_msg(subject=f'rec-{i}'))
                    barrier.wait()  # wait for the free sender
                outboxes[i] = outbox
            except BaseException as e:  # pragma: no cover
                errors.append(e)

        threads = [threading.Thread(target=recorder, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        barrier.wait()
        mail.send(make_msg(subject='free'))  # sent while all recorders active
        barrier.wait()
        for t in threads:
            t.join()

        assert not errors
        for i in range(n):
            assert [m.subject for m in outboxes[i]] == [f'rec-{i}']
        assert len(smtp.instances) == 1
        assert mail.suppress is None
