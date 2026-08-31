from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from wyreplumber.runtime import (
    AudioFormatValue,
    AudioPropertiesValue,
    FrozenDict,
    NodeState,
    RuntimeSnapshot,
    SpaChoiceValue,
    SpaIdValue,
)

from .signal_contracts import KnownSampleFormat

DURABLE_ENDPOINT_PROPERTY_KEYS = frozenset(
    {
        "api.alsa.card",
        "api.alsa.path",
        "api.bluez5.address",
        "api.bluez5.connection",
        "device.bus",
        "device.bus-id",
        "device.name",
        "device.product.id",
        "device.serial",
        "device.string",
        "device.vendor.id",
        "media.class",
        "node.name",
        "object.path",
        "open-cinema.endpoint-id",
        "open-cinema.owner",
        "open-cinema.adapter.id",
        "open-cinema.adapter.kind",
        "open-cinema.adapter.direction",
        "open-cinema.provider",
        "open-cinema.plugin.id",
        "open-cinema.instance.id",
        "open-cinema.generation",
    }
)

PROCESSOR_KIND_PROPERTY_KEYS = (
    "opencinema.processor.kind",
    "open-cinema.processor.kind",
)


def _durable_properties(properties: FrozenDict) -> dict[str, object]:
    return {
        key: value
        for key, value in properties.items()
        if key in DURABLE_ENDPOINT_PROPERTY_KEYS
    }


class EndpointDirection(StrEnum):
    INPUT = "input"
    OUTPUT = "output"


@dataclass(frozen=True, slots=True)
class RuntimeEndpointReference:
    """Ephemeral operation target; never a durable endpoint identity."""

    generation: int
    node_id: int
    device_id: int | None

    @property
    def key(self) -> str:
        return f"runtime:{self.generation}:node:{self.node_id}"


@dataclass(frozen=True, slots=True)
class RuntimeRouteReference:
    generation: int
    device_id: int
    route_index: int


@dataclass(frozen=True, slots=True)
class RuntimeProfileReference:
    generation: int
    device_id: int
    profile_index: int


@dataclass(frozen=True, slots=True)
class EndpointPortSummary:
    name: str | None
    direction: str
    channel: str | None
    properties: FrozenDict


@dataclass(frozen=True, slots=True)
class EndpointProfileSummary:
    runtime: RuntimeProfileReference
    name: str
    description: str | None
    priority: int
    availability: str
    active: bool
    classes: tuple[str, ...]
    properties: FrozenDict


@dataclass(frozen=True, slots=True)
class EndpointRouteSummary:
    runtime: RuntimeRouteReference
    name: str
    description: str | None
    direction: str
    priority: int
    availability: str
    active: bool
    profile_names: tuple[str, ...]
    volume: float | None
    mute: bool | None
    properties: FrozenDict


@dataclass(frozen=True, slots=True)
class ObservedAudioValue:
    value: object
    known: bool
    choices: tuple[object, ...] = ()

    def to_document(self) -> dict[str, object]:
        return {
            "value": self.value,
            "known": self.known,
            "choices": list(self.choices),
        }


@dataclass(frozen=True, slots=True)
class EndpointFormatSummary:
    content: str
    media_type: ObservedAudioValue
    media_subtype: ObservedAudioValue
    sample_format: ObservedAudioValue
    rate: ObservedAudioValue
    channels: ObservedAudioValue
    positions: ObservedAudioValue
    codec: ObservedAudioValue

    def to_document(self) -> dict[str, object]:
        return {
            "content": self.content,
            "mediaType": self.media_type.to_document(),
            "mediaSubtype": self.media_subtype.to_document(),
            "sampleFormat": self.sample_format.to_document(),
            "rate": self.rate.to_document(),
            "channels": self.channels.to_document(),
            "positions": self.positions.to_document(),
            "codec": self.codec.to_document(),
        }


