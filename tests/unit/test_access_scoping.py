"""Access-scoping verification: least-privilege, read-only, no write path — sans real creds.

CLAUDE.md requires read-only, least-privilege access and that nothing ever touches
infrastructure. This module verifies everything checkable WITHOUT a live account:

  * config: credentials are never hardcoded and come only from Settings (env/.env);
  * session factory: the credential-resolution precedence is correct;
  * read-only: the AWS client only ever builds a Cost Explorer ("ce") client, and the
    ingestion + agent layers contain no infrastructure-mutating SDK calls at all.

WHAT IS NOT COVERED (open v1 debt, needs a real account): that a real least-privilege IAM
role/service-principal actually authenticates and is scoped read-only at the provider. That
live check is marked pending below, not silently skipped.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcca.config import Settings
from mcca.ingestion.aws.client import cost_explorer_client, session_kwargs

SRC = Path(__file__).resolve().parents[2] / "src" / "mcca"


# --- Config scoping ---------------------------------------------------------------------
def test_all_three_clouds_have_readonly_scoping_fields() -> None:
    s = Settings(_env_file=None)
    # Read-only credential/scope fields exist for every cloud (no write/admin fields).
    assert hasattr(s, "aws_profile") and hasattr(s, "aws_billing_account_id")
    assert hasattr(s, "azure_subscription_id") and hasattr(s, "azure_tenant_id")
    assert hasattr(s, "gcp_project_id") and hasattr(s, "gcp_billing_account_id")


def test_credentials_are_never_hardcoded() -> None:
    s = Settings(_env_file=None)
    assert s.aws_access_key_id is None
    assert s.aws_secret_access_key is None
    assert s.aws_session_token is None


# --- Session-factory credential precedence (no network, no real creds) ------------------
def test_profile_takes_precedence_over_static_keys() -> None:
    s = Settings(
        _env_file=None,
        aws_profile="finops-readonly",
        aws_access_key_id="AKIA_X",
        aws_secret_access_key="secret",
    )
    kwargs = session_kwargs(s)
    assert kwargs["profile_name"] == "finops-readonly"
    assert "aws_access_key_id" not in kwargs  # profile wins; static keys ignored


def test_static_keys_used_when_no_profile() -> None:
    s = Settings(
        _env_file=None,
        aws_access_key_id="AKIA_X",
        aws_secret_access_key="secret",
        aws_session_token="tok",
        aws_region="eu-west-1",
    )
    kwargs = session_kwargs(s)
    assert kwargs["aws_access_key_id"] == "AKIA_X"
    assert kwargs["aws_secret_access_key"] == "secret"
    assert kwargs["aws_session_token"] == "tok"
    assert kwargs["region_name"] == "eu-west-1"


def test_falls_back_to_default_chain_when_unset() -> None:
    # No profile, no static keys -> only region; boto3's own default chain resolves creds.
    kwargs = session_kwargs(Settings(_env_file=None))
    assert set(kwargs) == {"region_name"}


# --- Read-only client behaviour ---------------------------------------------------------
class _RecordingSession:
    """Captures the boto3 service + config a client is built with (no AWS calls)."""

    def __init__(self) -> None:
        self.built: list[tuple[str, dict]] = []

    def client(self, service_name: str, **kwargs):
        self.built.append((service_name, kwargs))
        return object()


def test_cost_explorer_client_builds_only_the_readonly_ce_service() -> None:
    session = _RecordingSession()
    cost_explorer_client(session=session)
    assert len(session.built) == 1
    service, kwargs = session.built[0]
    assert service == "ce"  # Cost Explorer: a read-only billing API
    # Adaptive retries are configured (read path hygiene), never write options.
    assert kwargs["config"].retries["mode"] == "adaptive"


# --- Structural "no write path" guarantees ----------------------------------------------
# boto3/SDK method fragments that mutate infrastructure or data. None may appear in the
# ingestion layer — it is read-only by construction.
_MUTATING_FRAGMENTS = (
    "terminate_",
    "delete_",
    "create_bucket",
    "put_object",
    "run_instances",
    "modify_",
    "stop_instances",
    "reboot_",
    "update_stack",
    ".create(",
    ".delete(",
    ".update(",
)


def _sources(*relative_dirs: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in relative_dirs:
        for path in (SRC / rel).rglob("*.py"):
            out[str(path)] = path.read_text(encoding="utf-8")
    return out


def test_aws_client_only_ever_names_readonly_services() -> None:
    # The only boto3 service string the AWS client references is the read-only "ce".
    text = (SRC / "ingestion" / "aws" / "client.py").read_text(encoding="utf-8")
    assert '"ce"' in text
    for write_service in ('"ec2"', '"s3"', '"rds"', '"lambda"'):
        assert write_service not in text


def test_ingestion_layer_has_no_infrastructure_mutations() -> None:
    offenders = []
    for path, text in _sources("ingestion").items():
        for fragment in _MUTATING_FRAGMENTS:
            if fragment in text:
                offenders.append(f"{path}: {fragment}")
    assert not offenders, "mutating call(s) found in ingestion: " + "; ".join(offenders)


def test_agent_and_tools_never_import_cloud_sdks() -> None:
    # The reasoning/tool layer must not even be able to reach a cloud SDK.
    banned = ("import boto3", "from boto3", "import botocore", "azure.", "google.cloud")
    offenders = []
    for path, text in _sources("agent", "tools").items():
        for token in banned:
            if token in text:
                offenders.append(f"{path}: {token}")
    assert not offenders, "cloud SDK reference in agent/tools: " + "; ".join(offenders)


# --- Live paths are not yet wired (so nothing can reach a real account) -----------------
def test_azure_and_gcp_live_clients_are_not_wired() -> None:
    from mcca.ingestion.azure.client import cost_management_client
    from mcca.ingestion.gcp.client import bigquery_client

    # The real cloud clients deliberately raise until a real account is available — the
    # synthetic providers are the only live path today. This is why live scoping is pending.
    with pytest.raises(NotImplementedError):
        cost_management_client(Settings(_env_file=None))
    with pytest.raises(NotImplementedError):
        bigquery_client(Settings(_env_file=None))


# --- Pending live verification (explicit, not silent) -----------------------------------
@pytest.mark.skip(
    reason="LIVE ACCESS-SCOPING CHECK PENDING — requires a real least-privilege cloud "
    "account to confirm the reader role authenticates and is scoped read-only. Open v1 debt."
)
def test_live_least_privilege_credentials_are_readonly() -> None:  # pragma: no cover
    # Intentionally unimplemented: with a real account, assert the configured role can call
    # the billing/cost read APIs and is denied any write/terminate action.
    raise AssertionError("requires real cloud credentials")
