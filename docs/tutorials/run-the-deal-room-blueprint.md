# Run the deal room blueprint

The tutorial starts the local deal room application and opens the synthetic
Project Titan room.

## Requirements

Install Python 3 and Docker. Install LM Studio, load the approved Bonsai 27B
artifact, and start its OpenAI compatible local server on port 1234.

## Check the host

From the repository root, run:

```bash
blueprints/deal-room-analyst/scripts/preflight
```

Resolve every failed requirement before starting the application. A warning
states a limit that does not block the engineering demo.

## Start the application

Run:

```bash
blueprints/deal-room-analyst/scripts/run
```

The command starts or checks the required local services and serves the Prism
workspace on port 8787.

## Review Project Titan

Open:

```text
http://127.0.0.1:8787/rooms/project_titan_lbo/first-pass
```

Read the decision question, inspect the saved first pass, and open a citation.
Then, use Activity to ask a follow up question.

## Inspect the evaluation

Open:

```text
http://127.0.0.1:8787/rooms/project_titan_lbo/evaluation
```

The page shows recorded runs and missing evidence. A missing cloud or hybrid
run appears as not measured.

## Stop the services

Stop the foreground process with Control C. The runtime data remains under
`.runtime/`, which Git ignores.
