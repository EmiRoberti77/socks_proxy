import asyncio
from pickle import TRUE
import struct
import socket
import json
import os
import time
import socks5_commands as sc

BUFFER = 65536
SO_MARK = 36  # Linux socket option; requires CAP_NET_ADMIN to set
_DEBUG = False

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

async def open_connection_marked(host: str, port: int, mark: int) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """
    Open an outbound TCP connection with SO_MARK set so iptables can bypass NAT redirection.
    If setting the mark fails (no privileges), falls back to a normal open_connection.
    """
    loop = asyncio.get_running_loop()
    try:
        addrinfos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        if not addrinfos:
            raise OSError(f"getaddrinfo returned no results for {host}:{port}")
        family, socktype, proto, _, sockaddr = addrinfos[0]
        sock = socket.socket(family=family, type=socktype, proto=proto)
        try:
            sock.setsockopt(socket.SOL_SOCKET, SO_MARK, int(mark))
        except Exception as e:
            # Don't break connectivity if we can't mark; caller may still work if NAT isn't active.
            if _DEBUG:
                agent_log("H12", "socks5_dcs.py:open_connection_marked", "SO_MARK failed, falling back", {
                    "host": host, "port": port, "mark": mark, "error": str(e)
                })
            sock.close()
            return await asyncio.open_connection(host, port)

        sock.setblocking(False)
        try:
            await loop.sock_connect(sock, sockaddr)
        except Exception:
            sock.close()
            raise
        return await asyncio.open_connection(sock=sock)
    except Exception:
        return await asyncio.open_connection(host, port)

async def handle_client(reader:asyncio.StreamReader, writer:asyncio.StreamWriter):
    """SOCKS5 server that routes to final targets"""
    addr = writer.get_extra_info('peername')
    print(f'DCS: New SOCKS5 client connected from {addr}')
    if _DEBUG:
        agent_log("H9", "socks5_dcs.py:handle_client", "SOCKS5 client connected", {"peer": addr})
    
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
            # Default matches scripts/redirect_tcp_ppproxy.sh BYPASS_MARK
            bypass_mark = int(os.environ.get("SOCKS_PROXY_BYPASS_MARK", "1"), 0)
            target_reader, target_writer = await open_connection_marked(dst_host, dst_port, bypass_mark)
            if _DEBUG:
                agent_log("H10", "socks5_dcs.py:handle_client", "connected final target", {
                    "dst_host": dst_host, "dst_port": dst_port
                })
        except Exception as e:
            writer.write(pack_reply(sc.REP_GENERAL_FAILURE))
            await writer.drain()
            await close_writer(writer)
            print(f'DCS: ERR:Target connection:{str(e)}')
            if _DEBUG:
                agent_log("H11", "socks5_dcs.py:handle_client", "final target connect failed", {
                    "dst_host": dst_host, "dst_port": dst_port, "error": str(e)
                })
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
    if _DEBUG:
        agent_log("H0", "socks5_dcs.py:main", "DCS listening", {"addrs": addrs})
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass