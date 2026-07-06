"""Read-only boto3 client factory for AWS billing/usage services.

Builds boto3 clients (Cost Explorer today; CloudWatch / S3-for-CUR later) from Settings,
using a named profile or explicit credentials. READ-ONLY: callers must only ever invoke
read APIs; the agent never mutates or terminates infrastructure.

boto3 is imported lazily so that pure ingestion helpers (flattening, normalization) and
their tests do not require AWS to be configured just to import this package.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcca.config import Settings, get_settings

if TYPE_CHECKING:  # avoid importing boto3 at module load
    from boto3 import Session


def build_session(settings: Settings | None = None) -> Session:
    """Return a boto3 Session configured for least-privilege, read-only access.

    Resolution order for credentials: an explicit profile, then explicit static keys,
    then boto3's own default chain (env vars, shared config, instance/role). Nothing is
    hardcoded — everything comes from Settings (env/.env).
    """
    import boto3

    settings = settings or get_settings()
    kwargs: dict[str, Any] = {"region_name": settings.aws_region}
    if settings.aws_profile:
        kwargs["profile_name"] = settings.aws_profile
    elif settings.aws_access_key_id and settings.aws_secret_access_key:
        kwargs["aws_access_key_id"] = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        if settings.aws_session_token:
            kwargs["aws_session_token"] = settings.aws_session_token
    return boto3.Session(**kwargs)


def cost_explorer_client(settings: Settings | None = None, session: Session | None = None) -> Any:
    """Return a read-only Cost Explorer (`ce`) client with adaptive retries."""
    from botocore.config import Config

    settings = settings or get_settings()
    session = session or build_session(settings)
    return session.client(
        "ce",
        config=Config(retries={"max_attempts": 10, "mode": "adaptive"}),
    )
