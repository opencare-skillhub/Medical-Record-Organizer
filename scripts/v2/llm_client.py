"""
v2 LLM 客户端

通过 .env 配置 provider 与模型，避免在代码里写死默认模型。

模型规格写法：`provider:model`，例如
  - stepfun:step-3.5-flash
  - siliconflow:deepseek-ai/DeepSeek-V4-Flash
  - openai:gpt-4o-mini

provider 名（小写）对应 .env 里的 *_API_KEY / *_BASE_URL，支持：
  stepfun / siliconflow / openai

相关环境变量：
  LLM_DEFAULT_MODEL       主模型规格，默认 stepfun:step-3.5-flash
  LLM_FALLBACK_MODELS     逗号分隔的备选模型规格，失败时按序降级
                          默认 stepfun:step-3.5-flash,siliconflow:deepseek-ai/DeepSeek-V4-Flash

  STEP_API_KEY / STEP_API_BASE_URL
  OCR_API_KEY(SILICONFLOW_API_KEY) / OCR_BASE_URL(SILICONFLOW_BASE_URL)
  OPENAI_API_KEY / OPENAI_BASE_URL
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Provider 注册表：provider 名 -> (key 取值, base_url 取值)
# ---------------------------------------------------------------------------
_PROVIDERS: Dict[str, Dict[str, Any]] = {
    'stepfun': {
        'key': lambda: os.getenv('STEP_API_KEY', ''),
        'url': lambda: os.getenv('STEP_API_BASE_URL', 'https://api.stepfun.com/v1'),
    },
    'siliconflow': {
        'key': lambda: os.getenv('OCR_API_KEY') or os.getenv('SILICONFLOW_API_KEY', ''),
        'url': lambda: os.getenv('OCR_BASE_URL') or os.getenv('SILICONFLOW_BASE_URL', 'https://api.siliconflow.cn/v1'),
    },
    'openai': {
        'key': lambda: os.getenv('OPENAI_API_KEY', ''),
        'url': lambda: os.getenv('OPENAI_BASE_URL', 'https://api.openai.com/v1'),
    },
}

# 默认模型规格（未配置 env 时兜底）
_DEFAULT_PRIMARY = 'stepfun:step-3.5-flash'
_DEFAULT_FALLBACKS = 'stepfun:step-3.5-flash,siliconflow:deepseek-ai/DeepSeek-V4-Flash'


# ---------------------------------------------------------------------------
# 模型规格解析
# ---------------------------------------------------------------------------
def parse_model_spec(spec: str) -> Tuple[str, str]:
    """解析 `provider:model`，返回 (provider, model)。

    缺少 provider 前缀时，按第一个已配置 key 的 provider 兜底。
    """
    if ':' in spec:
        provider, model = spec.split(':', 1)
        provider = provider.strip().lower()
        model = model.strip()
        if provider in _PROVIDERS:
            return provider, model
    # 无 provider 前缀：挑第一个已配置 key 的 provider
    for name in _PROVIDERS:
        if _PROVIDERS[name]['key']():
            return name, spec.strip()
    return 'stepfun', spec.strip()


def resolve_default_model() -> str:
    """读取主模型规格。"""
    return os.getenv('LLM_DEFAULT_MODEL', _DEFAULT_PRIMARY).strip()


def resolve_fallback_models() -> List[str]:
    """读取备选模型规格列表。"""
    raw = os.getenv('LLM_FALLBACK_MODELS', _DEFAULT_FALLBACKS)
    return [m.strip() for m in raw.split(',') if m.strip()]


# ---------------------------------------------------------------------------
# 客户端构建
# ---------------------------------------------------------------------------
def _build_client_for(provider: str):
    """为指定 provider 构建 OpenAI 兼容客户端。"""
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError('openai 未安装，请运行: pip install openai') from exc

    cfg = _PROVIDERS.get(provider)
    if not cfg:
        raise RuntimeError(f'未知 LLM provider: {provider}')
    api_key = cfg['key']()
    base_url = cfg['url']()
    if not api_key or not base_url:
        raise RuntimeError(f'provider {provider} 未配置 API key 或 base_url')
    return OpenAI(api_key=api_key, base_url=base_url.rstrip('/') + '/')


def _build_openai_client():
    """兼容旧调用：返回主 provider 的客户端。"""
    primary_spec = resolve_default_model()
    provider, _ = parse_model_spec(primary_spec)
    return _build_client_for(provider)


# ---------------------------------------------------------------------------
# 调用入口
# ---------------------------------------------------------------------------
def call_llm_with_schema(
    messages: List[Dict[str, Any]],
    schema: Dict[str, Any],
    *,
    model: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: int = 2000,
    timeout: int = 60,
) -> Dict[str, Any]:
    """调用 LLM 并用 JSON mode 约束输出。

    model 为模型规格（`provider:model`），为 None 时取 LLM_DEFAULT_MODEL。
    """
    spec = model or resolve_default_model()
    provider, model_name = parse_model_spec(spec)
    client = _build_client_for(provider)
    response = client.chat.completions.create(
        model=model_name,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={'type': 'json_object'},
    )
    content = response.choices[0].message.content or '{}'
    return json.loads(content)


def call_llm_with_retry(
    messages: List[Dict[str, Any]],
    schema: Dict[str, Any],
    *,
    model: Optional[str] = None,
    max_retries: int = 3,
    temperature: float = 0.1,
    max_tokens: int = 2000,
    timeout: int = 60,
) -> Dict[str, Any]:
    """带重试的 LLM 调用，失败时按 LLM_FALLBACK_MODELS 降级。"""
    primary = model or resolve_default_model()
    chain: List[str] = [primary]
    for fb in resolve_fallback_models():
        if fb not in chain:
            chain.append(fb)

    last_error: Optional[Exception] = None
    for spec in chain[:max_retries]:
        try:
            return call_llm_with_schema(
                messages,
                schema,
                model=spec,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
        except Exception as exc:  # pragma: no cover - 网络失败兜底
            last_error = exc
            logger.warning('LLM 调用失败 spec=%s: %s', spec, exc)
            continue
    raise RuntimeError(f'LLM 调用失败（{max_retries}次重试）：{last_error}')
