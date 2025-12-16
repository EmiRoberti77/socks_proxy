import asyncio
from datetime import datetime
import argparse

BUFFER = 65536

def time_stamp():
    return datetime.now().isoformat()

def output(time:str, len:int):
    print(f'[{time}] {str(len)} bytes')

async def close_writer(writer:asyncio.StreamWriter):
    try:
        if not writer.is_closing():
            writer.close()
            await writer.wait_closed()
    except:
        pass

async def handle(reader:asyncio.StreamReader, writer:asyncio.StreamWriter):
    addr = writer.get_extra_info('peername')
    print(f'Connected {addr}')
    while True:
        data = await reader.read(BUFFER)
        if not data:
            break
        
        output(time_stamp(), len(data))
        writer.write(data)
        await writer.drain()
    
    await close_writer(writer)

async def main(host, port):
    server = await asyncio.start_server(handle, host, port)
    print(f'Listening on {host}:{port}')
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-H', '--host', required=True)
    parser.add_argument('-P', '--port', required=True)
    args = parser.parse_args()
    try:
        asyncio.run(main(args.host, args.port))
    except KeyboardInterrupt:
        print('exit')
