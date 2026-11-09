from __future__ import annotations

import importlib
import pkgutil

import flask_ezmail


def test_public_api():
    for name in flask_ezmail.__all__:
        assert hasattr(flask_ezmail, name)


def test_all_modules_import():
    for mod in pkgutil.walk_packages(flask_ezmail.__path__, 'flask_ezmail.'):
        importlib.import_module(mod.name)


def test_py_typed_marker():
    from importlib.resources import files

    assert files('flask_ezmail').joinpath('py.typed').is_file()
