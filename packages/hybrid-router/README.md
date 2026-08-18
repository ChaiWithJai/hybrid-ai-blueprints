# Hybrid router

The hybrid router assigns a request to a local or cloud provider under a named
policy. Cloud use requires explicit authorization and a separate data owner
approval when private deal room context is present.

The current implementation is in `core/hybrid_router.py`,
`core/cloud_consent.py`, and `core/ai_provider.py`.
