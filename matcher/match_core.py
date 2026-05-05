"""
赛事匹配核心模块
实现两个平台赛事的自动匹配算法
"""

from typing import List, Dict, Any, Optional, Tuple
import logging
from datetime import datetime, timedelta
from fuzzywuzzy import fuzz
import re

class MatchCore:
    """
    赛事匹配核心类
    通过联赛名称、队伍名称、比赛时间等维度匹配两个平台的赛事
    """

    def __init__(self, config: Dict[str, Any], logger: logging.Logger):
        """
        初始化匹配器

        Args:
            config: 配置字典
            logger: 日志记录器
        """
        self.config = config
        self.logger = logger
        self.similarity_threshold = config.get('similarity_threshold', 80)
        self.time_tolerance = config.get('time_tolerance', 5)  # 分钟

    def normalize_team_name(self, team_name: str) -> str:
        """
        标准化队伍名称，去除特殊字符和空格

        Args:
            team_name: 原始队伍名称

        Returns:
            标准化后的队伍名称
        """
        if not team_name:
            return ""

        # 转换为小写
        normalized = team_name.lower()

        # 移除常见的修饰词
        modifiers = [
            'fc', 'cf', 'afc', 'university', 'univ', 'college', 'club',
            'team', 'sports', 'association', 'assoc', 'football',
            'basketball', '竞技', '俱乐部', '大学', '学院'
        ]

        for modifier in modifiers:
            normalized = re.sub(rf'\b{re.escape(modifier)}\b', '', normalized)

        # 移除特殊字符和多余空格
        normalized = re.sub(r'[^\w\s]', '', normalized)
        normalized = re.sub(r'\s+', ' ', normalized).strip()

        return normalized

    def calculate_team_similarity(self, team1: str, team2: str) -> float:
        """
        计算两个队伍名称的相似度

        Args:
            team1: 队伍1名称
            team2: 队伍2名称

        Returns:
            相似度分数 (0-100)
        """
        if not team1 or not team2:
            return 0

        # 标准化队伍名称
        norm_team1 = self.normalize_team_name(team1)
        norm_team2 = self.normalize_team_name(team2)

        # 使用多种相似度算法计算
        ratio = fuzz.ratio(norm_team1, norm_team2)
        partial_ratio = fuzz.partial_ratio(norm_team1, norm_team2)
        token_sort_ratio = fuzz.token_sort_ratio(norm_team1, norm_team2)
        token_set_ratio = fuzz.token_set_ratio(norm_team1, norm_team2)

        # 取最高分
        similarity = max(ratio, partial_ratio, token_sort_ratio, token_set_ratio)

        return similarity

    def parse_match_time(self, time_str: str) -> Optional[datetime]:
        """
        解析比赛时间字符串

        Args:
            time_str: 时间字符串

        Returns:
            datetime对象，解析失败返回None
        """
        if not time_str:
            return None

        # 常见的时间格式
        formats = [
            '%Y-%m-%d %H:%M',
            '%Y-%m-%d %H:%M:%S',
            '%Y/%m/%d %H:%M',
            '%Y/%m/%d %H:%M:%S',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M:%S.%f'
        ]

        for fmt in formats:
            try:
                return datetime.strptime(time_str.strip(), fmt)
            except ValueError:
                continue

        return None

    def is_time_match(self, time1: str, time2: str) -> bool:
        """
        判断两个比赛时间是否匹配

        Args:
            time1: 时间1字符串
            time2: 时间2字符串

        Returns:
            时间匹配返回True，否则返回False
        """
        dt1 = self.parse_match_time(time1)
        dt2 = self.parse_match_time(time2)

        if not dt1 or not dt2:
            return False

        # 计算时间差（分钟）
        time_diff = abs((dt1 - dt2).total_seconds() / 60)

        return time_diff <= self.time_tolerance

    def match_matches(self, platform_a_matches: List[Dict[str, Any]],
                     platform_b_matches: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        匹配两个平台的赛事

        Args:
            platform_a_matches: 平台A的赛事列表
            platform_b_matches: 平台B的赛事列表

        Returns:
            匹配结果字典，包含匹配成功和失败的赛事
        """
        matched_pairs = []
        unmatched_a = []
        unmatched_b = platform_b_matches.copy()

        self.logger.info(f"开始匹配赛事: 平台A {len(platform_a_matches)} 场, 平台B {len(platform_b_matches)} 场")

        for match_a in platform_a_matches:
            best_match = None
            best_score = 0

            for match_b in unmatched_b[:]:
                score = self._calculate_match_score(match_a, match_b)

                if score > best_score and score >= self.similarity_threshold:
                    best_match = match_b
                    best_score = score

            if best_match:
                matched_pairs.append({
                    'platform_a': match_a,
                    'platform_b': best_match,
                    'match_score': best_score
                })
                unmatched_b.remove(best_match)
                self.logger.debug(f"匹配成功: {match_a['home_team']} vs {match_a['away_team']}, 分数: {best_score}")
            else:
                unmatched_a.append(match_a)
                self.logger.debug(f"匹配失败: {match_a['home_team']} vs {match_a['away_team']}")

        result = {
            'matched_pairs': matched_pairs,
            'unmatched_a': unmatched_a,
            'unmatched_b': unmatched_b,
            'match_statistics': {
                'total_a': len(platform_a_matches),
                'total_b': len(platform_b_matches),
                'matched_count': len(matched_pairs),
                'unmatched_a_count': len(unmatched_a),
                'unmatched_b_count': len(unmatched_b),
                'match_rate': len(matched_pairs) / max(len(platform_a_matches), 1) * 100
            }
        }

        self.logger.info(f"匹配完成: 成功 {len(matched_pairs)} 对, 匹配率 {result['match_statistics']['match_rate']:.1f}%")
        return result

    def _calculate_match_score(self, match_a: Dict[str, Any], match_b: Dict[str, Any]) -> float:
        """
        计算两个赛事的匹配分数

        Args:
            match_a: 平台A的赛事
            match_b: 平台B的赛事

        Returns:
            匹配分数 (0-100)
        """
        scores = []

        # 联赛名称相似度
        league_similarity = fuzz.ratio(
            match_a.get('league_name', '').lower(),
            match_b.get('league_name', '').lower()
        )
        scores.append(league_similarity * 0.2)  # 权重20%

        # 主队名称相似度
        home_similarity = self.calculate_team_similarity(
            match_a.get('home_team', ''),
            match_b.get('home_team', '')
        )
        scores.append(home_similarity * 0.3)  # 权重30%

        # 客队名称相似度
        away_similarity = self.calculate_team_similarity(
            match_a.get('away_team', ''),
            match_b.get('away_team', '')
        )
        scores.append(away_similarity * 0.3)  # 权重30%

        # 比赛时间匹配度
        time_match = self.is_time_match(
            match_a.get('match_time', ''),
            match_b.get('match_time', '')
        )
        time_score = 100 if time_match else 0
        scores.append(time_score * 0.2)  # 权重20%

        # 计算总分
        total_score = sum(scores)
        return total_score

    def find_match_by_info(self, target_match: Dict[str, Any],
                          candidate_matches: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        根据赛事信息查找匹配的赛事

        Args:
            target_match: 目标赛事
            candidate_matches: 候选赛事列表

        Returns:
            匹配的赛事，未找到返回None
        """
        best_match = None
        best_score = 0

        for candidate in candidate_matches:
            score = self._calculate_match_score(target_match, candidate)

            if score > best_score and score >= self.similarity_threshold:
                best_match = candidate
                best_score = score

        if best_match:
            self.logger.debug(f"找到匹配赛事: {target_match.get('home_team')} vs {target_match.get('away_team')}, 分数: {best_score}")

        return best_match

    def validate_match_result(self, match_pair: Dict[str, Any]) -> bool:
        """
        验证匹配结果的有效性

        Args:
            match_pair: 匹配的赛事对

        Returns:
            有效返回True，无效返回False
        """
        match_a = match_pair['platform_a']
        match_b = match_pair['platform_b']

        # 基本验证
        if not match_a.get('home_team') or not match_a.get('away_team'):
            return False

        if not match_b.get('home_team') or not match_b.get('away_team'):
            return False

        # 比赛状态验证
        valid_statuses = ['未开始', '进行中']
        if match_a.get('match_status') not in valid_statuses:
            return False

        if match_b.get('match_status') not in valid_statuses:
            return False

        # 时间验证
        if not self.is_time_match(match_a.get('match_time', ''), match_b.get('match_time', '')):
            return False

        return True