@dataclass(frozen=True, slots=True)
class EndpointLatencySummary:
    milliseconds: float | None
    raw: str | int | float | None
    known: bool

    def to_document(self) -> dict[str, object]:
        return {
            "milliseconds": self.milliseconds,
            "raw": self.raw,
            "known": self.known,
        }


@dataclass(frozen=True, slots=True)
class RuntimeEndpointCandidate:
    runtime: RuntimeEndpointReference
    direction: EndpointDirection
    name: str | None
    description: str | None
    media_class: str
    node_state: str
    node_error: str | None
    node_properties: FrozenDict
    device_name: str | None
    device_description: str | None
    device_media_class: str | None
    device_properties: FrozenDict
    ports: tuple[EndpointPortSummary, ...]
    profiles: tuple[EndpointProfileSummary, ...]
    routes: tuple[EndpointRouteSummary, ...]
    formats: tuple[EndpointFormatSummary, ...]
    volume: float | None
    mute: bool | None
    latency: EndpointLatencySummary
    is_default: bool
    is_linked: bool
    has_active_signal: bool
    volume_writable: bool = False
    mute_writable: bool = False

    @property
    def runtime_key(self) -> str:
        return self.runtime.key

    @property
    def managed_adapter(self) -> dict[str, object] | None:
        adapter_id = self.node_properties.get("open-cinema.adapter.id")
        if not isinstance(adapter_id, str) or not adapter_id:
            return None
        return {
            "id": adapter_id,
            "kind": self.node_properties.get("open-cinema.adapter.kind"),
            "direction": self.node_properties.get("open-cinema.adapter.direction"),
            "owner": self.node_properties.get("open-cinema.owner"),
        }

    def selector_facts(self) -> dict[str, object]:
        """Return durable evidence only; runtime numeric IDs are intentionally absent."""

        return {
            "direction": self.direction.value,
            "name": self.name,
            "description": self.description,
            "mediaClass": self.media_class,
            "device": {
                "name": self.device_name,
                "description": self.device_description,
                "mediaClass": self.device_media_class,
                "properties": _durable_properties(self.device_properties),
            },
            "nodeProperties": _durable_properties(self.node_properties),
            "profiles": [profile.name for profile in self.profiles],
            "routes": [route.name for route in self.routes],
        }

    def projection_document(self) -> dict[str, object]:
        """Return UI runtime state with one explicitly ephemeral opaque key."""

        managed_adapter = self.managed_adapter
        return {
            "runtimeKey": self.runtime_key,
            **self.selector_facts(),
            "origin": "managed-adapter"
            if managed_adapter is not None
            else "runtime-device",
            "managed": managed_adapter is not None,
            "owner": "open-cinema" if managed_adapter is not None else None,
            "managedAdapter": managed_adapter,
            "state": self.node_state,
            "error": self.node_error,
            "default": self.is_default,
            "linked": self.is_linked,
            "activeSignal": self.has_active_signal,
            "ports": [
                {
                    "name": port.name,
                    "direction": port.direction,
                    "channel": port.channel,
                    "properties": port.properties.to_dict(),
                }
                for port in self.ports
            ],
            "profiles": [
                {
                    "name": profile.name,
                    "description": profile.description,
                    "priority": profile.priority,
                    "availability": profile.availability,
                    "active": profile.active,
                    "classes": list(profile.classes),
                    "properties": profile.properties.to_dict(),
                }
                for profile in self.profiles
            ],
            "routes": [
                {
                    "name": route.name,
                    "description": route.description,
                    "direction": route.direction,
                    "priority": route.priority,
                    "availability": route.availability,
                    "active": route.active,
                    "profiles": list(route.profile_names),
                    "volume": route.volume,
                    "mute": route.mute,
                    "properties": route.properties.to_dict(),
                }
                for route in self.routes
            ],
            "audioCapabilities": {
                "formats": [item.to_document() for item in self.formats],
                "volume": {
                    "value": self.volume,
                    "known": self.volume is not None,
                    "readable": self.volume is not None,
                    "writable": self.volume_writable,
                },
                "mute": {
                    "value": self.mute,
                    "known": self.mute is not None,
                    "readable": self.mute is not None,
                    "writable": self.mute_writable,
                },
                "latency": self.latency.to_document(),
            },
        }


