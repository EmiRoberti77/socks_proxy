import asyncio
import struct
from time import process_time_ns
from tokenize import Pointfloat

_LINE = '-------------------------------'
HOST, PORT = '0.0.0.0', 9001

async def read_exact(reader:asyncio.StreamReader, n:int):
    return await reader.readexactly(n)

async def print_line(line_count, prio, msg_type, channel, length, payload):
    print(f'[DCS({line_count})] prio={prio} msg_type={msg_type} channel={channel} lengh={length}')
    print(f'[DCS({line_count})] payload={payload}')
    print(_LINE)
    
async def handle_client(reader:asyncio.StreamReader, writer:asyncio.StreamWriter):
    peer = writer.get_extra_info('peername')
    print(f'[DCS Connected]:{peer}')

    line_count = 0
    try:
        while True:
            hdr = await read_exact(reader=reader, n=8)
            prio, msg_type, channel, length = struct.unpack('!BBBB', hdr)
            payload = await read_exact(reader=reader, n=length)
            await print_line(line_count, prio, msg_type, channel, length, payload)
            line_count += 1
    except asyncio.IncompleteReadError:
        pass
    except Exception as e:
        print(e)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except:
            pass

async def main():
    server = await asyncio.start_server(client_connected_cb=handle_client, host=HOST, port=PORT)
    print(f'[DCS] listening on {HOST}:{PORT}')
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main=main())
    except KeyboardInterrupt:
        print('exit')