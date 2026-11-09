from __future__ import annotations

import pytest
from email.header import decode_header, make_header

from flask_ezmail.utils import (
    FlaskMailUnicodeDecodeError,
    _has_newline,
    force_text,
    sanitize_address,
    sanitize_addresses,
    sanitize_subject,
)


def decode(value: str) -> str:
    return str(make_header(decode_header(value)))


class TestForceText:
    def test_str_passthrough(self):
        s = 'héllo'
        assert force_text(s) is s

    def test_bytes_decoded(self):
        assert force_text('héllo'.encode()) == 'héllo'

    def test_bytearray_decoded(self):
        assert force_text(bytearray(b'abc')) == 'abc'

    def test_bytes_with_encoding(self):
        assert force_text('héllo'.encode('latin-1'), encoding='latin-1') == 'héllo'

    def test_bad_bytes_raise_custom_error(self):
        with pytest.raises(FlaskMailUnicodeDecodeError) as exc:
            force_text(b'\xff\xfe\xfa')
        assert exc.value.obj == b'\xff\xfe\xfa'
        assert 'You passed in' in str(exc.value)

    def test_errors_replace(self):
        assert force_text(b'a\xffb', errors='replace') == 'a�b'

    def test_non_string_objects(self):
        assert force_text(42) == '42'
        assert force_text(None) == 'None'

    def test_exception_does_not_hit_strings_only(self):
        # Previously referenced an undefined ``strings_only`` name.
        assert force_text(ValueError('boom')) == 'boom'

    def test_lazy_string(self):
        class Lazy:
            def __str__(self):
                return 'lazy'

        assert force_text(Lazy()) == 'lazy'


class TestSanitize:
    def test_subject_ascii_untouched(self):
        assert sanitize_subject('Hello') == 'Hello'

    def test_subject_unicode_encoded(self):
        result = sanitize_subject('Héllo')
        assert result.startswith('=?utf-8?')

    def test_address_plain(self):
        assert sanitize_address('a@example.com') == 'a@example.com'

    def test_address_with_name(self):
        # Display names are always RFC 2047 encoded (inherited Flask-Mail behaviour).
        result = sanitize_address('Alice <a@example.com>')
        assert decode(result) == 'Alice <a@example.com>'

    def test_address_tuple(self):
        assert decode(sanitize_address(('Alice', 'a@example.com'))) == 'Alice <a@example.com>'

    def test_address_unicode_name(self):
        result = sanitize_address('Ålice <a@example.com>')
        assert result.endswith('<a@example.com>')
        assert '=?utf-8?' in result

    def test_address_idn_domain(self):
        assert sanitize_address('user@exämple.com') == 'user@xn--exmple-cua.com'

    def test_addresses(self):
        assert [decode(a) for a in sanitize_addresses(['a@x.com', ('B', 'b@x.com')])] == [
            'a@x.com',
            'B <b@x.com>',
        ]


class TestHasNewline:
    @pytest.mark.parametrize('value', ['a\nb', 'a\rb', ('Name\n', 'a@x.com')])
    def test_true(self, value):
        assert _has_newline(value)

    @pytest.mark.parametrize('value', [None, '', 'abc', ('Name', 'a@x.com')])
    def test_false(self, value):
        assert not _has_newline(value)
