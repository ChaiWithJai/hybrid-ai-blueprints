# Run the deal room blueprint

The tutorial starts the local Hybrid AI Blueprint and opens the synthetic
Project Titan deal room. You will inspect a guarded first pass, open a cited
source passage, review the shared room activity, and inspect the evaluation
state.

![Project Titan deal room overview](../assets/screenshots/deal-room-overview.png)

Project Titan is synthetic. The workflow is suitable for a public demo, but it
does not provide model accuracy or customer evidence.

## What you will run

The local demo uses the following parts:

- Bonsai 27B runs through LM Studio on a loopback endpoint.
- The Python server parses the deal room and applies evidence checks.
- The browser provides the shared review workspace.
- Buzz stores signed room messages on a local relay.
- Docker runs the local Buzz services.

Read the [architecture guide](../architecture/README.md) for the complete data
flow.

## Requirements

The current setup has been verified on macOS. Other operating systems have not
completed the same host checks.

Install the following software before you continue:

- Git
- Python 3
- Docker Desktop or another working Docker daemon
- LM Studio and its `lms` command line tool
- The Bonsai 27B artifact registered as `27b@q1_0`

The repository does not contain model weights. You must obtain the approved
artifact separately.

## Clone the repository

Run:

```bash
git clone https://github.com/ChaiWithJai/hybrid-ai-blueprints.git
cd hybrid-ai-blueprints
```

The `main` branch contains the verified public demo.

## Start Bonsai 27B

Open LM Studio and load the model registered as `27b@q1_0`. Start the local
server on `http://127.0.0.1:1234`.

You can also use the LM Studio command line tool when the artifact is already
installed:

```bash
lms load 27b@q1_0 --identifier 27b@q1_0 --yes
```

Confirm that LM Studio reports the model as loaded:

```bash
lms ps
```

The runtime profile is defined in
[`models/bonsai-27b/runtime-profiles/lm-studio.yaml`](../../models/bonsai-27b/runtime-profiles/lm-studio.yaml).

## Check the host

Run the preflight check from the repository root:

```bash
blueprints/deal-room-analyst/scripts/preflight
```

The command checks Python, Docker, the PDF and OCR tools, the local model
endpoint, and the Bonsai model state. Resolve every failed requirement before
you start the application. A warning records a missing benchmark detail, but
it does not block the engineering demo.

Expected final lines:

```text
Required checks passed.
Boundary: same-host preflight; this is not clean-machine reproduction.
```

## Start the application

Run:

```bash
blueprints/deal-room-analyst/scripts/run
```

The command starts the local Buzz services, runs a live preflight check, and
serves the workspace on port 8787.

Expected final lines:

```text
Prism Vault local prototype listening at http://127.0.0.1:8787
Prism Vault v0: http://127.0.0.1:8787/rooms/project_titan_lbo
```

Keep the terminal open while you use the demo.

## Confirm the service state

Open another terminal in the repository and run:

```bash
curl -fsS http://127.0.0.1:8787/api/status | python3 -m json.tool
```

Confirm that the response reports a configured local model and a live Buzz
relay. The exact trace counts and room counts can differ from the screenshots.

## Bind the demo room

The demo rooms are listed from the catalog, but each one needs its own Buzz
channel before its workspace opens. On a fresh clone none are bound, and the
room page shows "Opening workspace" indefinitely. Bind them once:

```bash
cd blueprints/deal-room-analyst/app
python3 scripts/seed_fixture_room.py --all
```

Expected output, with one line per room:

```text
project_aeroflux_crossborder_ma: bound to channel <uuid> with 4 documents
project_biovanguard_carveout: bound to channel <uuid> with 4 documents
project_titan_lbo: bound to channel <uuid> with 4 documents
sample_ma_acquisition: bound to channel <uuid> with 4 documents
```

The command is idempotent, so running it again reports the existing bindings
instead of creating more channels. Confirm the binding with the workspace API
rather than the page, because the room route returns the single-page shell and
answers 200 even when nothing is bound:

