# Draft Build vs. Buy Strategy: Modern AI Infrastructure & Sovereign Workspaces

> **Research status.** This guide recommends a target direction for evangelizing
> the Bonsai family. Recommendations, cited comparisons, and projections are not
> proof of an installed model or measured result in this repository.
> The source bibliography for the precise third-party benchmark, license,
> latency, memory, and energy figures is not included here. Treat those figures
> as unverified research notes until sources and reproduction evidence are
> attached. The accepted current-cycle decision is ADR 0001.

**Author**: Draft working group; no approval record is stored in this repository  
**Target Audience**: CTOs, Chief AI Officers, Platform Engineering Leads, Compliance CISOs  
**Date**: August 13, 2026

---

## Executive Summary

Enterprise leaders evaluating generative AI infrastructure face a critical strategic question: **What should we build in-house, what open-source foundation should we adopt, and what commercial services should we license?**

A common failure mode is building custom implementations at the wrong abstraction layers (e.g., spending 18 months training a foundation model from scratch or building an OCR neural network) while buying commoditized cloud wrappers that violate corporate data sovereignty and rack up unsustainable token bills.

This guide proposes a **Build vs. Buy decision framework** across three core
infrastructure layers. ADR 0001 narrows the current implementation to adopting
the serving runtime and building the workload, evidence, policy, and evaluation
layers.

---

## The 3-Layer Build vs. Buy Framework

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Layer 1: Low-Bit LLM Compute & Edge Acceleration                                                │
├─────────────────────────────────────────────────────────────────────────────────────────────────┤
│ • CURRENT PILOT: LM Studio/Bionic serving one 27B Q1_0 artifact.                                │
│ • EVALUATE: BitNet.cpp only with a versioned compatibility and performance test.                │
│ • DEFER: Custom kernels until profiling shows an adopted-runtime bottleneck.                    │
└────────────────────────────────────────────────┬────────────────────────────────────────────────┘
                                                 │
┌────────────────────────────────────────────────▼────────────────────────────────────────────────┐
│ Layer 2: Document Ingestion & Structural Extraction                                             │
├─────────────────────────────────────────────────────────────────────────────────────────────────┤
│ • CURRENT: Internal Markdown, text, CSV, and JSON parser.                                       │
│ • EVALUATE: Docling, Marker, and MinerU using version-pinned fixtures and license review.        │
│ • BUILD: Domain-Specific Deal Room AST Ingestion & Coordinate Preservation Pipelines.           │
└────────────────────────────────────────────────┬────────────────────────────────────────────────┘
                                                 │
┌────────────────────────────────────────────────▼────────────────────────────────────────────────┐
│ Layer 3: Agentic Execution Sandboxing & Runtime Isolation                                       │
├─────────────────────────────────────────────────────────────────────────────────────────────────┤
│ • BUY / ADOPT MANAGED: Modal / E2B ONLY for non-sensitive public/cloud workloads.               │
│ • CURRENT: AST allowlist, resource limits, and a macOS sandbox-exec profile.                    │
│ • EVALUATE: Firecracker/gVisor only against a threat model and measured platform requirements.  │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Detailed Layer-by-Layer Evaluation

### Layer 1: Low-Bit Compute & Model Serving

| Component | Options | Decision | Rationale |
| :--- | :--- | :--- | :--- |
| **Model Weights & Training** | 1. Train a base model<br>2. License a cloud model API<br>3. **Pilot Bonsai 27B / 8B Family** | **PILOT Bonsai 27B; EVALUATE THE FAMILY** | Current evidence covers one 27B artifact on bounded workloads. Training-cost, reasoning-retention, VRAM, and 262K-context comparisons are unverified research inputs until sourced and reproduced. Cloud use is a separate explicit path and is incompatible with a local-only request when deal-room context would be sent. |
| **Compute Execution Kernel** | 1. Adopted LM Studio/llama.cpp runtime<br>2. Evaluate BitNet.cpp<br>3. Consider a custom fused kernel only after profiling | **ADOPT SERVING RUNTIME FOR PILOT; DEFER CUSTOM KERNEL** | The repository has no kernel implementation or comparative profile. Claims about FP16 materialization, cache pressure, or speedup remain hypotheses until measured against the exact artifact and workload. |

---

### Layer 2: Document Parsing & Layout Recognition

| Option | Current repository evidence | Required decision evidence |
| :--- | :--- | :--- |
| **Docling** | Not installed or benchmarked | Pin version and models; legal review; compare PDF, OCR, tables, order, latency, memory, and failure behavior |
| **Marker** | Not installed or benchmarked | Pin version and models; legal review; run the same fixture set |
| **MinerU** | Not installed or benchmarked | Pin version and models; legal review; run the same fixture set |
| **Custom OCR** | Not implemented | Consider only if measured product failures cannot be solved at a maintained integration boundary |

*Research recommendation*: Evaluate **Docling** against licensed, version-pinned
PDF/OCR/XLSX fixtures before adoption. The repository has not reproduced the
table-accuracy, resource, licensing, or long-context claims in this comparison.

---

### Layer 3: Agentic Execution Sandboxing

| Strategy | Current repository evidence | Required decision evidence |
| :--- | :--- | :--- |
| **Commercial serverless** | Not integrated | Data-boundary review, approved provider, workload compatibility, latency, and failure test |
| **Firecracker** | Not installed | Threat model, host compatibility, filesystem/network confinement, startup and resource measurements |
| **gVisor / `nvproxy`** | Not installed | Threat model, supported GPU/runtime matrix, escape testing, latency, and resource measurements |
| **Wasmtime** | Not installed | Python/library compatibility, capability model, startup and resource measurements |

*Research recommendation*: Evaluate Firecracker and gVisor only after threat
model, platform, GPU, and latency requirements are fixed. Neither runtime is
installed, and this document provides no proof of safe multi-tenant GPU sharing
or air-gap compliance.

---

## Hypotheses to Validate Before Evangelizing Bonsai 27B

### 1. The Single-GPU Workstation Breakthrough (20 GB VRAM Limit)
* Reproduce weight, KV-cache, runtime-overhead, and peak-memory measurements for
  FP16, conventional 4-bit, and the named Bonsai artifact.
* Treat the earlier 54 GB, 17.6 GB, and 10.87 GB figures as unverified inputs,
  not capacity-planning facts.

### 2. Eliminating Lossy RAG Chunking in M&A Deal Rooms
Measure whether bounded retrieval or full-context input performs better on
cross-document covenant cases. The current 16,384-token pilot does not show
that Bonsai holds an entire private deal room in memory.

### 3. Sub-2-Bit Coding Agent Reliability
Run a source-linked BFCL and repository-level coding evaluation. The earlier
74.01 BFCL figure has not been reproduced here, and the current fourteen-case
Python pilot does not establish full coding-agent capability.

### 4. Energy-per-token hypothesis

Measure wall power, idle baseline, prompt and generation phases, output tokens,
runtime configuration, and repeated-run variance for every compared system.
This repository has no energy telemetry, so it makes no energy, carbon, or
cloud-hardware comparison.
