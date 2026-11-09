from __future__ import annotations

from typing import Any

import pytest
from flask import Flask

from flask_ezmail import Mail


class FakeSMTP:
    """Stand-in for smtplib.SMTP / SMTP_SSL that records every call."""

    instances: list[FakeSMTP] = []

    def __init__(self, host: str = '', port: int = 0, ssl: bool = False) -> None:
        self.host = host
        self.port = port
        self.ssl = ssl
        self.debuglevel: int | None = None
        self.started_tls = False
        self.login_args: tuple[str, str] | None = None
        self.sent: list[tuple[Any, ...]] = []
        self.quit_called = False
        FakeSMTP.instances.append(self)

    def set_debuglevel(self, level: int) -> None:
        self.debuglevel = level

    def starttls(self) -> None:
        self.started_tls = True

    def login(self, username: str, password: str) -> None:
        self.login_args = (username, password)

    def sendmail(self, from_addr, to_addrs, msg, mail_options=(), rcpt_options=()):
        self.sent.append((from_addr, to_addrs, msg, mail_options, rcpt_options))
        return {}

    def quit(self) -> None:
        self.quit_called = True


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMTP]:
    FakeSMTP.instances = []
    monkeypatch.setattr('smtplib.SMTP', lambda host='', port=0: FakeSMTP(host, port))
    monkeypatch.setattr(
        'smtplib.SMTP_SSL', lambda host='', port=0: FakeSMTP(host, port, ssl=True)
    )
    return FakeSMTP


@pytest.fixture
def app() -> Flask:
    app = Flask(__name__)
    app.config.update(
        FLASK_MAIL_SERVER='smtp.example.com',
        FLASK_MAIL_DEFAULT_SENDER='sender@example.com',
    )
    return app


@pytest.fixture
def mail() -> Mail:
    return Mail(server='smtp.example.com', port=2525, default_sender='sender@example.com')
