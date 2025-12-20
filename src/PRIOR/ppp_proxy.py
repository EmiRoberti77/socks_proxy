import asyncio
import struct
import time
from dataclasses import Field, dataclass, field
from typing import Any, Optional

HOST, PORT = ('127.0.0.1', 9001) 

# priority:0 highest, 255 lowest
PRIO_CONTROL = 0
PRIO_DATA = 50

TYPE_MAPPING = 1
TYPE_TELEMETRY = 2
TYPE_VIDEO = 3

@dataclass(order=True)
class OutMsg():
    priority:int
    seq:int
    msg_type:int = field(compare=False)
    channel:int = field(compare=False)
    payload:bytes = field(compare=False)


class PPPClient():
    def __init__(self, host:str, port:int) -> None:
        self.host, self.port = host, port
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.q = asyncio.PriorityQueue()
        self._seq = 0

    def _frame(self, msg:OutMsg) -> bytes:
        header = struct.pack('!BBBB', msg.priority, msg.msg_type, msg.channel, len(msg.payload))
        return header + msg.payload
    
    async def connect(self):
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)

    async def send_loop(self):
        assert self.writer is not None
        while True:
            msg: OutMsg = self.q.get()
            if msg.payload == '__shutdown__':
                break
            self.writer(self._frame(msg=msg))
            await self.writer.drain()
            self.q.task_done()
    
    async def enqueue(self, priority:int, msg_type:int, channel:int, payload:bytes):
        self._seq += 1
        await self.q.put(OutMsg(priority, self._seq, msg_type, channel, payload))
    
    async def close(self):
        await self.enqueue(255, 0, 0, b'__shutdown__')
        await self.q.join()
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()

async def main():
    ppp = PPPClient(HOST, PORT)
    await ppp.connect()

    sender_task = asyncio.create_task(ppp.send_loop())

    await ppp.enqueue(PRIO_CONTROL, TYPE_MAPPING, 1, b'map: ch=1 target=telemetry')

    for i in range(10):
        await ppp.enqueue(PRIO_DATA, TYPE_VIDEO, 1, f'video_chunk:{i}'.encode('utf-8'))

        await asyncio.sleep(0.5)

    await ppp.close()
    await sender_task


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('exit') 



