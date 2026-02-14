#LLM Execution Implementation V1


from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import hashlib
import os
import time
import random

from openai import OpenAI


LLM_EXECUTOR_VERSION = "LLM_EXECUTOR_V1"


@dataclass
class LLMAttemptLog:
    attempt_number: int
    status: str  # OK | RETRY | FAILED
    error_type: Optional[str]
    error_message: Optional[str]
    latency_ms: Optional[int]


@dataclass
class LLMExecutionResult:
    request_id: str
    model_name: str
    prompt_sha256: str
    generation_status: str  # OK | FAILED | NO_EVIDENCE
    raw_model_text: str
    finish_reason: Optional[str]
    response_id: Optional[str]
    attempts: List[LLMAttemptLog]
    llm_latency_ms: Optional[int]
    prompt_tokens_actual: Optional[int]
    completion_tokens_actual: Optional[int]
    total_tokens_actual: Optional[int]
    metadata: Dict[str, Any]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sleep_with_backoff(attempt_index: int, base_seconds: float = 1.0, max_seconds: float = 8.0) -> None:
    # Exponential backoff with jitter
    sleep_s = min(max_seconds, base_seconds * (2 ** attempt_index))
    jitter = random.uniform(0.0, 0.25 * sleep_s)
    time.sleep(sleep_s + jitter)


