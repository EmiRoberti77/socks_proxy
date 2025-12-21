# setup_ppp_transparent_proxy.md

## Purpose

This document explains **how to set up a local transparent proxy (PPP → DCS)** on a **single Windows machine** using:

- **WSL** for:
  - VSG Gateway
  - iptables transparent redirection
  - PPP (transparent TCP proxy)
- **Linux VM** for:
  - DCS (SOCKS5 server)
- **Windows host** for:
  - CCS (video/control service)

The goal is to **force selected TCP traffic (video/data plane)** through PPP and DCS **even though all components run on the same physical machine**, avoiding loopback bypass issues.

---

## Final Working Architecture

```
VSG Gateway (WSL)
  |
  |  (connects to dummy IP)
  v
iptables REDIRECT (WSL nat/OUTPUT)
  |
  v
PPP Transparent Proxy (WSL :6767)
  |
  |  SOCKS5
  v
DCS SOCKS5 Server (Linux VM :1081)
  |
  v
CCS (Windows host :7979)
```

---

## Why This Is Needed

- Loopback traffic never enters the Linux network stack
- WSL iptables cannot intercept loopback
- Dummy IP forces traffic through PPP

---

## Fixed Addresses Used

| Purpose | Address |
|------|-------|
Dummy target | `198.18.0.1:7979` |
PPP ingress | `0.0.0.0:6767` |
DCS SOCKS5 | `192.168.32.128:1081` |
CCS real | `192.168.1.109:7979` |

---

## Step 1 — Gateway Configuration (WSL)

Configure the VSG Gateway target:

```
198.18.0.1:7979
```

---

## Step 2 — iptables Rules (WSL)

```bash
sudo iptables -t nat -F OUTPUT

sudo iptables -t nat -A OUTPUT -p tcp --dport 6767 -j RETURN
sudo iptables -t nat -A OUTPUT -p tcp -d 192.168.32.128 --dport 1081 -j RETURN

sudo iptables -t nat -A OUTPUT   -p tcp -d 198.18.0.1 --dport 7979   -j REDIRECT --to-ports 6767
```

---

## Step 3 — PPP Destination Override

```python
DST_OVERRIDE = {
    ("198.18.0.1", 7979): ("192.168.1.109", 7979),
}
```

Applied after `SO_ORIGINAL_DST` resolution.

---

## Step 4 — Start Order

1. Start DCS (Linux VM)
2. Start PPP (WSL)
3. Start Gateway (WSL)

---

## Verification

- PPP should see active connections on port 6767
- DCS should connect to CCS IP
- CCS should see VM IP as remote peer

---

## Rollback

```bash
sudo iptables -t nat -F OUTPUT
```

---

## Key Takeaways

- Loopback cannot be intercepted
- Dummy IP breaks same-host shortcuts
- PPP rewrites destination
- DCS remains generic
