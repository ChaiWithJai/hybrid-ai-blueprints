# Update demo screenshots

Update screenshots when the visible workflow changes. Do not update a
screenshot to hide a failed or incomplete product state.

## Before you capture

Use a clean Git worktree and start the blueprint through its documented run
command. Confirm that the canonical demo URL loads and that the browser console
has no errors.

Use the synthetic fixtures for public screenshots: Project Titan for the deal
room, Dorothy for CareLine. Do not capture customer files, credentials, local
file paths, private model details, reviewer identities, or an operator's name.

Each blueprint keeps its own screenshots and its own manifest, per
[ADR 0003](../ADR_0003_CATALOG_SCALING_PATTERN.md):

| Blueprint | Directory | Capture |
| --- | --- | --- |
| Deal room analyst | `docs/assets/screenshots/` | Manual, following this guide |
| CareLine voice check-in | `docs/assets/screenshots/careline/` | Scripted, see below |

## Required views

Capture the following states at 1280 by 720 or larger:

1. The Overview tab with the decision state.
2. A cited source passage.
3. The Sources tab with the admitted file inventory.
4. The Activity tab with a source checked answer.
5. The human Review queue.
6. The Eval lab with route coverage and release gates.

Store the PNG files in `docs/assets/screenshots/`.

## Update the manifest

Update `docs/assets/screenshots/manifest.json` with the following values:

- Capture time
- Source commit
- Canonical application URL
- Synthetic fixture name and class
- Viewport size
- Screenshot state
- SHA256 hash
- Claim boundary

The manifest must describe what the screenshot shows. It must not claim model
accuracy or customer value.

## Update the guides

Add each required screenshot to the [demo tour](../demo/README.md). Add a
screenshot to the getting started guide only when it helps the reader complete
the next step.

Use meaningful alternative text. Explain the visible state in the paragraph
before or after the image.

## CareLine

CareLine's capture is scripted, so the state is the same every time and the
manifest is written for you:

```bash
# 1. a scratch database, so the picture shows a first pass and not an
#    accumulation of local runs
export CARELINE_DB=/tmp/careline_demo.db && rm -f "$CARELINE_DB"
blueprints/careline-voice-checkin/scripts/run

# 2. one demo cycle: three calls, which leaves memory and one alert
cd blueprints/careline-voice-checkin/app
uv run python scripts/demo_run.py

# 3. capture. playwright-core comes from the deal room application
(cd ../../deal-room-analyst/app && npm install && npm run setup:browser)
node scripts/capture_screenshots.mjs --base-url http://127.0.0.1:8100
```

The script drives the real browser client, so it cannot capture a state the
product cannot reach. It refuses to capture if the self-voice option names an
operator, because that label is an operator setting served from `/api/config`
and a committed screenshot showing one person's name would be wrong for everyone
else. Unset `CARELINE_SELF_NAME` before capturing.

The resident's line is scripted, so the concern signals — and therefore the
severity and score shown in the alert panel — are identical on every capture.

## Verify

Run:

```bash
python3 tooling/documentation/validate_links.py
cd blueprints/deal-room-analyst/app && python3 -m unittest tests.test_documentation_assets
```

The asset test checks both manifests: the required screenshot set, PNG headers,
minimum dimensions, and SHA-256 hashes. It also asserts that CareLine's
screenshot is referenced from both the root README and the blueprint README, and
that its recorded state names no operator. The link check confirms that every
local page and image exists.

A screenshot whose hash no longer matches its manifest entry fails the test. That
is the intended behaviour: replace the image and the manifest together, in one
change, so provenance never drifts from the file.
