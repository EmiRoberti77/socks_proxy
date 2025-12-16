# SOCKS5 Proxy Protocol and Implementation Guide

## Table of Contents

1. [What is SOCKS5?](#what-is-socks5)
2. [SOCKS5 Protocol Overview](#socks5-protocol-overview)
3. [Protocol Flow](#protocol-flow)
4. [Architecture Overview](#architecture-overview)
5. [Implementation Details](#implementation-details)
6. [Data Flow Diagrams](#data-flow-diagrams)

---

## What is SOCKS5?

SOCKS5 is a network protocol that acts as an intermediary between a client and a server. It provides a way for clients to establish TCP (and UDP) connections through a proxy server without the client needing to know the proxy's details.

### Key Benefits:

- **Transparency**: Client applications don't need modification
- **Security**: Can route traffic through secure networks
- **Flexibility**: Supports IPv4, IPv6, and domain names
- **Bidirectional**: Full-duplex communication support

---

## SOCKS5 Protocol Overview

### Protocol Phases

The SOCKS5 protocol consists of three main phases:

```
┌─────────────────────────────────────────────────────────┐
│ Phase 1: Authentication Negotiation                      │
│ Client → Proxy: [VER, NMETHODS, METHODS...]             │
│ Proxy → Client: [VER, METHOD]                           │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ Phase 2: Connection Request                             │
│ Client → Proxy: [VER, CMD, RSV, ATYP, DST.ADDR, PORT]  │
│ Proxy → Client: [VER, REP, RSV, ATYP, BND.ADDR, PORT]   │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│ Phase 3: Data Transfer                                   │
│ Client ↔ Proxy ↔ Target Server (bidirectional)         │
└─────────────────────────────────────────────────────────┘
```

### Protocol Fields

**Version (VER)**: Always `0x05` for SOCKS5

**Methods**: Authentication methods

- `0x00`: No authentication required
- `0x01`: GSSAPI
- `0x02`: Username/Password
- `0xFF`: No acceptable methods

**Commands (CMD)**:

- `0x01`: CONNECT (TCP connection)
- `0x02`: BIND (TCP port binding)
- `0x03`: UDP ASSOCIATE

**Address Types (ATYP)**:

- `0x01`: IPv4 address (4 bytes)
- `0x03`: Domain name (1 byte length + domain)
- `0x04`: IPv6 address (16 bytes)

**Replies (REP)**:

- `0x00`: Succeeded
- `0x01`: General SOCKS server failure
- `0x07`: Command not supported
- `0x08`: Address type not supported

---

## Protocol Flow

### Phase 1: Authentication Negotiation

```
Client                          Proxy Server
  │                                 │
  │─── [VER=5, NMETHODS=1, 0x00] ──>│
  │                                 │
  │<── [VER=5, METHOD=0x00] ────────│
  │                                 │
```

**What happens:**

1. Client sends version (5), number of methods (1), and method (0x00 = no auth)
2. Proxy responds with version (5) and selected method (0x00)

### Phase 2: Connection Request

```
Client                          Proxy Server
  │                                 │
  │─── [VER, CMD=CONNECT, RSV,     │
  │     ATYP, DST.ADDR, PORT] ────>│
  │                                 │
  │     [Proxy connects to target]  │
  │                                 │
  │<── [VER, REP=SUCCESS, RSV,     │
  │     ATYP, BND.ADDR, PORT] ─────│
  │                                 │
```

**What happens:**

1. Client sends connection request with target address and port
2. Proxy establishes connection to target server
3. Proxy responds with success and bound address/port

### Phase 3: Data Transfer

```
Client                          Proxy Server                    Target Server
  │                                 │                                 │
  │─── [Data Packet 1] ───────────>│                                 │
  │                                 │─── [Data Packet 1] ────────────>│
  │                                 │                                 │
  │                                 │<── [Response Packet 1] ────────│
  │<── [Response Packet 1] ───────│                                 │
  │                                 │                                 │
  │─── [Data Packet 2] ───────────>│                                 │
  │                                 │─── [Data Packet 2] ────────────>│
  │                                 │                                 │
```

**What happens:**

1. Client sends data to proxy
2. Proxy forwards data to target server
3. Target server responds
4. Proxy forwards response back to client
5. This continues bidirectionally until connection closes

---

## Architecture Overview

### System Architecture

This codebase implements a **two-tier proxy architecture**:

```
┌─────────────┐
│   Client    │ (Regular TCP connection)
│ Application │
└──────┬──────┘
       │
       │ Port-based routing
       │
┌──────▼────────────────────────────────────────┐
│         PPP Proxy (socks5_ppp.py)             │
│  ┌──────────────────────────────────────────┐  │
│  │ Port 8887 → Target A                    │  │
│  │ Port 8888 → Target B                    │  │
│  │ Port 8889 → Target C                    │  │
│  └──────────────────────────────────────────┘  │
└──────┬────────────────────────────────────────┘
       │
       │ SOCKS5 Protocol
       │
┌──────▼────────────────────────────────────────┐
│      DCS Proxy (socks5_dcs.py)               │
│  ┌──────────────────────────────────────────┐  │
│  │ SOCKS5 Server                            │  │
│  │ Routes to final targets                  │  │
│  └──────────────────────────────────────────┘  │
└──────┬────────────────────────────────────────┘
       │
       │ Regular TCP
       │
┌──────▼──────┐
│   Target    │
│   Server    │
└─────────────┘
```

### Component Roles

**PPP Proxy (`socks5_ppp.py`)**:

- Accepts regular TCP connections from clients
- Uses port-based routing to determine target
- Converts regular TCP to SOCKS5 protocol
- Forwards SOCKS5 requests to DCS

**DCS Proxy (`socks5_dcs.py`)**:

- Implements full SOCKS5 server
- Receives SOCKS5 connection requests
- Connects to final target servers
- Tunnels bidirectional data

**Target Servers**:

- Any TCP server (HTTP, custom protocols, etc.)
- No SOCKS5 knowledge required

---

## Implementation Details

### Port-Based Routing

The PPP proxy uses a routing table to map client connection ports to target servers:

```
ROUTING_TABLE = {
    8887: ('127.0.0.1', 8891),  # Port 8887 → test_server:8891
    8888: ('127.0.0.1', 9000),  # Port 8888 → another_server:9000
    8889: ('example.com', 80),   # Port 8889 → example.com:80
}
```

**How it works:**

1. Client connects to PPP on a specific port (e.g., 8887)
2. PPP looks up the port in routing table
3. PPP extracts target host and port
4. PPP creates SOCKS5 tunnel to DCS requesting that target

### Connection Flow

```
┌──────────────────────────────────────────────────────────────┐
│ Step 1: Client connects to PPP                               │
│ Client → PPP:8887 (Regular TCP)                             │
└──────────────────────────────────────────────────────────────┘
                        ↓
┌──────────────────────────────────────────────────────────────┐
│ Step 2: PPP determines target from port                      │
│ Port 8887 → Lookup → Target: 127.0.0.1:8891                 │
└──────────────────────────────────────────────────────────────┘
                        ↓
┌──────────────────────────────────────────────────────────────┐
│ Step 3: PPP connects to DCS via SOCKS5                       │
│ PPP → DCS:1081 (SOCKS5 Protocol)                            │
│   - Auth negotiation                                          │
│   - Connection request: 127.0.0.1:8891                       │
│   - DCS responds: Success                                    │
└──────────────────────────────────────────────────────────────┘
                        ↓
┌──────────────────────────────────────────────────────────────┐
│ Step 4: DCS connects to target                               │
│ DCS → Target:8891 (Regular TCP)                             │
└──────────────────────────────────────────────────────────────┘
                        ↓
┌──────────────────────────────────────────────────────────────┐
│ Step 5: Bidirectional data tunneling                         │
│ Client ↔ PPP ↔ DCS ↔ Target                                  │
│ (All data flows transparently)                               │
└──────────────────────────────────────────────────────────────┘
```

### Bidirectional Data Flow

Both PPP and DCS implement bidirectional tunneling using two concurrent pipes:

```
┌─────────────────────────────────────────────────────────────┐
│                    Bidirectional Pipes                        │
│                                                              │
│  Client → Proxy → Target  (Forward pipe)                     │
│  Client ← Proxy ← Target  (Reverse pipe)                     │
│                                                              │
│  Both pipes run concurrently using asyncio tasks            │
│  Connection closes when either pipe closes                   │
└─────────────────────────────────────────────────────────────┘
```

---

## Data Flow Diagrams

### Complete End-to-End Flow

```
┌──────────┐         ┌──────────┐         ┌──────────┐         ┌──────────┐
│  Client  │         │   PPP    │         │   DCS    │         │  Target  │
│          │         │  Proxy   │         │  Proxy   │         │  Server  │
└────┬─────┘         └────┬─────┘         └────┬─────┘         └────┬─────┘
     │                    │                    │                    │
     │ TCP Connect        │                    │                    │
     │ Port 8887         │                    │                    │
     ├───────────────────>│                    │                    │
     │                    │                    │                    │
     │                    │ SOCKS5 Connect    │                    │
     │                    │ Port 1081         │                    │
     │                    ├───────────────────>│                    │
     │                    │                    │                    │
     │                    │ Auth: [5,1,0]      │                    │
     │                    ├───────────────────>│                    │
     │                    │                    │                    │
     │                    │ Auth Reply: [5,0]  │                    │
     │                    │<───────────────────┤                    │
     │                    │                    │                    │
     │                    │ Connect Request:   │                    │
     │                    │ [5,1,0,1,          │                    │
     │                    │  127.0.0.1,8891]  │                    │
     │                    ├───────────────────>│                    │
     │                    │                    │                    │
     │                    │                    │ TCP Connect       │
     │                    │                    │ 127.0.0.1:8891    │
     │                    │                    ├───────────────────>│
     │                    │                    │                    │
     │                    │                    │ Connection OK      │
     │                    │                    │<───────────────────┤
     │                    │                    │                    │
     │                    │ Connect Reply:    │                    │
     │                    │ [5,0,0,1,          │                    │
     │                    │  BND.ADDR,PORT]    │                    │
     │                    │<───────────────────┤                    │
     │                    │                    │                    │
     │                    │                    │                    │
     │ Data Packet 1      │                    │                    │
     ├───────────────────>│                    │                    │
     │                    │ Data Packet 1      │                    │
     │                    ├───────────────────>│                    │
     │                    │                    │ Data Packet 1      │
     │                    │                    ├───────────────────>│
     │                    │                    │                    │
     │                    │                    │ Response Packet 1  │
     │                    │                    │<───────────────────┤
     │                    │                    │                    │
     │                    │ Response Packet 1  │                    │
     │                    │<───────────────────┤                    │
     │                    │                    │                    │
     │ Response Packet 1  │                    │                    │
     │<───────────────────┤                    │                    │
     │                    │                    │                    │
     │ [Continues bidirectionally until connection closes]        │
     │                    │                    │                    │
```

### Multiple Clients Scenario

```
┌──────────┐
│ Client A │──┐
└──────────┘  │
             │  Port 8887
┌──────────┐ │  ┌──────────┐
│ Client B │─┼──│   PPP    │──┐
└──────────┘ │  │  Proxy   │  │
             │  └──────────┘  │
┌──────────┐ │                │  SOCKS5
│ Client C │─┘                │  Port 1081
└──────────┘                  │  ┌──────────┐
                              └──│   DCS    │──┐
                                 │  Proxy   │  │
                                 └──────────┘  │
                                                │
                                 ┌──────────┐  │
                                 │ Target A │──┘
                                 │ :8891    │
                                 └──────────┘
                                 ┌──────────┐
                                 │ Target B │──┐
                                 │ :9000    │  │
                                 └──────────┘  │
                                                │
                                 ┌──────────┐  │
                                 │ Target C │──┘
                                 │ :80      │
                                 └──────────┘
```

**Key Points:**

- Each client connects to a different port on PPP
- PPP routes each connection to different targets via DCS
- All connections are independent and concurrent
- DCS handles multiple SOCKS5 connections simultaneously

---

## Protocol Message Formats

### Authentication Request (Client → Proxy)

```
+----+----------+----------+
|VER | NMETHODS | METHODS  |
+----+----------+----------+
| 1  |    1     | 1 to 255 |
+----+----------+----------+
```

Example: `[0x05, 0x01, 0x00]` = SOCKS5, 1 method, no auth

### Authentication Reply (Proxy → Client)

```
+----+--------+
|VER | METHOD |
+----+--------+
| 1  |   1    |
+----+--------+
```

Example: `[0x05, 0x00]` = SOCKS5, no auth selected

### Connection Request (Client → Proxy)

```
+----+-----+-------+-------+----------+----------+
|VER | CMD |  RSV  | ATYP  | DST.ADDR| DST.PORT |
+----+-----+-------+-------+----------+----------+
| 1  |  1  | X'00' |   1   | Variable|    2     |
+----+-----+-------+-------+----------+----------+
```

Example for IPv4: `--

- VER=5, CMD=CONNECT, ATYP=IPv4, DST.ADDR=127.0.0.1, PORT=8891

Example for Domain: `[0x05, 0x01, 0x00, 0x03, 0x0B, 'e', 'x', 'a', 'm', 'p', 'l', 'e', '.', 'c', 'o', 'm', 0x00, 0x50]`

- VER=5, CMD=CONNECT, ATYP=Domain, Length=11, Domain="example.com", PORT=80

### Connection Reply (Proxy → Client)

```
+----+-----+-------+-------+----------+----------+
|VER | REP |  RSV  | ATYP  | BND.ADDR| BND.PORT |
+----+-----+-------+-------+----------+----------+
| 1  |  1  | X'00' |   1   | Variable |    2    |
+----+-----+-------+-------+----------+----------+
```

Example: `[0x05, 0x00, 0x00, 0x01, 192, 168, 1, 1, 0x12, 0x34]`

- VER=5, REP=SUCCESS, ATYP=IPv4, BND.ADDR=192.168.1.1, BND.PORT=4660

---

## Key Implementation Features

### 1. Asynchronous I/O

- Uses Python's `asyncio` for concurrent connections
- Non-blocking I/O allows handling multiple clients simultaneously
- Efficient resource usage

### 2. Port-Based Routing

- No client modification required
- Simple configuration via routing table
- Supports multiple targets simultaneously

### 3. Protocol Conversion

- PPP converts regular TCP to SOCKS5
- Transparent to clients
- Standard SOCKS5 protocol between PPP and DCS

### 4. Bidirectional Tunneling

- Two concurrent pipes per connection
- Full-duplex communication
- Automatic cleanup on connection close

### 5. Error Handling

- Proper SOCKS5 error codes
- Graceful connection cleanup
- Detailed logging for debugging

---

## Use Cases

### 1. Multi-Target Routing

Route different clients to different backend servers based on connection port.

### 2. Protocol Translation

Convert regular TCP clients to use SOCKS5 infrastructure.

### 3. Network Segmentation

Route traffic through controlled proxy infrastructure.

### 4. Load Distribution

Distribute connections across multiple backend servers.

---

## Summary

This implementation provides a flexible, scalable SOCKS5 proxy solution that:

- **Accepts regular TCP connections** (no client modifications needed)
- **Routes based on connection port** (simple configuration)
- **Uses standard SOCKS5 protocol** (compatible with SOCKS5 infrastructure)
- **Supports multiple concurrent connections** (asynchronous I/O)
- **Provides bidirectional tunneling** (full-duplex communication)
- **Handles multiple targets** (port-based routing table)

The two-tier architecture (PPP → DCS → Target) provides flexibility and separation of concerns, making it easy to add new routing rules or modify target servers without affecting clients.
