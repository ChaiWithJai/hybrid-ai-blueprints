# Bonsai 27B model card

## Intended role

Bonsai 27B is a candidate local answer model and a candidate evaluator. The
deal room analyst uses it to draft answers from a bounded evidence packet.

## Tested configuration

The local engineering prototype has used an LM Studio compatible endpoint on
IPv4 loopback with the model identifier `27b@q1_0`. The repository records
runtime and artifact evidence separately because a model name does not prove
which weights were loaded.

## Evidence boundary

The current evidence shows that the model completed bounded development tasks
through the Prism harness. It does not establish general coding ability, broad
deal analysis accuracy, long context reliability, family level capability, or
production security.

Blueprint evaluations measure the complete agent system. Model only studies
must use a separate benchmark and must not inherit blueprint results.

## Distribution

The repository does not contain model weights. Operators must obtain the model
and confirm that their license permits the planned use.
