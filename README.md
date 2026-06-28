# MeshCore CLI

Python CLI for sending and receiving messages over a MeshCore companion radio connected via USB serial.

## Requirements

- Seeed XIAO ESP32-S3 + WIO-SX1262, flashed with MeshCore companion firmware
- Python 3.12+, dependencies installed in `.venv`

```bash
pip install meshcore meshcore-cli
```

## Usage

### List channels

```bash
python -u main.py channels
```

### Create a channel

```bash
python -u main.py setup
```

Creates channel `#mv` on the device. The encryption key is derived automatically from the channel name — any other device that adds a channel with the same name will use the same key.

To use a different channel name, edit `CHANNEL_NAME` at the top of `main.py`.

### Send a message

```bash
python -u main.py send "hello world"
```

### Send a message periodically

```bash
python -u main.py periodic <seconds> "message text"
```

Sends the message to `#mv` repeatedly at the given interval. The period can be fractional (e.g. `30.5`). A timestamped confirmation is printed after each send. Press `Ctrl+C` to stop.

```bash
# Send "ping" every 60 seconds
python -u main.py periodic 60 "ping"

# Send every 5 minutes
python -u main.py periodic 300 "status check"
```

> **Note:** Only one process can hold the serial port at a time. Do not run `periodic` and `recv` simultaneously.

### Receive messages

```bash
python -u main.py recv
```

On startup it replays the last 20 messages from the local log, then listens for new ones. Press `Ctrl+C` to stop.

All received messages are appended to `messages.jsonl` in the project directory, so history is preserved across restarts.

> **Note:** The ESP32-S3 resets on every serial port open, which clears its in-memory message buffer. Messages that arrived while `recv` was not running are lost and cannot be recovered from the device. Keep `recv` running in the background to avoid gaps.

> **Note:** Only one process can hold the serial port at a time. Make sure no other instance of `main.py` is running before starting `recv`.

## Device

The device connects on `/dev/ttyACM0` at 115200 baud. The ESP32-S3 resets on every USB serial open, so the script waits 2.5 seconds after connecting before sending the first command. Edit `PORT` or the sleep duration at the top of `main.py` if needed.

If you get `ERROR: Device did not respond to appstart`, check that:
1. No other process is holding the port (`fuser /dev/ttyACM0`)
2. The device is flashed with companion firmware (not repeater/router firmware)