@dataclass(frozen=True, slots=True)
class EndpointInventorySnapshot:
    generation: int
    sequence: int
    captured_at: str
    candidates: tuple[RuntimeEndpointCandidate, ...]


def _direction(media_class: str | None) -> EndpointDirection | None:
    normalized = (media_class or "").lower()
    if normalized.startswith("audio/source"):
        return EndpointDirection.INPUT
    if normalized.startswith("audio/sink"):
        return EndpointDirection.OUTPUT
    return None


def _is_processor_resource(properties: FrozenDict) -> bool:
    """Keep graph-internal processor ports out of physical endpoint discovery."""

    explicitly_managed = any(
        isinstance(properties.get(key), str) and bool(properties.get(key).strip())
        for key in PROCESSOR_KIND_PROPERTY_KEYS
    )
    node_name = properties.get("node.name")
    native_camilladsp = (
        isinstance(node_name, str)
        and node_name.startswith("opencinema.camilladsp.")
        and isinstance(properties.get("node.group"), str)
    )
    return explicitly_managed or native_camilladsp


def _profile_summaries(snapshot, device_id):
    profiles = [
        profile for profile in snapshot.profiles if profile.device_id == device_id
    ]
    return tuple(
        EndpointProfileSummary(
            runtime=RuntimeProfileReference(
                snapshot.generation,
                profile.device_id,
                profile.index,
            ),
            name=profile.name,
            description=profile.description,
            priority=profile.priority,
            availability=profile.available.value,
            active=profile.active,
            classes=profile.classes,
            properties=profile.properties,
        )
        for profile in sorted(profiles, key=lambda value: (value.name, value.index))
    )


def _route_summaries(snapshot, device_id, profiles):
    profile_names = {
        profile.runtime.profile_index: profile.name for profile in profiles
    }
    routes = [route for route in snapshot.routes if route.device_id == device_id]
    return tuple(
        EndpointRouteSummary(
            runtime=RuntimeRouteReference(
                snapshot.generation,
                route.device_id,
                route.index,
            ),
            name=route.name,
            description=route.description,
            direction=route.direction.value,
            priority=route.priority,
            availability=route.available.value,
            active=route.active,
            profile_names=tuple(
                sorted(
                    profile_names[index]
                    for index in route.profile_ids
                    if index in profile_names
                )
            ),
            volume=route.volume,
            mute=route.mute,
            properties=route.properties,
        )
        for route in sorted(routes, key=lambda value: (value.name, value.index))
    )


def _spa_value(value, *, known_names=None):
    known_names = known_names or set()
    if value is None:
        return ObservedAudioValue(None, False)
    if isinstance(value, SpaChoiceValue):
        default = _spa_value(value.default, known_names=known_names)
        choices = tuple(
            _spa_value(item, known_names=known_names).value
            for item in value.alternatives
        )
        return ObservedAudioValue(default.value, default.known, choices)
    if isinstance(value, SpaIdValue):
        projected = value.name or f"{value.namespace}:{value.id}"
        return ObservedAudioValue(
            projected,
            bool(value.name) and (not known_names or value.name in known_names),
        )
    if isinstance(value, bool):
        return ObservedAudioValue(value, False)
    if isinstance(value, (int, float, str)):
        return ObservedAudioValue(
            value,
            not known_names or str(value) in known_names,
        )
    return ObservedAudioValue(repr(value), False)


