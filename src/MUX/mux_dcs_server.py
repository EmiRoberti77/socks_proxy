import asyncio
import struct
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

# -----------------------
# Minimal PPP framing
# -----------------------
# Header: type(1) priority(1) stream_id(2) payload_len(4)
HDR_FMT = "!BBHI"
HDR_LEN = struct.calcsize(HDR_FMT)

OPEN  = 1
DATA  = 2
CLOSE = 3

BUFFER = 64 * 1024


@dataclass
class StreamState:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    back_task: asyncio.Task
    closed: bool = False


async def read_exact(r: asyncio.StreamReader, n: int) -> bytes:
    return await r.readexactly(n)


async def read_frame(r: asyncio.StreamReader) -> Tuple[int, int, int, bytes]:
    hdr = await read_exact(r, HDR_LEN)
    msg_type, priority, stream_id, payload_len = struct.unpack(HDR_FMT, hdr)
    payload = await read_exact(r, payload_len) if payload_len else b""
    return msg_type, priority, stream_id, payload


def encode_frame(msg_type: int, priority: int, stream_id: int, payload: bytes = b"") -> bytes:
    return struct.pack(HDR_FMT, msg_type, priority, stream_id, len(payload)) + payload


async def safe_send(writer: asyncio.StreamWriter, data: bytes) -> bool:
    """
    Return False if the connection is gone (prevents BrokenPipe noise).
    """
    try:
        writer.write(data)
        await writer.drain()
        return True
    except (BrokenPipeError, ConnectionResetError):
        return False
    except asyncio.CancelledError:
        return False
    except Exception:
        return False


def parse_target(payload: bytes) -> Tuple[str, int]:
    """
    OPEN payload is ASCII: b"ip:port" or b"hostname:port"
    """
    text = payload.decode("utf-8", errors="replace").strip()
    host, port_str = text.rsplit(":", 1)
    return host, int(port_str)


async def target_to_ppp(stream_id: int,
                        target_reader: asyncio.StreamReader,
                        ppp_writer: asyncio.StreamWriter):
    """
    Reads bytes from the target socket and forwards them back to PPP as DATA frames.
    Stops cleanly if PPP disconnects (no BrokenPipe).
    """
    try:
        while True:
            data = await target_reader.read(BUFFER)
            if not data:
                break

            ok = await safe_send(ppp_writer, encode_frame(DATA, 0, stream_id, data))
            if not ok:
                return  # PPP connection is gone; stop quietly

    except asyncio.CancelledError:
        return
    except Exception:
        # In a spike/simple server, just stop.
        return
    finally:
        # Try to send CLOSE (only if PPP still alive)
        await safe_send(ppp_writer, encode_frame(CLOSE, 0, stream_id))


async def handle_ppp(ppp_reader: asyncio.StreamReader, ppp_writer: asyncio.StreamWriter):
    peer = ppp_writer.get_extra_info("peername")
    print(f"[DCS] PPP connected: {peer}")

    streams: Dict[int, StreamState] = {}

    async def close_stream(stream_id: int):
        st = streams.get(stream_id)
        if not st or st.closed:
            return
        st.closed = True

        # Stop back task first (prevents it writing after close)
        st.back_task.cancel()
        await asyncio.gather(st.back_task, return_exceptions=True)

        # Close target socket
        try:
            st.writer.close()
            await st.writer.wait_closed()
        except Exception:
            pass

        streams.pop(stream_id, None)
        print(f"[DCS] stream closed: {stream_id}")

    try:
        while True:
            msg_type, priority, stream_id, payload = await read_frame(ppp_reader)

            if msg_type == OPEN:
                # Create outbound connection for this stream_id
                try:
                    host, port = parse_target(payload)
                    tr, tw = await asyncio.open_connection(host, port)
                except Exception as e:
                    # Let PPP know it failed (optional); CLOSE is simplest
                    await safe_send(ppp_writer, encode_frame(CLOSE, 0, stream_id, b"open_failed"))
                    print(f"[DCS] OPEN failed stream={stream_id}: {e}")
                    continue

                # Start the return path task
                back_task = asyncio.create_task(target_to_ppp(stream_id, tr, ppp_writer))
                streams[stream_id] = StreamState(reader=tr, writer=tw, back_task=back_task)

                print(f"[DCS] OPEN stream={stream_id} -> {host}:{port} (PPP priority={priority})")

                # Optional: ACK OPEN (can help debugging)
                await safe_send(ppp_writer, encode_frame(OPEN, 0, stream_id, b"ok"))

            elif msg_type == DATA:
                st = streams.get(stream_id)
                if not st or st.closed:
                    # Unknown stream; ignore (or CLOSE back)
                    continue

                try:
                    st.writer.write(payload)
                    await st.writer.drain()
                except Exception:
                    # If target write fails, close stream and notify PPP
                    await close_stream(stream_id)
                    await safe_send(ppp_writer, encode_frame(CLOSE, 0, stream_id, b"target_write_failed"))

            elif msg_type == CLOSE:
                await close_stream(stream_id)

            else:
                # Unknown message type - ignore for simplicity
                pass

    except asyncio.IncompleteReadError:
        # PPP disconnected
        print(f"[DCS] PPP disconnected: {peer}")

    finally:
        # Clean up all streams BEFORE closing PPP writer
        for sid in list(streams.keys()):
            await close_stream(sid)

        # Now close the PPP writer (don't let errors bubble)
        try:
            ppp_writer.close()
            await ppp_writer.wait_closed()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            pass


async def main(host: str = "127.0.0.1", port: int = 9000):
    server = await asyncio.start_server(handle_ppp, host, port)
    addrs = ", ".join(str(s.getsockname()) for s in server.sockets or [])
    print(f"[DCS] mux server listening on {addrs}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
