# [PRD] Prism Vault: Air-Gapped Sovereign Workspace Runtime

> **Current product decision, August 17, 2026.** The active goal is a clear
> customer demo for one deal room workflow. Accuracy certification and
> commercial proof are outside the current goal. Their existing records remain
> historical work and do not control demo completion. See
> [`ADR_0002_DEMO_FIRST_SCOPE.md`](./ADR_0002_DEMO_FIRST_SCOPE.md) and
> [`DEMO_INFORMATION_ARCHITECTURE.md`](./DEMO_INFORMATION_ARCHITECTURE.md).

> **Document status — target-state requirements.** This PRD describes the
> product goal and researched architecture. It is not evidence that Bonsai
> weights, benchmark results, hardware kernels, or certified isolation are
> installed. See `README.md` and `docs/VERIFICATION_GATES.md` for current state.
> Measured pilot results are listed in the [benchmark card](./BENCHMARK_CARD.md).

**Summary**: Target design for an enterprise on-premises document processing and indexing runtime.  
**Created**: August 13, 2026  
**Proposed owner**: `product@prismml.ai`  
**Proposed contributors**: `engineering@prismml.ai`, `security@prismml.ai`  
**Status**: Draft target state; stakeholder approval is not recorded in this repository  
**RFC**: [RFC-0042: Prism Vault System Rails & Architecture](./RFC_0042_VAULT_ARCHITECTURE.md)

---

## Overview

### First product job

The minimum product job is to decide whether to advance, pause, or stop a deal,
and know what must happen next. A user opens an authorized M&A folder, states
the decision question, reads the status and reason, checks the priority files,
and records the team action at one stable room URL.

The current demo does not claim to produce a completed investment committee
memo or a certified answer. The demo acceptance contract is
[`DEMO_INFORMATION_ARCHITECTURE.md`](./DEMO_INFORMATION_ARCHITECTURE.md).

The target product is an enterprise-grade, on-premises document processing and
indexing runtime for highly confidential data, including multi-page PDFs,
scanned OCR documents, and multi-tab financial spreadsheets. The intended
production design would enforce offline operation, use a validated low-bit
model runtime, and support 100K to 262K-token workloads within a workstation
memory budget. None of those production, format, context-length, or network
claims is implemented by the current prototype. The current evidence boundary
is maintained in [`ARCHITECTURE_REALITY_MATRIX.md`](./ARCHITECTURE_REALITY_MATRIX.md).

