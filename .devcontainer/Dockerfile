FROM ubuntu:latest
LABEL authors="erwandaniel"

ARG TARGETOS
ARG TARGETARCH
ARG BUILDPLATFORM
ARG TARGETPLATFORM

RUN apt update && apt install -y \
    libpulse-dev libavutil-dev libavformat-dev \
    libavfilter-dev libavdevice-dev libclang-dev \
    ffmpeg wget pipewire dbus-user-session dbus-x11 sudo \
    git curl build-essential pkg-config libasound2-dev python3-dev \
    rsync libalsaplayer-dev librust-alsa-sys-dev \
    && rm -rf /var/lib/apt/lists/*

RUN echo "ubuntu ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/ubuntu \
    && chmod 440 /etc/sudoers.d/ubuntu

# Install Rust
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Build CamillaDSP from source
RUN mkdir -p ~/camilladsp ~/camilladsp/coeffs ~/camilladsp/configs && \
    cd /tmp && \
    wget https://github.com/HEnquist/camilladsp/releases/download/v4.0.0/camilladsp-linux-pipewire-${TARGETARCH}.tar.gz -O camilladsp.tar.gz && \
    tar -xvf camilladsp.tar.gz -C /usr/bin && \
    chmod +x /usr/bin/camilladsp

RUN wget https://github.com/HEnquist/camillagui-backend/releases/download/v4.0.0/bundle_linux_${TARGETARCH}.tar.gz -O ~/camilladsp/bundle_linux_${TARGETARCH}.tar.gz && \
    tar -xvf ~/camilladsp/bundle_linux_${TARGETARCH}.tar.gz -C /opt/

# Optional: avoid systemctl during docker build unless you really run systemd in container
RUN wget https://raw.githubusercontent.com/mdsimon2/RPi-CamillaDSP/main/camillagui.service \
      -O /lib/systemd/system/camillagui.service

# Install uv for the current arch
RUN set -eux; \
    case "${TARGETARCH}" in \
      arm64) UV_ARCH="aarch64-unknown-linux-gnu" ;; \
      amd64) UV_ARCH="x86_64-unknown-linux-gnu" ;; \
      *) echo "Unsupported TARGETARCH: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    cd /tmp && \
    wget "https://github.com/astral-sh/uv/releases/download/0.9.28/uv-${UV_ARCH}.tar.gz" && \
    tar -xzvf "uv-${UV_ARCH}.tar.gz" && \
    mv "uv-${UV_ARCH}"/uv /usr/bin/uv && \
    rm -rf /tmp/uv-*

RUN echo "export XDG_RUNTIME_DIR=/tmp/pipewire" >> /home/ubuntu/.bashrc

COPY entrypoint.sh /entrypoint.sh
COPY camilladsp/default.yml /etc/camilladsp/default.yml

RUN chmod +x /entrypoint.sh && mkdir -p /etc/camilladsp

EXPOSE 5005 1234

ENTRYPOINT ["/entrypoint.sh"]