def _format_summary(value: AudioFormatValue):
    sample_formats = {item.value for item in KnownSampleFormat}
    media_type = _spa_value(value.media_type)
    media_subtype = _spa_value(value.media_subtype)
    sample_format = _spa_value(value.sample_format, known_names=sample_formats)
    rate = _spa_value(value.rate)
    channels = _spa_value(value.channels)
    positions = ObservedAudioValue(
        tuple(
            position.name or f"{position.namespace}:{position.id}"
            for position in value.positions
        ),
        all(position.name is not None for position in value.positions),
    )
    codec = _spa_value(value.iec958_codec)
    content = "encoded" if codec.value is not None else "pcm"
    if media_type.value is None and media_subtype.value is None:
        content = "unknown"
    return EndpointFormatSummary(
        content=content,
        media_type=media_type,
        media_subtype=media_subtype,
        sample_format=sample_format,
        rate=rate,
        channels=channels,
        positions=positions,
        codec=codec,
    )


def _audio_capabilities(snapshot, node_id, device_id, routes):
    mixer_parameter = snapshot.parameters_by_key.get(("node", node_id, "Mixer"))
    mixer = next(
        (
            value
            for value in (mixer_parameter.values if mixer_parameter is not None else ())
            if isinstance(value, AudioPropertiesValue)
        ),
        None,
    )
    node_parameters = [
        parameter
        for parameter in snapshot.parameters
        if parameter.owner_type.lower() == "node" and parameter.owner_id == node_id
    ]
    device_parameters = [
        parameter
        for parameter in snapshot.parameters
        if device_id is not None
        and parameter.owner_type.lower() == "device"
        and parameter.owner_id == device_id
    ]
    formats = []
    node_audio_properties = None
    device_audio_properties = None

    def prefer_controls(
        current: AudioPropertiesValue | None,
        candidate: AudioPropertiesValue,
    ) -> AudioPropertiesValue:
        if current is None:
            return candidate
        current_score = sum(
            (
                current.volume is not None,
                current.mute is not None,
                bool(current.channel_volumes),
                bool(current.channel_positions),
            )
        )
        candidate_score = sum(
            (
                candidate.volume is not None,
                candidate.mute is not None,
                bool(candidate.channel_volumes),
                bool(candidate.channel_positions),
            )
        )
        return candidate if candidate_score > current_score else current

    for parameter in (*node_parameters, *device_parameters):
        for value in parameter.values:
            if isinstance(value, AudioFormatValue):
                formats.append(_format_summary(value))
            elif isinstance(value, AudioPropertiesValue):
                if parameter.owner_type.lower() == "node":
                    node_audio_properties = prefer_controls(
                        node_audio_properties, value
                    )
                else:
                    device_audio_properties = prefer_controls(
                        device_audio_properties, value
                    )
    # Node Props are the software controls mutated by the orchestrator. Device
    # Props often follow them (sometimes as another value of the same node
    # parameter) and describe the hardware object without volume fields; they
    # must not erase readable node controls.
    audio_properties = node_audio_properties or device_audio_properties
    active_route = next((route for route in routes if route.active), None)
    volume = mixer.volume if mixer is not None else (
        audio_properties.volume
        if audio_properties is not None and audio_properties.volume is not None
        else (active_route.volume if active_route is not None else None)
    )
    mute = mixer.mute if mixer is not None else (
        audio_properties.mute
        if audio_properties is not None and audio_properties.mute is not None
        else (active_route.mute if active_route is not None else None)
    )
    # Effective volume and mute are owned by WirePlumber's mixer API. Raw node
    # Props can claim write access even when the device route ignores direct
    # mutations, so only advertise controls when the mixer API resolved them.
    writable = bool(
        mixer is not None
        and mixer_parameter is not None
        and "w" in mixer_parameter.permissions.lower()
    )
    return (
        tuple(sorted(formats, key=lambda item: repr(item.to_document()))),
        volume,
        mute,
        writable,
    )


