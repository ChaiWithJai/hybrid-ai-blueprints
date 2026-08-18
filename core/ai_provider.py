"""Explicit AI provider boundaries for Prism Vault.

Providers use explicit protocol adapters behind one interface. LM Studio's
native chat API is supported for local Bonsai inference because it can disable
reasoning deterministically; approved cloud services use chat completions.
Nothing is contacted unless its endpoint is configured by the operator.
"""

from __future__ import annotations

import json
import ipaddress
import os
import re
import shlex
import subprocess
import time
import urllib.error
import urllib.request
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


class ProviderError(RuntimeError):
    pass


LOCAL_CONTEXT_RUNTIME_MARGIN_TOKENS = 32


@dataclass
class ProviderResult:
    provider_id: str
    model: str
    content: str
    latency_ms: float
    usage: Dict[str, int] = field(default_factory=dict)
    raw_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderStatus:
    provider_id: str
    kind: str
    configured: bool
    model: Optional[str]
    endpoint: Optional[str]
    artifact_sha256: Optional[str] = None
    runtime_name: Optional[str] = None
    runtime_version: Optional[str] = None
    hardware: Optional[str] = None
    protocol: str = "openai_chat_completions"
    network_scope: Optional[str] = None
    context_window_tokens: Optional[int] = None
    context_admission: Optional[str] = None


