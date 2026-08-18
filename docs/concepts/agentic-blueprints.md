# Agentic blueprints

An agentic blueprint is a versioned package that completes one defined job. It
contains a model, a harness, tools, an interface, an evaluation, and release
evidence.

## Why the package is the unit under test

A model does not complete professional work alone. The harness selects context,
calls tools, handles errors, enforces policy, and publishes the result. The
interface determines what a person can inspect and correct.

[Agents' Last Exam](https://agents-last-exam.org/) evaluates the complete agent
system on a task in a working environment. The agent keeps its model, tools,
memory, and action loop. The grader checks the resulting work.

Hybrid AI Blueprints uses the same unit. A blueprint result applies only to the
recorded model, harness, task, data, configuration, and limits.

## Required parts

A blueprint must include:

1. A use case with one named job and primary user.
2. A model and runtime manifest.
3. A harness with tools, policy, and limits.
4. A user interface or API.
5. A safe demonstration.
6. A task specific evaluation.
7. A release record with known limits.

## Comparisons

Two blueprint configurations are comparable only when they use the same task,
source snapshot, question, evidence packet, output contract, and limits. A
change to any of these fields creates a new experiment.

Model only benchmarks remain useful for component research. They must be
reported separately from blueprint results.
