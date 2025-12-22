import asyncio
import struct
import socket

MAGIC = b"PPP1"
VERSION = 1

MSG_OPEN  = 1
MSG_DATA  = 2
MSG_CLOSE = 3

ATYP_NONE   = 0
ATYP_IPV4   = 1
ATYP_DOMAIN = 3

HDR_FMT = "!4sBBBBIHH"
HDR_LEN = struct.calcsize(HDR_FMT)

BUFFER = 64 * 1024


def encode_frame(msg_type: int, flags: int, atyp: int, stream_id: int, meta: bytes = b"", payload: bytes = b"") -> bytes:
    hdr = struct.pack(HDR_FMT, MAGIC, VERSION, msg_type, flags, atyp, stream_id, len(meta), len(payload))
    return hdr + meta + payload


async def read_exact(reader: asyncio.StreamReader, n: int) -> bytes:
    return await reader.readexactly(n)


async def read_frame(reader: asyncio.StreamReader):
    hdr = await read_exact(reader, HDR_LEN)
    magic, ver, msg_type, flags, atyp, stream_id, meta_len, payload_len = struct.unpack(HDR_FMT, hdr)
    meta = await read_exact(reader, meta_len) if meta_len else b""
    payload = await read_exact(reader, payload_len) if payload_len else b""
    return msg_type, flags, atyp, stream_id, meta, payload


def open_meta_domain(host: str, port: int) -> tuple[int, bytes]:
    hb = host.encode("utf-8")
    meta = bytes([len(hb)]) + hb + struct.pack("!H", port)
    return ATYP_DOMAIN, meta


async def main():
    r, w = await asyncio.open_connection("127.0.0.1", 9000)

    # Open two independent streams over the SAME TCP connection
    sid1 = 1
    sid2 = 2

    atyp1, meta1 = open_meta_domain("example.com", 80)
    atyp2, meta2 = open_meta_domain("httpbin.org", 80)

    w.write(encode_frame(MSG_OPEN, 0, atyp1, sid1, meta=meta1))
    w.write(encode_frame(MSG_OPEN, 0, atyp2, sid2, meta=meta2))
    await w.drain()

    # Send HTTP GETs on both streams
    w.write(encode_frame(MSG_DATA, 0, ATYP_NONE, sid1, payload=b"GET / HTTP/1.1\r\nHost: example.com\r\n\r\n"))
    w.write(encode_frame(MSG_DATA, 0, ATYP_NONE, sid2, payload=b"GET /ip HTTP/1.1\r\nHost: httpbin.org\r\n\r\n"))
    await w.drain()

    # Read responses (interleaved)
    # In a real PPP you'd dispatch by stream_id to per-stream buffers/handlers
    for _ in range(10):
        msg_type, flags, atyp, stream_id, meta, payload = await read_frame(r)
        if msg_type == MSG_DATA:
            print(f"\n--- DATA stream={stream_id} ---\n{payload[:500]!r}\n")
        elif msg_type == MSG_OPEN:
            print(f"[OPEN-ACK] stream={stream_id}")
        elif msg_type == MSG_CLOSE:
            print(f"[CLOSE] stream={stream_id} reason={payload!r}")
            break

    # Close both streams
    w.write(encode_frame(MSG_CLOSE, 0, ATYP_NONE, sid1))
    w.write(encode_frame(MSG_CLOSE, 0, ATYP_NONE, sid2))
    await w.drain()

    w.close()
    await w.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
