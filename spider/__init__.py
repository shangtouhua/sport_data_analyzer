# 爬虫模块初始化
# 该模块包含通用爬虫基类和各个平台的解析器

from .base_spider import BaseSpider
from .platform_a_parser import PlatformAParser
from .platform_b_parser import PlatformBParser

__all__ = ['BaseSpider', 'PlatformAParser', 'PlatformBParser']