def local_endpoint_is_loopback_literal(endpoint: Optional[str]) -> bool:
    """Return true only for a plain HTTP URL whose host is a loopback IP literal."""
    if not endpoint:
        return False
    try:
        parsed = urllib.parse.urlsplit(endpoint)
        host = parsed.hostname
        address = ipaddress.ip_address(host) if host else None
        _ = parsed.port
    except (ValueError, TypeError):
        return False
    return bool(
        parsed.scheme == "http"
        and address is not None
        and (
            (address.version == 4 and address.is_loopback)
            or address == ipaddress.IPv6Address("::1")
        )
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


def require_loopback_local_endpoint(endpoint: Optional[str]) -> None:
    """Reject a configured local provider that is not bound to a loopback IP URL."""
    if endpoint and not local_endpoint_is_loopback_literal(endpoint):
        raise ProviderError(
            "PRISM_LOCAL_AI_URL must use plain HTTP with a loopback IP literal "
            "such as http://127.0.0.1:1234 or http://[::1]:1234"
        )


def cloud_endpoint_is_safe(endpoint: Optional[str]) -> bool:
    if not endpoint:
        return False
    try:
        parsed = urllib.parse.urlsplit(endpoint)
        _ = parsed.port
    except (ValueError, TypeError):
        return False
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


class OpenAICompatibleProvider:
    def __init__(
        self,
        provider_id: str,
        kind: str,
        endpoint: Optional[str],
        model: Optional[str],
        api_key: Optional[str] = None,
        timeout_seconds: float = 60.0,
        max_response_bytes: int = 2 * 1024 * 1024,
        deployment_evidence: Optional[Dict[str, str]] = None,
        max_completion_tokens: Optional[int] = 4096,
        prompt_suffix: Optional[str] = None,
        context_window_tokens: Optional[int] = None,
        artifact_path: Optional[str] = None,
        token_counter: Optional[Any] = None,
    ):
        if kind == "local":
            require_loopback_local_endpoint(endpoint)
        if kind == "cloud" and endpoint and not cloud_endpoint_is_safe(endpoint):
            raise ProviderError(
                "PRISM_CLOUD_AI_URL must use HTTPS without URL credentials, query parameters, or fragments"
            )
        self.provider_id = provider_id
        self.kind = kind
        self.endpoint = endpoint.rstrip("/") if endpoint else None
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.deployment_evidence = deployment_evidence or {}
        self.max_completion_tokens = max_completion_tokens
        self.prompt_suffix = prompt_suffix.strip() if prompt_suffix else None
        self.context_window_tokens = context_window_tokens
        self.artifact_path = str(Path(artifact_path).resolve()) if artifact_path else None
        self._token_counter = token_counter
        self._response_context_tokens: Dict[str, int] = {}
        if (self.context_window_tokens is None) != (self.artifact_path is None):
            raise ProviderError(
                "local context admission requires both a fitted context length and artifact path"
            )

    @property
    def configured(self) -> bool:
        return bool(self.endpoint and self.model)

    @property
    def supports_previous_response_id(self) -> bool:
        return False

    def status(self) -> ProviderStatus:
        endpoint_origin = None
        if self.endpoint:
            parsed = urllib.parse.urlsplit(self.endpoint)
            host = parsed.hostname or ""
            if ":" in host and not host.startswith("["):
                host = f"[{host}]"
            endpoint_origin = f"{parsed.scheme}://{host}"
            if parsed.port:
                endpoint_origin += f":{parsed.port}"
        return ProviderStatus(
            provider_id=self.provider_id,
            kind=self.kind,
            configured=self.configured,
            model=self.model,
            endpoint=endpoint_origin,
            artifact_sha256=self.deployment_evidence.get("artifact_sha256"),
            runtime_name=self.deployment_evidence.get("runtime_name"),
            runtime_version=self.deployment_evidence.get("runtime_version"),
            hardware=self.deployment_evidence.get("hardware"),
            protocol="openai_chat_completions",
            network_scope=(
                "loopback_ip_literal"
                if self.kind == "local" and local_endpoint_is_loopback_literal(self.endpoint)
                else "unverified_non_loopback"
                if self.kind == "local" and self.endpoint
                else "operator_configured"
                if self.endpoint
                else None
            ),
            context_window_tokens=self.context_window_tokens,
            context_admission=(
                "loaded_model_tokenizer_with_runtime_margin"
                if self.context_window_tokens is not None else None
            ),
        )

    def _admit_context(
        self,
        messages: List[Dict[str, str]],
        *,
        previous_response_id: Optional[str] = None,
    ) -> Optional[int]:
        """Fail before inference when the exact fitted context cannot hold the request."""
        if self.context_window_tokens is None:
            return None
        counter = self._token_counter or self._count_with_loaded_llama_tokenizer
        tokenizer_tokens = int(counter(messages))
        if tokenizer_tokens < 0:
            raise ProviderError("loaded model tokenizer returned an invalid token count")
        new_input_tokens = tokenizer_tokens + LOCAL_CONTEXT_RUNTIME_MARGIN_TOKENS
        prior_tokens = 0
        if previous_response_id is not None:
            if previous_response_id not in self._response_context_tokens:
                raise ProviderError(
                    "cannot admit a continuation whose prior response context is unavailable"
                )
            prior_tokens = self._response_context_tokens[previous_response_id]
        reserved_output = self.max_completion_tokens or 0
        required = prior_tokens + new_input_tokens + reserved_output
        if required > self.context_window_tokens:
            raise ProviderError(
                f"request requires {required} tokens including the {reserved_output}-token "
                f"output reserve, exceeding the measured {self.context_window_tokens}-token "
                "fitted context"
            )
        return prior_tokens + new_input_tokens

    def _count_with_loaded_llama_tokenizer(
        self, messages: List[Dict[str, str]],
    ) -> int:
        """Use the exact active llama.cpp chat template and tokenizer over loopback."""
        if not self.artifact_path or not self.context_window_tokens:
            raise ProviderError("exact local tokenizer admission is not configured")
        try:
            process_table = subprocess.run(
                ["/bin/ps", "-axo", "pid=,command="],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            ).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            raise ProviderError(f"could not inspect the loaded tokenizer process: {exc}") from exc
        matches: list[tuple[str, str]] = []
        for row in process_table.splitlines():
            _pid, separator, command = row.strip().partition(" ")
            if not separator:
                continue
            try:
                tokens = shlex.split(command)
            except ValueError:
                continue
            if not tokens or Path(tokens[0]).name != "llama-server":
                continue
            try:
                model_path = str(Path(tokens[tokens.index("--model") + 1]).resolve())
                host = tokens[tokens.index("--host") + 1]
                port = tokens[tokens.index("--port") + 1]
                api_key = tokens[tokens.index("--api-key") + 1]
                fitted = int(tokens[tokens.index("--fit-ctx") + 1])
            except (ValueError, IndexError):
                continue
            if (
                model_path == self.artifact_path
                and host == "127.0.0.1"
                and fitted == self.context_window_tokens
                and re.fullmatch(r"\d{1,5}", port)
            ):
                matches.append((port, api_key))
        if len(matches) != 1:
            raise ProviderError(
                "exactly one loaded llama.cpp process must match the configured artifact and fitted context"
            )
        port, api_key = matches[0]

        def post(path: str, body: Dict[str, Any]) -> Dict[str, Any]:
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}{path}",
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=10) as response:
                    raw = response.read(self.max_response_bytes + 1)
            except (OSError, urllib.error.URLError) as exc:
                raise ProviderError(f"loaded model tokenizer request failed: {exc}") from exc
            if len(raw) > self.max_response_bytes:
                raise ProviderError("loaded model tokenizer response was oversized")
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise ProviderError("loaded model tokenizer returned invalid JSON") from exc
            if not isinstance(payload, dict):
                raise ProviderError("loaded model tokenizer returned an invalid object")
            return payload

        applied = post("/apply-template", {"messages": messages})
        prompt = applied.get("prompt")
        if not isinstance(prompt, str):
            raise ProviderError("loaded model did not return its applied chat template")
        tokenized = post("/tokenize", {"content": prompt, "add_special": False})
        tokens = tokenized.get("tokens")
        if not isinstance(tokens, list) or not all(isinstance(token, int) for token in tokens):
            raise ProviderError("loaded model did not return an exact token list")
        return len(tokens)

    def complete(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        previous_response_id: Optional[str] = None,
    ) -> ProviderResult:
        if not self.configured:
            raise ProviderError(f"Provider {self.provider_id!r} is not configured")
        if previous_response_id is not None:
            raise ProviderError(
                f"Provider {self.provider_id!r} does not support previous_response_id"
            )
        request_messages = [dict(message) for message in messages]
        if self.prompt_suffix:
            for message in reversed(request_messages):
                if message.get("role") == "user":
                    message["content"] = f"{message.get('content', '')}\n{self.prompt_suffix}"
                    break
        admitted_input_tokens = self._admit_context(request_messages)
        request_body = {
            "model": self.model,
            "messages": request_messages,
            "temperature": temperature,
        }
        if self.max_completion_tokens is not None:
            request_body["max_tokens"] = self.max_completion_tokens
        payload = json.dumps(request_body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.endpoint}/v1/chat/completions", data=payload, headers=headers, method="POST"
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw_body = response.read(self.max_response_bytes + 1)
                if len(raw_body) > self.max_response_bytes:
                    raise ProviderError(
                        f"{self.provider_id} response exceeded {self.max_response_bytes} bytes"
                    )
                body = json.loads(raw_body.decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as exc:
            raise ProviderError(f"{self.provider_id} request failed: {exc}") from exc
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"{self.provider_id} returned an invalid chat-completions response") from exc
        if not isinstance(content, str) or not content.strip():
            finish_reason = body.get("choices", [{}])[0].get("finish_reason")
            raise ProviderError(
                f"{self.provider_id} returned no final content (finish_reason={finish_reason!r})"
            )
        usage = {k: int(v) for k, v in body.get("usage", {}).items() if isinstance(v, (int, float))}
        request_id = body.get("id")
        if isinstance(request_id, str) and admitted_input_tokens is not None:
            self._response_context_tokens[request_id] = (
                int(usage.get("prompt_tokens", admitted_input_tokens))
                + int(usage.get("completion_tokens", 0))
            )
        return ProviderResult(
            provider_id=self.provider_id,
            model=str(body.get("model", self.model)),
            content=content,
            latency_ms=(time.perf_counter() - started) * 1000,
            usage=usage,
            raw_metadata={
                "request_id": request_id,
                "prompt_suffix_applied": bool(self.prompt_suffix),
                "context_admission": (
                    "loaded_model_tokenizer_with_runtime_margin"
                    if admitted_input_tokens is not None else None
                ),
                "admitted_input_tokens": admitted_input_tokens,
                "context_runtime_margin_tokens": (
                    LOCAL_CONTEXT_RUNTIME_MARGIN_TOKENS
                    if admitted_input_tokens is not None else None
                ),
                "reserved_output_tokens": (
                    self.max_completion_tokens if admitted_input_tokens is not None else None
                ),
                "fitted_context_tokens": self.context_window_tokens,
                **self.deployment_evidence,
            },
        )


