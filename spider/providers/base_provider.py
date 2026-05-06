"""
体育提供商抽象基类
定义所有Provider必须实现的接口，包括URL识别、响应解码、数据标准化
"""

import json
import base64
import gzip
import logging
from typing import Dict, List, Optional, Any, Pattern
from abc import ABC, abstractmethod
from datetime import datetime


class BaseProvider(ABC):
    """Provider抽象基类"""

    def __init__(self, filter_config: Optional[Dict[str, Any]] = None):
        """
        Args:
            filter_config: 可选的过滤配置，如 {'sport_type': '足球', 'market_types': ['独赢']}
        """
        self.filter_config = filter_config or {}

    @property
    @abstractmethod
    def code(self) -> str:
        """提供商代码，如 'YBTY'"""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """提供商名称，如 'YBTY(开云体育)'"""
        ...

    @property
    @abstractmethod
    def api_domain_patterns(self) -> List[str]:
        """
        匹配API域名/URL的模式列表
        用于识别此Provider的API调用
        """
        ...

    def can_handle(self, url: str) -> bool:
        """判断此Provider是否能处理该URL"""
        return any(pattern in url for pattern in self.api_domain_patterns)

    def decode_response_data(self, data: str) -> Any:
        """
        解码gzipped+base64编码的响应数据
        YBTY的data字段是 base64(gzip(json)) 格式
        """
        try:
            compressed = base64.b64decode(data)
            decoded = gzip.decompress(compressed)
            return json.loads(decoded)
        except Exception:
            return None

    @abstractmethod
    def parse_match_detail(self, raw_data: Dict) -> Optional[Dict]:
        """
        解析赛事详情数据
        返回标准化字段: mid, league_name, home_team, away_team, match_time, match_status, sport_type
        """
        ...

    @abstractmethod
    def parse_odds(self, raw_data: Dict, match_info: Dict) -> List[Dict]:
        """
        解析赔率数据
        返回标准化赔率记录列表，每条含:
        platform, match_id, home_win_odds, draw_odds, away_win_odds,
        big_ball_odds, small_ball_odds, handicap, collect_time
        """
        ...

    def parse_timestamp(self, ts_ms: str) -> str:
        """将毫秒时间戳转为格式化字符串"""
        try:
            return datetime.fromtimestamp(int(ts_ms) / 1000).strftime('%Y-%m-%d %H:%M')
        except (ValueError, OSError):
            return ""

    def decimal_odds(self, int_odds: int) -> float:
        """将整数赔率转为十进制赔率 (198000 -> 1.98)"""
        return round(int_odds / 100000, 2)

    def normalize_status(self, status_code: str) -> str:
        """
        标准化比赛状态
        具体映射由子类实现
        """
        return "未开始"
