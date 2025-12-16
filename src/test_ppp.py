import asyncio

async def handle(r:asyncio.StreamReader, w:asyncio.StreamWriter):
    sock = w.get_extra_info('socket')
    peer = w.get_extra_info('peername')
    print(sock)
    print(peer)

    while True:
        data = await r.read(1024*1024)
        if not data:
            break
        w.write(data)
        await w.drain()
    
    w.close()
    await w.wait_closed()

async def main(host, port:int):
    server = await asyncio.start_server(handle, host, port)
    print(f'server started {host}:{port}')
    async with server:
        await server.serve_forever()

try:
    asyncio.run(main=main('0.0.0.0', 8887))
except KeyboardInterrupt:
    print('exit')