# [RFC-0042] Architectural Rails for Prism Vault: Infrastructure, Security, and Human-Agent Collaboration

> **Current application decision, August 17, 2026.** The active product goal is
> the customer demo defined in
> [`DEMO_INFORMATION_ARCHITECTURE.md`](./DEMO_INFORMATION_ARCHITECTURE.md).
> Accuracy certification and commercial proof no longer gate the demo. The
> architecture keeps their old records available without placing them in the
> main product path.

> **RFC status — proposed target architecture.** Component names and benchmark
> figures below capture research and design intent, not installed capability.
> Runtime claims require the evidence gates in `docs/VERIFICATION_GATES.md`.
> Current measured pilot results and limitations are in the
> [benchmark card](./BENCHMARK_CARD.md).

**Summary**: Proposes infrastructure and security rails for Prism Vault across compute, parsing, sandboxing, and model routing.  
**Created**: August 13, 2026  
**Current Version**: 1.0.0  
**PRD**: [[PRD] Prism Vault: Air-Gapped Sovereign Workspace Runtime](./PRD.md)  
**Status**: Draft target architecture; stakeholder approval is not recorded in this repository  
**Proposed owner**: `engineering@prismml.ai`  
**Required reviewers**: engineering, product, and security; sign-off artifacts absent

---

## Executive Architectural Summary

### Application contract

The first application contract is the source linked deal brief defined in
[`DEMO_INFORMATION_ARCHITECTURE.md`](./DEMO_INFORMATION_ARCHITECTURE.md).

The browser must make the application contract visible before it exposes the
system architecture. The primary route contains Overview, Sources, Activity,
and Evaluation. Evaluation reads the same Buzz room events as Activity and
saves annotations under the room identity. Decision notes and Technical
details remain secondary views inside Room details.

The current helper does not implement the proposed semantic scores below. It
records exact claim reproduction, exact configured denylist matches, and exact
fixture cell matches. Caller supplied table pass counts are ignored. Each
record states which broader property remains unmeasured.

The current schema helper has two bounded modes. A list checks only required
field presence. A field to JSON type map checks required top level values. Full
JSON Schema validation remains proposed work.
The architecture supports that job. Broad terms such as deal room auditing and
chat with data do not define release acceptance on their own.

Enterprise AI infrastructure requires balancing hardware efficiency, execution throughput, structural data fidelity, and multi-tenant security boundaries. As enterprise deployments transition from brittle third-party cloud API wrappers to sovereign, on-premises agent runtimes, engineering teams face critical structural trade-offs.

This RFC records target architecture recommendations for **Prism Vault**. It
does not record completed build decisions or installed infrastructure. The
accepted pilot boundary is ADR 0001: adopt LM Studio/Bionic serving and build
the deal-room workflow, policy, provenance, and evaluation layers. The deeper
recommendations below remain conditional across three infrastructure layers:
1. **Low-Bit Compute and Edge Acceleration**: Native 1.58-bit ternary models ($\{-1, 0, +1\}$), group-wise scaling ($g=128$), fused register-level dequantization, and the **Bonsai model family** (Bonsai 27B, Bonsai 8B, Bonsai Image 4B).
2. **Document Extraction and Structural Ingestion**: Docling multi-stage AST layout parsing with TableFormer (MIT License) vs. Marker/MinerU2.5/custom heuristics.
3. **Agentic Execution Sandboxing and Multi-Tenant Isolation**: Firecracker microVM snapshotting (for CPU tasks) and gVisor `runsc` with `nvproxy` mediated GPU ioctl interception (for local tensor/GPU tasks) vs. commercial serverless platforms (Modal/E2B).

---

## The Core Paradigm: "Do AI Right" (Opinionated Rails)

The proposed design groups enterprise AI into two lifecycle areas and one
application area. The diagram is a target map. It does not describe the
current repository.

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                      TARGET ONLY: Proposed PrismML Architecture                          │
└────────────────────────────────────────────┬─────────────────────────────────────────────┘
                                             │
    ┌────────────────────────────────────────┴────────────────────────────────────────┐
    ▼                                                                                 ▼
