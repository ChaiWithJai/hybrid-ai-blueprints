# Route local and cloud work

The router in `core/hybrid_router.py` selects a provider from the request
sensitivity, task, and configured policy. The local route can run without a
cloud provider. The cloud route fails before dispatch unless its consent
record is valid.

Use the deal room blueprint for a complete route comparison. The example does
not create a separate demonstration application.