```
┌────────────────────────────────────────────────────────┐
│      TARGET: Prism Vault Air-Gapped Boundary           │
└───────────────────────────┬────────────────────────────┘
                            │
   ┌────────────────────────┴────────────────────────┐
   ▼                                                 ▼
┌───────────────────────────────────┐ ┌───────────────────────────────────┐
│ Local Ingestion & Parsing Engine  │ │   Local Long-Context Execution    │
├───────────────────────────────────┤ ├───────────────────────────────────┤
│ • TARGET: Layout AST / Docling    │ │ • TARGET: validated low-bit model │
│ • Tabular Excel / CSV Extractor   │ │ • Hybrid 4-Bit KV Cache (16KB/tok)│
│ • PDF Layout & Document Tree      │ │ • TARGET: fused compute kernels   │
│ • Coordinate-Preserving Tables    │ │ • DSpark Speculative Drafter      │
└─────────────────┬─────────────────┘ └─────────────────▲─────────────────┘
                  │                                     │
                  └───────── In-Memory Ingestion ───────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│              TARGET: Zero-Telemetry Guardrail Firewall                  │
├─────────────────────────────────────────────────────────────────────────┤
│ • Loopback-Only Socket Binding (127.0.0.1)                              │
│ • eBPF Egress Filter (0 Packets Emitted)                                │
│ • Arize-Style Observability & Faithfulness Tracing                      │
│ • AST-Sandboxed Python Tool Execution                                   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Background

Regulated enterprise sectors—such as Mergers & Acquisitions (M&A), Public Sector/Defense, Healthcare, and Corporate Legal Advisory—handle high-stakes, proprietary data that cannot be transmitted across third-party cloud API boundaries due to strict data residency laws, non-disclosure agreements, and insider trading regulations.

Existing solutions force enterprises into an unacceptable compromise:
1. **Third-Party Cloud APIs (e.g., OpenAI, Anthropic)**: High reasoning capacity, but violates air-gap security constraints, introduces telemetry and IP leakage risks, and carries high recurring token-based operating costs.
2. **Traditional On-Premises RAG (FP16 / Standard 4-bit)**: Fails on localized hardware budgets. Standard 27B models in FP16 consume 54 GB of VRAM, while conventional 4-bit models trigger Out-Of-Memory (OOM) crashes when attempting to hold 100K+ token documents alongside their Key-Value (KV) cache on single workstation cards. Furthermore, aggressive text-chunking destroys the tabular relationships inside financial ledgers and legal cross-references.
3. **Ungoverned Local Agent Frameworks**: Rely on unverified script execution that exposes host systems to security escapes, hallucinated tool calls, and high energy draw.

The target design aims to address this through a **Trust & Context Lifecycle
(TCL)** and **Run Lifecycle Management (RLM)**. Docling-style parsing, 262K
context, and enforced air-gapping are proposed capabilities, not current
repository behavior. The current parser also admits HTML, bounded PDF, and
bounded XLSX. On the measured macOS prototype, image-only PDF pages use Apple
Vision OCR when they do not contain usable embedded text. The OCR path keeps
physical page citations, but it does not reconstruct tables or layout. A
three-page clean-raster engineering benchmark now measures its text accuracy.
The current run passes the engineering thresholds after the OCR raster changed
from 200 to 300 DPI. The same pages were used to choose the change, so the pass
is development regression evidence. Natural customer scans and independent
domain labels remain untested. XLSX support reads stored values and coordinates and applies a
bounded, audited subset of number formats while preserving raw values. It does
not recalculate formulas or provide full Excel formatting parity. The measured local model
pilot used a fitted 16,384-token context and no network-enforcement measurement.

---

## Problem Statement

Organizations cannot run long-context document analysis on-premises without encountering security non-compliance, hardware memory exhaustion, or severe computational and reasoning degradation.

---

## Personas & User Journeys

### Affected Persona 1: Enterprise CISO / Compliance Officer
* **Struggle**: Securing sensitive deal rooms and confidential customer data against accidental cloud leakage and untrusted execution.
* **Requirements**: 100% data residency guarantee, zero outbound telemetry, eBPF-enforced loopback binding, and cryptographically verifiable local audit traces.

### Affected Persona 2: IT Infrastructure & Operations Lead
* **Struggle**: Balancing computational budget with team demands; unable to procure backordered $50k+ server clusters (H100s/A100s).
* **Requirements**: Deploy multi-department AI workloads on standard workstation hardware (e.g., single RTX 4000 20GB or Mac Studio nodes) with energy consumption under 130W.

### Affected Persona 3: Data Analyst / M&A Legal Auditor
* **Struggle**: Reviewing 150+ page legal folders, scanned PDFs, and complex multi-tab Excel ledgers.
* **Requirements**: Ingest complete folders into one context window without lossy RAG chunking, preserving exact cell-coordinate structures and cross-document covenant relationships.

---

## Projected Mathematical Foundations & Intelligence Density

The figures in this section are unvalidated research inputs. Their source
bibliography and reproduction artifacts are not present in this repository.
They must not be presented as Prism Vault measurements; current measurements
are limited to the [benchmark card](./BENCHMARK_CARD.md).

### 1. Low-Bit Model Footprint & KV Cache Formula
Bonsai 27B utilizes a **hybrid-attention architecture** where only $L_{\text{attn}} = 16$ out of 64 layers carry an active self-attention KV cache (with $n_{\text{kv}} = 8$ GQA heads, $d = 128$ head dimension).

$$\text{KV Cache Rate}_{\text{FP16}} = 2 \times L_{\text{attn}} \times n_{\text{kv}} \times d \times 2 \text{ bytes} = 65,536 \text{ bytes/token} \approx 64 \text{ KiB/token}$$

With **4-bit KV Cache Quantization**:
$$\text{KV Cache Rate}_{\text{4-bit}} = 64 \text{ KiB/token} \div 4 = 16 \text{ KiB/token}$$

$$\text{Peak Memory}_{\text{Operational}} = W_{\text{compressed}} + \text{KV}(T) + M_{\text{overhead}}$$

For a 120,000 token M&A folder on Ternary Bonsai 27B:
$$\text{Peak Memory} = 7.15\text{ GB (Weights)} + 1.92\text{ GB (120K KV Cache)} + 1.80\text{ GB (Overhead + DSpark)} = 10.87\text{ GB} \le 20\text{ GB (RTX 4000 Ceiling)}$$

### 2. Intelligence Density Metric
$$D_I = \frac{\text{Benchmark Accuracy Score } (S)}{\text{Effective VRAM Footprint in GB } (M_{\text{eff}})}$$

Where $S$ evaluates emergent reasoning (BFCL v3 agentic tool use, MMLU-Redux, Tabular Cell Fidelity):
* **Baseline FP16 (56.86 GB total)**: $78.2 / 56.86 = \mathbf{1.37 \text{ pts/GB}}$
* **Conventional 4-bit Q4_K_XL (20.46 GB total)**: $77.1 / 20.46 = \mathbf{3.76 \text{ pts/GB}}$
* **Conventional 2-bit Q2_K (10.26 GB total)**: $72.7 / 10.26 = \mathbf{7.08 \text{ pts/GB}}$ *(Qualitative collapse in agentic loops)*
* **Ternary Bonsai 27B (8.76 GB total)**: $74.0 / 8.76 = \mathbf{8.44 \text{ pts/GB}}$ *(2.25x efficiency over 4-bit, zero reasoning collapse)*

---

## Requirements and Phases

### Phase 1: Air-Gapped Ingestion & Extraction Engine
* **Req 1.1 (Zero-Network Boundary Enforcement)**: Ingestion runtime binds strictly to `127.0.0.1`. eBPF/iptables drop all non-loopback egress packets.
* **Req 1.2 (Tabular & Layout AST Parsing)**: Multi-stage parser transforms PDFs, OCR scans, and Excel sheets into structured `DoclingDocument` ASTs, preserving table cell coordinates $(r, c, \text{span})$ and hierarchical section links.

### Phase 2: In-Memory Long-Context Indexing & KV Management
* **Req 2.1 (Fixed-Memory Sub-2-Bit Memory Allocation)**: Ingest 100K–262K token folders under a 12.0 GB VRAM limit.
* **Req 2.2 (Speculative Drafting & Fused Kernels)**: Integrate `DSpark` 6-layer drafting model and inline register-fused GEMM (`klein_fast` / AVX-512 / CUDA) so FP16 weights never materialize in RAM.

### Phase 3: Coding Agent, Arize-Style Observability & Buzz UI
* **Req 3.1 (AST-Sandboxed Coding Agent)**: Local coding agent executes verified Python scripts against ingested deal room data with strict capability boundaries.
* **Req 3.2 (Arize-Style Evaluation & Tracing)**: Capture full spans, latency, token energy ($mWh/\text{tok}$), semantic faithfulness, hallucination detection, and schema validity. Semantic faithfulness, hallucination detection, token energy, and general table extraction accuracy remain target requirements. The current prototype records exact lexical claim reproduction, configured denylist matches, exact fixture cell matches, required field presence, and bounded top level JSON type checks. It does not rename those checks as the target metrics, and it does not claim full JSON Schema validation.
* **Req 3.3 (Hybrid AI Router)**: Route proprietary deal-room tasks to local Bonsai by default. Cloud escalation fails before provider invocation unless an operator has configured an HTTPS provider and two distinct Buzz consent authorities. Each cloud request needs a short-lived policy signature bound to the prompt hash, exact room snapshot, provider, model, nonce, and expiry. Releasing deal-room context needs a second signature from the distinct data-owner key. Prism must restore each exact signed event from the configured Buzz channel before atomically consuming it once. A signed event supplied only in an HTTP body has no authority. The current redaction path is pattern based and is not a substitute for the second signature. This enforces request authorization and durable approval restoration, but it does not prove an air gap, provider trust, redaction completeness, or output quality.
* **Req 3.4 (Buzz collaborative workspace)**: The main room contains Overview, Sources, Activity, and Evaluation. A user can open a room, state a decision, run Bonsai, read a source linked brief, inspect a citation, discuss the result, review contextual room traces, and copy the room link without visiting another application.

Benchmark certification and buyer pricing work remain archived research inputs.
They are not current demo requirements.

---

## Required Approvals and Sign-off

No signed approval artifact is stored in this repository. The benchmark
governance ledger is unconfigured and contains zero of 12 required receipts.
Names and booleans in the benchmark manifest do not count as approval. A signed
Buzz authority assignment and role-specific, material-bound receipts are the
only executable approval path. These roles remain release requirements rather
than completed approvals.

| Stakeholder Role | Representative | Status |
| :--- | :--- | :--- |
| Project Engineering Lead | Unassigned | Not recorded |
| Product Manager | Unassigned | Not recorded |
| VP of Product | Unassigned | Not recorded |
| Sales Engineering Lead | Unassigned | Not recorded |
| Chief Information Security Officer | Unassigned | Not recorded |
