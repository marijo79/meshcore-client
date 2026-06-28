import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
import serial_asyncio_fast as serial_asyncio
from dotenv import load_dotenv
from meshcore import MeshCore
from meshcore.serial_cx import SerialConnection
from meshcore.events import EventType

load_dotenv(Path(__file__).parent / ".env")

PORT         = os.environ.get("MESHCORE_PORT", "/dev/ttyACM0")
BAUDRATE     = int(os.environ.get("MESHCORE_BAUDRATE", "115200"))
CHANNEL_NAME = os.environ.get("MESHCORE_CHANNEL", "#mv")
CONNECT_WAIT = float(os.environ.get("MESHCORE_CONNECT_WAIT", "2.5"))
_log_path    = os.environ.get("MESHCORE_LOG_FILE", "messages.jsonl")
LOG_FILE     = Path(_log_path) if Path(_log_path).is_absolute() else Path(__file__).parent / _log_path

_key_hex     = os.environ.get("MESHCORE_CHANNEL_KEY")
if _key_hex:
    if len(_key_hex) != 32:
        print(f"ERROR: MESHCORE_CHANNEL_KEY must be exactly 32 hex characters (16 bytes), got {len(_key_hex)}")
        sys.exit(1)
    CHANNEL_KEY: bytes | None = bytes.fromhex(_key_hex)
else:
    CHANNEL_KEY = None


class NoDTRSerialConnection(SerialConnection):
    """Opens the serial port with DTR disabled and waits for ESP32-S3 to finish
    its USB-triggered reset before returning, so send_appstart doesn't fire too early.
    """
    async def connect(self, timeout: float = 10.0):
        self._connected_event.clear()
        loop = asyncio.get_running_loop()
        await serial_asyncio.create_serial_connection(
            loop,
            lambda: self.MCSerialClientProtocol(self),
            self.port,
            baudrate=self.baudrate,
            dsrdtr=False,
        )
        await asyncio.wait_for(self._connected_event.wait(), timeout=timeout)
        await asyncio.sleep(CONNECT_WAIT)  # wait for ESP32-S3 reset + boot to finish
        return self.port


async def connect() -> MeshCore:
    cx = NoDTRSerialConnection(PORT, BAUDRATE)
    mc = MeshCore(cx)
    res = await mc.connect()
    if res is None:
        print("ERROR: Device did not respond to appstart.")
        sys.exit(1)
    return mc


async def find_or_add_channel(mc: MeshCore, name: str, key: bytes | None = None) -> int:
    """Return the channel index for `name`, creating it if not found."""
    for idx in range(8):
        event = await mc.commands.get_channel(idx)
        if event and event.type == EventType.CHANNEL_INFO:
            ch = event.payload
            ch_name = ch.get("channel_name", "")
            if ch_name == name:
                print(f"Channel '{name}' already exists at slot {idx}")
                return idx
            if not ch_name:
                key_note = f" (custom key)" if key else ""
                print(f"Adding channel '{name}' at slot {idx}{key_note}")
                await mc.commands.set_channel(idx, name, key)
                return idx
    print(f"ERROR: No free channel slots (checked 0-7)")
    sys.exit(1)


async def list_channels(mc: MeshCore):
    print("Channels:")
    for idx in range(8):
        event = await mc.commands.get_channel(idx)
        if event and event.type == EventType.CHANNEL_INFO:
            ch = event.payload
            name = ch.get("channel_name", "")
            if name:
                print(f"  [{idx}] {name}")


async def send_mode(mc: MeshCore, chan_idx: int, message: str):
    print(f"Sending to {CHANNEL_NAME} (slot {chan_idx}): {message!r}")
    event = await mc.commands.send_chan_msg(chan_idx, message)
    if event and event.type == EventType.OK:
        print("Sent OK")
    else:
        print(f"Send result: {event}")


def format_msg(ts: str, chan_idx, text: str, sender: str = None) -> str:
    if chan_idx is not None:
        return f"[{ts}] [#{chan_idx}] {text}"
    return f"[{ts}] [DM from {sender or 'unknown'}] {text}"


def log_and_print(ts: str, chan_idx, text: str, sender: str = None):
    line = format_msg(ts, chan_idx, text, sender)
    print(line, flush=True)
    entry = {"ts": ts, "channel_idx": chan_idx, "text": text, "sender": sender}
    with LOG_FILE.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def print_msg(event):
    data = event.payload
    chan_idx = data.get("channel_idx", None)
    text = data.get("text", data.get("msg", ""))
    sender = data.get("sender_name", data.get("pubkey_prefix")) if chan_idx is None else None
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_and_print(ts, chan_idx, text, sender)