def execute_llm_v1(
    request_id: str,
    prompt_result,
    policy,
    openai_api_key: str,
    model_name: str = "gpt-4o-mini",
    temperature: float = 0.0,
    timeout_seconds: int = 30,
    max_retries: int = 2,
    llm_config_version: str = "OPENAI_PUBLIC_V1",
) -> LLMExecutionResult:
    """
    LLM Execution Implementation V1.
    Contract highlights:
      - fixed model identity (no fallback)
      - prompt bytes not mutated
      - retries only for transient failures, same prompt bytes
      - token usage + latency logged
      - raw output preserved, no post-processing
    """

  # Refusal propagation

    if prompt_result.build_status != "OK":
        return LLMExecutionResult(
            request_id=request_id,
            model_name=model_name,
            prompt_sha256="",
            generation_status="NO_EVIDENCE",
            raw_model_text="",
            finish_reason=None,
            response_id=None,
            attempts=[],
            llm_latency_ms=None,
            prompt_tokens_actual=None,
            completion_tokens_actual=None,
            total_tokens_actual=None,
            metadata={
                "reason": "PROMPT_NOT_OK",
                "prompt_build_status": prompt_result.build_status,
                "llm_executor_version": LLM_EXECUTOR_VERSION,
                "llm_config_version": llm_config_version,
            },
        )

    prompt_text = prompt_result.prompt_text
    prompt_sha256 = _sha256(prompt_text)

    max_output_tokens = int(getattr(policy, "reserved_output_tokens", 800))

    client = OpenAI(api_key=openai_api_key, timeout=timeout_seconds)

    attempts: List[LLMAttemptLog] = []
    overall_start = time.time()

    last_error_type = None
    last_error_message = None

    for attempt_idx in range(max_retries + 1):
        attempt_number = attempt_idx + 1
        t0 = time.time()

        try:
          
            # 3) Send EXACT prompt bytes
            # Responses API is recommended for new projects
        
            resp = client.responses.create(
                model=model_name,
                input=prompt_text,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )

            latency_ms = int((time.time() - t0) * 1000)
            attempts.append(
                LLMAttemptLog(
                    attempt_number=attempt_number,
                    status="OK",
                    error_type=None,
                    error_message=None,
                    latency_ms=latency_ms,
                )
            )

       
            # Official SDK returns output text via resp.output_text in common cases
            raw_text = getattr(resp, "output_text", "") or ""

            # finish reason may be present depending on SDK version
            finish_reason = None
            if hasattr(resp, "output") and resp.output:
                try:
                    # Best-effort extraction, do not crash if structure differs
                    finish_reason = getattr(resp.output[0], "finish_reason", None)
                except Exception:
                    finish_reason = None

            response_id = getattr(resp, "id", None)

            usage = getattr(resp, "usage", None)
            prompt_tokens_actual = None
            completion_tokens_actual = None
            total_tokens_actual = None

            if usage is not None:
                # Best-effort: SDK schema may vary, keep it defensive
                prompt_tokens_actual = getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", None)
                completion_tokens_actual = getattr(usage, "output_tokens", None) or getattr(usage, "completion_tokens", None)
                total_tokens_actual = getattr(usage, "total_tokens", None)

            overall_latency_ms = int((time.time() - overall_start) * 1000)

            return LLMExecutionResult(
                request_id=request_id,
                model_name=model_name,
                prompt_sha256=prompt_sha256,
                generation_status="OK",
                raw_model_text=raw_text,
                finish_reason=finish_reason,
                response_id=response_id,
                attempts=attempts,
                llm_latency_ms=overall_latency_ms,
                prompt_tokens_actual=prompt_tokens_actual,
                completion_tokens_actual=completion_tokens_actual,
                total_tokens_actual=total_tokens_actual,
                metadata={
                    "llm_executor_version": LLM_EXECUTOR_VERSION,
                    "llm_config_version": llm_config_version,
                    "temperature": temperature,
                    "max_output_tokens": max_output_tokens,
                    "prompt_token_estimate": prompt_result.prompt_token_count,
                    "evidence_token_count": prompt_result.evidence_token_count,
                    "prompt_hash_from_builder": prompt_result.metadata.get("prompt_hash"),
                },
            )

        except Exception as e:
            latency_ms = int((time.time() - t0) * 1000)
            err_msg = str(e)
            err_type = type(e).__name__
            last_error_type = err_type
            last_error_message = err_msg

  
            # 5) Retry classification
            
            retryable = False
            lower = err_msg.lower()

            # Basic, defensive checks. In practice you can refine once you see real errors.
            if "timeout" in lower:
                retryable = True
                err_type = "TIMEOUT"
            elif "rate limit" in lower or "429" in lower:
                retryable = True
                err_type = "RATE_LIMIT_429"
            elif "5xx" in lower or "internal server error" in lower or "server error" in lower:
                retryable = True
                err_type = "SERVER_5XX"
            elif "connection" in lower or "network" in lower:
                retryable = True
                err_type = "NETWORK"

            attempts.append(
                LLMAttemptLog(
                    attempt_number=attempt_number,
                    status="RETRY" if retryable and attempt_idx < max_retries else "FAILED",
                    error_type=err_type,
                    error_message=err_msg[:5000],
                    latency_ms=latency_ms,
                )
            )

            if retryable and attempt_idx < max_retries:
                _sleep_with_backoff(attempt_idx)
                continue

            # Non-retryable or retries exhausted
            overall_latency_ms = int((time.time() - overall_start) * 1000)
            return LLMExecutionResult(
                request_id=request_id,
                model_name=model_name,
                prompt_sha256=prompt_sha256,
                generation_status="FAILED",
                raw_model_text="",
                finish_reason=None,
                response_id=None,
                attempts=attempts,
                llm_latency_ms=overall_latency_ms,
                prompt_tokens_actual=None,
                completion_tokens_actual=None,
                total_tokens_actual=None,
                metadata={
                    "llm_executor_version": LLM_EXECUTOR_VERSION,
                    "llm_config_version": llm_config_version,
                    "temperature": temperature,
                    "max_output_tokens": max_output_tokens,
                    "error_type": last_error_type,
                    "error_message": (last_error_message or "")[:5000],
                },
            )

    # Defensive fallback, should never hit
    overall_latency_ms = int((time.time() - overall_start) * 1000)
    return LLMExecutionResult(
        request_id=request_id,
        model_name=model_name,
        prompt_sha256=prompt_sha256,
        generation_status="FAILED",
        raw_model_text="",
        finish_reason=None,
        response_id=None,
        attempts=attempts,
        llm_latency_ms=overall_latency_ms,
        prompt_tokens_actual=None,
        completion_tokens_actual=None,
        total_tokens_actual=None,
        metadata={
            "llm_executor_version": LLM_EXECUTOR_VERSION,
            "llm_config_version": llm_config_version,
            "error_type": "UNKNOWN",
            "error_message": "Unexpected fallthrough in executor",
        },
    )
