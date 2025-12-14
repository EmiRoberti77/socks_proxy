import asyncio
import struct
import socket
from typing import Optional, Tuple
import socks5_commands as sc

BUFFER = 65536
# Configuration: Where is DCS running?
DCS_HOST = '127.0.0.1'
DCS_PORT = 1081  # DCS SOCKS5 server port

# Configuration: Port-based routing table
# Format: {ppp_port: (target_host, target_port)}
ROUTING_TABLE = {
    8887: ('127.0.0.1', 8891),  # Clients on port 8887 -> test_server:8891
    8888: ('127.0.0.1', 9000),  # Clients on port 8888 -> another_server:9000
    # 8889: ('example.com', 80),  # Clients on port 8889 -> example.com:80
}

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

async def socks5_connect_to_dcs(target_host: str, target_port: int):
    """Connect to DCS via SOCKS5 and request connection to final target"""
    # Connect to DCS SOCKS5 server
    reader, writer = await asyncio.open_connection(DCS_HOST, DCS_PORT)
    
    # SOCKS5 handshake
    writer.write(struct.pack('!BB', sc.SOCKS_VERSION, 1))  # VER, NMETHODS
    writer.write(b'\x00')  # No auth
    await writer.drain()
    
    # Receive auth reply
    response = await reader.readexactly(2)
    if response[0] != sc.SOCKS_VERSION or response[1] != 0x00:
        writer.close()
        await writer.wait_closed()
        raise Exception("SOCKS5 auth failed")
    
    # Send connect request to final target
    try:
        socket.inet_aton(target_host)
        atyp = sc.ATYP_IPV4
        addr_bytes = socket.inet_aton(target_host)
    except socket.error:
        atyp = sc.ATYP_DOMAIN
        addr_bytes = struct.pack('!B', len(target_host)) + target_host.encode('utf-8')
    
    request = struct.pack('!BBBB', sc.SOCKS_VERSION, sc.CMD_CONNECT, 0x00, atyp)
    request += addr_bytes
    request += struct.pack('!H', target_port)
    writer.write(request)
    await writer.drain()
    
    # Receive connect reply
    response = await reader.readexactly(4)
    ver, rep, rsv, atyp = struct.unpack('!BBBB', response)
    if rep != 0:
        writer.close()
        await writer.wait_closed()
        raise Exception(f"SOCKS5 connection failed: {rep}")
    
    # Skip BND.ADDR and BND.PORT
    if atyp == sc.ATYP_IPV4:
        await reader.readexactly(4)
    elif atyp == sc.ATYP_DOMAIN:
        domain_len = (await reader.readexactly(1))[0]
        await reader.readexactly(domain_len)
    elif atyp == 0x04:  # IPv6
        await reader.readexactly(16)
    await reader.readexactly(2)  # Port
    
    return reader, writer

async def read_target_info(reader: asyncio.StreamReader) -> tuple[str, int]:
    """Read target info from first packet: format "HOST:PORT\n" or binary format"""
    # Try to read first packet (peek)
    data = await reader.read(BUFFER)
    if not data:
        raise Exception("No data received")
    
    # Try to parse as text format "host:port\n"
    try:
        text = data.decode('utf-8', errors='ignore')
        if ':' in text and '\n' in text:
            parts = text.split('\n')[0].split(':')
            host = parts[0]
            port = int(parts[1])
            # Return remaining data
            remaining = data[len(f"{host}:{port}\n".encode('utf-8')):]
            return host, port, remaining
    except:
        pass
    
    # Default target (or use config)
    # For now, default to test_server
    return '127.0.0.1', 8888, data

async def pipe(reader:asyncio.StreamReader, writer:asyncio.StreamWriter, direction: str = ""):
    try:
        total_bytes = 0
        while True:
            data = await reader.read(BUFFER)
            if not data:
                print(f'WARN:no data:break {direction}')
                break
            writer.write(data)
            await writer.drain()
            total_bytes += len(data)
            print(f'DATA: {direction} {len(data)} bytes (total: {total_bytes})')
    except Exception as e:
        print(f'ERR:pipe:{direction}:{str(e)}')
    finally:
        print(f'INFO: Pipe closed {direction}, total bytes transferred: {total_bytes}')
        await close_writer(writer)

async def handle_client(reader:asyncio.StreamReader, writer:asyncio.StreamWriter):
    """Accept regular TCP connection, forward through SOCKS5 to DCS"""
    addr = writer.get_extra_info('peername')
    local_addr = writer.get_extra_info('sockname')
    local_port = local_addr[1] if local_addr else None
    
    print(f'PPP: New regular TCP client connected from {addr} on port {local_port}')
    
    try:
        if local_port and local_port in ROUTING_TABLE:
            target_host, target_port = ROUTING_TABLE[local_port]
            print(f'PPP: Routing port {local_port} -> {target_host}:{target_port} via DCS')
            # Read first data packet
            first_data = await reader.read(BUFFER)
        else:
            # Fallback: try to read routing info from packet
            print(f'PPP: Port {local_port} not in routing table, trying to parse from packet')
            target_host, target_port, first_data = await read_target_info(reader)
            print(f'PPP: Parsed routing to {target_host}:{target_port}')
        
        # Connect to DCS via SOCKS5
        dcs_reader, dcs_writer = await socks5_connect_to_dcs(target_host, target_port)
        print(f'PPP: Connected to DCS, tunnel established to {target_host}:{target_port}')
        
        # Send first data packet if any
        if first_data:
            dcs_writer.write(first_data)
            await dcs_writer.drain()
        
        # Tunnel data both ways
        t1 = asyncio.create_task(pipe(reader, dcs_writer, f"client->DCS->{target_host}:{target_port}"))
        t2 = asyncio.create_task(pipe(dcs_reader, writer, f"DCS->{target_host}:{target_port}->client"))
        
        done, pending = await asyncio.wait({t1, t2}, return_when=asyncio.FIRST_COMPLETED)
        for p in pending:
            p.cancel()
            
    except Exception as e:
        print(f'PPP: Error: {e}')
    finally:
        await close_writer(writer)

async def main():
    # Start multiple servers, one for each port in routing table
    servers = []
    for port, (target_host, target_port) in ROUTING_TABLE.items():
        server = await asyncio.start_server(handle_client, '0.0.0.0', port)
        addrs = ", ".join(str(s.getsockname()) for s in server.sockets or [])
        servers.append(server)
        print(f"PPP Proxy listening on {addrs} -> {target_host}:{target_port} via DCS")
    
    # Keep all servers running concurrently
    async def run_server(server):
        async with server:
            await server.serve_forever()
    
    # Create tasks for all servers
    tasks = [asyncio.create_task(run_server(server)) for server in servers]
    
    # Wait for all servers (they run forever until interrupted)
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass