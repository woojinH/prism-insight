import atexit
import sys
import textwrap
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

CONFIG_DIR = PROJECT_ROOT / "trading" / "config"
CONFIG_FILE = CONFIG_DIR / "kis_devlp.yaml"
_CREATED_TEST_CONFIG = False

if not CONFIG_FILE.exists():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        textwrap.dedent(
            """
            my_agent: test-agent
            default_mode: demo
            auto_trading: true
            default_product_code: "01"
            default_unit_amount: 100000
            default_unit_amount_usd: 250
            my_app: PSREALKEY
            my_sec: real-secret
            paper_app: PSVTTESTKEY
            paper_sec: paper-secret
            my_htsid: test-user
            prod: https://example.com
            vps: https://example.com
            ops: wss://example.com
            vops: wss://example.com
            accounts:
              - name: bootstrap-demo
                mode: demo
                account: "12345678"
                product: "01"
                market: all
                primary: true
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    _CREATED_TEST_CONFIG = True


if _CREATED_TEST_CONFIG:
    atexit.register(lambda: CONFIG_FILE.unlink(missing_ok=True))

from trading import kis_auth as ka


def _patch_cfg(monkeypatch, cfg):
    monkeypatch.setattr(ka, "_cfg", cfg, raising=False)
    monkeypatch.setattr(
        ka,
        "DEFAULT_PRODUCT_CODE",
        str(cfg.get("default_product_code", cfg.get("my_prod", "01"))),
        raising=False,
    )
    monkeypatch.setattr(
        ka,
        "DEFAULT_BUY_AMOUNT_KRW",
        int(cfg.get("default_unit_amount", 0) or 0),
        raising=False,
    )
    monkeypatch.setattr(
        ka,
        "DEFAULT_BUY_AMOUNT_USD",
        float(cfg.get("default_unit_amount_usd", 0) or 0),
        raising=False,
    )


def _base_cfg():
    return {
        "default_product_code": "01",
        "default_unit_amount": 100000,
        "default_unit_amount_usd": 250.0,
        "my_prod": "01",
    }


def test_get_configured_accounts_normalizes_filters_and_preserves_overrides(monkeypatch):
    cfg = _base_cfg()
    cfg["accounts"] = [
        {
            "name": "kr-demo",
            "mode": "demo",
            "account": "11112222",
            "product": "01",
            "market": "kr",
            "buy_amount_krw": 77777,
        },
        {
            "name": "us-demo-primary",
            "mode": "demo",
            "account": "33334444",
            "product": "01",
            "market": "us",
            "primary": True,
            "buy_amount_usd": 123.45,
        },
        {
            "name": "us-real",
            "mode": "real",
            "account": "55556666",
            "product": "01",
            "market": "us",
        },
    ]
    _patch_cfg(monkeypatch, cfg)

    us_demo_accounts = ka.get_configured_accounts(svr="demo", market="us")

    assert [account["name"] for account in us_demo_accounts] == ["us-demo-primary"]
    assert us_demo_accounts[0]["svr"] == "vps"
    assert us_demo_accounts[0]["account_key"] == "vps:33334444:01"
    assert us_demo_accounts[0]["primary"] is True
    assert us_demo_accounts[0]["buy_amount_usd"] == 123.45


def test_get_configured_accounts_does_not_cross_market_fallback(monkeypatch):
    cfg = _base_cfg()
    cfg["accounts"] = [
        {
            "name": "kr-demo",
            "mode": "demo",
            "account": "11112222",
            "product": "01",
            "market": "kr",
        }
    ]
    _patch_cfg(monkeypatch, cfg)

    assert ka.get_configured_accounts(svr="demo", market="us") == []


def test_get_configured_accounts_supports_legacy_fallback(monkeypatch):
    cfg = _base_cfg()
    cfg.update(
        {
            "my_acct_stock": "87654321",
            "my_paper_stock": "12345678",
            "my_prod": "01",
        }
    )
    _patch_cfg(monkeypatch, cfg)

    with pytest.warns(DeprecationWarning):
        accounts = ka.get_configured_accounts()

    assert [account["name"] for account in accounts] == [
        "legacy-real-stock",
        "legacy-demo-stock",
    ]
    assert accounts[0]["market"] == "all"
    assert accounts[0]["primary"] is True
    assert accounts[0]["buy_amount_krw"] == 100000
    assert accounts[0]["buy_amount_usd"] == 250.0
    assert accounts[1]["account_key"] == "vps:12345678:01"


def test_resolve_account_prefers_primary_then_first(monkeypatch):
    cfg = _base_cfg()
    cfg["accounts"] = [
        {
            "name": "first-us",
            "mode": "demo",
            "account": "10000001",
            "product": "01",
            "market": "us",
        },
        {
            "name": "primary-us",
            "mode": "demo",
            "account": "10000002",
            "product": "01",
            "market": "us",
            "primary": True,
        },
    ]
    _patch_cfg(monkeypatch, cfg)

    primary = ka.resolve_account(svr="vps", market="us")
    assert primary["name"] == "primary-us"

    cfg["accounts"][1]["primary"] = False
    _patch_cfg(monkeypatch, cfg)

    fallback = ka.resolve_account(svr="vps", market="us")
    assert fallback["name"] == "first-us"


def test_resolve_account_supports_account_key(monkeypatch):
    cfg = _base_cfg()
    cfg["accounts"] = [
        {
            "name": "acct-a",
            "mode": "demo",
            "account": "11110000",
            "product": "01",
            "market": "kr",
        },
        {
            "name": "acct-b",
            "mode": "demo",
            "account": "22220000",
            "product": "01",
            "market": "kr",
        },
    ]
    _patch_cfg(monkeypatch, cfg)

    resolved = ka.resolve_account(
        svr="vps",
        product="01",
        account_key="vps:22220000:01",
        market="kr",
    )

    assert resolved["name"] == "acct-b"
    assert resolved["account"] == "22220000"


def test_get_configured_accounts_rejects_unknown_mode(monkeypatch):
    _patch_cfg(monkeypatch, _base_cfg())

    with pytest.raises(ValueError, match="Unknown server mode"):
        ka.get_configured_accounts(svr="staging")


def test_get_configured_accounts_rejects_too_many_accounts(monkeypatch):
    cfg = _base_cfg()
    cfg["accounts"] = [
        {
            "name": f"acct-{index}",
            "mode": "demo",
            "account": f"{10000000 + index}",
            "product": "01",
            "market": "kr",
        }
        for index in range(11)
    ]
    _patch_cfg(monkeypatch, cfg)

    with pytest.raises(ValueError, match="Too many accounts configured"):
        ka.get_configured_accounts()


def test_auth_rereads_token_under_issue_lock_before_requesting(monkeypatch, tmp_path):
    # 2026-11-09 13:57: two cron jobs saw the expired token together; the second hit EGW00133 (1/min).
    cfg = {**_base_cfg(), "paper_app": "PSVTTESTKEY", "paper_sec": "paper-secret", "vps": "https://example.com"}
    _patch_cfg(monkeypatch, cfg)
    monkeypatch.setattr(ka, "config_root", str(tmp_path))
    reads = iter([None, "token-saved-by-peer"])
    monkeypatch.setattr(ka, "read_token", lambda account_key=None: next(reads))
    monkeypatch.setattr(ka, "_request_token_with_retry", lambda *a, **k: pytest.fail("must not request a new token"))
    seen = {}
    monkeypatch.setattr(ka, "changeTREnv", lambda token, *a, **k: seen.setdefault("token", token))

    ka.auth(svr="vps")

    assert seen["token"] == "token-saved-by-peer"
    assert not (tmp_path / ".token_issue.lock").exists()


def _shared_cfg(monkeypatch, tmp_path):
    cfg = {**_base_cfg(), "my_app": "PSREALKEY", "my_sec": "real-secret", "prod": "https://example.com/"}
    _patch_cfg(monkeypatch, cfg)
    monkeypatch.setattr(ka, "config_root", str(tmp_path / "root"))
    (tmp_path / "root").mkdir()
    monkeypatch.delenv("INVEST_HUB_HOME", raising=False)
    monkeypatch.setenv("KIS_SHARED_TOKEN_DIR", str(tmp_path / "shared"))
    monkeypatch.setattr(ka, "validate_credentials", lambda *a, **k: (True, ""))
    seen = {}
    monkeypatch.setattr(ka, "changeTREnv", lambda token, *a, **k: seen.setdefault("token", token))
    return seen


def test_auth_uses_shared_token_from_other_programs(monkeypatch, tmp_path):
    # 2026-11-23: invest-hub programs held the same app key in separate caches; KIS texts on every issue.
    import json
    from datetime import datetime, timedelta, timezone

    seen = _shared_cfg(monkeypatch, tmp_path)
    shared = tmp_path / "shared"
    shared.mkdir()
    until = (datetime.now(timezone.utc) + timedelta(hours=20)).isoformat()
    ka._shared_token_path(shared, "https://example.com", "PSREALKEY").write_text(
        json.dumps({"token": "shared-token", "until": until, "base": "https://example.com"}))
    monkeypatch.setattr(ka, "read_token", lambda account_key=None: None)
    monkeypatch.setattr(ka, "_request_token_with_retry", lambda *a, **k: pytest.fail("must reuse the shared token"))

    ka.auth(svr="prod")

    assert seen["token"] == "shared-token"


def test_auth_saves_new_token_to_shared_store(monkeypatch, tmp_path):
    import json
    from datetime import datetime, timezone

    seen = _shared_cfg(monkeypatch, tmp_path)
    monkeypatch.setattr(ka, "read_token", lambda account_key=None: None)
    saved = []
    monkeypatch.setattr(ka, "save_token", lambda *a, **k: saved.append(a))
    monkeypatch.setattr(ka, "_request_token_with_retry", lambda *a, **k: {
        "access_token": "new-token", "access_token_token_expired": "2099-11-24 16:10:26"})

    ka.auth(svr="prod")

    assert seen["token"] == "new-token" and saved
    f = ka._shared_token_path(tmp_path / "shared", "https://example.com", "PSREALKEY")
    data = json.loads(f.read_text())
    assert data["token"] == "new-token" and data["base"] == "https://example.com"
    assert datetime.fromisoformat(data["until"]) == datetime(2099, 11, 24, 7, 10, 26, tzinfo=timezone.utc)  # KST to UTC
    assert oct(f.stat().st_mode & 0o777) == "0o600"
    assert ka.read_shared_token("https://example.com", "PSREALKEY") == "new-token"
    assert ka.read_shared_token("https://example.com", "OTHERKEY") is None
    assert not (tmp_path / "shared" / ".issue.lock").exists()


def test_shared_store_off_without_env(monkeypatch, tmp_path):
    monkeypatch.delenv("INVEST_HUB_HOME", raising=False)
    monkeypatch.delenv("KIS_SHARED_TOKEN_DIR", raising=False)
    assert ka._shared_token_dir() is None
    assert ka.read_shared_token("https://example.com", "PSREALKEY") is None
    ka.save_shared_token("https://example.com", "PSREALKEY", "t", "2099-01-01 00:00:00")  # no-op, no error
