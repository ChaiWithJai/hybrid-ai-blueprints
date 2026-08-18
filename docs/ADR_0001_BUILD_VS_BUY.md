# ADR 0001: Adopt the model-serving layer; build the product evidence layer

- Status: Accepted for the current goal cycle
- Date: 2026-08-14
- Supersedes: implicit plans to build a custom inference engine before product validation

## Decision

For this goal cycle, PrismML will:

1. **Adopt** an existing OpenAI-compatible local serving runtime capable of
   loading the identified Bonsai 27B artifact.
2. **Build** the coding-agent orchestration, private-folder ingestion, hybrid
   routing policy, evidence provenance, evaluation dataset, and trace export.
3. **Use** a cloud provider only as an explicitly approved comparison path;
   deal-room contents remain excluded unless a second, separate data-release
   control is enabled.
4. **Defer** custom quantization kernels, a custom inference engine, and hardened
   multi-tenant isolation until measured product results justify those projects.

This ADR selects an integration boundary. It does not prove that Bonsai 27B is
installed, performant, secure, or accurate.

## Why

The postmortem showed that attempting to represent every target layer at once
created disconnected stubs and verification theater. The differentiating work
for the stated objective is the repeatable deal-room/coding-agent workload and
its evidence trail, not a newly written model server. A standard serving
contract also makes Bonsai-local and cloud comparison falsifiable without
pretending the providers are equivalent.

## Required evidence before revisiting the decision

A custom runtime or kernel project needs all of the following:

- a saved Bonsai-local benchmark artifact identifying exact weights and server;
- a measured bottleneck attributable to the adopted runtime;
- a target metric and baseline (latency, throughput, memory, or energy);
- an owner, test hardware, and a rollback path;
- an independent oracle showing output correctness before performance claims.

## Consequences

- The LM Studio native integration invokes the named Bonsai artifact. The
  current source-bound run passed 4 of 4 synthetic engineering cases. The
  result measures structured checks and filename attribution. It does not
  establish semantic grounding, deal-room accuracy, general coding reliability,
  hardware efficiency, or production readiness.
- The deterministic workflows are regression baselines, not model results.
- “Local-only policy” describes a routing decision; it does not mean certified
  air-gap or zero egress.
- Firecracker, gVisor, custom megakernels, OCR and full document-layout
  ingestion, and enterprise multi-tenancy remain future decisions with separate
  acceptance gates. The current product has bounded XLSX and text-bearing PDF
  ingestion; those implementations do not establish full spreadsheet or layout
  parity.
