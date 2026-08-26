FROM debian:trixie-slim

ARG TARGETARCH
ARG UV_VERSION=0.9.28

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       bash ca-certificates curl sudo git build-essential pkg-config \
       python3 python3-dev python3-venv python3-pip \
       pipewire pipewire-alsa pipewire-bin wireplumber \
       libpipewire-0.3-dev libwireplumber-0.5-dev libspa-0.2-bluetooth \
       dbus-daemon dbus-user-session \
       libavutil-dev libavformat-dev libavfilter-dev libavdevice-dev \
       redis-tools \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash --groups audio,video opencinema \
    && echo "opencinema ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/opencinema \
    && chmod 0440 /etc/sudoers.d/opencinema

RUN set -eux; \
    case "${TARGETARCH}" in \
      arm64) uv_arch="aarch64-unknown-linux-gnu" ;; \
      amd64) uv_arch="x86_64-unknown-linux-gnu" ;; \
      *) echo "Unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSLo /tmp/uv.tar.gz \
      "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-${uv_arch}.tar.gz"; \
    tar -xzf /tmp/uv.tar.gz -C /tmp; \
    install -m 0755 "/tmp/uv-${uv_arch}/uv" /usr/local/bin/uv; \
    rm -rf /tmp/uv.tar.gz "/tmp/uv-${uv_arch}"

COPY pipewire/90-open-cinema-dev.conf /etc/pipewire/pipewire.conf.d/90-open-cinema-dev.conf
COPY wireplumber/91-open-cinema-policy.conf /etc/wireplumber/wireplumber.conf.d/91-open-cinema-policy.conf
COPY entrypoint.sh start-pipewire.sh /usr/local/lib/open-cinema-dev/
COPY fakes/ /usr/local/lib/open-cinema-dev/fakes/
RUN chmod 0644 \
      /etc/pipewire/pipewire.conf.d/90-open-cinema-dev.conf \
      /etc/wireplumber/wireplumber.conf.d/91-open-cinema-policy.conf \
    && chmod 0755 /usr/local/lib/open-cinema-dev/*.sh /usr/local/lib/open-cinema-dev/fakes/*.py

ENV XDG_RUNTIME_DIR=/tmp/open-cinema-runtime
ENV DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/open-cinema-runtime/bus
ENV PIPEWIRE_REMOTE=pipewire-0
ENV OPEN_CINEMA_DECODER_FIXTURES=/pcm-auto-decoder/tests/fixtures/codec_status.ndjson

USER opencinema
WORKDIR /workspace
ENTRYPOINT ["/usr/local/lib/open-cinema-dev/entrypoint.sh"]
CMD ["sleep", "infinity"]
