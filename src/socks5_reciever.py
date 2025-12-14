import asyncio
import struct
import socket
import socks5_commands as sc

BUFFER = 65536

async def close_writer(writer:asyncio.StreamWriter):
    try:
        writer.close()
        await writer.wait_closed()
    except Exception:
        pass

async def read_extract(reader:asyncio.StreamReader, n:int)->bytes:
    return await reader.readexactly(n)

async def read_socks_addr(reader: asyncio.StreamReader, atyp: int) -> tuple[str, int]:
    if atyp == sc.ATYP_IPV4:
        host = socket.inet_ntoa(await read_extract(reader, 4))
    elif atyp == sc.ATYP_IPV6:
        host = socket.inet_ntop(socket.AF_INET6, await read_extract(reader, 16))
    elif atyp == sc.ATYP_DOMAIN:
        ln = (await read_extract(reader, 1))[0]
        host = (await read_extract(reader, ln)).decode("utf-8", errors="replace")
    else:
        raise ValueError("Unsupported ATYP")
    port = struct.unpack("!H", await read_extract(reader, 2))[0]
    return host, port

def pack_reply(rep:int, bind_host:str = '0.0.0.0', bind_port:int=0)->bytes:
    try:
        addr = socket.inet_pton(socket.AF_INET, bind_host)
        atyp = sc.ATYP_IPV4
        addr_part = addr
    except OSError:
        atyp = sc.ATYP_IPV4
        addr_part = socket.inet_pton('0.0.0.0')
    return struct.pack('!BBBB', sc.SOCKS_VERSION, rep, 0x00, atyp) + addr_part + struct.pack('!H', bind_port)

async def pipe(reader:asyncio.StreamReader, writer:asyncio.StreamWriter, direction: str = ""):
    try:
        total_bytes = 0
        while True:
            data = await reader.read(BUFFER)
            if not data:
                print(f'DCS: WARN:no data:break {direction}')
                break
            writer.write(data)
            await writer.drain()
            total_bytes += len(data)
            print(f'DCS: DATA: {direction} {len(data)} bytes (total: {total_bytes})')
    except Exception as e:
        print(f'DCS: ERR:pipe:{direction}:{str(e)}')
    finally:
        print(f'DCS: INFO: Pipe closed {direction}, total bytes transferred: {total_bytes}')
        await close_writer(writer)

async def handle_client(reader:asyncio.StreamReader, writer:asyncio.StreamWriter):
    """SOCKS5 server that routes to final targets"""
    addr = writer.get_extra_info('peername')
    print(f'DCS: New SOCKS5 client connected from {addr}')
    
    try:
        # SOCKS5 handshake
        ver = (await read_extract(reader, 1))[0]
        if ver != sc.SOCKS_VERSION:
            await close_writer(writer)
            print(f'DCS: ERR:{ver}!={sc.SOCKS_VERSION}')
            return
        
        nmethods = (await read_extract(reader, 1))[0]
        methods = await read_extract(reader, nmethods)
        
        if 0x00 not in methods:
            await close_writer(writer)
            print(f'DCS: ERR:0x00 auth')
            return
        
        # Send auth reply
        writer.write(struct.pack('!BB', sc.SOCKS_VERSION, 0x00))
        await writer.drain()
        
        # Read connect request
        ver, cmd, rsv, atyp = struct.unpack('!BBBB', await read_extract(reader, 4))
        if ver != sc.SOCKS_VERSION or rsv != 0x00:
            await close_writer(writer)
            print(f'DCS: ERR:connect request')
            return
        
        if cmd != sc.CMD_CONNECT:
            writer.write(pack_reply(sc.REP_COMMAND_NOT_SUPPORTED))
            await writer.drain()
            await close_writer(writer)
            print(f'DCS: ERR:connect request')
            return
        
        # Get target address
        try:
            dst_host, dst_port = await read_socks_addr(reader, atyp=atyp)
        except ValueError as ve:
            writer.write(pack_reply(sc.REP_ADDR_TYPE_NOT_SUPPORTED))
            await writer.drain()
            await close_writer(writer)
            print(f'DCS: ERR:Value Error:{str(ve)}')
            return
        
        print(f'DCS: Connecting to final target {dst_host}:{dst_port}')
        
        # Connect to final target
        try:
            target_reader, target_writer = await asyncio.open_connection(dst_host, dst_port)
        except Exception as e:
            writer.write(pack_reply(sc.REP_GENERAL_FAILURE))
            await writer.drain()
            await close_writer(writer)
            print(f'DCS: ERR:Target connection:{str(e)}')
            return
        
        # Send success reply
        sock = target_writer.get_extra_info('socket')
        bhost, bport = sock.getsockname()[0], sock.getsockname()[1]
        writer.write(pack_reply(sc.REP_SUCCEEDED, bind_host=bhost, bind_port=bport))
        await writer.drain()
        print(f'DCS: Connected to {dst_host}:{dst_port}, tunneling...')
        
        # Tunnel data both ways
        t1 = asyncio.create_task(pipe(reader, target_writer, f"SOCKS5->{dst_host}:{dst_port}"))
        t2 = asyncio.create_task(pipe(target_reader, writer, f"{dst_host}:{dst_port}->SOCKS5"))
        
        done, pending = await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
        for p in pending:
            p.cancel()
            
    except asyncio.IncompleteReadError:
        pass
    except Exception as e:
        print(f'DCS: Error: {e}')
    finally:
        await close_writer(writer)

async def main(host="0.0.0.0", port=1081):
    server = await asyncio.start_server(handle_client, host, port)
    addrs = ", ".join(str(s.getsockname()) for s in server.sockets or [])
    print(f"DCS SOCKS5 server listening on {addrs}")
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass