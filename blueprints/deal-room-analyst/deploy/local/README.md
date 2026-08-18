# Run the local deployment

The local deployment runs the Prism web application, Buzz, and the Bonsai
endpoint on one workstation.

Run `../../scripts/preflight` before startup. Then run `../../scripts/run`.

The current checks verify local service readiness and loopback configuration.
They do not prove an air gap, a clean machine installation, or production
isolation.
