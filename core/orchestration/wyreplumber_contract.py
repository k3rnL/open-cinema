"""Compatibility handshake for Open Cinema's required runtime binding."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from importlib.metadata import PackageNotFoundError, version

SUPPORTED_WYREPLUMBER_CONTRACT = 1
SUPPORTED_WIREPLUMBER_API_FAMILY = "0.5"


class WyrePlumberCompatibilityError(RuntimeError):
    """The installed binding cannot safely drive this Open Cinema release."""


@dataclass(frozen=True, slots=True)
class WyrePlumberCompatibility:
    package_version: str
    orchestration_contract: int
    wireplumber_api_family: str


def _package_version() -> str:
    try:
        return version("wyreplumber")
    except PackageNotFoundError:
        return "unknown"


def validate_wyreplumber_contract(
    *,
    orchestration_contract: object,
    wireplumber_api_family: object,
    package_version: str = "unknown",
) -> WyrePlumberCompatibility:
    """Validate detached metadata without opening a WirePlumber connection."""

    if isinstance(orchestration_contract, bool) or not isinstance(orchestration_contract, int):
        raise WyrePlumberCompatibilityError(
            "WyrePlumber does not expose a valid orchestration contract version. "
            "Install the Open Cinema-tested binding before enabling runtime observation."
        )
    if orchestration_contract < SUPPORTED_WYREPLUMBER_CONTRACT:
        raise WyrePlumberCompatibilityError(
            f"WyrePlumber orchestration contract {orchestration_contract} is too old; "
            f"Open Cinema requires exactly {SUPPORTED_WYREPLUMBER_CONTRACT}."
        )
    if orchestration_contract > SUPPORTED_WYREPLUMBER_CONTRACT:
        raise WyrePlumberCompatibilityError(
            f"WyrePlumber orchestration contract {orchestration_contract} is too new; "
            f"Open Cinema requires exactly {SUPPORTED_WYREPLUMBER_CONTRACT}. "
            "Upgrade Open Cinema before enabling runtime observation."
        )
    if wireplumber_api_family != SUPPORTED_WIREPLUMBER_API_FAMILY:
        observed = "missing" if wireplumber_api_family is None else repr(wireplumber_api_family)
        raise WyrePlumberCompatibilityError(
            f"WyrePlumber {package_version} was built for WirePlumber API family "
            f"{observed}; Open Cinema production orchestration requires "
            f"{SUPPORTED_WIREPLUMBER_API_FAMILY!r}. Rebuild the binding with "
            "WYREPLUMBER_WP_API=0.5."
        )
    return WyrePlumberCompatibility(
        package_version=package_version,
        orchestration_contract=orchestration_contract,
        wireplumber_api_family=wireplumber_api_family,
    )


def require_wyreplumber_contract(binding: object | None = None) -> WyrePlumberCompatibility:
    """Import and validate the binding before runtime observation is started."""

    if binding is None:
        try:
            binding = import_module("wyreplumber")
        except (ImportError, OSError) as error:
            raise WyrePlumberCompatibilityError(
                "WyrePlumber could not be imported. Install the coordinated binding "
                "and its WirePlumber 0.5 native dependencies before enabling runtime "
                "observation."
            ) from error

    return validate_wyreplumber_contract(
        orchestration_contract=getattr(
            binding,
            "ORCHESTRATION_CONTRACT_VERSION",
            None,
        ),
        wireplumber_api_family=getattr(
            binding,
            "WIREPLUMBER_BUILD_API_FAMILY",
            None,
        ),
        package_version=_package_version(),
    )
