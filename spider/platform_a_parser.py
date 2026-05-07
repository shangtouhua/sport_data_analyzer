"""
平台A解析器
继承BaseSpider，使用Playwright网络拦截从iframe中提取第三方体育提供商赔率数据。

平台A是一个Next.js SPA聚合平台，体育数据来自第三方提供商(YBTY/IMTY等)的iframe，
直连API(/site/api/v1/odds)返回404，因此改用Playwright浏览器自动化 + 网络拦截方案。
"""

from typing import Dict, List, Any, Optional
import logging
import os

from .base_spider import BaseSpider
from .iframe_network_interceptor import IframeDataExtractor

class PlatformAParser(BaseSpider):
    """
    平台A解析器
    使用Playwright拦截iframe API响应，通过Provider解析赔率数据
    """

    def __init__(self, config: Dict[str, Any], logger: logging.Logger):
        """
        初始化平台A解析器

        Args:
            config: 爬虫配置
            logger: 日志记录器
        """
        super().__init__(config, logger)
        self.platform_name = "platform_a"

        # 平台A特定配置
        # 注意: config 是 spider 子配置（main.py传入spider_config），
        # 因此 platform_a 在 config.platforms.platform_a 路径下
        platform_config = config.get('platforms', {}).get('platform_a', {})
        self.base_url = platform_config.get('base_url', '')
        self.login_url = platform_config.get('login_url', '')
        self.login_api = platform_config.get('login_api', '')
        self.odds_endpoint = platform_config.get('odds_endpoint', '')

        # 登录凭证
        self.credentials = platform_config.get('credentials', {})

        # 验证码配置
        self.captcha_config = platform_config.get('captcha', {})

        # Playwright爬取配置
        pw_scraping = config.get('playwright_scraping', {})
        self.pw_provider = pw_scraping.get('provider', 'YBTY')
        self.pw_headless = pw_scraping.get('headless', True)
        self.pw_capture_duration = pw_scraping.get('capture_duration_ms', 15000)
        self.pw_cookie_path = pw_scraping.get('cookie_path', 'data/platform_a_cookies.json')

        # 完整的URL（优先使用login_api，回退到login_url）
        self.full_login_url = f"{self.base_url}{self.login_api}" if self.login_api else f"{self.base_url}{self.login_url}"

    async def crawl_matches(self, platform_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        爬取赛事数据的主方法
        使用Playwright网络拦截从第三方体育提供商iframe提取赔率数据

        Args:
            platform_config: 平台配置

        Returns:
            赛事数据列表
        """
        self.logger.info(f"开始爬取平台数据: {platform_config['name']}")

        # 确保已登录（验证cookie有效）
        if not await self._ensure_login():
            self.logger.error("登录失败，无法爬取数据")
            return []

        # 读取并打印活跃的过滤条件
        filters = self.config.get('playwright_scraping', {}).get('filters', {})
        sport_filter = filters.get('sport_type')
        market_filter = filters.get('market_types')
        if sport_filter or market_filter:
            self.logger.info(f"数据过滤: sport_type={sport_filter}, market_types={market_filter}")

        self.logger.info(
            f"使用Playwright拦截 [{self.pw_provider}] 数据, "
            f"超时: {self.pw_capture_duration}ms"
        )

        # 使用IframeDataExtractor通过Playwright捕获数据
        extractor = IframeDataExtractor(self.config, self.logger)
        matches = await extractor.extract_from_page(
            provider_code=self.pw_provider,
            cookie_path=self.pw_cookie_path,
            headless=self.pw_headless,
            capture_duration=self.pw_capture_duration,
        )

        # 如果匹配数为0，可能是API结构变化或数据未加载完成
        if not matches:
            self.logger.warning("未提取到赛事数据（可能原因：cookie已过期、iframe未加载、API结构变化）")

        self.logger.info(f"Playwright提取完成，共 {len(matches)} 场比赛")
        return matches

    async def _ensure_login(self) -> bool:
        """
        确保登录状态
        优先使用cookie登录，cookie无效时才尝试Playwright或API登录

        Returns:
            是否成功登录
        """
        # 如果已经通过cookie登录，直接验证登录状态
        if self.is_logged_in:
            return await self.ensure_login(
                login_url=self.full_login_url,
                credentials={},  # cookie模式下不传密码，避免fallback到API登录
                captcha_config=self.captcha_config,
                max_retries=1
            )

        # 检查cookie_login配置：如果启用了cookie但未登录，说明cookie文件无效或被拒绝
        cookie_config = self.config.get('platforms', {}).get('platform_a', {}).get('cookie_login', {})
        if cookie_config.get('enabled', False):
            cookie_file = cookie_config.get('cookie_file', '')
            cookie_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), cookie_file)
            if os.path.exists(cookie_path):
                self.logger.warning("Cookie文件无效或已过期，尝试使用Playwright自动登录...")
            else:
                self.logger.info("Cookie文件不存在，尝试其他登录方式")

        # 尝试Playwright自动登录
        playwright_available = False
        try:
            import playwright
            playwright_available = True
        except ImportError:
            pass

        if playwright_available and self.credentials.get('username'):
            self.logger.info("Cookie登录不可用，尝试Playwright自动登录...")
            success = await self._login_with_playwright(self.credentials)
            if success:
                return True

        # 最后尝试API登录（需要平台支持，大概率因AES加密失败）
        if self.credentials.get('username') and self.credentials.get('password'):
            self.logger.warning("API直接登录成功率低（平台使用AES加密密码），建议使用cookie方式")
            return await self.ensure_login(
                login_url=self.full_login_url,
                credentials=self.credentials,
                captcha_config=self.captcha_config,
                max_retries=self.captcha_config.get('retry_limit', 3)
            )

        self.logger.error("所有登录方式均不可用")
        self.logger.info("请在浏览器登录后导出cookie到 data/platform_a_cookies.json")
        return False