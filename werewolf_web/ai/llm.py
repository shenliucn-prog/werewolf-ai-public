"""统一 LLM 客户端（OpenAI 兼容接口）+ 无 Key 时的确定性降级。

降级模式：根据角色/身份/游戏状态用规则生成合理的发言与决策，
保证没有任何 Key / 离线时也能完整跑通一局。
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from .. import config


@dataclass(frozen=True)
class LLMRuntimeConfig:
    """Per-game, non-persistent model settings.

    A user key is intentionally kept only in this object and is never exposed
    by ``public_status`` or written to game memory/reviews.
    """
    enabled: bool
    base_url: str
    api_key: str
    model: str
    temperature: float
    timeout_seconds: float
    max_calls: int
    reasoning_effort: str = ""
    reasoning_param: str = ""

    @classmethod
    def from_config(cls, cfg: Any = config.CONFIG) -> "LLMRuntimeConfig":
        return cls(
            enabled=cfg.LLM_ENABLED,
            base_url=cfg.LLM_BASE_URL,
            api_key=cfg.LLM_API_KEY,
            model=cfg.LLM_MODEL,
            temperature=cfg.LLM_TEMPERATURE,
            timeout_seconds=cfg.LLM_TIMEOUT_SECONDS,
            max_calls=cfg.LLM_GAME_MAX_CALLS,
            reasoning_effort=cfg.LLM_REASONING_EFFORT,
            reasoning_param=cfg.LLM_REASONING_PARAM,
        )

    @classmethod
    def from_request(cls, values: dict | None) -> "LLMRuntimeConfig":
        """Merge a validated, one-game override onto local defaults.

        This deliberately accepts only a narrow allow-list.  In particular,
        callers cannot alter retry policy or inject arbitrary provider fields.
        """
        base = cls.from_config()
        values = values or {}
        if not isinstance(values, dict):
            return base

        def text(name: str, default: str, limit: int = 240) -> str:
            value = values.get(name, default)
            return value.strip()[:limit] if isinstance(value, str) else default

        def number(name: str, default: float, low: float, high: float) -> float:
            try:
                return max(low, min(high, float(values.get(name, default))))
            except (TypeError, ValueError):
                return default

        enabled = values.get("enabled", base.enabled)
        if isinstance(enabled, str):
            enabled = enabled.lower() in ("1", "true", "yes", "on")
        base_url = text("base_url", base.base_url)
        # A caller redirecting requests must supply their own credential.
        # Otherwise a custom endpoint could receive the server's default key.
        default_key = base.api_key if base_url.rstrip("/") == base.base_url.rstrip("/") else ""
        return cls(
            enabled=bool(enabled),
            base_url=base_url,
            api_key=text("api_key", default_key, 512),
            model=text("model", base.model),
            temperature=number("temperature", base.temperature, 0.0, 2.0),
            timeout_seconds=number("timeout_seconds", base.timeout_seconds, 1.0, 30.0),
            max_calls=int(number("max_calls", base.max_calls, 0, 120)),
            reasoning_effort=text("reasoning_effort", base.reasoning_effort, 32),
            reasoning_param=text("reasoning_param", base.reasoning_param, 64),
        )


class LLMClient:
    """Best-effort language service around an authoritative local game core."""

    MAX_FAILURES = 2

    def __init__(self, runtime: LLMRuntimeConfig | None = None):
        self.runtime = runtime or LLMRuntimeConfig.from_config()
        self._client = None
        self.calls = 0
        self.failures = 0
        self.unavailable_reason = "disabled"
        if self.runtime.enabled and self.runtime.api_key:
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    base_url=self.runtime.base_url,
                    api_key=self.runtime.api_key,
                    timeout=self.runtime.timeout_seconds,
                    max_retries=0,
                )
            except Exception:  # pragma: no cover
                # Provider errors can contain request details; never echo them
                # because this process may be serving user-supplied keys.
                print("[LLM] 初始化失败，降级为本地表达。")
                self._client = None
                self.unavailable_reason = "client_unavailable"
            else:
                self.unavailable_reason = ""
        elif not self.runtime.api_key:
            self.unavailable_reason = "no_api_key"

    @property
    def online(self) -> bool:
        return (self._client is not None and self.failures < self.MAX_FAILURES
                and self.calls < self.runtime.max_calls)

    def public_status(self) -> dict:
        """Safe session telemetry for the UI; it never contains credentials."""
        if self.online:
            return {"mode": "online", "label": "模型润色可用", "model": self.runtime.model,
                    "calls": self.calls, "max_calls": self.runtime.max_calls}
        if self._client is not None:
            reason = self.unavailable_reason or "model_unavailable"
            return {"mode": "degraded", "label": "已切换本地表达", "reason": reason,
                    "calls": self.calls, "max_calls": self.runtime.max_calls}
        return {"mode": "offline", "label": "本地策略与表达", "reason": self.unavailable_reason,
                "calls": 0, "max_calls": self.runtime.max_calls}

    def generate(self, system: str, prompt: str, temperature: float | None = None,
                 max_tokens: int = 600) -> str | None:
        """Return provider text or ``None``; never make a game wait indefinitely."""
        if not self.online:
            return None
        request: dict[str, Any] = {
            "model": self.runtime.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": prompt}],
            "temperature": temperature if temperature is not None else self.runtime.temperature,
            "max_tokens": max_tokens,
        }
        # Reasoning controls are provider-specific.  Sending one requires an
        # explicit configured field name; generic endpoints receive none.
        if self.runtime.reasoning_effort and self.runtime.reasoning_param:
            request["extra_body"] = {
                self.runtime.reasoning_param: self.runtime.reasoning_effort
            }
        self.calls += 1
        try:
            resp = self._client.chat.completions.create(**request)
            text = (resp.choices[0].message.content or "").strip()
            if not text:
                raise ValueError("empty model response")
            self.failures = 0
            return text
        except Exception:
            self.failures += 1
            if self.failures >= self.MAX_FAILURES:
                self.unavailable_reason = "circuit_open"
            print("[LLM] 调用失败，使用本地表达。")
            return None

    def chat(self, system: str, prompt: str, temperature: float | None = None,
             max_tokens: int = 600) -> str:
        return self.generate(system, prompt, temperature, max_tokens) or self._fallback(system, prompt)

    # ---------- 降级规则引擎 ----------
    def _fallback(self, system: str, prompt: str) -> str:
        """极简规则降级：从 prompt 中识别任务类型，生成合理文本。"""
        p = prompt
        # 夜间行动（JSON 请求）
        if "ACTION_JSON" in p or "返回JSON" in p or "json" in p.lower() and "验" in p or "刀" in p:
            return self._fallback_action(p)
        # 投票
        if "投" in p and ("票数" in p or "投票" in p or "target" in p.lower()):
            return self._fallback_vote(p)
        # 默认发言
        return self._fallback_speech(p)

    def _fallback_action(self, p: str) -> str:
        # 狼刀：随机一个非狼存活
        m = re.search(r"可取目标[：:]\s*\[([^\]]*)\]", p)
        if "刀" in p and m:
            targets = [t.strip() for t in m.group(1).split(",") if t.strip()]
            if targets:
                return json.dumps({"target": int(targets[0])}, ensure_ascii=False)
        if "验" in p and m:
            targets = [t.strip() for t in m.group(1).split(",") if t.strip()]
            if targets:
                return json.dumps({"target": int(targets[0])}, ensure_ascii=False)
        if "守" in p and m:
            targets = [t.strip() for t in m.group(1).split(",") if t.strip()]
            if targets:
                return json.dumps({"target": int(targets[0])}, ensure_ascii=False)
        if "救" in p or "毒" in p:
            return json.dumps({"save": None, "poison": None}, ensure_ascii=False)
        return json.dumps({}, ensure_ascii=False)

    def _fallback_vote(self, p: str) -> str:
        m = re.search(r"可投目标[：:]\s*\[([^\]]*)\]", p)
        if m:
            targets = [t.strip() for t in m.group(1).split(",") if t.strip()]
            # 优先投带"查杀"或"狼"标记的
            for t in targets:
                if "查杀" in t or "狼人" in t:
                    num = re.search(r"(\d+)", t)
                    if num:
                        return json.dumps({"target": int(num.group(1))}, ensure_ascii=False)
            if targets:
                num = re.search(r"(\d+)", targets[0])
                if num:
                    return json.dumps({"target": int(num.group(1))}, ensure_ascii=False)
        return json.dumps({"target": None}, ensure_ascii=False)

    def _fallback_speech(self, p: str) -> str:
        if "预言家" in p and "查杀" in p:
            return "我是真预言家，昨晚验出查杀，大家跟我出他。"
        if "狼人" in p:
            return "我是狼人，这局划水，先听听大家怎么说。"
        return "我是好人，目前信息不多，先听预言家和分析，再决定站边。"
