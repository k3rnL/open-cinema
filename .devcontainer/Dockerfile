FROM ubuntu:latest
LABEL authors="erwandaniel"

RUN apt update && apt install -y \
    libpulse-dev libavutil-dev libavformat-dev \
    libavfilter-dev libavdevice-dev libclang-dev \
    ffmpeg wget pulseaudio sudo \
    git curl build-essential pkg-config libasound2-dev python3-dev \
    curl build-essential libalsaplayer-dev librust-alsa-sys-dev  # Should be in a build container

RUN echo "ubuntu ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/ubuntu \
    && chmod 440 /etc/sudoers.d/ubuntu

# Install Rust for building CamillaDSP
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

# Build CamillaDSP from source with PulseAudio support
RUN mkdir ~/camilladsp ~/camilladsp/coeffs ~/camilladsp/configs && \
    cd /tmp && \
    git clone --depth 1 --branch v3.0.1 https://github.com/HEnquist/camilladsp.git && \
    cd camilladsp && \
    cargo build --release --features pulse-backend && \
    cp target/release/camilladsp /usr/local/bin/ && \
    cd / && rm -rf /tmp/camilladsp

RUN wget https://github.com/HEnquist/camillagui-backend/releases/download/v3.0.3/bundle_linux_aarch64.tar.gz -O ~/camilladsp/bundle_linux_aarch64.tar.gz && \
    tar -xvf ~/camilladsp/bundle_linux_aarch64.tar.gz -C /opt/

RUN wget https://raw.githubusercontent.com/mdsimon2/RPi-CamillaDSP/main/camillagui.service -O /lib/systemd/system/camillagui.service && \
    sed -i "s|username|$(id -u -n)|g" /lib/systemd/system/camillagui.service && \
    systemctl enable camillagui

RUN curl -LsSf https://astral.sh/uv/install.sh | sh

COPY entrypoint.sh /entrypoint.sh
COPY camilladsp/default.yml /etc/camilladsp/default.yml

RUN chmod +x /entrypoint.sh && mkdir -p /etc/camilladsp

EXPOSE 5005 1234

ENTRYPOINT ["/entrypoint.sh"]