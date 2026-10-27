"""Auth validation tests."""

from __future__ import annotations

import pytest

from abw_mcp.auth import AuthError, verify_token


def test_verify_token_valid(settings_factory, token_factory, patched_jwks):
    settings = settings_factory("research")
    token = token_factory(settings, roles=["Research.Read"], oid="oid-priya")
    caller = verify_token(token, settings)
    assert caller.oid == "oid-priya"
    assert caller.roles == ("Research.Read",)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"aud": "wrong-aud"}, "bad_audience"),
        ({"tid": "wrong-tid"}, "bad_tenant"),
        ({"iss": "https://example.invalid/issuer"}, "bad_issuer"),
        ({"exp_delta": -120}, "expired"),
        ({"nbf_delta": 600}, "not_yet_valid"),
        ({"scopes": "Wrong.Scope"}, "missing_scope"),
        ({"azp": "rogue-client"}, "bad_azp"),
        ({"extra": {"idtyp": "app"}, "oid": "", "upn": "app"}, "app_only"),
    ],
)
def test_verify_token_matrix(settings_factory, token_factory, patched_jwks, overrides, expected):
    settings = settings_factory("research")
    token = token_factory(settings, roles=["Research.Read"], **overrides)
    with pytest.raises(AuthError) as exc:
        verify_token(token, settings)
    assert exc.value.reason_code == expected


def test_verify_token_garbage(settings_factory, patched_jwks):
    settings = settings_factory("research")
    with pytest.raises(AuthError) as exc:
        verify_token("not-a-jwt", settings)
    assert exc.value.reason_code == "bad_signature"
