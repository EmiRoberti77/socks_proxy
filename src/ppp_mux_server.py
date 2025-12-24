import asyncio
import struct
import socket
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

MAGIC = b"PPP1"
VERSION = 1

# Message types
MSG_OPEN  = 1
MSG_DATA  = 2
MSG_CLOSE = 3

# Address types (match SOCKS-ish values)
ATYP_NONE   = 0
ATYP_IPV4   = 1
ATYP_DOMAIN = 3

# Fixed header: magic(4) ver(1) type(1) flags(1) atyp(1) stream_id(4) meta_len(2) payload_len(2)
HDR_FMT = "!4sBBBBIHH"
HDR_LEN = struct.calcsize(HDR_FMT)

BUFFER = 64 * 1024


@dataclass
class Frame:
    msg_type: int
    flags: int
    atyp: int
    stream_id: int
    meta: bytes
    payload: bytes


async def read_exact(reader: asyncio.StreamReader, n: int) -> bytes:
    return await reader.readexactly(n)


async def read_frame(reader: asyncio.StreamReader) -> Frame:
    hdr = await read_exact(reader, HDR_LEN)
    magic, ver, msg_type, flags, atyp, stream_id, meta_len, payload_len = struct.unpack(HDR_FMT, hdr)

    if magic != MAGIC:
        raise ValueError(f"Bad magic: {magic!r}")
    if ver != VERSION:
        raise ValueError(f"Unsupported version: {ver}")

    meta = await read_exact(reader, meta_len) if meta_len else b""
    payload = await read_exact(reader, payload_len) if payload_len else b""

    return Frame(msg_type=msg_type, flags=flags, atyp=atyp, stream_id=stream_id, meta=meta, payload=payload)


def encode_frame(msg_type: int, flags: int, atyp: int, stream_id: int, meta: bytes = b"", payload: bytes = b"") -> bytes:
    meta_len = len(meta)
    payload_len = len(payload)
    hdr = struct.pack(HDR_FMT, MAGIC, VERSION, msg_type, flags, atyp, stream_id, meta_len, payload_len)
    return hdr + meta + payload


def parse_open_meta(atyp: int, meta: bytes) -> Tuple[str, int]:
    """
    OPEN meta encodes destination.
    IPV4: 4 bytes ip + 2 bytes port
    DOMAIN: 1 byte len + domain + 2 bytes port
    """
    if atyp == ATYP_IPV4:
        if len(meta) != 6:
            raise ValueError("Bad IPV4 meta length")
        host = socket.inet_ntoa(meta[0:4])
        port = struct.unpack("!H", meta[4:6])[0]
        return host, port

    if atyp == ATYP_DOMAIN:
        if len(meta) < 1 + 2:
            raise ValueError("Bad DOMAIN meta length")
        ln = meta[0]
        if len(meta) != 1 + ln + 2:
            raise ValueError("Bad DOMAIN meta length")
        host = meta[1:1+ln].decode("utf-8", errors="replace")
        port = struct.unpack("!H", meta[1+ln:1+ln+2])[0]
        return host, port

    raise ValueError(f"Unsupported atyp: {atyp}")


class StreamState:
    """
    Represents one muxed stream_id -> one outbound TCP connection to a target.
    """
    def __init__(self, target_writer: asyncio.StreamWriter, target_reader: asyncio.StreamReader):
        self.target_writer = target_writer
        self.target_reader = target_reader
        self.closed = False


async def target_to_mux(stream_id: int, state: StreamState, mux_writer: asyncio.StreamWriter):
    """
    Read from target socket, send DATA frames back upstream.
    """
    try:
        while True:
            data = await state.target_reader.read(BUFFER)
            if not data:
                break
            mux_writer.write(encode_frame(MSG_DATA, flags=0, atyp=ATYP_NONE, stream_id=stream_id, payload=data))
            await mux_writer.drain()
    except Exception:
        pass
    finally:
        # Tell upstream we're done
        try:
            mux_writer.write(encode_frame(MSG_CLOSE, flags=0, atyp=ATYP_NONE, stream_id=stream_id, payload=b"eof"))
            await mux_writer.drain()
        except Exception:
            pass


async def handle_mux_connection(mux_reader: asyncio.StreamReader, mux_writer: asyncio.StreamWriter):
    peer = mux_writer.get_extra_info("peername")
    print(f"[mux] connected: {peer}")

    streams: Dict[int, StreamState] = {}
    back_tasks: Dict[int, asyncio.Task] = {}

    async def close_stream(stream_id: int, reason: bytes = b""):
        state = streams.get(stream_id)
        if not state:
            return
        if state.closed:
            return
        state.closed = True
        try:
            state.target_writer.close()
            await state.target_writer.wait_closed()
        except Exception:
            pass
        task = back_tasks.pop(stream_id, None)
        if task:
            task.cancel()
        streams.pop(stream_id, None)

    try:
        while True:
            frame = await read_frame(mux_reader)

            if frame.msg_type == MSG_OPEN:
                # OPEN: create outbound connection to target based on meta
                try:
                    host, port = parse_open_meta(frame.atyp, frame.meta)
                    tr, tw = await asyncio.open_connection(host, port)
                    state = StreamState(target_writer=tw, target_reader=tr)
                    streams[frame.stream_id] = state

                    # Ack OPEN (optional). Here we reuse OPEN with empty meta/payload as "OK"
                    mux_writer.write(encode_frame(MSG_OPEN, flags=0, atyp=ATYP_NONE, stream_id=frame.stream_id))
                    await mux_writer.drain()

                    # Start target->mux pump
                    back_tasks[frame.stream_id] = asyncio.create_task(target_to_mux(frame.stream_id, state, mux_writer))
                    print(f"[mux] OPEN stream={frame.stream_id} -> {host}:{port}")

                except Exception as e:
                    # Send CLOSE with error reason
                    msg = f"open_failed:{type(e).__name__}".encode()
                    mux_writer.write(encode_frame(MSG_CLOSE, flags=0, atyp=ATYP_NONE, stream_id=frame.stream_id, payload=msg))
                    await mux_writer.drain()

            elif frame.msg_type == MSG_DATA:
                # DATA: forward payload to the target for that stream_id
                state = streams.get(frame.stream_id)
                if not state or state.closed:
                    # Stream not open; ignore or close upstream stream
                    continue
                try:
                    state.target_writer.write(frame.payload)
                    await state.target_writer.drain()
                except Exception:
                    await close_stream(frame.stream_id, reason=b"write_failed")

            elif frame.msg_type == MSG_CLOSE:
                # CLOSE: shutdown that stream
                await close_stream(frame.stream_id, reason=frame.payload)

            else:
                # Unknown message; ignore or terminate
                pass

    except asyncio.IncompleteReadError:
        print(f"[mux] disconnected: {peer}")
    finally:
        # Cleanup all streams
        for sid in list(streams.keys()):
            await close_stream(sid)
        try:
            mux_writer.close()
            await mux_writer.wait_closed()
        except Exception:
            pass


async def main(host="0.0.0.0", port=9000):
    server = await asyncio.start_server(handle_mux_connection, host, port)
    addrs = ", ".join(str(s.getsockname()) for s in server.sockets or [])
    print(f"PPP mux server listening on {addrs}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
