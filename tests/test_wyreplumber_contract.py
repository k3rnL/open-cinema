from types import SimpleNamespace

import pytest

from core.orchestration.wyreplumber_contract import (
    SUPPORTED_WIREPLUMBER_API_FAMILY,
    SUPPORTED_WYREPLUMBER_CONTRACT,
    WyrePlumberCompatibilityError,
    require_wyreplumber_contract,
    validate_wyreplumber_contract,
)


def test_supported_binding_contract_is_accepted() -> None:
    result = validate_wyreplumber_contract(
        orchestration_contract=1,
        wireplumber_api_family="0.5",
        package_version="0.1.0",
    )

    assert result.package_version == "0.1.0"
    assert result.orchestration_contract == SUPPORTED_WYREPLUMBER_CONTRACT
    assert result.wireplumber_api_family == SUPPORTED_WIREPLUMBER_API_FAMILY


@pytest.mark.parametrize(
    ("provided", "message"),
    ((0, "too old"), (2, "too new"), (None, "does not expose")),
)
def test_incompatible_contract_versions_fail_clearly(provided, message) -> None:
    with pytest.raises(WyrePlumberCompatibilityError, match=message):
        validate_wyreplumber_contract(
            orchestration_contract=provided,
            wireplumber_api_family="0.5",
        )


def test_non_production_wireplumber_build_is_rejected() -> None:
    with pytest.raises(
        WyrePlumberCompatibilityError,
        match=r"built for WirePlumber API family '0\.4'.*requires '0\.5'",
    ):
        validate_wyreplumber_contract(
            orchestration_contract=1,
            wireplumber_api_family="0.4",
            package_version="0.1.0",
        )


def test_runtime_handshake_reads_public_binding_metadata() -> None:
    result = require_wyreplumber_contract(
        SimpleNamespace(
            ORCHESTRATION_CONTRACT_VERSION=1,
            WIREPLUMBER_BUILD_API_FAMILY="0.5",
        )
    )

    assert result.orchestration_contract == 1
    assert result.wireplumber_api_family == "0.5"
