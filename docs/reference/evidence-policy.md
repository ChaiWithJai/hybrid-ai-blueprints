# Evidence policy

Evidence supports a specific claim about a specific package. A passing test
must not be used to support a broader claim than it measured.

## Release evidence

A release directory contains a report, a manifest, machine readable check
results, and artifact hashes. The report states the package version, source
snapshot, environment, checks, reviewers, failures, and known limits.

## Development evidence

Development traces, screenshots, and failed attempts can remain in the
repository when they explain an important correction. They must state their
scope and must not appear as current release evidence.

## Private evidence

Private source files, prompts, answers, notes, and traces remain outside Git.
The release record may contain approved hashes and summary measures when the
customer agreement permits it.

## Synthetic evidence

Synthetic evidence can prove software behavior. It cannot prove domain
accuracy, user value, reviewer identity, buyer demand, or willingness to pay.
