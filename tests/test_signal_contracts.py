import pytest

from core.orchestration.signal_contracts import (
    AudioContent,
    ChannelLayout,
    KnownSampleFormat,
    LatencyRange,
    MediaKind,
    PortContract,
    PortDirection,
    SignalContract,
)


def test_audio_signal_contract_round_trip_is_canonical() -> None:
    contract = SignalContract(
        media_kind=MediaKind.AUDIO,
        content=AudioContent.PCM,
        sample_formats=(KnownSampleFormat.S32LE, KnownSampleFormat.S16LE),
        rates=(96000, 48000, 48000),
        layouts=(
            ChannelLayout(6, ("FL", "FR", "FC", "LFE", "SL", "SR")),
            ChannelLayout(2, ("FL", "FR")),
        ),
        latency=LatencyRange(minimum_ms=2.5, maximum_ms=40),
        capabilities=("volume", "mute"),
        required_capabilities=("clock-sync",),
    )

    document = contract.to_document()

    assert document["rates"] == [48000, 96000]
    assert document["sampleFormats"] == ["S16LE", "S32LE"]
    assert SignalContract.from_document(document) == contract


def test_compatible_ports_need_direction_format_and_capability_overlap() -> None:
    source = PortContract(
        name="output",
        direction=PortDirection.OUTPUT,
        signal=SignalContract(
            media_kind=MediaKind.AUDIO,
            content=AudioContent.PCM,
            rates=(48000, 96000),
            sample_formats=("S16LE", "S32LE"),
            layouts=(ChannelLayout(2, ("FL", "FR")),),
            capabilities=("volume", "mute"),
        ),
    )
    target = PortContract(
        name="input",
        direction=PortDirection.INPUT,
        signal=SignalContract(
            media_kind=MediaKind.AUDIO,
            content=AudioContent.PCM,
            rates=(48000,),
            sample_formats=("S16LE",),
            layouts=(ChannelLayout(2, ("FL", "FR")),),
            required_capabilities=("mute",),
        ),
    )

    assert source.compatibility_with(target).compatible is True


def test_incompatible_ports_report_each_contract_dimension() -> None:
    source = PortContract(
        name="encoded",
        direction=PortDirection.INPUT,
        signal=SignalContract(
            media_kind="audio",
            content="encoded",
            codecs=("ac3",),
            rates=(48000,),
            sample_formats=("S16LE",),
            layouts=(ChannelLayout(2, ("FL", "FR")),),
            latency=LatencyRange(100, 200),
            required_capabilities=("passthrough",),
        ),
    )
    target = PortContract(
        name="pcm",
        direction=PortDirection.OUTPUT,
        signal=SignalContract(
            media_kind="audio",
            content="pcm",
            codecs=("dts",),
            rates=(96000,),
            sample_formats=("FLOAT32LE",),
            layouts=(ChannelLayout(6),),
            latency=LatencyRange(0, 50),
            required_capabilities=("mute",),
        ),
    )

    result = source.compatibility_with(target)

    assert result.compatible is False
    assert set(result.reasons) == {
        "source_direction",
        "target_direction",
        "content",
        "codec",
        "sample_format",
        "rate",
        "layout",
        "latency",
        "source_capability",
        "target_capability",
    }


@pytest.mark.parametrize(
    "contract",
    (
        lambda: SignalContract(media_kind="control", content="pcm"),
        lambda: SignalContract(media_kind="audio", rates=(0,)),
        lambda: SignalContract(
            media_kind="audio",
            layouts=(ChannelLayout(2, ("FL",)),),
        ),
        lambda: SignalContract(
            media_kind="audio",
            latency=LatencyRange(20, 10),
        ),
    ),
)
def test_malformed_signal_contracts_are_rejected(contract) -> None:
    with pytest.raises(ValueError):
        contract()
