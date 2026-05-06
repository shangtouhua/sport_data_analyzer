"""
YBTY(开云体育) Provider
解析YBTY iframe中的赛事详情和赔率数据
"""

import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

from .base_provider import BaseProvider


logger = logging.getLogger(__name__)


class YBTYProvider(BaseProvider):
    """YBTY(开云体育) 数据提供商"""

    def __init__(self, filter_config: Optional[Dict[str, Any]] = None):
        super().__init__(filter_config)

    @property
    def code(self) -> str:
        return "YBTY"

    @property
    def name(self) -> str:
        return "YBTY(开云体育)"

    @property
    def api_domain_patterns(self) -> List[str]:
        return [
            "api.2y3cznx9.com/yewu11",
            "api.2y3cznx9.com/yewu12",
        ]

    # 市场类型: hpt → 中文名
    MARKET_TYPES = {
        1: "独赢",
        2: "让球",
        5: "大小",
        7: "让球胜平负",
    }

    # otd 映射: (市场hpt) → {otd值: 方向}
    OTD_MAP = {
        1: {47: "home", 48: "draw", 49: "away"},      # 全场独赢
        2: {3: "home", 4: "away"},                      # 全场让球
        5: {2: "over", 1: "under"},                     # 全场大小
        7: {7: "home", 8: "draw", 9: "away"},           # 让球胜平负
    }

    def parse_match_detail(self, raw_data: Dict) -> Optional[Dict]:
        """
        解析 getMatchDetailPB 响应
        字段:
          mid: 赛事ID
          mhn: 主队名称
          man: 客队名称
          tn: 联赛名称
          tnjc: 联赛简称
          csna: 体育类型
          mgt: 比赛时间(毫秒时间戳)
          mst: 状态码
        """
        match_info = {
            "mid": str(raw_data.get("mid", "")),
            "league_name": raw_data.get("tn", raw_data.get("tnjc", "")),
            "home_team": raw_data.get("mhn", ""),
            "away_team": raw_data.get("man", ""),
            "sport_type": raw_data.get("csna", "足球"),
            "match_time": self.parse_timestamp(raw_data.get("mgt", "0")),
            "match_status": self._map_status(raw_data.get("mst", "")),
            "raw_status": raw_data.get("mst", ""),
        }
        if not match_info["home_team"] or not match_info["away_team"]:
            logger.warning(f"YBTY赛事详情缺少队伍信息: mid={match_info['mid']}")
            return None

        # 运动类型过滤：只保留指定运动类型的赛事
        sport_filter = self.filter_config.get("sport_type")
        if sport_filter and match_info["sport_type"] != sport_filter:
            logger.debug(f"跳过非{sport_filter}赛事: {match_info['home_team']} vs {match_info['away_team']} (csna={raw_data.get('csna')})")
            return None

        return match_info

    def parse_odds(self, raw_data: Any, match_info: Dict) -> List[Dict]:
        """
        解析 getMatchOddsInfoPB 响应
        raw_data 是解码后的列表，每项是一个市场组
        """
        if not isinstance(raw_data, list):
            return []

        mid = match_info.get("mid", "")
        if not mid:
            return []

        collect_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 检查市场类型过滤配置
        market_types = self.filter_config.get("market_types", [])
        only_1x2 = market_types and "独赢" in market_types and len(market_types) == 1

        # 查找需要的市场
        market_1x2 = self._find_market(raw_data, hpt=1, hpid="1")     # 全场独赢

        home_win = draw = away_win = None
        if market_1x2:
            m = self._extract_otd(market_1x2, self.OTD_MAP[1])
            home_win, draw, away_win = m.get("home"), m.get("draw"), m.get("away")

        # Handicap
        handicap_value = home_handicap_odds = away_handicap_odds = None
        if not only_1x2:
            market_handicap = self._find_market(raw_data, hpt=2, hpid="4") # 全场让球
            if market_handicap:
                hl = market_handicap.get("hl", [])
                if hl:
                    handicap_value = hl[0].get("hv")
                    m = self._extract_otd(market_handicap, self.OTD_MAP[2])
                    home_handicap_odds, away_handicap_odds = m.get("home"), m.get("away")

        # Over/Under
        big_ball = small_ball = ou_handicap = None
        if not only_1x2:
            market_ou = self._find_market(raw_data, hpt=5, hpid="2")      # 全场大小
            if market_ou:
                hl = market_ou.get("hl", [])
                if hl:
                    ou_handicap = hl[0].get("hv")
                    m = self._extract_otd(market_ou, self.OTD_MAP[5])
                    big_ball, small_ball = m.get("over"), m.get("under")

        # handicap优先使用让球盘值，其次大小球值
        handicap = ou_handicap if handicap_value is None else handicap_value

        record = {
            "platform": self.code,
            "match_id": mid,
            "home_win_odds": home_win,
            "draw_odds": draw,
            "away_win_odds": away_win,
            "big_ball_odds": big_ball,
            "small_ball_odds": small_ball,
            "handicap": self._parse_handicap_float(handicap),
            "home_handicap_odds": home_handicap_odds,
            "away_handicap_odds": away_handicap_odds,
            "collect_time": collect_time,
        }
        return [record]

    def _find_market(self, data: list, hpt: int, hpid: str) -> Optional[Dict]:
        """在解码后的数据中查找指定市场组"""
        for item in data:
            if isinstance(item, dict) and item.get("hpt") == hpt and item.get("hpid") == hpid:
                return item
        for item in data:
            if isinstance(item, dict) and item.get("hpt") == hpt:
                return item
        return None

    def _extract_otd(self, market: Dict, otd_map: Dict) -> Dict[str, Optional[float]]:
        """通用otd提取: 根据otd映射表提取赔率"""
        result = {v: None for v in otd_map.values()}
        hl = market.get("hl", [])
        if not hl:
            return result
        for ol_item in hl[0].get("ol", []):
            otd = ol_item.get("otd")
            if otd in otd_map:
                result[otd_map[otd]] = self.decimal_odds(ol_item.get("obv", ol_item.get("ov", 0)))
        return result

    def _parse_handicap_float(self, hv: Optional[str]) -> Optional[float]:
        """将盘口值转为浮点数，支持 '1.5/2' 格式取均值"""
        if hv is None:
            return None
        if '/' in hv:
            parts = hv.split('/')
            try:
                return round((float(parts[0]) + float(parts[1])) / 2, 2)
            except (ValueError, IndexError):
                return None
        try:
            return float(hv)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def parse_hotlive_match(match_data: Dict) -> Optional[Dict]:
        """
        解析主站 hotLive/list API 返回的单场比赛数据，提取赛事信息与独赢赔率

        hotLive/list 响应结构:
          matchId: 赛事ID
          homeName: 主队名称
          visitName: 客队名称
          tournamentName: 联赛名称
          startAt: 比赛时间 (YYYY-MM-DD HH:MM:SS)
          matchClass: 运动类型 (football → 足球)
          oddsV2.singleWin.homeWin: 主胜赔率
          oddsV2.singleWin.awayWin: 客胜赔率
          oddsV2.singleWin.invincible: 平局赔率
        """
        match_id = str(match_data.get("matchId", ""))
        home_team = match_data.get("homeName", "")
        away_team = match_data.get("visitName", "")
        if not home_team or not away_team:
            return None

        match_class = match_data.get("matchClass", "")
        sport_type_map = {"football": "足球", "basketball": "篮球", "tennis": "网球"}
        sport_type = sport_type_map.get(match_class, match_class)

        league_name = match_data.get("tournamentName") or match_data.get("matchName", "")

        odds = match_data.get("oddsV2", {}).get("singleWin", {})

        return {
            "mid": match_id,
            "league_name": league_name,
            "home_team": home_team,
            "away_team": away_team,
            "sport_type": sport_type,
            "match_time": match_data.get("startAt", ""),
            "match_status": "未开始",
            "home_win_odds": odds.get("homeWin"),
            "draw_odds": odds.get("invincible"),
            "away_win_odds": odds.get("awayWin"),
        }

    def _map_status(self, status_code: str) -> str:
        """映射比赛状态: 620=未开始, 1=进行中"""
        return {"620": "未开始", "600": "未开始", "1": "进行中", "2": "已结束"}.get(status_code, "未开始")
