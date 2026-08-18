# Deal room blueprint architecture

The diagrams describe the implementation shipped in this repository. Solid
lines show working paths. Dotted lines show optional or incomplete paths.

## System context

The browser uses one local server for the workspace and API. The server reads
only the folder selected by the operator. It reaches Bonsai through a loopback
endpoint and stores shared room events in the local Buzz relay.

```mermaid
flowchart LR
    Human["Deal team member"] --> Web["Prism browser workspace<br/>web/"]
    Web --> Server["Local application server<br/>server.py"]
    Server --> Parser["Document parser and source anchors<br/>core/doc_parser.py"]
    Parser --> Folder["Authorized deal room folder"]
    Server --> FirstPass["Retrieval, first pass, and evidence guards<br/>core/first_pass.py"]
    FirstPass --> Local["Bonsai 27B through LM Studio<br/>loopback only"]
    Server --> BuzzBridge["Buzz bridge<br/>core/buzz_bridge.py"]
    BuzzBridge --> Buzz["Local Buzz relay<br/>signed events"]
    Server --> TraceStore["Local trace and evaluation records"]
    TraceStore -.->|explicit privacy limited export| Phoenix["Local Arize Phoenix collector"]
    Server -.->|signed consent required| Cloud["Configured cloud model"]
```

## Local request path

The application separates the model draft from publication. A rejected draft
stays in its trace. The interface can show an evidence safe fallback, but the
fallback does not convert the rejected draft into a passing model result.

```mermaid
sequenceDiagram
    actor Reviewer
    participant UI as Browser workspace
    participant API as Local server
    participant Files as Authorized folder
    participant Parse as Parser and retrieval
    participant Model as Bonsai 27B
    participant Guard as Evidence guards
    participant Buzz as Buzz relay
    participant Eval as Trace and evaluation store

    Reviewer->>UI: Ask a deal question
    UI->>API: Submit room and question
    API->>Files: Read admitted files
    Files-->>Parse: File bytes and metadata
    Parse-->>API: Source passages and anchors
    API->>Model: Send bounded evidence packet
    Model-->>API: Return candidate answer
    API->>Guard: Check structure, claims, numbers, and citations
    alt Candidate passes
        Guard-->>API: Accept candidate
        API->>Buzz: Publish signed answer and citations
    else Candidate fails
        Guard-->>API: Reject candidate and keep failure trace
        API->>Buzz: Publish bounded source excerpt fallback
    end
    API->>Eval: Record route, spans, checks, and release state
    API-->>UI: Return the published room state
```

## Hybrid routing and consent

Deal room work uses the local route by default. A cloud route must be
configured by the operator, use HTTPS, redact known personal data, and receive
short lived signed consent. Cloud and hybrid benchmark runs have not been
completed.

```mermaid
flowchart TD
    Request["Incoming task"] --> Policy{"Local only policy,<br/>active deal room, or confidential content?"}
    Policy -- "Yes" --> LocalReady{"Local model available?"}
    LocalReady -- "Yes" --> Bonsai["Run Bonsai locally"]
    LocalReady -- "No" --> Deterministic["Use deterministic local workflow"]
    Policy -- "No" --> CloudReady{"Cloud provider configured?"}
    CloudReady -- "No" --> NoCloud["Return cloud not configured"]
    CloudReady -- "Yes" --> Redact["Apply configured redaction rules"]
    Redact --> Consent{"Valid signed dispatch consent?<br/>Valid context consent when needed?"}
    Consent -- "No" --> Block["Block cloud dispatch"]
    Consent -- "Yes" --> Cloud["Call approved HTTPS provider"]
    Bonsai -.->|planned review composition| Hybrid["Local draft and cloud review"]
    Cloud -.->|comparison not measured| Hybrid
```

The routing code lives in
[`core/hybrid_router.py`](../../core/hybrid_router.py). The provider boundary
lives in [`core/ai_provider.py`](../../core/ai_provider.py), and signed cloud
consent lives in [`core/cloud_consent.py`](../../core/cloud_consent.py).

## Evaluation and observability

The release process keeps each evaluation layer separate. A critical failure
in source fidelity, evidence, numbers, citations, or policy cannot be hidden by
an average score from another layer.

```mermaid
flowchart LR
    Run["Agent run"] --> Trace["Local trace with model, tool, retrieval, and workflow spans"]
    Trace --> Deterministic["Deterministic checks"]
    Trace --> Review["Blind human review"]
    Trace --> Judge["Candidate model judges"]
    Review --> Calibration["Judge calibration against held out human labels"]
    Judge --> Calibration
    Deterministic --> Gates["Release gates"]
    Review --> Gates
    Calibration --> Gates
    Gates --> Evidence["Versioned release evidence"]
    Trace -.->|manual privacy limited OTLP export| Phoenix["Arize Phoenix"]

    Fidelity["1. Document fidelity"] --> Retrieval["2. Retrieval"]
    Retrieval --> Answer["3. Answer"]
    Answer --> Workflow["4. Workflow"]
    Workflow --> HumanUse["5. Human usefulness"]
    HumanUse --> Deployment["6. Deployment behavior"]
    Deployment --> Value["7. Business value"]
```

The local trace schema and checks live in
[`core/arize_evals.py`](../../core/arize_evals.py). The explicit Phoenix
exporter lives in
[`scripts/export_eval_review_to_phoenix.py`](../../scripts/export_eval_review_to_phoenix.py).
The [observability guide](../concepts/observability-and-evaluation.md) explains
the OpenTelemetry and OpenInference terms.

## Repository boundaries

```mermaid
flowchart TB
    Catalog["CATALOG.yaml"] --> UseCase["use-cases/<br/>job and economic reason"]
    Catalog --> Blueprint["blueprints/<br/>model, harness, interface, and evaluations"]
    Blueprint --> Models["models/<br/>model cards and runtime profiles"]
    Blueprint --> Packages["packages/<br/>shared component contracts"]
    Blueprint --> Benchmarks["benchmarks/<br/>task and grading contracts"]
    Blueprint --> Demo["deal_rooms/<br/>safe demonstration fixtures"]
    Blueprint --> Evidence["evidence/<br/>test and release records"]
    Docs["docs/<br/>tutorials, guides, concepts, reference, and decisions"] --> Blueprint
```

The [blueprint manifest](../../blueprints/deal-room-analyst/blueprint.yaml) is
the source of truth for the first package. The [catalog](../../CATALOG.yaml) is
the source of truth for repository discovery.
