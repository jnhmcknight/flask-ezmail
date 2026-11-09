from . import connection, mail, message
from .connection import BadHeaderError, Connection, email_dispatched
from .mail import Mail
from .message import Attachment, Message

name = 'flask_ezmail'

__all__ = [
    'Attachment',
    'BadHeaderError',
    'Connection',
    'Mail',
    'Message',
    'connection',
    'email_dispatched',
    'mail',
    'message',
]
