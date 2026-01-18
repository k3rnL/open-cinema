#!/usr/bin/env bash

set -e

echo "Starting PulseAudio..."

# Remove old pipes if they exist
rm -f /tmp/pa.input /tmp/pa.output

# Create fresh pipe files
mkfifo /tmp/pa.input
mkfifo /tmp/pa.output

# Start PulseAudio with pipe source and sink
pulseaudio -D -n \
    -L "module-pipe-source source_name=fifo_input file=/tmp/pa.input rate=48000 format=S16LE channels=2" \
    -L "module-pipe-sink sink_name=fifo_output file=/tmp/pa.output rate=48000 format=float32LE channels=6" \
    -L module-native-protocol-unix \
    -L module-native-protocol-tcp \
    --exit-idle-time=1000000

# Wait for PulseAudio to start
sleep 2

# Verify PulseAudio modules loaded
echo "Checking PulseAudio status..."
pactl list sources short | grep fifo_input && echo "✓ Source fifo_input loaded" || echo "✗ Source fifo_input FAILED"
pactl list sinks short | grep fifo_output && echo "✓ Sink fifo_output loaded" || echo "✗ Sink fifo_output FAILED"

echo "Starting CamillaDSP..."
# Start CamillaDSP with websocket enabled (use copied config from Dockerfile)
camilladsp -p 1234 -a 0.0.0.0 /etc/camilladsp/default.yml &

# Wait a moment for CamillaDSP to start
sleep 2

echo "Starting CamillaGUI..."
service camillagui start 2>/dev/null || echo "CamillaGUI service not available (optional)"

echo "==================================="
echo "Development environment ready!"
echo "PulseAudio: Running"
echo "CamillaDSP: Running on websocket port 1234"
echo "CamillaGUI: Check service status"
echo "==================================="

exec bash