class LMStudioNativeProvider(OpenAICompatibleProvider):
    """LM Studio native adapter with an auditable reasoning-off response."""

    def status(self) -> ProviderStatus:
        status = super().status()
        status.protocol = "lmstudio_native_chat"
        return status

    @property
    def supports_previous_response_id(self) -> bool:
        return True

    def complete(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        previous_response_id: Optional[str] = None,
    ) -> ProviderResult:
        if not self.configured:
            raise ProviderError(f"Provider {self.provider_id!r} is not configured")
        request_messages = [dict(message) for message in messages]
        if self.prompt_suffix:
            for message in reversed(request_messages):
                if message.get("role") == "user":
                    message["content"] = f"{message.get('content', '')}\n{self.prompt_suffix}"
                    break
        admitted_input_tokens = self._admit_context(
            request_messages, previous_response_id=previous_response_id,
        )
        system_prompt = "\n\n".join(
            message.get("content", "") for message in request_messages
            if message.get("role") == "system"
        )
        conversation = [
            message for message in request_messages if message.get("role") != "system"
        ]
        if previous_response_id:
            if any(message.get("role") == "assistant" for message in conversation):
                raise ProviderError(
                    "LM Studio continuation input must not repeat prior assistant output"
                )
            native_input = "\n\n".join(
                message.get("content", "") for message in conversation
            )
        elif len(conversation) <= 1:
            native_input = conversation[0].get("content", "") if conversation else ""
        else:
            native_input = "\n\n".join(
                f"{message.get('role', 'user').upper()} MESSAGE\n{message.get('content', '')}"
                for message in conversation
            )
        request_body: Dict[str, Any] = {
            "model": self.model,
            "input": native_input,
            "system_prompt": system_prompt,
            "reasoning": "off",
            "temperature": temperature,
            "store": False,
        }
        if self.max_completion_tokens is not None:
            request_body["max_output_tokens"] = self.max_completion_tokens
        if previous_response_id:
            request_body["previous_response_id"] = previous_response_id
        request = urllib.request.Request(
            f"{self.endpoint}/api/v1/chat",
            data=json.dumps(request_body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw_body = response.read(self.max_response_bytes + 1)
                if len(raw_body) > self.max_response_bytes:
                    raise ProviderError(
                        f"{self.provider_id} response exceeded {self.max_response_bytes} bytes"
                    )
                body = json.loads(raw_body.decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ProviderError(f"{self.provider_id} request failed: {exc}") from exc

        output = body.get("output")
        if not isinstance(output, list):
            raise ProviderError(f"{self.provider_id} returned an invalid LM Studio response")
        content = "\n".join(
            item["content"] for item in output
            if isinstance(item, dict) and item.get("type") == "message"
            and isinstance(item.get("content"), str)
        )
        if not content.strip():
            raise ProviderError(f"{self.provider_id} returned no final content")
        stats = body.get("stats", {})
        if not isinstance(stats, dict):
            raise ProviderError(f"{self.provider_id} returned invalid generation stats")
        reasoning_tokens = stats.get("reasoning_output_tokens")
        if reasoning_tokens != 0:
            raise ProviderError(
                f"{self.provider_id} did not prove reasoning was disabled "
                f"(reasoning_output_tokens={reasoning_tokens!r})"
            )
        prompt_tokens = int(stats.get("input_tokens", 0))
        completion_tokens = int(stats.get("total_output_tokens", 0))
        if (self.max_completion_tokens is not None
                and completion_tokens >= self.max_completion_tokens):
            raise ProviderError(
                f"{self.provider_id} exhausted its {self.max_completion_tokens}-token output budget; "
                "the response may be truncated"
            )
        response_id = body.get("response_id")
        if isinstance(response_id, str) and admitted_input_tokens is not None:
            self._response_context_tokens[response_id] = prompt_tokens + completion_tokens
        return ProviderResult(
            provider_id=self.provider_id,
            model=str(body.get("model_instance_id", self.model)),
            content=content,
            latency_ms=(time.perf_counter() - started) * 1000,
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            raw_metadata={
                "request_id": response_id,
                "protocol": "lmstudio_native_chat",
                "reasoning_output_tokens": reasoning_tokens,
                "tokens_per_second": stats.get("tokens_per_second"),
                "time_to_first_token_seconds": stats.get("time_to_first_token_seconds"),
                "prompt_suffix_applied": bool(self.prompt_suffix),
                "previous_response_id_used": previous_response_id,
                "context_admission": (
                    "loaded_model_tokenizer_with_runtime_margin"
                    if admitted_input_tokens is not None else None
                ),
                "admitted_input_tokens": admitted_input_tokens,
                "context_runtime_margin_tokens": (
                    LOCAL_CONTEXT_RUNTIME_MARGIN_TOKENS
                    if admitted_input_tokens is not None else None
                ),
                "reserved_output_tokens": (
                    self.max_completion_tokens if admitted_input_tokens is not None else None
                ),
                "fitted_context_tokens": self.context_window_tokens,
                **self.deployment_evidence,
            },
        )


class ProviderRegistry:
    """Build provider configuration from environment without logging secrets."""

    def __init__(self):
        def env_number(name: str, default: int) -> int:
            raw = os.environ.get(name)
            if raw is None:
                return default
            try:
                value = int(raw)
            except ValueError as exc:
                raise ProviderError(f"{name} must be an integer") from exc
            if value <= 0:
                raise ProviderError(f"{name} must be greater than zero")
            return value

        def env_optional_number(name: str) -> Optional[int]:
            raw = os.environ.get(name)
            if raw is None:
                return None
            try:
                value = int(raw)
            except ValueError as exc:
                raise ProviderError(f"{name} must be an integer") from exc
            if value <= 0:
                raise ProviderError(f"{name} must be greater than zero")
            return value

        local_protocol = os.environ.get("PRISM_LOCAL_AI_PROTOCOL", "openai").strip().lower()
        if local_protocol not in {"openai", "lmstudio-native"}:
            raise ProviderError(
                "PRISM_LOCAL_AI_PROTOCOL must be 'openai' or 'lmstudio-native'"
            )
        local_provider_class = (
            LMStudioNativeProvider if local_protocol == "lmstudio-native"
            else OpenAICompatibleProvider
        )
        local_endpoint = os.environ.get("PRISM_LOCAL_AI_URL")
        require_loopback_local_endpoint(local_endpoint)
        self.local = local_provider_class(
            "local_bonsai",
            "local",
            local_endpoint,
            os.environ.get("PRISM_LOCAL_AI_MODEL", "bonsai-27b"),
            os.environ.get("PRISM_LOCAL_AI_KEY"),
            timeout_seconds=env_number("PRISM_LOCAL_AI_TIMEOUT_SECONDS", 300),
            deployment_evidence={
                "artifact_sha256": os.environ.get("PRISM_LOCAL_AI_ARTIFACT_SHA256"),
                "runtime_name": os.environ.get("PRISM_LOCAL_AI_RUNTIME"),
                "runtime_version": os.environ.get("PRISM_LOCAL_AI_RUNTIME_VERSION"),
                "hardware": os.environ.get("PRISM_LOCAL_AI_HARDWARE"),
            },
            max_completion_tokens=env_number("PRISM_LOCAL_AI_MAX_TOKENS", 4096),
            prompt_suffix=os.environ.get("PRISM_LOCAL_AI_PROMPT_SUFFIX"),
            context_window_tokens=env_optional_number("PRISM_LOCAL_AI_CONTEXT_TOKENS"),
            artifact_path=os.environ.get("PRISM_LOCAL_AI_ARTIFACT_PATH"),
        )
        self.cloud = OpenAICompatibleProvider(
            "cloud_ai",
            "cloud",
            os.environ.get("PRISM_CLOUD_AI_URL"),
            os.environ.get("PRISM_CLOUD_AI_MODEL"),
            os.environ.get("PRISM_CLOUD_AI_KEY"),
            timeout_seconds=env_number("PRISM_CLOUD_AI_TIMEOUT_SECONDS", 60),
            max_completion_tokens=env_number("PRISM_CLOUD_AI_MAX_TOKENS", 4096),
            prompt_suffix=os.environ.get("PRISM_CLOUD_AI_PROMPT_SUFFIX"),
        )

    def statuses(self) -> List[ProviderStatus]:
        return [self.local.status(), self.cloud.status()]

    def select(self, provider_id: str) -> OpenAICompatibleProvider:
        providers = {self.local.provider_id: self.local, self.cloud.provider_id: self.cloud}
        if provider_id not in providers:
            raise ProviderError(f"Unknown provider: {provider_id}")
        return providers[provider_id]
