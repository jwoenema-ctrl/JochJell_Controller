"""Decoder identifiers kept independently of a command station wire format."""

from __future__ import annotations


def normalize_decoder_protocol(protocol: str) -> str:
    """Keep legacy metadata readable while normalizing known protocol aliases."""
    if not isinstance(protocol, str):
        raise ValueError("decoder protocol must be text")
    value = protocol.strip()
    key = value.lower()
    if key in ("", "dcc", "z21 lan"):
        return "DCC"
    if key in ("mm", "motorola", "märklin motorola", "marklin motorola"):
        return "MM"
    if key in ("mfx", "m4"):
        return "MFX"
    # Historical decoder_type fields sometimes contain a decoder model name.
    # Such text keeps its original value and the former DCC address limits.
    return value


def validate_decoder_address(address: int | None, protocol: str, *, legacy_dcc_zero: bool = False) -> None:
    if address is None:
        return
    if type(address) is not int:
        raise ValueError("decoder_address must be an integer")
    canonical = normalize_decoder_protocol(protocol)
    maximum = {"MM": 255, "MFX": 65535}.get(canonical, 16383)
    minimum = 0 if legacy_dcc_zero and canonical not in ("MM", "MFX") else 1
    if not minimum <= address <= maximum:
        raise ValueError(f"decoder_address must be between {minimum} and {maximum} for {canonical}")
