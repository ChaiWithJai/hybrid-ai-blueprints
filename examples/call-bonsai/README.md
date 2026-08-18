# Call the local model

The local provider in `core/ai_provider.py` uses an OpenAI compatible endpoint.
The provider accepts only an explicit IPv4 loopback address or the IPv6
loopback address.

Run the blueprint preflight before using the provider:

```bash
blueprints/deal-room-analyst/scripts/preflight
```

The preflight checks that the requested model is loaded. It does not prove the
model artifact identity unless the operator supplies and verifies the required
artifact metadata.
