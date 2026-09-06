"""全局配置：读取 .env，提供 LLM 客户端参数与游戏常量。"""
import os
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
PERSONA_DIR = os.path.join(DATA_DIR, "personas")
STATIC_DIR = os.path.join(BASE_DIR, "static")
PORTRAIT_DIR = os.path.join(STATIC_DIR, "img", "portraits")
REVIEW_DIR = os.path.join(DATA_DIR, "reviews")
HOST_STYLE_PATH = os.path.join(DATA_DIR, "host_style.json")
BOARDS_PATH = os.path.join(DATA_DIR, "boards.json")


def _load_env():
    """极简 .env 解析（不依赖 python-dotenv）。"""
    env = {}
    path = os.path.join(BASE_DIR, ".env")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


_env = _load_env()

# .env 优先，其次系统环境变量
def _get(key, default=None):
    return _env.get(key) or os.environ.get(key, default)


class Config:
    LLM_BASE_URL = _get("LLM_BASE_URL", "https://api.deepseek.com/v1")
    LLM_API_KEY = _get("LLM_API_KEY", "")
    LLM_MODEL = _get("LLM_MODEL", "deepseek-chat")
    LLM_TEMPERATURE = float(_get("LLM_TEMPERATURE", "0.85"))
    LLM_ENABLED = _get("LLM_ENABLED", "true").lower() in ("1", "true", "yes", "on")
    # These are availability controls, not game-balance knobs.  The local
    # strategy engine remains authoritative regardless of their values.
    LLM_TIMEOUT_SECONDS = float(_get("LLM_TIMEOUT_SECONDS", "8"))
    LLM_GAME_MAX_CALLS = int(_get("LLM_GAME_MAX_CALLS", "36"))
    # Leave the request key empty for generic OpenAI-compatible services.
    # Providers with a reasoning switch can opt in, e.g.
    # LLM_REASONING_PARAM=reasoning_effort.
    LLM_REASONING_EFFORT = _get("LLM_REASONING_EFFORT", "")
    LLM_REASONING_PARAM = _get("LLM_REASONING_PARAM", "")

    PORT = int(_get("PORT", "8000"))

    # 是否真正启用云端 LLM：有 Key 且开关开启
    @property
    def use_llm(self) -> bool:
        return self.LLM_ENABLED and bool(self.LLM_API_KEY) and self.LLM_API_KEY not in (
            "", "sk-your-key-here")


CONFIG = Config()


def ensure_dirs():
    for d in (DATA_DIR, PERSONA_DIR, STATIC_DIR, PORTRAIT_DIR, REVIEW_DIR):
        os.makedirs(d, exist_ok=True)