┌──────────────────────────────────────────────────┐ ┌──────────────────────────────────────────────────┐
│        RUN LIFECYCLE MANAGEMENT (RLM)            │ │        TRUST & CONTEXT LIFECYCLE (TCL)           │
├──────────────────────────────────────────────────┤ ├──────────────────────────────────────────────────┤
│ Enforces operational efficiency & throughput     │ │ Enforces data sovereignty, zero-telemetry, and   │
│ across heterogeneous hardware targets.           │ │ deterministic agent reasoning guarantees.        │
├──────────────────────────────────────────────────┤ ├──────────────────────────────────────────────────┤
│ • Prism Compile / Weight-Packing (Q1_0 / Q2_0)   │ │ • Prism Vault Air-Gapped Workspace & RAG         │
│ • Prism Megakernel (klein_fast fused GEMM)       │ │ • Arize-Style Observability & Faithfulness Eval  │
│ • Prism Memory Engine (4-Bit Hybrid KV Cache)    │ │ • AST-Sandboxed Python Execution Engine          │
│ • DSpark Speculative Drafter Acceleration        │ │ • Hybrid AI Router (Local Sovereignty vs Cloud)  │
└──────────────────────────────────────────────────┘ └──────────────────────────────────────────────────┘
                                             │
                                             ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                  APPLICATION LIFECYCLE: COMPOSABLE WORKFLOW TIERS                         │
├──────────────────────────────────────────────────────────────────────────────────────────┤
│ Tier 1: Chat with Data (Air-Gapped RAG: Full 100K-262K Document Folders, Zero Chunking)  │
│ Tier 2: Golden Agentic Workflows (Deterministic BFCL v3 Tool Calling & JSON Schemas)     │
│ Tier 3: Buzz-Style Human+Agent Developer Workspace (Co-authoring, Shared Memory Canvas)  │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Target Build vs. Buy Recommendations Across All 3 Infrastructure Layers

Every decision in this table is a research recommendation unless a current-state
artifact in [`ARCHITECTURE_REALITY_MATRIX.md`](./ARCHITECTURE_REALITY_MATRIX.md)
proves otherwise. Capitalized BUILD and ADOPT labels do not mean the component
exists in this repository.

| Infrastructure Layer | Component Evaluated | Decision | Trade-Off Rationale & Engineering Blueprint |
| :--- | :--- | :--- | :--- |
| **Layer 1: Low-Bit Compute** | Standard llama.cpp dequant vs BitNet.cpp LUT vs **Custom Fused Megakernel (`klein_fast` / AVX-512)** | **PROPOSED: evaluate adopted runtimes before a custom kernel project** | A custom fused CUDA, Metal, or AVX-512 kernel remains a research option. The team must first reproduce a runtime bottleneck, output oracle, hardware target, and rollback plan. |
| **Layer 1: Model Architecture** | Proprietary foundation model vs **Bonsai 27B / 8B / 4B Family** | **PILOT / EVALUATE Bonsai Family** | The served 27B artifact is suitable for workload evaluation. Family-level reasoning retention, VRAM, and long-context figures remain unverified research inputs and cannot justify adoption until reproduced. |
| **Layer 2: Document Ingestion** | Custom heuristics vs Marker vs MinerU2.5 vs **Docling (IBM / Linux Foundation)** | **PROPOSED: evaluate Docling and other parsers** | The current parser supports bounded text, CSV, JSON, HTML, XLSX, and PDF input. On the measured macOS prototype, Apple Vision reads image-only PDF pages and keeps page anchors. The current three-page clean-raster benchmark passes its engineering thresholds after the OCR raster changed from 200 to 300 DPI. The same pages were used to select and verify the change, so the result is development regression evidence. It does not cover natural customer scans, general reading order, tables, or layout. XLSX reads stored values and coordinates, preserves raw numeric values, and applies a bounded audited subset of number formats. It does not recalculate formulas, execute macros, traverse external links, or provide full Excel display-format parity. A fixture benchmark and license review must precede any Docling decision. |
| **Layer 3: Execution Sandboxing** | Standard `runc` vs Wasmtime vs Modal/E2B vs **Firecracker (CPU) + gVisor `runsc` (GPU)** | **DEFERRED: define the threat model before selection** | Firecracker and gVisor are not installed. The current AST and subprocess boundary is a prototype. Isolation selection needs escape tests, platform support evidence, and measured cost. |
| **Cross-Cutting: Routing & Observability** | Centralized cloud observability vs a local evaluation service | **CURRENT PILOT: local vendor neutral trace records** | The pilot records a verified SHA-256 local JSONL event chain and separate evaluation dimensions. The chain is neither signed, externally anchored, nor immutable. Energy remains null because it was not measured. |

