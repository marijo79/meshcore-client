# MeshCore CLI

Python CLI for sending and receiving messages over a MeshCore companion radio connected via USB serial.

## Requirements

- Seeed XIAO ESP32-S3 + WIO-SX1262, flashed with MeshCore companion firmware
- Python 3.12+, dependencies installed in `.venv`

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
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

## Configuration

All tunables live in `.env` in the project root. Copy and edit as needed:

```bash
cp .env .env.local  # optional — .env is already read directly
```

| Variable | Default | Description |
|---|---|---|
| `MESHCORE_PORT` | `/dev/ttyACM0` | Serial port the companion radio is connected to |
| `MESHCORE_BAUDRATE` | `115200` | Baud rate (must match firmware) |
| `MESHCORE_CHANNEL` | `#mv` | Channel name used by `setup`, `send`, and `recv` |
| `MESHCORE_CHANNEL_KEY` | *(none)* | Encryption key as a 32-char hex string (16 bytes). Required for channels whose name does not start with `#`. |
| `MESHCORE_LOG_FILE` | `messages.jsonl` | Path to the message log; relative paths resolve from the project root |
| `MESHCORE_CONNECT_WAIT` | `2.5` | Seconds to wait after the ESP32-S3 USB-triggered reset before sending commands |

### Channel key behaviour

- **`#`-prefixed channels** (e.g. `#mv`): the key is derived automatically from the channel name via SHA-256. Leave `MESHCORE_CHANNEL_KEY` unset.
- **Named channels** (e.g. `Public`): you must supply the matching 32-char hex key so the device uses the same key as other nodes on that channel.

```bash
# Join the MeshCore default "Public" channel
MESHCORE_CHANNEL=Public
MESHCORE_CHANNEL_KEY=<32-char hex key for Public>
```

Shell environment variables always take precedence over `.env`:

```bash
MESHCORE_PORT=/dev/ttyUSB0 python -u main.py recv
```

To find which port the device is on:

```bash
ls /dev/tty{ACM,USB}*
# or
dmesg | grep tty | tail -5
```

The ESP32-S3 resets on every USB serial open, so the script waits `MESHCORE_CONNECT_WAIT` seconds after connecting before sending the first command.

If you get `ERROR: Device did not respond to appstart`, check that:
1. No other process is holding the port (`fuser /dev/ttyACM0`)
2. The device is flashed with companion firmware (not repeater/router firmware)
3. Try increasing `MESHCORE_CONNECT_WAIT` to `4.0` or higher on slow hardware