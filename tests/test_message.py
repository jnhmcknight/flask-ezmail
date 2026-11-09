from __future__ import annotations

import email
import warnings
from email import policy

import pytest

from flask_ezmail import Attachment, Message
from flask_ezmail.message import DEFAULT_CONTENT_TYPE, guess_content_type


def parse(msg: Message) -> email.message.EmailMessage:
    return email.message_from_bytes(msg.as_bytes(), policy=policy.default)


class TestBasics:
    def test_defaults(self):
        msg = Message()
        assert msg.subject == ''
        assert msg.recipients == []
        assert msg.cc == [] and msg.bcc == []
        assert msg.attachments == []
        assert msg.sender is None
        assert msg.msgId.startswith('<')

    def test_sender_tuple(self):
        msg = Message(sender=('Alice', 'a@example.com'))
        assert msg.sender == 'Alice <a@example.com>'

    def test_send_to_combines_and_dedupes(self):
        msg = Message(recipients=['a@x.com', 'b@x.com'], cc=['b@x.com'], bcc=['c@x.com'])
        assert msg.send_to == {'a@x.com', 'b@x.com', 'c@x.com'}

    def test_add_recipient(self):
        msg = Message(recipients=['a@x.com'])
        msg.add_recipient('b@x.com')
        assert msg.recipients == ['a@x.com', 'b@x.com']

    def test_str_and_bytes(self):
        msg = Message('Hi', sender='a@x.com', recipients=['b@x.com'], body='hello')
        assert 'hello' in str(msg)
        assert b'hello' in bytes(msg)


class TestBody:
    def test_plain_body(self):
        msg = Message(body='hello')
        assert msg.body == 'hello'

    def test_body_generated_from_html(self):
        msg = Message(html='<p>Hello <b>world</b></p>')
        assert msg.body is not None
        assert 'Hello world' in msg.body

    def test_explicit_body_wins_over_html(self):
        msg = Message(body='plain', html='<p>html</p>')
        assert msg.body == 'plain'

    def test_html_property(self):
        msg = Message(html='<p>x</p>')
        assert msg.alts == {'html': '<p>x</p>'}
        msg.html = None
        assert msg.alts == {}

    def test_html_from_alts_is_kept(self):
        # Passing html via alts must not be wiped by the html=None default.
        msg = Message(alts={'html': '<p>x</p>'})
        assert msg.html == '<p>x</p>'

    def test_alts_iterable(self):
        msg = Message(alts=[('html', '<p>x</p>')])
        assert msg.html == '<p>x</p>'


class TestMimeStructure:
    def test_plain_only(self):
        parsed = parse(Message(sender='a@x.com', recipients=['b@x.com'], body='hello'))
        assert parsed.get_content_type() == 'text/plain'
        assert parsed.get_content().strip() == 'hello'

    def test_empty_body_does_not_crash(self):
        parsed = parse(Message(sender='a@x.com', recipients=['b@x.com']))
        assert parsed.get_content_type() == 'text/plain'

    def test_html_alternative(self):
        parsed = parse(
            Message(sender='a@x.com', recipients=['b@x.com'], body='p', html='<b>h</b>')
        )
        assert parsed.get_content_type() == 'multipart/mixed'
        (alt,) = parsed.get_payload()
        assert alt.get_content_type() == 'multipart/alternative'
        types = [p.get_content_type() for p in alt.get_payload()]
        assert types == ['text/plain', 'text/html']

    def test_html_only_includes_generated_plain(self):
        parsed = parse(Message(sender='a@x.com', recipients=['b@x.com'], html='<p>Hi</p>'))
        plain = parsed.get_payload()[0].get_payload()[0]
        assert plain.get_content().strip() == 'Hi'

    def test_attachment_without_html(self):
        msg = Message(sender='a@x.com', recipients=['b@x.com'], body='see attached')
        msg.attach('data.bin', 'application/octet-stream', b'\x00\x01')
        parsed = parse(msg)
        assert parsed.get_content_type() == 'multipart/mixed'
        body, att = parsed.get_payload()
        assert body.get_content_type() == 'text/plain'
        assert att.get_filename() == 'data.bin'
        assert att.get_content() == b'\x00\x01'


class TestHeaders:
    def test_basic_headers(self):
        msg = Message(
            'Subject line',
            sender='Alice <a@x.com>',
            recipients=['b@x.com', 'c@x.com', 'b@x.com'],
            cc=['d@x.com'],
            reply_to='r@x.com',
            body='x',
            date=0,
            extra_headers={'X-Custom': 'yes'},
        )
        parsed = parse(msg)
        assert parsed['Subject'] == 'Subject line'
        assert parsed['From'] == 'Alice <a@x.com>'
        assert parsed['To'] == 'b@x.com, c@x.com'
        assert parsed['Cc'] == 'd@x.com'
        assert parsed['Reply-To'] == 'r@x.com'
        assert parsed['X-Custom'] == 'yes'
        assert parsed['Message-ID'] == msg.msgId
        assert parsed['Date'] is not None

    def test_bcc_not_in_headers(self):
        parsed = parse(Message(sender='a@x.com', recipients=['b@x.com'], bcc=['h@x.com']))
        assert parsed['Bcc'] is None
        assert 'h@x.com' not in str(parsed)

    def test_no_subject_header_when_empty(self):
        assert parse(Message(sender='a@x.com', recipients=['b@x.com']))['Subject'] is None

    def test_unicode_subject(self):
        parsed = parse(Message('Héllo wörld', sender='a@x.com', recipients=['b@x.com']))
        assert parsed['Subject'] == 'Héllo wörld'

    def test_charset(self):
        parsed = parse(
            Message(sender='a@x.com', recipients=['b@x.com'], body='x', charset='iso-8859-1')
        )
        assert parsed.get_content_charset() == 'iso-8859-1'

    def test_crlf_line_endings(self):
        raw = Message(sender='a@x.com', recipients=['b@x.com'], body='x').as_bytes()
        assert b'\r\n' in raw


