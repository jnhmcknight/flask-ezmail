# Flask-EZMail-NG

Flask-EZMail-NG is easier email for Flask.

It is a maintained fork of [Flask-EZMail](https://github.com/JeffVandrewJr/flask-ezmail), which is itself a fork of Flask-Mail. It keeps a high level of compatibility with Flask-Mail, so very little code needs to change to switch from one to the other.

Flask-Mail is a convenient wrapper for `smtplib`, but it requires SMTP settings to be loaded when the app is created. If your users enter SMTP settings after app creation (for example through a web-based admin panel while the app is running), Flask-Mail needs workarounds.

Flask-EZMail-NG is designed to be flexible. You can load SMTP settings at app creation like you would with Flask-Mail, or at any later time. Settings live on the `Mail` object itself rather than on the Flask app, so a `Mail` can be created on the fly, pickled, or stored as a database model, and it can send without an app context (from a Celery task or a script, for example).

Requires Python 3.10+.

## Installation

The package is published as `flask-ezmail-ng`, but it is imported as `flask_ezmail`:

```bash
pip install flask-ezmail-ng
# or
uv add flask-ezmail-ng
```

```python
from flask_ezmail import Mail, Message
```

## Creating a Mail object

### From the Flask config

```python
# app/__init__.py
from flask import Flask
from flask_ezmail import Mail

mail = Mail()

def create_app():
    app = Flask(__name__)
    app.config.from_object('config')
    mail.init_app(app)
    return app
```

`mail.init_app(app)` fills in any setting you did not pass to `Mail(...)` from these config keys:

| Config key | Default |
|---|---|
| `FLASK_MAIL_CONNECTION_CLASS` | `'smtp'` (see [Amazon SES](#amazon-ses)) |
| `FLASK_MAIL_SERVER` | required for SMTP: `ValueError` if missing |
| `FLASK_MAIL_PORT` | `None` (smtplib's default: 25, or 465 for SSL) |
| `FLASK_MAIL_USERNAME` | `None` |
| `FLASK_MAIL_PASSWORD` | `None` |
| `FLASK_MAIL_USE_TLS` | `False` |
| `FLASK_MAIL_USE_SSL` | `False` |
| `FLASK_MAIL_DEFAULT_SENDER` | `None` |
| `FLASK_MAIL_MAX_EMAILS` | `None` (no limit per connection) |
| `FLASK_MAIL_SUPPRESS` | `app.testing` |
| `FLASK_MAIL_DEBUG` | `app.debug` |

Arguments passed to `Mail(...)` explicitly always win over the config, including `False` values:

```python
mail = Mail(use_tls=False)   # stays False even if FLASK_MAIL_USE_TLS=True
mail.init_app(app)
```

The extension registers itself as `app.extensions['ezmail']`.

### Directly, without a Flask app

```python
from flask_ezmail import Mail

mail = Mail(
    server='smtp.example.com',
    username='user',
    password='secret',
    port=587,
    use_tls=True,
    default_sender='noreply@example.com',
)
```

### At runtime, from user input

Say your users fill out a form in an admin panel to set SMTP settings after the app has started:

```python
from app.forms import EmailSetupForm
from flask_ezmail import Mail

@app.route('/emailsetup', methods=['GET', 'POST'])
def email_setup():
    form = EmailSetupForm()

    # ... render the form, accept POST data, etc.

    mail = Mail(
        server=form.server.data,
        username=form.username.data,
        password=form.password.data,
        port=form.port.data,
        use_tls=True,
        default_sender=form.default_sender.data,
    )
```

You'll probably want to keep that object for use elsewhere in your app. Two options:

1. Pickle it and save it to Redis:

    ```python
    import pickle

    # assumes redis is set up in app/__init__.py
    current_app.redis.set('mail', pickle.dumps(mail))
    ```

2. With Flask-SQLAlchemy, make a model that inherits from `Mail` and store it in your database:

    ```python
    # app/models.py
    from flask_ezmail import Mail

    class Email(Mail, db.Model):
        __table_args__ = {'extend_existing': True}
        id = db.Column(db.Integer, primary_key=True)
        server = db.Column(db.String(128))
        port = db.Column(db.Integer)
        username = db.Column(db.String(128))
        password = db.Column(db.String(128))
        default_sender = db.Column(db.String(128))
        use_tls = db.Column(db.Boolean)
        use_ssl = db.Column(db.Boolean)
        debug = db.Column(db.Boolean)
        max_emails = db.Column(db.Integer)
        suppress = db.Column(db.Boolean)
    ```

    Then fetch it when you need it, and change settings on the fly:

    ```python
    mail = Email.query.first()
    if mail is not None:
        mail.server = 'example.net'
        db.session.commit()
    ```

    Columns left `NULL` are filled from the Flask config if you call `mail.init_app(app)`.

## Sending email

`Message` works the same way as in Flask-Mail:

```python
from flask_ezmail import Message

msg = Message(
    'Test Message',
    sender='sender@example.com',   # optional when default_sender is set
    recipients=['recipient@example.com'],
    body='Hello!',
)
mail.send(msg)

# or the shortcut:
mail.send_message('Test Message', recipients=['recipient@example.com'], body='Hello!')
```

**HTML email:** if you pass `html` without `body`, a plain-text version is generated from the HTML automatically (with [inscriptis](https://github.com/weblyzard/inscriptis)):

```python
msg = Message('Welcome', recipients=['a@example.com'], html='<h1>Hi!</h1><p>Thanks for joining.</p>')
```

**Attachments:** if you leave out the content type, it is guessed from the filename (falling back to `application/octet-stream`):

```python
with open('report.pdf', 'rb') as fp:
    msg.attach('report.pdf', data=fp.read())                     # application/pdf
msg.attach('data.bin', 'application/octet-stream', b'\x00\x01')  # explicit type
msg.attach('logo.png', data=png_bytes, disposition='inline', headers={'Content-ID': '<logo>'})
```

**Bulk sending:** use `connect()` to reuse one SMTP connection. If `max_emails` is set, the connection is reopened after that many messages:

```python
with mail.connect() as conn:
    for user in users:
        conn.send(Message('Newsletter', recipients=[user.email], body='...'))
```

## Amazon SES

Instead of SMTP, mail can go through the SES v2 API with boto3, so credentials come from the standard AWS chain (instance profiles, ECS task roles, EKS pod identity, Lambda roles, `AWS_PROFILE` / SSO) and there are no SMTP passwords to store or rotate.

```bash
pip install 'flask-ezmail-ng[ses]'
```

```python
FLASK_MAIL_CONNECTION_CLASS = 'ses'
FLASK_MAIL_DEFAULT_SENDER = 'noreply@example.com'

# All optional:
FLASK_MAIL_SES_REGION = 'us-east-1'            # else boto3's normal region lookup
FLASK_MAIL_SES_PROFILE = 'mail'                # else the default credential chain
FLASK_MAIL_SES_CONFIGURATION_SET = 'tracking'  # attached to every message
```

`FLASK_MAIL_SERVER` and the other SMTP settings are not needed. The role needs `ses:SendEmail` and `ses:SendRawEmail` on the sending identity (and on the configuration set, if one is used). Bcc recipients are delivered without appearing in the headers. A rejected send raises `flask_ezmail.providers.ses.SESSendError`, a subclass of `smtplib.SMTPException`.

`connection_class` (or `FLASK_MAIL_CONNECTION_CLASS`) also accepts a `Connection` subclass or an import path such as `'myapp.mail:MyConnection'`, for custom providers:

```python
mail = Mail(connection_class='ses')
```

## Testing

When `app.testing` is true (or `FLASK_MAIL_SUPPRESS=True`), messages are validated but never actually sent.

`record_messages()` captures messages and suppresses sending for the duration of the block:

```python
def test_signup_sends_email(app, client):
    with mail.record_messages() as outbox:
        client.post('/signup', data={'email': 'a@example.com'})

    assert len(outbox) == 1
    assert outbox[0].subject == 'Welcome'
```

Recording is scoped to the current thread or async task and to that `Mail` object, so tests running in parallel don't see each other's messages. `mail.suppress` is never modified. Messages sent from threads you start yourself inside the block are not captured.

## Signals

`email_dispatched` fires for every message, including suppressed ones. Receivers use the same signature as Flask-Mail: the message is the sender, and `app` is the current Flask app (or `None` outside an app context):

```python
from flask_ezmail import email_dispatched

@email_dispatched.connect
def log_message(message, app):
    print(f'Sent {message.subject!r} to {message.recipients}')
```

## Differences from Flask-Mail

- Config keys use the `FLASK_MAIL_` prefix (`FLASK_MAIL_SERVER`, not `MAIL_SERVER`).
- `Mail` takes SMTP settings as constructor arguments; use `Mail()` + `init_app(app)` instead of `Mail(app)`.
- Sending does not require an app context.
- The default sender is applied when a message is sent, not when it is created.
- One `Mail` holds one set of settings, rather than one per app.

## Development

```bash
uv sync
uv run pytest
uv run mypy
```
