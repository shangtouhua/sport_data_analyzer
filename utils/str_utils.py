"""
字符串处理工具类
提供字符串相似度计算、格式化等功能
"""

import re
from typing import List, Dict, Any, Optional
from fuzzywuzzy import fuzz


class StringUtils:
    """
    字符串处理工具类
    封装常用的字符串处理功能
    """

    @staticmethod
    def normalize_string(text: str) -> str:
        """
        标准化字符串，移除特殊字符和多余空格

        Args:
            text: 原始字符串

        Returns:
            标准化后的字符串
        """
        if not text:
            return ""

        # 转换为小写
        normalized = text.lower()

        # 移除特殊字符，只保留字母、数字和空格
        normalized = re.sub(r'[^\w\s]', '', normalized)

        # 移除多余空格
        normalized = re.sub(r'\s+', ' ', normalized).strip()

        return normalized

    @staticmethod
    def calculate_similarity(str1: str, str2: str) -> float:
        """
        计算两个字符串的相似度

        Args:
            str1: 字符串1
            str2: 字符串2

        Returns:
            相似度分数 (0-100)
        """
        if not str1 or not str2:
            return 0

        # 标准化字符串
        norm_str1 = StringUtils.normalize_string(str1)
        norm_str2 = StringUtils.normalize_string(str2)

        # 使用多种算法计算相似度
        ratio = fuzz.ratio(norm_str1, norm_str2)
        partial_ratio = fuzz.partial_ratio(norm_str1, norm_str2)
        token_sort_ratio = fuzz.token_sort_ratio(norm_str1, norm_str2)
        token_set_ratio = fuzz.token_set_ratio(norm_str1, norm_str2)

        # 取最高分
        similarity = max(ratio, partial_ratio, token_sort_ratio, token_set_ratio)

        return similarity

    @staticmethod
    def extract_numbers(text: str) -> List[float]:
        """
        从文本中提取数字

        Args:
            text: 文本

        Returns:
            数字列表
        """
        if not text:
            return []

        # 匹配整数和小数
        number_pattern = r'[-+]?\d*\.?\d+'
        matches = re.findall(number_pattern, text)

        numbers = []
        for match in matches:
            try:
                # 尝试转换为浮点数
                number = float(match)
                numbers.append(number)
            except ValueError:
                continue

        return numbers

    @staticmethod
    def extract_odds(text: str) -> Optional[float]:
        """
        从文本中提取赔率

        Args:
            text: 文本

        Returns:
            赔率，提取失败返回None
        """
        numbers = StringUtils.extract_numbers(text)

        # 赔率通常大于1
        for number in numbers:
            if number > 1:
                return number

        return None

    @staticmethod
    def format_team_name(team_name: str) -> str:
        """
        格式化队伍名称

        Args:
            team_name: 原始队伍名称

        Returns:
            格式化后的队伍名称
        """
        if not team_name:
            return ""

        # 移除常见修饰词
        modifiers = [
            'fc', 'cf', 'afc', 'university', 'univ', 'college', 'club',
            'team', 'sports', 'association', 'assoc', 'football',
            'basketball', '竞技', '俱乐部', '大学', '学院', '体育'
        ]

        formatted = team_name.lower()
        for modifier in modifiers:
            formatted = re.sub(rf'\b{re.escape(modifier)}\b', '', formatted, flags=re.IGNORECASE)

        # 移除特殊字符和多余空格
        formatted = re.sub(r'[^\w\s]', '', formatted)
        formatted = re.sub(r'\s+', ' ', formatted).strip()

        return formatted.title()

    @staticmethod
    def format_odds(odds: float, decimal_places: int = 2) -> str:
        """
        格式化赔率显示

        Args:
            odds: 赔率
            decimal_places: 小数位数

        Returns:
            格式化后的赔率字符串
        """
        if not odds or odds <= 0:
            return "N/A"

        return f"{odds:.{decimal_places}f}"

    @staticmethod
    def format_currency(amount: float, currency: str = "¥") -> str:
        """
        格式化货币显示

        Args:
            amount: 金额
            currency: 货币符号

        Returns:
            格式化后的货币字符串
        """
        if amount is None:
            return f"{currency}0.00"

        return f"{currency}{amount:.2f}"

    @staticmethod
    def truncate_text(text: str, max_length: int, suffix: str = "...") -> str:
        """
        截断文本

        Args:
            text: 原始文本
            max_length: 最大长度
            suffix: 后缀

        Returns:
            截断后的文本
        """
        if not text or len(text) <= max_length:
            return text

        return text[:max_length - len(suffix)] + suffix

    @staticmethod
    def safe_get(data: Dict[str, Any], key: str, default: Any = None) -> Any:
        """
        安全获取字典值

        Args:
            data: 字典
            key: 键
            default: 默认值

        Returns:
            值或默认值
        """
        if not data or not isinstance(data, dict):
            return default

        return data.get(key, default)

    @staticmethod
    def join_strings(strings: List[str], separator: str = ", ") -> str:
        """
        连接字符串列表

        Args:
            strings: 字符串列表
            separator: 分隔符

        Returns:
            连接后的字符串
        """
        if not strings:
            return ""

        # 过滤空字符串
        filtered_strings = [s for s in strings if s and s.strip()]

        return separator.join(filtered_strings)

    @staticmethod
    def remove_duplicates(strings: List[str]) -> List[str]:
        """
        移除重复字符串（保持顺序）

        Args:
            strings: 字符串列表

        Returns:
            去重后的字符串列表
        """
        if not strings:
            return []

        seen = set()
        result = []

        for string in strings:
            if string not in seen:
                seen.add(string)
                result.append(string)

        return result

    @staticmethod
    def extract_domain(url: str) -> Optional[str]:
        """
        从URL中提取域名

        Args:
            url: URL

        Returns:
            域名，提取失败返回None
        """
        if not url:
            return None

        # 简单的域名提取
        domain_pattern = r'https?://([^/:]+)'
        match = re.search(domain_pattern, url)

        if match:
            return match.group(1)

        return None

    @staticmethod
    def validate_odds_format(odds_str: str) -> bool:
        """
        验证赔率格式

        Args:
            odds_str: 赔率字符串

        Returns:
            格式正确返回True，否则返回False
        """
        if not odds_str:
            return False

        try:
            odds = float(odds_str)
            return odds > 1.0
        except ValueError:
            return False