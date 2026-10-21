from importlib import import_module

import pytest

registry_mod = import_module("01_HCM.registry")
protocol = import_module("08_servises.common.protocol")

verify = registry_mod.ModuleRegistry.verify_client_identity

DEVICE_ID = "2ccf675d3414"
VALID_CERT = {
    "subjectAltName": (
        ("URI", "urn:homecontrol:device:2ccf675d3414"),
    )
}


def test_matching_certificate():
    assert verify(
        VALID_CERT, {"device_id": DEVICE_ID}
    ) == DEVICE_ID


def test_normalized_mac_identity():
    assert verify(
        VALID_CERT, {"device_id": "2c:cf:67:5d:34:14"}
    ) == DEVICE_ID


@pytest.mark.parametrize(
    "cert,ident",
    [
        (None, {"device_id": DEVICE_ID}),
        ({}, {"device_id": DEVICE_ID}),
        (VALID_CERT, {}),
        (VALID_CERT, {"device_id": "ffffffffffff"}),
        (VALID_CERT, {"device_id": "invalid"}),
        (
            {"subjectAltName": "not-a-sequence"},
            {"device_id": DEVICE_ID},
        ),
        (
            {"subjectAltName": (("URI", "urn:homecontrol:device:not-a-device-id"),)},
            {"device_id": DEVICE_ID},
        ),
        (
            {"subjectAltName": (("DNS", "lab1"),)},
            {"device_id": DEVICE_ID},
        ),
        (
            {"subjectAltName": (
                ("URI", "urn:homecontrol:device:2ccf675d3414"),
                ("URI", "urn:homecontrol:device:2ccf675d3414"),
            )},
            {"device_id": DEVICE_ID},
        ),
        (
            {"subjectAltName": (
                ("URI", "urn:homecontrol:device:2ccf675d3414"),
                ("URI", "urn:homecontrol:device:48b02d87db16"),
            )},
            {"device_id": DEVICE_ID},
        ),
    ],
)
def test_reject_invalid_identity(cert, ident):
    with pytest.raises(protocol.ProtocolError):
        verify(cert, ident)


def test_reject_impersonation():
    with pytest.raises(protocol.ProtocolError, match="mismatch"):
        verify(
            VALID_CERT,
            {"device_id": "48:b0:2d:87:db:16"},
        )


def test_reject_legacy_uuid_only_when_certificate_identity_required():
    with pytest.raises(protocol.ProtocolError, match="requires device_id"):
        verify(
            VALID_CERT,
            {"module_uuid": "7b156ddf-c4f8-4984-881e-5e05caf8b89d"},
        )
