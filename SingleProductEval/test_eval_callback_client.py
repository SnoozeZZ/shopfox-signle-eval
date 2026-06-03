"""Tests for callback response parsing."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from SingleProductEval.eval_callback_client import _parse_callback_response


def test_parse_callback_code_zero():
    resp = MagicMock()
    resp.is_success = True
    resp.status_code = 200
    resp.json.return_value = {"code": 0, "message": "ok", "data": True}
    ok, err = _parse_callback_response(resp)
    assert ok is True
    assert err is None


def test_parse_callback_nonzero_code():
    resp = MagicMock()
    resp.is_success = True
    resp.status_code = 200
    resp.json.return_value = {"code": 1, "message": "fail", "data": False}
    ok, err = _parse_callback_response(resp)
    assert ok is False
    assert "code=1" in (err or "")
