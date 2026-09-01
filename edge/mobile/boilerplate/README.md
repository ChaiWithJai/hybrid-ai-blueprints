# bonsai_edge — the Serverpod boilerplate

One Serverpod backend + one Flutter shell where each kill-target prototype
is a **namespace bundle**, not a new app. The pattern is transplanted from
[violet_rails](https://github.com/restarone/violet_rails), verified against
its actual source (`app/models/api_namespace.rb`, `api_resource.rb`,
`api_action.rb`, `external_api_client.rb`), then inverted for offline-first:
in violet_rails the actions run on the server; here the interesting actions
run on the phone, and the server is deliberately dumb.

## The violet_rails pattern, in one paragraph

A business use case in violet_rails is data, not code: an `ApiNamespace`
(name, version, JSONB `properties` template, associations) whose rows are
`ApiResource`s (JSONB properties), which automatically get REST/GraphQL
endpoints, rendered forms/CMS pages, and `ApiAction`s — declarative
behaviors (send_email, send_web_request with payload mapping, redirect,
custom) fired on create/update/destroy/error, executed async with lifecycle
tracking. `ExternalApiClient` adds cron/on-demand/webhook integrations. A
whole use case exports/imports as one JSON document. Their wiki builds a
hackathon site, a newsletter engine, an LLM document-review flow, and a
Discord bot from these primitives with zero new code.

## The transplant (and the three deliberate inversions)

| violet_rails | bonsai_edge | Why it changes |
| --- | --- | --- |
| `ApiNamespace` + JSONB template | `Namespace` model + JSON `propertiesTemplate`; shared validator enforces required fields | Serverpod is statically typed; the generic path uses one `EdgeResource` model with a JSON `properties` field |
| `ApiResource` (JSONB row) | `EdgeResource { namespaceId, familyId, properties, sourceRef?, syncState }` | Same idea + tenancy scope + sync state for offline |
| `ApiAction` w/ Ruby `eval` | **Registry of named, pre-compiled Dart handlers** configured by JSON params; triggers = afterCreate/afterUpdate hooks in the generic endpoint | No eval in Dart; violet's `payload_mapping` + string interpolation transplants cleanly, `custom_action` becomes a registered function per demo |
| Actions run server-side (Sidekiq) | **Client actions first-class**: transcribe/summarize/translate/extract run on-device via Bonsai + whisper + Kokoro; server actions limited to send_email / webhook / fan-out | The intelligence is the client; the server cannot read E2EE payloads anyway |
| `ExternalApiClient` (cron/webhook) | Serverpod `FutureCall`s + one webhook route; keep retry counters + `state_metadata` | Direct mapping |
| Postgres-schema-per-subdomain tenancy | `familyId` scope column + row-level checks; per-family feature flags as a config row | Simpler, and offline sync needs row-scoped data, not schema isolation |
| Namespace export/import JSON | **The demo bundle format** (`bundle.json`): namespace template + action configs + model-pack refs + eval fixtures | A demo installs like a violet_rails use case imports |
| CMS pages / liquid snippets | Flutter shell renders surfaces from the namespace's form-properties JSON | Widgets replace `cms:helper` |

## Repository layout (once `serverpod create` runs)

```
edge/mobile/
  bonsai_edge_server/        # serverpod create output (server + client pkg)
    lib/src/models/          #   namespace.spy.yaml, edge_resource.spy.yaml,
    lib/src/endpoints/       #   + typed models per demo where codegen earns it
    lib/src/actions/         #   the action-handler registry
  bonsai_edge_flutter/       # one shell app; each demo = a feature module
    lib/demos/<demo>/        #   registered against its namespace bundle
    lib/core/                #   local store (drift), sync engine, model runner
  bundles/                   # one bundle.json per demo — the violet JSON analog
```

## Core models (the generic path)

```yaml
class: Namespace
table: edge_namespace
fields:
  slug: String
  version: int
  propertiesTemplate: String   # JSON: {field: {type, required, default}}
  clientActions: String        # JSON: ordered action configs (on-device)
  serverActions: String        # JSON: action configs (registry names + params)
  syncMode: String             # none | opt_in | always  (05-catch-up: none)

class: EdgeResource
table: edge_resource
fields:
  namespaceId: int
  familyId: int
  properties: String           # JSON payload (violet's JSONB)
  sourceRef: String?           # grounding pointer; conventions from the deal room
  syncState: String            # local | queued | synced
indexes:
  edge_resource_ns_family_idx:
    fields: namespaceId, familyId
```

Typed models (demo 01's `VoiceNote`, demo 06's `RemittanceRecord`) exist
alongside the generic path when a demo needs codegen'd Dart types on-device;
the namespace row still registers them so actions/eval/tooling stay uniform.

## Serverpod-asymptote guardrails (from this repo's review, baked in)

1. **Single-thread-per-process:** capacity plan is N small processes behind
   the LB; Redis message-central bridging is on from the first two-process
   test, not retrofitted.
2. **No connection draining:** the Flutter sync engine treats streams as an
   optimization over `pollSince` — every demo must pass its script with the
   stream killed mid-run.
3. **Diff-based migrations, no merge tooling:** one migration author per
   iteration; migrations regenerate on trunk only.
4. **Committed codegen + CI drift check:** `serverpod generate` +
   `git diff --exit-code` in CI, mirroring Serverpod's own workflow.
5. **Postgres required, Redis optional, SQLite for the laptop loop:**
   dev profile runs the 3.5+ SQLite template path so the tmux cockpit needs
   no Docker.

## The client-only rule

A demo module MUST run with the server absent (demo 05 registers zero
endpoints and is the test of this rule). `bundle.json` marks `syncMode:
none` and the shell must not degrade. This is the product thesis expressed
as an architectural test.

## Bootstrap

```
./bootstrap.sh      # installs dart/flutter/serverpod via official channels,
                    # runs `serverpod create bonsai_edge`, applies core models,
                    # `serverpod generate`, seeds namespace bundles
make dev            # tmux cockpit (see tmux-dev.sh)
make check          # generate-drift + analyze + tests
```

Toolchain is NOT vendored here; nothing in this directory claims a running
system until `bootstrap.sh` has been executed on a machine with the
prerequisites and the result is recorded — evidence-boundary conventions of
this repository apply to the boilerplate too.
