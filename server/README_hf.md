---
title: anotify relay
emoji: 🔔
colorFrom: blue
colorTo: green
sdk: docker
pinned: true
license: mit
---

# anotify public relay

Free public notification relay for [anotify](https://github.com/cupcake777/anotify).

**Rate-limited:** 30 requests/min per IP, 2KB max payload, no logs retained.

**Make it private:** set an `ANOTIFY_TOKEN` secret in the Space settings. The
relay stays in public (rate-limited) mode but then requires that token on
every `send` / client connection — no other changes needed.

Self-host for production use.