def _latency(properties):
    raw = properties.get("node.latency")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw >= 0:
        return EndpointLatencySummary(float(raw), raw, True)
    if isinstance(raw, str):
        try:
            frames, rate = raw.split("/", 1)
            milliseconds = int(frames) / int(rate) * 1000
            return EndpointLatencySummary(milliseconds, raw, True)
        except (ValueError, ZeroDivisionError):
            return EndpointLatencySummary(None, raw, False)
    return EndpointLatencySummary(None, raw, False)


def map_runtime_endpoints(snapshot: RuntimeSnapshot) -> EndpointInventorySnapshot:
    if not isinstance(snapshot, RuntimeSnapshot):
        raise TypeError("snapshot must be a detached WyrePlumber RuntimeSnapshot")
    candidates = []
    linked_node_ids = {
        node_id
        for link in snapshot.links
        for node_id in (link.output_node_id, link.input_node_id)
    }
    for node in snapshot.nodes:
        if _is_processor_resource(node.properties):
            continue
        media_class = node.media_class or node.properties.get("media.class")
        direction = _direction(media_class)
        if (
            direction is None
            and str(media_class).lower().startswith("stream/output/audio")
            and isinstance(node.properties.get("open-cinema.plugin.id"), str)
            and isinstance(node.properties.get("open-cinema.instance.id"), str)
        ):
            # A managed playback stream outputs audio into the Open Cinema graph,
            # so it is presented as an input endpoint rather than a physical sink.
            direction = EndpointDirection.INPUT
        if direction is None:
            continue
        device = snapshot.devices_by_id.get(node.device_id)
        device_id = device.id if device is not None else None
        profiles = (
            _profile_summaries(snapshot, device_id) if device_id is not None else ()
        )
        routes = (
            _route_summaries(snapshot, device_id, profiles)
            if device_id is not None
            else ()
        )
        formats, volume, mute, controls_writable = _audio_capabilities(
            snapshot,
            node.id,
            device_id,
            routes,
        )
        ports = tuple(
            EndpointPortSummary(
                name=port.name,
                direction=port.direction.value,
                channel=port.channel,
                properties=port.properties,
            )
            for port in sorted(
                (
                    snapshot.ports_by_id[port_id]
                    for port_id in (*node.input_port_ids, *node.output_port_ids)
                    if port_id in snapshot.ports_by_id
                ),
                key=lambda value: (value.direction.value, value.name or "", value.id),
            )
        )
        target = (
            snapshot.defaults.audio_source
            if direction == EndpointDirection.INPUT
            else snapshot.defaults.audio_sink
        )
        candidates.append(
            RuntimeEndpointCandidate(
                runtime=RuntimeEndpointReference(
                    generation=snapshot.generation,
                    node_id=node.id,
                    device_id=device_id,
                ),
                direction=direction,
                name=node.name,
                description=node.description,
                media_class=str(media_class),
                node_state=node.state.value,
                node_error=node.error,
                node_properties=node.properties,
                device_name=device.name if device is not None else None,
                device_description=device.description if device is not None else None,
                device_media_class=device.media_class if device is not None else None,
                device_properties=(
                    device.properties if device is not None else FrozenDict()
                ),
                ports=ports,
                profiles=profiles,
                routes=routes,
                formats=formats,
                volume=volume,
                mute=mute,
                latency=_latency(node.properties),
                is_default=(target is not None and target.resolved_node_id == node.id),
                is_linked=node.id in linked_node_ids,
                has_active_signal=node.state == NodeState.RUNNING,
                volume_writable=controls_writable,
                mute_writable=controls_writable,
            )
        )
    return EndpointInventorySnapshot(
        generation=snapshot.generation,
        sequence=snapshot.sequence,
        captured_at=snapshot.captured_at,
        candidates=tuple(
            sorted(
                candidates,
                key=lambda candidate: (
                    candidate.direction.value,
                    candidate.name or "",
                    candidate.runtime.node_id,
                ),
            )
        ),
    )