```bash
curl -fsS 'http://127.0.0.1:8787/api/workspace?room=project_titan_lbo' \
  | python3 -m json.tool | head -8
```

Expect `room_name`, `total_documents: 4`, and an empty `parse_warnings` list. An
`{"error": "workspace_not_bound"}` response means the seeding step did not run
in this application directory.

## Review Project Titan

Open the canonical demo URL:

```text
http://127.0.0.1:8787/rooms/project_titan_lbo/first-pass
```

A newly bound room has no review yet, so the Overview tab opens on "What
should the team decide?" with a prefilled decision focus. The screenshots in
this tutorial show the state *after* a review, not the state you land on.

First, run the review. Leave the prefilled decision focus as it is and select
**Review deal room**. The button disables while the model works. On the
measured host, with Bonsai 27B served by LM Studio, this took about 80 seconds
for Titan's four documents. When it finishes, the Overview tab shows a decision
status, the reason, the decision question, and the priority files to read next.

The expected result is **Not Ready To Advance**, with "The automated review did
not meet the source rules." The guard pausing the draft is the demonstration,
not a failure: the model's first pass did not satisfy the source rules, so the
product refuses to present it as a finished brief. A run that advanced without
review would be the surprising outcome.

The decision question is generated, so its wording can differ between runs. On
the measured run it read: "Should Project Titan advance despite the mismatch
between debt paydown and the Section 2.02 cash sweep terms?"

Second, select a priority file to open the exact cited passage.

![Debt terms citation preview](../assets/screenshots/cited-source-evidence.png)

Third, open the Sources tab and inspect the files admitted from the folder.

![Project Titan source inventory](../assets/screenshots/source-inventory.png)

Fourth, open the Activity tab. Ask a source bound question or leave a team
note. The answer and its citations stay with the room.

![Project Titan team activity](../assets/screenshots/team-activity.png)

## Inspect the evaluations

Open the Evaluation tab and keep Review queue selected. The queue shows a full
trace so a reviewer can judge the answer in context.

![Evaluation review queue](../assets/screenshots/evaluation-review-queue.png)

Select Eval lab to see route coverage, judge calibration, and release gates.

![Evaluation lab](../assets/screenshots/evaluation-lab.png)

The local development route contains recorded evidence. Cloud and hybrid runs
remain unmeasured until an operator configures a provider, records the required
consent, and runs the same cases.

## Run the verification suite

Run:

```bash
blueprints/deal-room-analyst/scripts/verify
```

The command validates the catalog and documentation links before it runs the
Python tests. A passing software suite does not replace blind domain review,
private customer testing, or the pricing exercise.

## Use an authorized folder

Select Open folder in the left navigation. Choose a folder you are allowed to
process and inspect the preview before you create its room.

Do not add customer documents to the repository. The application stores local
runtime data under `.runtime/`, and Git ignores that directory.

## Stop the services

Press Control C in the terminal that runs the application. The command stops
the foreground server. Docker can keep the Buzz containers available for the
next run.

To stop the Buzz containers, run:

```bash
docker compose -f infra/buzz/compose.yml down
```

## Troubleshooting

### The preflight says Bonsai is not loaded

Run `lms ps` and confirm that `27b@q1_0` is present. Load the model again if it
is missing, then rerun the preflight check.

### The page reports that Buzz is unavailable

Confirm that Docker is running, then rerun the blueprint start command. The
command creates or checks the Buzz containers and runs the live relay check.

### Port 8787 or 3030 is already in use

Find the local process or container that owns the port. Stop only the process
you recognize, then rerun the start command.

### The preflight reports missing deployment metadata

The engineering demo can continue. A benchmark claim cannot continue until
you record the model artifact hash, runtime name and version, and hardware in
the required environment variables.

### The evaluation says "Not enough evidence"

The message is the expected state until qualified reviewers label the traces
and the same task set has local, cloud, and hybrid results. Do not replace the
missing runs with simulated outputs.

## Next steps

Read the [demo tour](../demo/README.md) for a guided product walkthrough. Read
the [evaluation contract](../../blueprints/deal-room-analyst/evals/README.md)
before you record a benchmark result.
