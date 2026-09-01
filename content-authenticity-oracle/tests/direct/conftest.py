import sys
import os

import pytest

_real_unlink = os.unlink


def _windows_safe_unlink(path, *args, **kwargs):
    try:
        return _real_unlink(path, *args, **kwargs)
    except PermissionError:
        return None


os.unlink = _windows_safe_unlink


def warp_to(direct_vm, iso: str) -> None:
    direct_vm.warp(iso)
    gl = sys.modules.get("genlayer.gl")
    if gl is None:
        return
    raw = getattr(gl, "message_raw", None)
    if isinstance(raw, dict):
        raw["datetime"] = iso
    nested = getattr(getattr(gl, "message", None), "raw", None)
    if isinstance(nested, dict):
        nested["datetime"] = iso


@pytest.fixture
def contract(direct_deploy, direct_vm, direct_alice):
    # Deploy under a known, fixed sender (direct_alice) so admin-gated tests have a proven
    # fixture identity to assert against, rather than relying on whatever the framework's
    # default sender happens to be at deploy time.
    direct_vm.sender = direct_alice
    deployed = direct_deploy("contracts/ContentAuthenticityOracle.py")
    direct_vm.sender = direct_alice
    return deployed
