import asyncio
import struct
import socket
import json
import os
import time
from typing import Optional, Tuple
import socks5_commands as sc

BUFFER = 65536

INGRESS_BIND_HOST = '0.0.0.0'
INGRESS_PORT = 6767

DCS_HOST = '127.0.0.1'
DCS_PORT = 1081  # DCS SOCKS5 server port

# Linux IPv4 original destination socket option
SO_ORIGINAL_DST = 80

# region agent log
def agent_log(hypothesis_id: str, location: str, message: str, data: dict, run_id: str = "pre-fix") -> None:
    try:
        log_dir = '/mnt/c/code/VSG/socks_proxy/.cursor'
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, 'debug.log')
        payload = {
            "sessionId": "debug-session",
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        with open(log_path, 'a') as f:
            f.write(json.dumps(payload) + "\n")
    except Exception:
        # Never raise from logging
        pass
# endregion

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
        addr_part = socket.inet_pton(socket.AF_INET, '0.0.0.0')
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

async def read_target_info(reader: asyncio.StreamReader) -> tuple[str, int, bytes]:
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
    
    # No header found; fail fast instead of guessing a local default
    raise ValueError("No routing header 'HOST:PORT\\n' found in first packet for direct-ingress connection")

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

def get_original_dst(writer: asyncio.StreamWriter) -> Optional[tuple[str, int]]:
    """
    Attempt to retrieve the original destination for REDIRECTed connections (IPv4).
    Returns (ip, port) or None if unavailable.
    """
    try:
        sock: Optional[socket.socket] = writer.get_extra_info('socket')  # type: ignore[assignment]
    except Exception:
        sock = None
    if not sock:
        return None
    # Only IPv4 sockaddr_in is handled here
    try:
        if sock.family != socket.AF_INET:
            return None
        data = sock.getsockopt(socket.SOL_IP, SO_ORIGINAL_DST, 16)
        # struct sockaddr_in: family(2), port(2), addr(4), zero(8)
        _, port, raw_ip = struct.unpack('!HH4s8x', data)
        ip = socket.inet_ntoa(raw_ip)
        return ip, port
    except Exception:
        return None

async def handle_client(reader:asyncio.StreamReader, writer:asyncio.StreamWriter):
    """Accept regular TCP connection, forward through SOCKS5 to DCS"""
    addr = writer.get_extra_info('peername')
    local_addr = writer.get_extra_info('sockname')
    local_port = local_addr[1] if local_addr else None
    
    print(f'PPP: New regular TCP client connected from {addr} on port {local_port}')
    agent_log("H1", "socks5_ppp.py:handle_client", "client connected", {"peer": addr, "local_port": local_port})
    
    try:
        first_data = b''
        # Prefer original destination if traffic arrived via NAT REDIRECT
        orig = get_original_dst(writer)
        agent_log("H2", "socks5_ppp.py:handle_client", "after SO_ORIGINAL_DST", {"orig": orig})
        if orig:
            # If original destination points back to our own ingress (e.g., direct local connect),
            # treat it as absent so we can parse target from the first packet instead of looping.
            if (orig[1] == INGRESS_PORT and orig[0] in ('127.0.0.1', '0.0.0.0', '::1')):
                print(f'PPP: SO_ORIGINAL_DST is ingress ({orig[0]}:{orig[1]}), will parse target from packet')
                orig = None
        if orig:
            target_host, target_port = orig
            print(f'PPP: Using SO_ORIGINAL_DST -> {target_host}:{target_port}')
        else:
            print('PPP: No SO_ORIGINAL_DST, parsing first packet')
            agent_log("H3", "socks5_ppp.py:handle_client", "parsing header", {})
            target_host, target_port, first_data = await read_target_info(reader)
        parsed_from_packet = orig is None
        agent_log("H4", "socks5_ppp.py:handle_client", "target decided", {
            "target_host": target_host, "target_port": target_port, "parsed_from_packet": parsed_from_packet
        })
        
        # Loop guard: allow loopback only if target was explicitly provided via first packet parsing.
        if ((target_host in ('127.0.0.1', '::1') and not parsed_from_packet) or
            target_port == INGRESS_PORT or
            (target_host == DCS_HOST and target_port == DCS_PORT)):
            print(f'PPP: Loop guard triggered, refusing to proxy to {target_host}:{target_port}')
            agent_log("H5", "socks5_ppp.py:handle_client", "loop guard triggered", {
                "target_host": target_host, "target_port": target_port, "parsed_from_packet": parsed_from_packet
            })
            return
        
        # Connect to DCS via SOCKS5
        agent_log("H6", "socks5_ppp.py:handle_client", "connecting DCS", {
            "dcs_host": DCS_HOST, "dcs_port": DCS_PORT, "target_host": target_host, "target_port": target_port
        })
        dcs_reader, dcs_writer = await socks5_connect_to_dcs(target_host, target_port)
        print(f'PPP: Connected to DCS, tunnel established to {target_host}:{target_port}')
        agent_log("H7", "socks5_ppp.py:handle_client", "connected DCS", {
            "target_host": target_host, "target_port": target_port
        })
        
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
        agent_log("H8", "socks5_ppp.py:handle_client", "exception", {"error": str(e)})
    finally:
        await close_writer(writer)

async def main(): 
    server = await asyncio.start_server(handle_client, INGRESS_BIND_HOST, INGRESS_PORT)
    addrs = ", ".join(str(s.getsockname()) for s in server.sockets or [])
    print(f"PPP Proxy listening on {addrs} (single ingress) via DCS")
    agent_log("H0", "socks5_ppp.py:main", "PPP listening", {"addrs": addrs})
    async with server:
        await server.serve_forever()
    
    # Keep all servers running concurrently
    async def run_server(server):
        async with server:
            await server.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass