# Harness source

The current harness source remains in `core/`. It contains parsing, retrieval,
model providers, policy routing, calculations, Buzz publication, trace records,
and evaluation helpers.

The blueprint manifest pins the exact source path. A future split must preserve
the package contract and pass the same tests.
