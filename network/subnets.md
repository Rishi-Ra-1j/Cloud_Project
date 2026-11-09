# Subnetting — 10.20.0.0/16 (Task 5)

Allocate largest requirement first, starting at 10.20.0.0, each subnet
placed immediately after the previous one, using the smallest prefix
that fits. Usable hosts = 2^(32-prefix) - 2 (network and broadcast
addresses are not usable).

## Working

- app, 1,000 hosts: need 2^10 = 1,024 addresses (1,022 usable) -> /22.
  10.20.0.0/22 covers 10.20.0.0-10.20.3.255.
- public, 250 hosts: need 2^8 = 256 addresses (254 usable) -> /24.
  Next free address is 10.20.4.0, so 10.20.4.0/24.
- data, 100 hosts: need 2^7 = 128 addresses (126 usable) -> /25.
  Next free address is 10.20.5.0, so 10.20.5.0/25, covering
  10.20.5.0-10.20.5.127.
- management, 20 hosts: need 2^5 = 32 addresses (30 usable) -> /27.
  Next free address is 10.20.5.128, so 10.20.5.128/27, covering
  10.20.5.128-10.20.5.159.

## Table

| Subnet | Network address | Prefix | Usable host range | Broadcast address | Usable hosts |
|---|---|---|---|---|---|
| app | 10.20.0.0 | /22 | 10.20.0.1 - 10.20.3.254 | 10.20.3.255 | 1,022 |
| public | 10.20.4.0 | /24 | 10.20.4.1 - 10.20.4.254 | 10.20.4.255 | 254 |
| data | 10.20.5.0 | /25 | 10.20.5.1 - 10.20.5.126 | 10.20.5.127 | 126 |
| management | 10.20.5.128 | /27 | 10.20.5.129 - 10.20.5.158 | 10.20.5.159 | 30 |

## Why a stateless NACL needs separate reply rules, and why order matters

A NACL is stateless: it does not remember connections. Every packet,
including a reply, is checked on its own against the rules for its
direction. So a reply coming back from the app subnet on an ephemeral
port (1024-65535) is not automatically allowed just because the
outbound request was allowed; it needs its own inbound allow rule,
and a reply going back to a client needs its own outbound allow rule.
Without those rules the reply is denied by the default deny.

Rules are checked lowest number first and the first match wins.
The deny for 198.51.100.0/24 must therefore have a lower rule number
than the allow rules for TCP 80/443 from anywhere, otherwise a packet
from that abusive range to port 443 would match the allow rule first
and be allowed. In network/nacl.json the deny is rule 100 and the
80/443 allows are rules 110/120.

Verified: `python tools/nacl_sim.py network/nacl.json network/packets_sample.jsonl --check`
gives 6/6 correct on the sample packets.
