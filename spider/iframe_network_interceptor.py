"""
核心爬取引擎：使用 Playwright 网络拦截捕获第三方体育提供商 iframe 中的赔率数据

工作流程:
  1. 使用已登录的 cookie 启动 Playwright 浏览器
  2. 导航到体育提供商页面（如 /game/sport/ob）
  3. 通过 page.on('response') 拦截 JSON API 响应
  4. 使用对应的 Provider 解码(gzip+base64)并解析数据
  5. 返回标准化赛事数据
"""

import asyncio
import json
import os
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

from .providers import get_provider, BaseProvider


logger = logging.getLogger(__name__)


class IframeDataExtractor:
    """
    Playwright iframe 数据提取器

    使用方式:
        extractor = IframeDataExtractor(config, logger)
        matches = await extractor.extract_from_page(
            provider_code="YBTY",
            cookie_path="data/platform_a_cookies.json",
        )
    """

    # 导航等待时间
    NAVIGATE_TIMEOUT = 60000       # 页面加载超时
    CAPTURE_WAIT = 15000           # 等待API响应捕获时间
    NETWORK_IDLE_TIMEOUT = 15000   # 等待网络空闲超时

    def __init__(self, config: Dict[str, Any], logger_obj: logging.Logger = None):
        """
        Args:
            config: 全局配置字典
            logger_obj: 日志记录器
        """
        self.config = config
        self.logger = logger_obj or logger

        platform_cfg = config.get('spider', {}).get('platforms', {}).get('platform_a', {})
        self.base_url = platform_cfg.get('base_url', 'https://www.uompld.vip:7988')

        # 读取数据过滤配置
        pw_scraping = config.get('spider', {}).get('playwright_scraping', {})
        self.filter_config = pw_scraping.get('filters', {})

        # 提供商路径映射
        self.provider_paths = {
            "YBTY": "/game/sport/ob",
            "IMTY": "/game/sport/im",
            "FBTY": "/game/sport/fb",
            "DBTY": "/game/sport/db",
            "XJTY": "/game/sport/V188",
        }

    def _load_cookies(self, cookie_path: str) -> List[Dict]:
        """从文件加载cookie并转为Playwright格式"""
        full_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), cookie_path)
        if not os.path.exists(full_path):
            self.logger.error(f"Cookie文件不存在: {full_path}")
            return []

        with open(full_path, 'r', encoding='utf-8') as f:
            raw_cookies = json.load(f)

        pw_cookies = []
        for c in raw_cookies:
            if isinstance(c, dict) and c.get('name') and c.get('value'):
                pw_cookies.append({
                    'name': c['name'],
                    'value': c['value'],
                    'domain': c.get('domain', 'www.uompld.vip'),
                    'path': c.get('path', '/'),
                    'httpOnly': c.get('httpOnly', False),
                    'secure': c.get('secure', True),
                    'sameSite': c.get('sameSite', 'Lax'),
                })
        return pw_cookies

    async def extract_from_page(
        self,
        provider_codes: List[str] = None,
        provider_code: str = None,
        cookie_path: str = "data/platform_a_cookies.json",
        headless: bool = True,
        capture_duration: int = None,
    ) -> List[Dict[str, Any]]:
        """
        从多个体育提供商页面提取赛事数据

        Args:
            provider_codes: 提供商代码列表，默认["YBTY", "DBTY", "IMTY", "FBTY"]
            provider_code: 单个提供商代码（向后兼容）
            cookie_path: cookie文件路径
            headless: 是否无头模式
            capture_duration: 捕获等待时间(毫秒)

        Returns:
            标准化赛事数据列表
        """
        if provider_code:
            codes = [provider_code]
        elif provider_codes:
            codes = provider_codes
        else:
            codes = ["YBTY", "DBTY", "IMTY", "FBTY"]

        wait_ms = capture_duration or self.CAPTURE_WAIT

        cookies = self._load_cookies(cookie_path)
        if not cookies:
            self.logger.error(f"无法加载cookie: {cookie_path}")
            return []

        self.logger.info(f"已加载 {len(cookies)} 个cookie, 将爬取 {len(codes)} 个提供商")

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            self.logger.error("需安装playwright: pip install playwright && playwright install chromium")
            return []

        all_captured = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=headless,
                args=['--no-sandbox', '--disable-blink-features=AutomationControlled'],
            )

            context = await browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                locale='zh-CN',
                user_agent=(
                    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/125.0.0.0 Safari/537.36'
                ),
            )

            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            """)
            await context.add_cookies(cookies)

            page = await context.new_page()

            async def on_response(response):
                """拦截所有JSON响应"""
                content_type = response.headers.get('content-type', '')
                if 'json' not in content_type:
                    return
                try:
                    body = await response.json()
                    url = response.url
                    self.logger.info(f"[捕获JSON] {url}")
                    all_captured.append({
                        'url': url,
                        'method': response.request.method,
                        'status': response.status,
                        'headers': dict(response.headers),
                        'body': body,
                    })
                except Exception:
                    pass

            page.on('response', on_response)

            try:
                # 先访问主站首页触发 hotLive/list API
                self.logger.info(f"导航到主站: {self.base_url}")
                await page.goto(self.base_url, wait_until='domcontentloaded', timeout=self.NAVIGATE_TIMEOUT)
                await page.wait_for_timeout(5000)

                # 依次导航到每个提供商的iframe
                for code in codes:
                    path = self.provider_paths.get(code, "/game/sport/ob")
                    url = f"{self.base_url}{path}"
                    self.logger.info(f"[{code}] 导航到提供商页面: {url}")
                    try:
                        await page.goto(url, wait_until='domcontentloaded', timeout=self.NAVIGATE_TIMEOUT)
                        await page.wait_for_timeout(wait_ms)
                        try:
                            await page.wait_for_load_state('networkidle', timeout=self.NETWORK_IDLE_TIMEOUT)
                        except Exception:
                            pass
                        await page.wait_for_timeout(2000)
                    except Exception as e:
                        self.logger.error(f"[{code}] 页面加载出错: {e}")

                self.logger.info(f"总共捕获 {len(all_captured)} 个API响应")

            except Exception as e:
                self.logger.error(f"页面加载出错: {e}")
            finally:
                page.remove_listener('response', on_response)
                await browser.close()

        # 对每个provider解析数据
        all_results = []
        for code in codes:
            provider = get_provider(code, filter_config=self.filter_config)
            # hotLive/list 仅返回 YB venue 数据，优先用于 YBTY
            if code == "YBTY":
                hotlive_results = self._capture_hotlive_matches(provider, all_captured)
                if hotlive_results:
                    self.logger.info(f"[{code}] 从 hotLive/list 获取到 {len(hotlive_results)} 场比赛")
                    all_results.extend(hotlive_results)
                    continue

            # 解析 iframe API 响应（用于非YBTY provider，或YBTY hotLive失败时的回退）
            provider_responses = [r for r in all_captured if provider.can_handle(r.get('url', ''))]
            if not provider_responses:
                # 回退：使用第三方API响应（排除主站API）
                provider_responses = [r for r in all_captured
                                      if '/site/api/' not in r.get('url', '')
                                      and '/game/api/' not in r.get('url', '')
                                      and '/act/api/' not in r.get('url', '')
                                      and '/ins/api/' not in r.get('url', '')
                                      and '/page/' not in r.get('url', '')
                                      and '/api/json-cache/' not in r.get('url', '')]
            results = self._parse_captured_data(provider, provider_responses)
            if results:
                self.logger.info(f"[{code}] 从 iframe API 获取到 {len(results)} 场比赛")
            else:
                self.logger.warning(f"[{code}] 未获取到数据（提供商可能不可用或API格式不同）")
            all_results.extend(results)

        self.logger.info(f"全部提供商共提取 {len(all_results)} 场比赛")
        return all_results

    def _parse_captured_data(
        self, provider: BaseProvider, captured: List[Dict]
    ) -> List[Dict[str, Any]]:
        """
        解析捕获的API响应，合并赛事详情和赔率

        1. 按URL路径分类（getMatchDetailPB / getMatchOddsInfoPB）
        2. 解析赛事详情，按mid索引
        3. 解析赔率并合并到对应赛事
        """
        if not captured:
            return []

        detail_responses = []
        odds_responses = []

        for resp in captured:
            url = resp.get('url', '')
            body = resp.get('body', {})
            if not isinstance(body, dict):
                continue
            data = body.get('data', '')
            if not data or body.get('code', '') != '0000000':
                continue

            if 'getMatchDetailPB' in url:
                detail_responses.append(resp)
            elif 'getMatchOddsInfoPB' in url:
                odds_responses.append(resp)

        self.logger.info(
            f"解析 {len(detail_responses)} 个详情, {len(odds_responses)} 个赔率"
        )

        # 解析赛事详情 → mid索引
        match_map = {}
        for resp in detail_responses:
            decoded = provider.decode_response_data(resp['body']['data'])
            if decoded:
                match_info = provider.parse_match_detail(decoded)
                if match_info and match_info.get('mid'):
                    # 二次运动类型检查（belt-and-suspenders）
                    sport_filter = self.filter_config.get("sport_type")
                    if sport_filter and match_info.get("sport_type") != sport_filter:
                        continue
                    match_map[match_info['mid']] = match_info

        # 解析赔率并合并
        results = []
        for mid, match_info in match_map.items():
            match_odds_list = []
            for resp in odds_responses:
                url = resp.get('url', '')
                if f'mid={mid}' in url or f'mid%3D{mid}' in url:
                    decoded = provider.decode_response_data(resp['body']['data'])
                    if decoded:
                        odds_records = provider.parse_odds(decoded, match_info)
                        match_odds_list.extend(odds_records)

            result = dict(match_info)
            result['platform'] = provider.code
            result['collect_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            if match_odds_list:
                odds = match_odds_list[0]
                result.update({
                    'home_win_odds': odds.get('home_win_odds'),
                    'draw_odds': odds.get('draw_odds'),
                    'away_win_odds': odds.get('away_win_odds'),
                    'big_ball_odds': odds.get('big_ball_odds'),
                    'small_ball_odds': odds.get('small_ball_odds'),
                    'handicap': odds.get('handicap'),
                })
                self.logger.info(
                    f"成功: {match_info.get('home_team')} vs "
                    f"{match_info.get('away_team')}"
                )
            else:
                self.logger.warning(
                    f"无赔率: {match_info.get('home_team')} vs "
                    f"{match_info.get('away_team')}"
                )

            results.append(result)

        self.logger.info(f"共提取 {len(results)} 场比赛")
        return results

    def _capture_hotlive_matches(
        self, provider: BaseProvider, captured: List[Dict]
    ) -> List[Dict[str, Any]]:
        """
        从捕获的响应中提取主站 hotLive/list 的比赛数据

        hotLive/list 一次性返回全部比赛的基本信息 + 独赢赔率（homeWin/awayWin/invincible），
        无需逐个调用 YBTY iframe API，是获取独赢赔率最高效的方式。
        """
        for resp in captured:
            url = resp.get('url', '')
            if '/site/api/v1/video/hotLive/list' not in url:
                continue
            body = resp.get('body', {})
            if not isinstance(body, dict):
                continue
            data = body.get('data', {})
            if not isinstance(data, dict):
                continue
            match_list = data.get('list', [])
            if not match_list:
                continue

            self.logger.info(
                f"发现 hotLive/list 响应: {len(match_list)} 场比赛 "
                f"(page={data.get('page')}, total={data.get('total')})"
            )

            results = []
            sport_filter = self.filter_config.get("sport_type")
            for match_data in match_list:
                match_info = provider.parse_hotlive_match(match_data)
                if not match_info:
                    continue
                # sport_type 过滤
                if sport_filter and match_info.get("sport_type") != sport_filter:
                    continue
                match_info['platform'] = provider.code
                match_info['collect_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                results.append(match_info)

            self.logger.info(f"hotLive/list 过滤后共 {len(results)} 场比赛")
            return results

        return []