def show_history(n: int = 20):
    if not LOG_FILE.exists():
        return
    lines = LOG_FILE.read_text().splitlines()
    recent = lines[-n:] if len(lines) > n else lines
    if recent:
        print(f"--- last {len(recent)} messages from log ---")
        for raw in recent:
            try:
                e = json.loads(raw)
                print(format_msg(e["ts"], e["channel_idx"], e["text"], e.get("sender")))
            except (json.JSONDecodeError, KeyError):
                pass
        print("--- live ---")


async def drain_messages(mc: MeshCore):
    """Pull all pending messages from the device one by one until NO_MORE_MSGS.
    Printing is handled by the CHANNEL_MSG_RECV / CONTACT_MSG_RECV subscriptions.
    """
    while True:
        event = await mc.commands.get_msg()
        if event is None or event.type == EventType.NO_MORE_MSGS:
            break


async def periodic_mode(mc: MeshCore, chan_idx: int, message: str, period: float):
    print(f"Sending {message!r} to {CHANNEL_NAME} (slot {chan_idx}) every {period}s. Ctrl+C to stop.")
    try:
        while True:
            event = await mc.commands.send_chan_msg(chan_idx, message)
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            status = "OK" if event and event.type == EventType.OK else repr(event)
            print(f"[{ts}] Sent: {status}")
            await asyncio.sleep(period)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass


async def receive_mode(mc: MeshCore, chan_idx: int):
    show_history()

    mc.subscribe(EventType.CHANNEL_MSG_RECV, lambda e: print_msg(e))
    mc.subscribe(EventType.CONTACT_MSG_RECV, lambda e: print_msg(e))

    async def on_messages_waiting(_event):
        await drain_messages(mc)

    mc.subscribe(EventType.MESSAGES_WAITING, on_messages_waiting)
    await drain_messages(mc)

    print("Type a message and press Enter to send. Ctrl+C to quit.")

    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)

    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            message = line.decode().rstrip("\n").strip()
            if message:
                await mc.commands.send_chan_msg(chan_idx, message)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass


async def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("setup", "send", "recv", "channels", "periodic"):
        print("Usage:")
        print("  python main.py setup                         - create #mv channel on device")
        print("  python main.py channels                      - list all channels")
        print("  python main.py send <message>                - send message to #mv")
        print("  python main.py recv                          - show history + listen for messages")
        print("  python main.py periodic <seconds> <message>  - send message repeatedly at interval")
        sys.exit(0)

    cmd = sys.argv[1]

    print(f"Connecting to {PORT}...")
    mc = await connect()
    print(f"Connected. Node: {mc.self_info.get('adv_name', '?')}")

    if cmd == "channels":
        await list_channels(mc)

    elif cmd == "setup":
        chan_idx = await find_or_add_channel(mc, CHANNEL_NAME, CHANNEL_KEY)
        print(f"Done. Channel '{CHANNEL_NAME}' is at slot {chan_idx}.")
        print(f"Set the same channel on your other device to start messaging.")

    elif cmd == "send":
        if len(sys.argv) < 3:
            print("Usage: python main.py send <message>")
            sys.exit(1)
        message = " ".join(sys.argv[2:])
        chan_idx = await find_or_add_channel(mc, CHANNEL_NAME, CHANNEL_KEY)
        await send_mode(mc, chan_idx, message)

    elif cmd == "recv":
        chan_idx = await find_or_add_channel(mc, CHANNEL_NAME, CHANNEL_KEY)
        print(f"Channel '{CHANNEL_NAME}' is slot {chan_idx}")
        await receive_mode(mc, chan_idx)

    elif cmd == "periodic":
        if len(sys.argv) < 4:
            print("Usage: python main.py periodic <seconds> <message>")
            sys.exit(1)
        try:
            period = float(sys.argv[2])
        except ValueError:
            print(f"ERROR: period must be a number, got {sys.argv[2]!r}")
            sys.exit(1)
        message = " ".join(sys.argv[3:])
        chan_idx = await find_or_add_channel(mc, CHANNEL_NAME, CHANNEL_KEY)
        await periodic_mode(mc, chan_idx, message, period)

    await mc.disconnect()


if __name__ == "__main__":
    asyncio.run(main())