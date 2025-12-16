import asyncio
import argparse
from datetime import datetime

BUFFER = 65536

async def close_writer(writer:asyncio.StreamWriter):
    try:
        if not writer.is_closing():
            print(f'closing writer')
            writer.close()
            await writer.wait_closed
    except Exception:
        pass

async def handle_client(reader:asyncio.StreamReader, writer:asyncio.StreamWriter):
    addr = writer.get_extra_info('peername')
    print(f'connected into handle client {addr}')
    while True:    
        try:
            data = await reader.read(BUFFER)
            if not data:
                break
            
            print(f'[{datetime.now().isoformat()}]->read:{len(data)} bytes')
            writer.write(data)
            await writer.drain()
        except Exception as e:
            print(e)
    
    await close_writer(writer)
        

async def main(host:str, port:int):
    server = await asyncio.start_server(handle_client, host, port)
    addr = ', '.join(str(sock.getsockname()) for sock in server.sockets)
    print(f'Serving on {addr}')
    
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('-H', '--host', required=True)
    parser.add_argument('-P', '--port', required=True)
    args = parser.parse_args()
    try:
        asyncio.run(main=main(args.host, int(args.port)))
    except KeyboardInterrupt:
        print('exit')