---

## Detailed System Specifications

### 1. Low-Bit Model Family & The Coding Agent
The target design proposes **Ternary Bonsai 27B** as the flagship model for
constrained coding-agent and financial-analysis workloads. The current pilot
has invoked one `27b@q1_0` artifact on bounded Python and first-pass tasks; it
does not prove autonomous coding, multi-file synthesis, or general financial
audit reliability.

* **Weight Alphabet**: $\{-1, 0, +1\}$ with group-wise scale $s_g \in \text{FP16}$ ($g=128$).
* **Reconstruction**: $w_i = s_g \cdot t_i$.
* **Fused Register Kernel Execution**:
  Weights are streamed as packed 2-bit or sub-2-bit structures into hardware registers (`_pext_u32` / SIMD byte-shuffle / Metal simdgroup), where they are unpacked and scaled in-register. FP16 uncompressed matrices **never touch global DRAM/VRAM**.
* **Target Coding Agent Integration**:
  A production coding agent would inspect authorized file trees, synthesize
  verification scripts, and execute them inside a hardened isolation boundary.
  The current pilot accepts bounded Python tasks and runs AST approved code in
  a resource limited child process. On the measured macOS host, an operating
  system profile denies child network access, process forks, and reads under
  `/Users`, `/Volumes`, and `/Network`. It also denies the resolved current
  project and selected deal-room roots when needed and records the effective
  roots in the trace. It limits writes to one temporary run directory. Other
  readable system paths remain available, and the profile does not provide a
  container or multi tenant security boundary.

### 2. Deal Room Ingestion & Structural Document Parsing
Deal rooms contain unstructured legal PDFs, multi-tab Excel ledgers, board resolutions, and regulatory filings.

* **Target coordinate preserving parser**: A future layout parser would capture
  row, column, rowspan, and colspan values. The current parser does not preserve
  merged PDF or spreadsheet cells.
* **Target document hierarchy**: Docling is one option for a richer document
  tree. It is not installed or selected.
* **Target long context path**: The proposed design would test up to 262,000
  tokens. The measured pilot used a 16,384 token context.

### 3. Arize-Style Evaluation & Observability Framework
Observability is critical to evangelizing Bonsai 27B and proving that sub-2-bit models do not suffer qualitative reasoning collapse.

The product benchmark does not use one aggregate faithfulness or hallucination
score as its release decision. It uses separate hard gates for source integrity,
claim support, numerical accuracy, component completeness, answer absence,
workflow delivery, and human usefulness. The detailed evaluator contract is in
[`FIRST_PASS_UNDERWRITING_BENCHMARK.md`](./FIRST_PASS_UNDERWRITING_BENCHMARK.md).

* **Proposed evaluation dimensions**:
  1. **Faithfulness Score ($0.0 - 1.0$)**: Verifies that every claim in the generated audit is grounded in the source deal room documents.
  2. **Hallucination Detection ($0.0 - 1.0$)**: Scans for ungrounded financial figures, phantom debt covenants, or fabricated legal statutes.
  3. **Tabular Cell Precision & Recall**: Verifies 100% cell accuracy against raw CSV/Excel balances.
  4. **BFCL v3 Agentic Schema Compliance**: Validates that generated tool calls and JSON responses strictly adhere to predefined typing schemas.
  5. **Energy-per-Token ($mWh/\text{tok}$)**: Computes $E_{\text{tg}} = \frac{P_{\text{tg}} \times 3.6}{r_{\text{tg}}}$ to measure true operational energy efficiency compared to cloud baselines.

