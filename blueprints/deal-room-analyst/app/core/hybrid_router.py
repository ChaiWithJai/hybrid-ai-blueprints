"""Capability-aware policy routing for the local prototype.

No model weights or cloud connector ship with this repository. Decisions name
only runtimes that can actually be invoked and never imply that egress occurred.
"""

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class RoutingDecision:
    target_tier: str
    reason: str
    is_local_only_policy: bool
    redaction_applied: bool
    sanitized_prompt: str
    estimated_cost_usd: Optional[float]
    estimated_energy_mwh_per_token: Optional[float]
    metadata: Dict[str, Any]


class HybridAIRouter:
    """Apply confidentiality policy to the capabilities currently installed."""

    CONFIDENTIAL_KEYWORDS = [
        "acquisition", "merger", "ebitda", "covenant", "default", "litigation",
        "patent infringement", "balance sheet", "debt", "charter", "meridian",
        "novatech", "apex", "loan agreement", "confidential", "nda", "insider",
    ]
    PII_PATTERNS = [
        (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7}\b", "[REDACTED_EMAIL]"),
        (r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED_SSN]"),
        (r"\b\d{4}-\d{4}-\d{4}-\d{4}\b", "[REDACTED_CARD]"),
        (r"\bMarcus Vance\b", "[REDACTED_EXECUTIVE_1]"),
        (r"\bElena Rostova\b", "[REDACTED_EXECUTIVE_2]"),
    ]

    def __init__(self, default_local_only_policy: bool = True):
        self.default_local_only_policy = default_local_only_policy

    def evaluate_routing(
        self,
        query: str,
        deal_room_active: bool = True,
        force_cloud_override: bool = False,
        local_only_policy_override: Optional[bool] = None,
        local_ai_available: bool = False,
        cloud_ai_available: bool = False,
        cloud_dispatch_authorized: bool = False,
    ) -> RoutingDecision:
        local_only_policy = (self.default_local_only_policy if local_only_policy_override is None
                             else local_only_policy_override)
        contains_confidential = any(k in query.lower() for k in self.CONFIDENTIAL_KEYWORDS)

        local_policy = local_only_policy or deal_room_active or (contains_confidential and not force_cloud_override)
        if local_policy:
            target = "LOCAL_BONSAI" if local_ai_available else "LOCAL_DETERMINISTIC_WORKFLOW"
            reason = (
                "Policy selected the configured local Bonsai-compatible provider."
                if local_ai_available else
                "Policy selected the deterministic baseline because no local AI provider is configured."
            )
            return RoutingDecision(
                target_tier=target,
                reason=reason,
                is_local_only_policy=bool(local_only_policy),
                redaction_applied=False,
                sanitized_prompt=query,
                estimated_cost_usd=None,
                estimated_energy_mwh_per_token=None,
                metadata={
                    "runtime": ("configured_local_provider" if local_ai_available
                                else "deterministic_template_runner"),
                    "provider_configured": local_ai_available,
                    "model_loaded": None,
                    "network_isolation": "not_measured",
                },
            )

        sanitized = query
        redacted = False
        for pattern, replacement in self.PII_PATTERNS:
            updated = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)
            redacted = redacted or updated != sanitized
            sanitized = updated

        target = (
            "CLOUD_NOT_CONFIGURED" if not cloud_ai_available else
            "CLOUD_AI" if cloud_dispatch_authorized else
            "CLOUD_CONSENT_REQUIRED"
        )
        return RoutingDecision(
            target_tier=target,
            reason=(
                "Policy selected the configured cloud provider after signed consent validation."
                if target == "CLOUD_AI" else
                "A non-local path was requested, but no cloud provider is configured."
                if target == "CLOUD_NOT_CONFIGURED" else
                "A configured cloud path requires short-lived signed policy consent."
            ),
            is_local_only_policy=False,
            redaction_applied=redacted,
            sanitized_prompt=sanitized,
            estimated_cost_usd=None,
            estimated_energy_mwh_per_token=None,
            metadata={"connector": "cloud_ai" if cloud_ai_available else None,
                      "provider_configured": cloud_ai_available,
                      "cloud_dispatch_authorized": cloud_dispatch_authorized,
                      "egress_attempted": None, "model_loaded": None,
                      "note": "Routing decision precedes provider invocation."},
        )
