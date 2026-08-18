# Application source

The current application source remains in the repository root during the first
catalog migration:

- `server.py` serves the API and browser application.
- `web/` contains the browser interface.

The blueprint manifest points to these canonical paths. The project will move
the source only after import paths and release tooling no longer depend on the
root layout.
