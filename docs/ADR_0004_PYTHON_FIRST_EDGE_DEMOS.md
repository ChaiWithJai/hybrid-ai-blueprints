# ADR 0004 — Edge demos run Python-web-first; Serverpod stays the productization path

Status: accepted, 2026-08-31

## Context

The edge/mobile plan originally called for prototyping every demo on
Serverpod + Flutter, violet_rails-style. The verified host has neither
Dart, Flutter, nor the Serverpod CLI installed, while it does have the
stack every existing blueprint in this repository already runs on:
stdlib Python, SQLite, a local LM Studio endpoint serving the Bonsai
family, and a browser. Waiting on a toolchain install to see whether the
product ideas survive contact with the live model would have inverted the
risk order: the model was the unknown, not the framework.

## Decision

Prototype and test the demos on a stdlib-Python platform (`edgekit`)
implementing the same architecture the Serverpod boilerplate specifies —
namespace bundles, JSON-property resources, a pre-compiled client-action
registry, offline-first queue semantics — with designed single-file web
frontends served by stdlib HTTP servers. Keep the Serverpod boilerplate
(`edge/mobile/boilerplate/`) as the documented productization path; its
bootstrap and tmux cockpit remain the on-ramp once the toolchain lands.

## Consequences

- Every demo was testable against live Bonsai 1.7b the same day, which is
  what produced the portfolio kills (ADR 0003) — the framework could not
  have surfaced those.
- The violet_rails transplant is validated in running code: porting the
  namespace/action/store contract to Serverpod is now a translation of a
  working design rather than a bet.
- The web demos are the design layer's reference implementation; the
  future Flutter shell inherits tokens, sprites, copy rules, and the
  offline-state semantics already proven here.
- Cost: nothing here exercises Dart codegen, real websockets, or mobile
  packaging — those risks stay open until the Serverpod path is built.
