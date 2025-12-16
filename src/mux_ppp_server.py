import asyncio
import struct
from collections import deque

# Header: type(1) priority(1) stream_id(2) payload_len(4)
HDR_FMT = "!BBHI"
HDR_LEN = struct.calcsize(HDR_FMT)

OPEN  = 1
DATA  = 2
CLOSE = 3

def encode_frame(msg_type: int, priority: int, stream_id: int, payload: bytes = b"") -> bytes:
    return struct.pack(HDR_FMT, msg_type, priority, stream_id, len(payload)) + payload

async def read_exact(r: asyncio.StreamReader, n: int) -> bytes:
    return await r.readexactly(n)

async def read_frame(r: asyncio.StreamReader):
    hdr = await read_exact(r, HDR_LEN)
    msg_type, priority, stream_id, payload_len = struct.unpack(HDR_FMT, hdr)
    payload = await read_exact(r, payload_len) if payload_len else b""
    return msg_type, priority, stream_id, payload


class PPP:
    """
    PPP keeps priority queues and decides what to send next over ONE TCP tunnel.
    Priority 7 = highest, 0 = lowest
    """
    def __init__(self, writer: asyncio.StreamWriter):
        self.writer = writer
        self.queues = {p: deque() for p in range(8)}  # 0..7
        self.running = True

        # simple "bandwidth shaping": bytes per tick
        # pretend link is constrained; change this number to see effect
        self.bytes_per_tick = 200

    def enqueue(self, priority: int, frame: bytes):
        priority = max(0, min(7, priority))
        self.queues[priority].append(frame)

    async def scheduler_loop(self):
        """
        Each tick, we can send only bytes_per_tick bytes.
        We always drain higher priority queues first.
        """
        while self.running:
            budget = self.bytes_per_tick

            for prio in range(7, -1, -1):  # 7 -> 0
                while self.queues[prio] and budget > 0:
                    frame = self.queues[prio][0]
                    if len(frame) > budget:
                        # Not enough budget this tick; wait for next tick.
                        break

                    self.queues[prio].popleft()
                    self.writer.write(frame)
                    budget -= len(frame)

            await self.writer.drain()

            # tick interval = how often we schedule sends
            await asyncio.sleep(0.05)

    def set_link_bandwidth(self, bytes_per_tick: int):
        self.bytes_per_tick = max(50, bytes_per_tick)


async def main():
    r, w = await asyncio.open_connection("127.0.0.1", 9000)
    ppp = PPP(w)

    # Start scheduler
    sched_task = asyncio.create_task(ppp.scheduler_loop())

    # Two streams, both to the same dummy target for demo
    # Stream 1 = HIGH priority (telemetry/control)
    # Stream 2 = LOW priority (bulk)
    STREAM_HIGH = 1
    STREAM_LOW  = 2
    target = b"127.0.0.1:7777"

    # OPEN both streams
    ppp.enqueue(7, encode_frame(OPEN, priority=7, stream_id=STREAM_HIGH, payload=target))
    ppp.enqueue(1, encode_frame(OPEN, priority=1, stream_id=STREAM_LOW,  payload=target))

    # Enqueue data: High priority sends short messages more frequently.
    async def produce_high():
        i = 0
        while i < 20:
            msg = f"HIGH-{i}\n".encode()
            ppp.enqueue(7, encode_frame(DATA, priority=7, stream_id=STREAM_HIGH, payload=msg))
            i += 1
            await asyncio.sleep(0.10)

    async def produce_low():
        i = 0
        while i < 10:
            msg = (f"low-bulk-{i} " + ("X" * 80) + "\n").encode()
            ppp.enqueue(1, encode_frame(DATA, priority=1, stream_id=STREAM_LOW, payload=msg))
            i += 1
            await asyncio.sleep(0.15)

    # Simulate bandwidth changing (like degraded network)
    async def bandwidth_changes():
        # Start "okay"
        ppp.set_link_bandwidth(250)
        await asyncio.sleep(1.0)
        # Degrade
        print("[PPP] Link degraded: less bandwidth")
        ppp.set_link_bandwidth(120)
        await asyncio.sleep(1.0)
        # Recover
        print("[PPP] Link recovered: more bandwidth")
        ppp.set_link_bandwidth(300)

    # Reader loop: print replies coming back from DCS (which come from target)
    async def read_replies():
        try:
            while True:
                msg_type, prio, sid, payload = await read_frame(r)
                if msg_type == DATA:
                    print(f"[PPP] RX stream={sid}: {payload!r}")
                elif msg_type == CLOSE:
                    print(f"[PPP] RX CLOSE stream={sid}")
        except asyncio.IncompleteReadError:
            pass

    await asyncio.gather(
        produce_high(),
        produce_low(),
        bandwidth_changes(),
        read_replies(),
    )

    # Close streams
    ppp.enqueue(7, encode_frame(CLOSE, priority=7, stream_id=STREAM_HIGH))
    ppp.enqueue(1, encode_frame(CLOSE, priority=1, stream_id=STREAM_LOW))
    await asyncio.sleep(0.2)

    ppp.running = False
    sched_task.cancel()

    w.close()
    await w.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
