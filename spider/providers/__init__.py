"""
体育提供商模块
每个第三方体育提供商(如YBTY/开云体育)实现为一个Provider类，
通过Playwright网络拦截获取iframe中的赔率数据。
"""

from typing import Optional, Dict, Any

from .base_provider import BaseProvider
from .yb_provider import YBTYProvider

# 注册所有可用的provider
AVAILABLE_PROVIDERS = {
    "YBTY": YBTYProvider,
}


def get_provider(code: str, filter_config: Optional[Dict[str, Any]] = None) -> BaseProvider:
    """根据提供商代码获取Provider实例，可传入过滤配置"""
    cls = AVAILABLE_PROVIDERS.get(code)
    if cls:
        return cls(filter_config=filter_config)
    raise ValueError(f"未知的提供商代码: {code}, 可用: {list(AVAILABLE_PROVIDERS.keys())}")


def get_all_providers() -> list:
    """获取所有已注册的Provider实例"""
    return [cls() for cls in AVAILABLE_PROVIDERS.values()]


__all__ = ["BaseProvider", "YBTYProvider", "AVAILABLE_PROVIDERS", "get_provider", "get_all_providers"]
