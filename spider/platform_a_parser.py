"""
平台A解析器
继承BaseSpider，实现针对平台A的页面解析逻辑
"""

from typing import Dict, List, Any, Optional
from bs4 import BeautifulSoup
import logging
import re
import os
import json
from datetime import datetime
from .base_spider import BaseSpider

class PlatformAParser(BaseSpider):
    """
    平台A解析器
    针对平台A的页面结构和数据格式进行解析
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
        platform_config = config.get('spider', {}).get('platforms', {}).get('platform_a', {})
        self.base_url = platform_config.get('base_url', '')
        self.login_url = platform_config.get('login_url', '')
        self.login_api = platform_config.get('login_api', '')
        self.odds_endpoint = platform_config.get('odds_endpoint', '')

        # 登录凭证
        self.credentials = platform_config.get('credentials', {})

        # 验证码配置
        self.captcha_config = platform_config.get('captcha', {})

        # 完整的URL（优先使用login_api，回退到login_url）
        self.full_login_url = f"{self.base_url}{self.login_api}" if self.login_api else f"{self.base_url}{self.login_url}"
        self.full_odds_url = f"{self.base_url}{self.odds_endpoint}"

    def extract_match_info(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """
        从平台A页面提取赛事信息

        Args:
            soup: BeautifulSoup对象

        Returns:
            赛事信息列表
        """
        matches = []

        try:
            # 示例解析逻辑，需要根据实际页面结构调整
            # 假设赛事信息在class为'match-item'的元素中
            match_elements = soup.find_all('div', class_='match-item')

            for element in match_elements:
                match_data = self._parse_single_match(element)
                if match_data:
                    matches.append(match_data)

        except Exception as e:
            self.logger.error(f"解析平台A页面失败: {str(e)}")

        return matches

    def _parse_single_match(self, element: BeautifulSoup) -> Optional[Dict[str, Any]]:
        """
        解析单场比赛信息

        Args:
            element: 单个赛事的BeautifulSoup元素

        Returns:
            赛事数据字典，解析失败返回None
        """
        try:
            # 提取赛事类型
            sport_type = self._extract_sport_type(element)

            # 提取联赛名称
            league_name = self._extract_league_name(element)

            # 提取队伍信息
            home_team, away_team = self._extract_team_names(element)

            # 提取比赛时间
            match_time = self._extract_match_time(element)

            # 提取比赛状态
            match_status = self._extract_match_status(element)

            # 提取赔率信息
            odds_data = self._extract_odds(element)

            # 构建完整赛事数据
            match_data = {
                'platform': self.platform_name,
                'sport_type': sport_type,
                'league_name': league_name,
                'home_team': home_team,
                'away_team': away_team,
                'match_time': match_time,
                'match_status': match_status,
                'home_win_odds': odds_data.get('home_win'),
                'draw_odds': odds_data.get('draw'),
                'away_win_odds': odds_data.get('away_win'),
                'big_ball_odds': odds_data.get('big_ball'),
                'small_ball_odds': odds_data.get('small_ball'),
                'handicap': odds_data.get('handicap'),
                'collect_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }

            return match_data

        except Exception as e:
            self.logger.error(f"解析单场比赛失败: {str(e)}")
            return None

    def _extract_sport_type(self, element: BeautifulSoup) -> str:
        """提取赛事类型"""
        # 示例实现，需要根据实际页面结构调整
        sport_elem = element.find('span', class_='sport-type')
        if sport_elem:
            sport_text = sport_elem.get_text().strip()
            # 映射到标准赛事类型
            sport_mapping = {
                '足球': '足球',
                '篮球': '篮球',
                '网球': '网球',
                'basketball': '篮球',
                'football': '足球',
                'tennis': '网球'
            }
            return sport_mapping.get(sport_text, sport_text)
        return '未知'

    def _extract_league_name(self, element: BeautifulSoup) -> str:
        """提取联赛名称"""
        league_elem = element.find('div', class_='league-name')
        if league_elem:
            return league_elem.get_text().strip()
        return '未知联赛'

    def _extract_team_names(self, element: BeautifulSoup) -> tuple:
        """提取主队和客队名称"""
        home_elem = element.find('span', class_='home-team')
        away_elem = element.find('span', class_='away-team')

        home_team = home_elem.get_text().strip() if home_elem else '未知主队'
        away_team = away_elem.get_text().strip() if away_elem else '未知客队'

        return home_team, away_team

    def _extract_match_time(self, element: BeautifulSoup) -> str:
        """提取比赛时间"""
        time_elem = element.find('span', class_='match-time')
        if time_elem:
            time_text = time_elem.get_text().strip()
            # 尝试解析时间格式
            try:
                # 假设格式为 "2024-01-15 20:30"
                datetime.strptime(time_text, '%Y-%m-%d %H:%M')
                return time_text
            except ValueError:
                # 如果格式不匹配，返回原始文本
                return time_text
        return ''

    def _extract_match_status(self, element: BeautifulSoup) -> str:
        """提取比赛状态"""
        status_elem = element.find('span', class_='match-status')
        if status_elem:
            status_text = status_elem.get_text().strip()
            status_mapping = {
                '未开始': '未开始',
                '进行中': '进行中',
                '已结束': '已结束',
                'not_started': '未开始',
                'in_progress': '进行中',
                'finished': '已结束'
            }
            return status_mapping.get(status_text, status_text)
        return '未开始'

    def _extract_odds(self, element: BeautifulSoup) -> Dict[str, float]:
        """提取赔率信息"""
        odds_data = {
            'home_win': None,
            'draw': None,
            'away_win': None,
            'big_ball': None,
            'small_ball': None,
            'handicap': None
        }

        try:
            # 胜平负赔率
            odds_elements = element.find_all('div', class_='odds-item')
            if len(odds_elements) >= 3:
                odds_data['home_win'] = float(odds_elements[0].get_text().strip())
                odds_data['draw'] = float(odds_elements[1].get_text().strip())
                odds_data['away_win'] = float(odds_elements[2].get_text().strip())

            # 大小球赔率
            ball_odds = element.find('div', class_='ball-odds')
            if ball_odds:
                big_elem = ball_odds.find('span', class_='big-ball')
                small_elem = ball_odds.find('span', class_='small-ball')
                handicap_elem = ball_odds.find('span', class_='handicap')

                if big_elem:
                    odds_data['big_ball'] = float(big_elem.get_text().strip())
                if small_elem:
                    odds_data['small_ball'] = float(small_elem.get_text().strip())
                if handicap_elem:
                    odds_data['handicap'] = float(handicap_elem.get_text().strip())

        except (ValueError, AttributeError) as e:
            self.logger.warning(f"赔率解析失败: {str(e)}")

        return odds_data

    async def crawl_matches(self, platform_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        爬取赛事数据的主方法（包含登录检查）

        Args:
            platform_config: 平台配置

        Returns:
            赛事数据列表
        """
        self.logger.info(f"开始爬取平台数据: {platform_config['name']}")

        # 确保已登录
        if not await self._ensure_login():
            self.logger.error("登录失败，无法爬取数据")
            return []

        # 构建完整的赔率页面URL
        url = self.full_odds_url

        self.logger.info(f"获取赔率页面: {url}")

        # 使用已登录的session获取页面
        html_content = await self.fetch_page(url, timeout=platform_config.get('timeout', 30))
        if not html_content:
            self.logger.error(f"获取页面内容失败: {url}")
            # 如果获取失败，可能是登录状态失效，重置登录状态
            self.is_logged_in = False
            return []

        try:
            soup = self.parse_html(html_content)
            matches = self.extract_match_info(soup)
            self.logger.info(f"成功爬取 {len(matches)} 场比赛数据")
            return matches
        except Exception as e:
            self.logger.error(f"解析页面失败: {str(e)}")
            return []

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
        cookie_config = self.config.get('spider', {}).get('platforms', {}).get('platform_a', {}).get('cookie_login', {})
        if cookie_config.get('enabled', False):
            cookie_file = cookie_config.get('cookie_file', '')
            cookie_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), cookie_file)
            if os.path.exists(cookie_path):
                # cookie文件存在但加载失败（占位符或过期），要求用户重新导出
                self.logger.error("Cookie文件无效或包含占位符值，请重新在浏览器登录后导出")
                self.logger.info("运行 python tools/extract_cookies.py 获取操作指南")
                return False
            # cookie文件不存在，尝试Playwright自动登录
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