### 4. Hybrid AI Architecture & Safe Cloud Escalation
The prototype provides an explicit policy router; the production design would
add organizational enforcement and independently validated redaction:
* **Current local policy path**: Proprietary deal room work selects the local
  provider when it is configured. The provider accepts only plain HTTP URLs
  with an IPv4 loopback address or the exact IPv6 `::1` address. DNS aliases,
  private network addresses, and ambiguous URL forms fail during configuration.
  The URL rule does not prove an air gap or zero egress.
* **Current Escalation Boundary (Cloud Frontier)**: Cloud dispatch is denied before provider invocation unless an HTTPS provider and two distinct Buzz authority keys are configured. Each request requires a policy-signed event with a maximum 15-minute lifetime. The event binds the prompt hash, exact room snapshot, provider origin, model, nonce, and expiry. Deal-room context requires a second event signed by the distinct data-owner key. The submitted raw events have no authority by themselves. Prism restores their exact signed fields from the configured Buzz channel before an atomic local ledger consumes the nonce and event IDs. Missing, different, unpublished, or replayed events fail before the provider call. The WebUI reports this state but cannot collect a private signing key or turn cloud access on with a checkbox. The prototype still uses a small explicit pattern-based redaction set, not local NER. This proves the authorization and same-relay restoration boundary in tests; it does not prove an independent trust domain, provider trust, external reachability, redaction completeness, cost, energy, or response quality.
* **Current Buyer Evidence Boundary**: A pricing record cannot authorize its own buyer key. A separately configured commercial authority must publish a Buzz event that approves the buyer key for the exact POC identity and roles. The buyer then signs the complete authorized record with a distinct key. Prism restores and compares both exact events from the configured authority channel on every evaluation. A self-issued key, raw JSON signature, missing event, changed event, or shared authority and buyer key fails. This proves control of two keys and two signed statements. It does not prove legal identity, employment, payment settlement, deal authorization, or market demand.

---

## Application Tiers (The Buzz.xyz Pattern)

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│             TARGET TIER 3: Human and agent collaborative workspace                       │
│   • Shared Context & State Canvas (Live File Tree, Table Inspector, Real-time Diff)      │
│   • Human-in-the-Loop Sign-Off Gates (Covenant Violations, Code Deployment)             │
│   • Local WebSockets over Loopback (Zero Latency, Zero Telemetry)                        │
└────────────────────────────────────────────┬─────────────────────────────────────────────┘
                                             │
                                             ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                    TARGET TIER 2: Reviewed workflow engine                               │
│   • Deterministic Multi-Step Tool Calling (AST-Verified Python Scripts)                  │
│   • M&A Deal Room Auditing (EBITDA Adjustments, Debt Covenant Cross-Check)               │
│   • Strict JSON Schema Enforcement & Automated Fallback Loops                            │
└────────────────────────────────────────────┬─────────────────────────────────────────────┘
                                             │
                                             ▼
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                  TARGET TIER 1: Enforced local long context retrieval                    │
│   • 100K–262K Full Document Folder Ingestion into Bonsai 27B Memory                      │
│   • Lossless Docling AST Document Tree & Coordinate Table Reconstruction                 │
│   • 4-Bit Hybrid KV Cache Management (16 KiB/token)                                      │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Target Security Controls (Not Implemented)

The following are target requirements. The current prototype proves loopback
application binding, AST and subprocess restrictions, a macOS child profile,
and an unsigned local SHA-256 trace chain. The macOS profile denies child
network access and limits writes to one temporary run directory. It does not
implement or prove eBPF egress filtering, signed or externally anchored audit
logs, cross platform write confinement, or hardened multi tenant isolation.

1. **Loopback Binding**: Product services must bind strictly to `127.0.0.1`.
2. **eBPF Egress Filtering**: A future network control must measure and enforce outbound traffic policy.
3. **Execution Isolation**: Production isolation must replace the current prototype AST and child-process boundary.
4. **Local Cryptographic Audit Trail**: A future append-only design must define chaining, key custody, verification, and retention before making integrity claims.
