from __future__ import annotations

import math
import platform
import re
import shutil
import socket
import subprocess
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")
_CPU_LOCK = threading.Lock()
_CPU_SAMPLE: tuple[int, int] | None = None


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_text(path: Path, *, maximum: int = 4096) -> str:
    with path.open("r", encoding="utf-8") as stream:
        return stream.read(maximum).strip()


def _optional(name: str, function: Callable[[], T], unavailable: list[str]) -> T | None:
    try:
        return function()
    except (OSError, ValueError, subprocess.SubprocessError):
        unavailable.append(name)
        return None


def hostname() -> str:
    value = socket.gethostname().strip()
    if not value:
        raise ValueError("hostname is empty")
    return value


def hardware_model(path: Path = Path("/proc/device-tree/model")) -> str:
    return _read_text(path, maximum=512).rstrip("\x00")


def operating_system(path: Path = Path("/etc/os-release")) -> str:
    fields: dict[str, str] = {}
    for line in _read_text(path).splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        fields[key] = value.strip().strip('"').strip("'")
    system_name = fields.get("PRETTY_NAME") or fields.get("NAME")
    if not system_name:
        raise ValueError("operating system name is unavailable")
    return system_name


def kernel() -> str:
    value = platform.release().strip()
    if not value:
        raise ValueError("kernel release is empty")
    return value


def boot_id(path: Path = Path("/proc/sys/kernel/random/boot_id")) -> str:
    value = _read_text(path, maximum=128)
    if not re.fullmatch(r"[0-9a-fA-F-]{8,64}", value):
        raise ValueError("boot identifier is invalid")
    return value.lower()


def uptime_seconds(path: Path = Path("/proc/uptime")) -> float:
    value = float(_read_text(path, maximum=128).split()[0])
    if not math.isfinite(value) or value < 0:
        raise ValueError("uptime is invalid")
    return round(value, 3)


def storage(path: str = "/") -> dict[str, int | float]:
    usage = shutil.disk_usage(path)
    percent = usage.used / usage.total * 100 if usage.total else 0.0
    return {
        "usedBytes": usage.used,
        "totalBytes": usage.total,
        "percent": round(percent, 2),
    }


def memory(path: Path = Path("/proc/meminfo")) -> dict[str, int | float]:
    values: dict[str, int] = {}
    for line in _read_text(path, maximum=16384).splitlines():
        key, _, raw = line.partition(":")
        match = re.search(r"([0-9]+)", raw)
        if match:
            values[key] = int(match.group(1)) * 1024
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    if not total or available is None:
        raise ValueError("memory totals are unavailable")
    used = max(total - available, 0)
    return {
        "usedBytes": used,
        "totalBytes": total,
        "percent": round(used / total * 100, 2),
    }


def _cpu_totals(path: Path = Path("/proc/stat")) -> tuple[int, int]:
    first = _read_text(path, maximum=4096).splitlines()[0].split()
    if not first or first[0] != "cpu" or len(first) < 5:
        raise ValueError("aggregate CPU counters are unavailable")
    counters = [int(value) for value in first[1:]]
    total = sum(counters)
    idle = counters[3] + (counters[4] if len(counters) > 4 else 0)
    return total, idle


def cpu_percent() -> float:
    global _CPU_SAMPLE
    with _CPU_LOCK:
        current = _cpu_totals()
        previous = _CPU_SAMPLE
        _CPU_SAMPLE = current
    if previous is None or current[0] <= previous[0]:
        total, idle = current
    else:
        total = current[0] - previous[0]
        idle = current[1] - previous[1]
    if total <= 0:
        raise ValueError("CPU counter interval is empty")
    return round(max(0.0, min(100.0, (total - idle) / total * 100)), 2)


def temperature_celsius(path: Path = Path("/sys/class/thermal/thermal_zone0/temp")) -> float:
    raw = float(_read_text(path, maximum=64))
    value = raw / 1000 if raw > 500 else raw
    if not math.isfinite(value) or not -40 <= value <= 150:
        raise ValueError("temperature is outside the supported range")
    return round(value, 1)


def throttling() -> dict[str, object]:
    executable = shutil.which("vcgencmd")
    if not executable:
        raise OSError("vcgencmd is unavailable")
    result = subprocess.run(
        [executable, "get_throttled"],
        check=True,
        capture_output=True,
        text=True,
        timeout=0.5,
    )
    match = re.search(r"0x([0-9a-fA-F]+)", result.stdout[:128])
    if match is None:
        raise ValueError("vcgencmd returned an invalid throttling value")
    value = int(match.group(1), 16)
    return {"supported": True, "active": value != 0, "raw": f"0x{value:x}"}


def collect_overview(*, readiness: dict[str, object]) -> dict[str, object]:
    unavailable: list[str] = []
    throttle = _optional("throttling", throttling, unavailable)
    return {
        "schemaVersion": 1,
        "observedAt": timestamp(),
        "hostname": _optional("hostname", hostname, unavailable),
        "model": _optional("model", hardware_model, unavailable),
        "operatingSystem": _optional("operatingSystem", operating_system, unavailable),
        "kernel": _optional("kernel", kernel, unavailable),
        "bootId": _optional("bootId", boot_id, unavailable),
        "uptimeSeconds": _optional("uptimeSeconds", uptime_seconds, unavailable),
        "storage": _optional("storage", storage, unavailable),
        "temperatureCelsius": _optional("temperatureCelsius", temperature_celsius, unavailable),
        "throttling": (
            throttle if throttle is not None else {"supported": False, "active": None, "raw": None}
        ),
        "application": readiness,
        "unavailableFields": unavailable,
    }


def collect_metrics() -> dict[str, object]:
    unavailable: list[str] = []
    return {
        "schemaVersion": 1,
        "observedAt": timestamp(),
        "cpuPercent": _optional("cpuPercent", cpu_percent, unavailable),
        "memory": _optional("memory", memory, unavailable),
        "unavailableFields": unavailable,
    }