class TestBadHeaders:
    @pytest.mark.parametrize(
        'kwargs',
        [
            {'subject': 'bad\nsubject'},
            {'subject': 'bad\r\nsubject'},
            {'subject': 'trailing\r\n'},
            {'subject': 'line\r\n\r\n folded'},
            {'subject': 'line\r\n '},
            {'sender': 'a@x.com\nBcc: evil@x.com'},
            {'reply_to': 'r@x.com\r\n'},
            {'recipients': ['b@x.com\n']},
        ],
    )
    def test_bad(self, kwargs):
        base = {'sender': 'a@x.com', 'recipients': ['b@x.com']}
        base.update(kwargs)
        assert Message(**base).has_bad_headers()

    @pytest.mark.parametrize('subject', ['fine', 'folded\r\n continued', 'tab\r\n\tfold'])
    def test_good(self, subject):
        assert not Message(subject, sender='a@x.com', recipients=['b@x.com']).has_bad_headers()

    def test_is_bad_headers_deprecated(self):
        msg = Message('ok', sender='a@x.com', recipients=['b@x.com'])
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            assert msg.is_bad_headers() is False
        assert any(issubclass(x.category, DeprecationWarning) for x in w)


class TestAttachments:
    @pytest.mark.parametrize(
        'filename,expected',
        [
            ('report.pdf', 'application/pdf'),
            ('photo.PNG', 'image/png'),
            ('notes.txt', 'text/plain'),
            ('page.html', 'text/html'),
            ('archive.unknownext', DEFAULT_CONTENT_TYPE),
            ('noextension', DEFAULT_CONTENT_TYPE),
            (None, DEFAULT_CONTENT_TYPE),
            ('', DEFAULT_CONTENT_TYPE),
        ],
    )
    def test_guess_content_type(self, filename, expected):
        assert guess_content_type(filename) == expected

    def test_attachment_guesses_type(self):
        assert Attachment('a.pdf').content_type == 'application/pdf'

    def test_explicit_type_wins(self):
        assert Attachment('a.pdf', 'text/plain').content_type == 'text/plain'

    def test_attachment_defaults(self):
        att = Attachment()
        assert att.content_type == DEFAULT_CONTENT_TYPE
        assert att.disposition == 'attachment'
        assert att.headers == {}

    def test_attach_without_content_type_builds(self):
        msg = Message(sender='a@x.com', recipients=['b@x.com'], body='x')
        msg.attach('report.pdf', data=b'%PDF-1.4')
        att = parse(msg).get_payload()[1]
        assert att.get_content_type() == 'application/pdf'
        assert att.get_content() == b'%PDF-1.4'

    def test_content_type_cleared_after_init_is_guessed(self):
        msg = Message(sender='a@x.com', recipients=['b@x.com'], body='x')
        msg.attach('photo.png', data=b'png')
        msg.attachments[0].content_type = None  # type: ignore[assignment]
        assert parse(msg).get_payload()[1].get_content_type() == 'image/png'

    def test_content_type_without_subtype(self):
        msg = Message(sender='a@x.com', recipients=['b@x.com'], body='x')
        msg.attach('x', 'application', b'data')
        assert parse(msg).get_payload()[1].get_content_type() == 'application/octet-stream'

    def test_inline_disposition_and_headers(self):
        msg = Message(sender='a@x.com', recipients=['b@x.com'], html='<img src="cid:logo">')
        msg.attach('logo.png', data=b'png', disposition='inline', headers={'Content-ID': '<logo>'})
        att = parse(msg).get_payload()[1]
        assert att.get_content_disposition() == 'inline'
        assert att['Content-ID'] == '<logo>'
        assert att.get_content_type() == 'image/png'

    def test_unicode_filename(self):
        msg = Message(sender='a@x.com', recipients=['b@x.com'], body='x')
        msg.attach('résumé.pdf', data=b'x')
        att = parse(msg).get_payload()[1]
        assert att.get_filename() == 'résumé.pdf'

    def test_ascii_attachments(self):
        msg = Message(sender='a@x.com', recipients=['b@x.com'], body='x', ascii_attachments=True)
        msg.attach('résumé   final.pdf', data=b'x')
        att = parse(msg).get_payload()[1]
        assert att.get_filename() == 'resume final.pdf'

    def test_attachments_list_in_constructor(self):
        msg = Message(
            sender='a@x.com',
            recipients=['b@x.com'],
            body='x',
            attachments=[Attachment('a.txt', data=b'1'), Attachment('b.csv', data=b'2')],
        )
        types = [p.get_content_type() for p in parse(msg).get_payload()[1:]]
        assert types == ['text/plain', 'text/csv']
