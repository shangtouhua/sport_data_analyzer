"""
平台B解析器
继承BaseSpider，实现针对平台B的页面解析逻辑
"""

from typing import Dict, List, Any, Optional
from bs4 import BeautifulSoup
import logging
import re
from datetime import datetime
from .base_spider import BaseSpider

class PlatformBParser(BaseSpider):
    """
    平台B解析器
    针对平台B的页面结构和数据格式进行解析
    """

    def __init__(self, config: Dict[str, Any], logger: logging.Logger):
        """
        初始化平台B解析器

        Args:
            config: 爬虫配置
            logger: 日志记录器
        """
        super().__init__(config, logger)
        self.platform_name = "platform_b"

    def extract_match_info(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """
        从平台B页面提取赛事信息

        Args:
            soup: BeautifulSoup对象

        Returns:
            赛事信息列表
        """
        matches = []

        try:
            # 示例解析逻辑，需要根据实际页面结构调整
            # 假设赛事信息在class为'game-list'的table中
            match_table = soup.find('table', class_='game-list')
            if match_table:
                rows = match_table.find_all('tr', class_='game-row')
                for row in rows:
                    match_data = self._parse_single_match(row)
                    if match_data:
                        matches.append(match_data)

        except Exception as e:
            self.logger.error(f"解析平台B页面失败: {str(e)}")

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
        sport_elem = element.find('td', class_='sport-category')
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
        league_elem = element.find('td', class_='league-info')
        if league_elem:
            return league_elem.get_text().strip()
        return '未知联赛'

    def _extract_team_names(self, element: BeautifulSoup) -> tuple:
        """提取主队和客队名称"""
        teams_cell = element.find('td', class_='teams-cell')
        if teams_cell:
            home_elem = teams_cell.find('span', class_='home-team-name')
            away_elem = teams_cell.find('span', class_='away-team-name')

            home_team = home_elem.get_text().strip() if home_elem else '未知主队'
            away_team = away_elem.get_text().strip() if away_elem else '未知客队'

            return home_team, away_team
        return '未知主队', '未知客队'

    def _extract_match_time(self, element: BeautifulSoup) -> str:
        """提取比赛时间"""
        time_elem = element.find('td', class_='match-datetime')
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
        status_elem = element.find('td', class_='game-status')
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
            odds_cells = element.find_all('td', class_='odds-cell')
            if len(odds_cells) >= 3:
                odds_data['home_win'] = float(odds_cells[0].get_text().strip())
                odds_data['draw'] = float(odds_cells[1].get_text().strip())
                odds_data['away_win'] = float(odds_cells[2].get_text().strip())

            # 大小球赔率
            handicap_cell = element.find('td', class_='handicap-odds')
            if handicap_cell:
                big_elem = handicap_cell.find('span', class_='over')
                small_elem = handicap_cell.find('span', class_='under')
                handicap_elem = handicap_cell.find('span', class_='line')

                if big_elem:
                    odds_data['big_ball'] = float(big_elem.get_text().strip())
                if small_elem:
                    odds_data['small_ball'] = float(small_elem.get_text().strip())
                if handicap_elem:
                    odds_data['handicap'] = float(handicap_elem.get_text().strip())

        except (ValueError, AttributeError) as e:
            self.logger.warning(f"赔率解析失败: {str(e)}")

        return odds_data