# Decision 0001: Use a blueprint monorepo

Date: August 18, 2026

Status: Accepted

## Decision

The repository is named `hybrid-ai-blueprints`. PrismML sponsors and stewards
it. The repository stores use cases, runnable blueprints, shared packages,
model cards, examples, research, documentation, and release evidence.

## Reason

The runtime, harness, and evaluation contracts still change together. A
monorepo keeps each change testable and prevents the first blueprint from
copying shared code.

The project name describes the category instead of the sponsor. The sponsor
line states who maintains the work. Manifests remain model and provider neutral.

## Growth path

The project may move mature blueprints into separate repositories when they
need independent releases or maintainers. Each separate repository must keep
the same manifest and evidence contract, while the main catalog links to it.

## Rejected options

A repository named after PrismML would make the open package format look tied
to one company product. A folder of unrelated demos would hide shared runtime
and evaluation contracts. Separate repositories now would copy code and make
cross blueprint changes hard to verify.
