"""Read-only system-state decoding, Z21 LAN specification sections 2.18–2.19."""
import struct


def decode_system_state(data):
    if len(data) != 16:
        raise ValueError("Z21 system state must contain 16 bytes")
    main, programming, filtered, temperature, supply, voltage, state, extended, _, capabilities = struct.unpack("<hhhhHHBBBB", data)
    return {"available": True, "current_a": main / 1000,
            "filtered_current_a": filtered / 1000, "voltage_v": voltage / 1000,
            "estimated_watts": abs(filtered) * voltage / 1_000_000,
            "temperature_c": temperature, "track_power": not bool(state & 2),
            "short_circuit": bool(state & 4), "emergency_stop": bool(state & 1)}
