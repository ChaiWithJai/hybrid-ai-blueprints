# Update demo screenshots

Update screenshots when the visible workflow changes. Do not update a
screenshot to hide a failed or incomplete product state.

## Before you capture

Use a clean Git worktree and start the blueprint through its documented run
command. Confirm that the canonical demo URL loads and that the browser console
has no errors.

Use Project Titan for public screenshots. Do not capture customer files,
credentials, local file paths, private model details, or reviewer identities.

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

## Verify

Run:

```bash
python3 tooling/documentation/validate_links.py
cd blueprints/deal-room-analyst/app && python3 -m unittest tests.test_documentation_assets
```

The asset test checks the required screenshot set, PNG headers, dimensions,
and hashes. The link check confirms that every local page and image exists.
