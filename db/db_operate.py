"""
数据库操作工具类
封装增删改查（CRUD）操作
"""

import sqlite3
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import json

class DatabaseOperator:
    """
    数据库操作器
    封装所有数据库操作，提供统一的CRUD接口
    """

    def __init__(self, db_path: str, logger: logging.Logger):
        """
        初始化数据库操作器

        Args:
            db_path: 数据库文件路径
            logger: 日志记录器
        """
        self.db_path = db_path
        self.logger = logger

    def _execute_query(self, query: str, params: tuple = ()) -> List[Tuple]:
        """
        执行查询语句

        Args:
            query: SQL查询语句
            params: 查询参数

        Returns:
            查询结果列表
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(query, params)
                return cursor.fetchall()
        except Exception as e:
            self.logger.error(f"查询执行失败: {query}, 错误: {str(e)}")
            return []

    def _execute_update(self, query: str, params: tuple = ()) -> bool:
        """
        执行更新语句

        Args:
            query: SQL更新语句
            params: 更新参数

        Returns:
            执行成功返回True，失败返回False
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            self.logger.error(f"更新执行失败: {query}, 错误: {str(e)}")
            return False

    def insert_match_info(self, match_data: Dict[str, Any]) -> Optional[int]:
        """
        插入赛事基础信息

        Args:
            match_data: 赛事数据字典

        Returns:
            成功返回match_id，失败返回None
        """
        try:
            query = """
            INSERT OR IGNORE INTO match_info
            (league_name, home_team, away_team, match_time, match_status)
            VALUES (?, ?, ?, ?, ?)
            """

            params = (
                match_data['league_name'],
                match_data['home_team'],
                match_data['away_team'],
                match_data['match_time'],
                match_data['match_status']
            )

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                conn.commit()

                if cursor.rowcount > 0:
                    # 获取插入的match_id
                    match_id = cursor.lastrowid
                    self.logger.debug(f"插入赛事信息成功，match_id: {match_id}")
                    return match_id
                else:
                    # 如果插入被忽略（重复数据），查询现有的match_id
                    match_id = self.get_match_id(match_data)
                    return match_id

        except Exception as e:
            self.logger.error(f"插入赛事信息失败: {str(e)}")
            return None

    def get_match_id(self, match_data: Dict[str, Any]) -> Optional[int]:
        """
        根据赛事信息获取match_id

        Args:
            match_data: 赛事数据字典

        Returns:
            match_id，未找到返回None
        """
        query = """
        SELECT match_id FROM match_info
        WHERE league_name = ? AND home_team = ? AND away_team = ? AND match_time = ?
        """

        params = (
            match_data['league_name'],
            match_data['home_team'],
            match_data['away_team'],
            match_data['match_time']
        )

        result = self._execute_query(query, params)
        if result:
            return result[0][0]
        return None

    def insert_odds_record(self, match_id: int, odds_data: Dict[str, Any]) -> bool:
        """
        插入赔率记录

        Args:
            match_id: 赛事ID
            odds_data: 赔率数据字典

        Returns:
            插入成功返回True，失败返回False
        """
        try:
            query = """
            INSERT OR IGNORE INTO odds_record
            (match_id, platform, home_win_odds, draw_odds, away_win_odds,
             big_ball_odds, small_ball_odds, handicap, collect_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """

            params = (
                match_id,
                odds_data['platform'],
                odds_data.get('home_win_odds'),
                odds_data.get('draw_odds'),
                odds_data.get('away_win_odds'),
                odds_data.get('big_ball_odds'),
                odds_data.get('small_ball_odds'),
                odds_data.get('handicap'),
                odds_data['collect_time']
            )

            success = self._execute_update(query, params)
            if success:
                self.logger.debug(f"插入赔率记录成功，match_id: {match_id}, 平台: {odds_data['platform']}")
            return success

        except Exception as e:
            self.logger.error(f"插入赔率记录失败: {str(e)}")
            return False

    def get_latest_odds(self, match_id: int) -> List[Dict[str, Any]]:
        """
        获取指定赛事的最新赔率记录

        Args:
            match_id: 赛事ID

        Returns:
            赔率记录列表
        """
        query = """
        SELECT * FROM odds_record
        WHERE match_id = ?
        ORDER BY collect_time DESC
        LIMIT 2  -- 获取两个平台的数据
        """

        results = self._execute_query(query, (match_id,))
        return [dict(row) for row in results]

    def get_matches_without_odds(self, platform: str) -> List[Dict[str, Any]]:
        """
        获取指定平台缺少赔率数据的赛事

        Args:
            platform: 平台名称

        Returns:
            赛事信息列表
        """
        query = """
        SELECT mi.* FROM match_info mi
        LEFT JOIN odds_record or ON mi.match_id = or.match_id AND or.platform = ?
        WHERE or.record_id IS NULL
        ORDER BY mi.match_time
        """

        results = self._execute_query(query, (platform,))
        return [dict(row) for row in results]

    def get_arbitrage_opportunities(self, min_profit_rate: float = 2.0) -> List[Dict[str, Any]]:
        """
        获取套利机会

        Args:
            min_profit_rate: 最小利润率阈值

        Returns:
            套利机会列表
        """
        query = """
        SELECT
            mi.match_id,
            mi.league_name,
            mi.home_team,
            mi.away_team,
            mi.match_time,
            platform_a.home_win_odds as a_home_win,
            platform_a.away_win_odds as a_away_win,
            platform_b.home_win_odds as b_home_win,
            platform_b.away_win_odds as b_away_win,
            platform_a.collect_time as a_collect_time,
            platform_b.collect_time as b_collect_time
        FROM match_info mi
        INNER JOIN odds_record platform_a ON mi.match_id = platform_a.match_id
            AND platform_a.platform = 'platform_a'
        INNER JOIN odds_record platform_b ON mi.match_id = platform_b.match_id
            AND platform_b.platform = 'platform_b'
        WHERE mi.match_status IN ('未开始', '进行中')
        ORDER BY mi.match_time
        """

        results = self._execute_query(query)
        opportunities = []

        for row in results:
            row_dict = dict(row)
            # 计算套利机会（这里简化处理，实际需要更复杂的计算）
            arbitrage_data = self._calculate_arbitrage(row_dict)
            if arbitrage_data and arbitrage_data['profit_rate'] >= min_profit_rate:
                opportunities.append(arbitrage_data)

        return opportunities

    def _calculate_arbitrage(self, match_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        计算套利数据

        Args:
            match_data: 赛事数据

        Returns:
            套利数据字典
        """
        try:
            # 简化的套利计算，实际需要更复杂的数学模型
            a_home = match_data.get('a_home_win')
            b_away = match_data.get('b_away_win')

            if not a_home or not b_away:
                return None

            # 计算套利利润率
            implied_prob_a = 1 / a_home
            implied_prob_b = 1 / b_away
            total_prob = implied_prob_a + implied_prob_b

            if total_prob < 1:
                profit_rate = (1 - total_prob) / total_prob * 100
                return {
                    'match_id': match_data['match_id'],
                    'league_name': match_data['league_name'],
                    'home_team': match_data['home_team'],
                    'away_team': match_data['away_team'],
                    'profit_rate': round(profit_rate, 2),
                    'a_odds': a_home,
                    'b_odds': b_away
                }

        except Exception as e:
            self.logger.error(f"计算套利失败: {str(e)}")

        return None

    def export_to_json(self, filename: str) -> bool:
        """
        导出数据为JSON格式

        Args:
            filename: 导出文件名

        Returns:
            导出成功返回True，失败返回False
        """
        try:
            query = """
            SELECT
                mi.match_id, mi.league_name, mi.home_team, mi.away_team,
                mi.match_time, mi.match_status,
                or.platform, or.home_win_odds, or.draw_odds, or.away_win_odds,
                or.big_ball_odds, or.small_ball_odds, or.handicap, or.collect_time
            FROM match_info mi
            LEFT JOIN odds_record or ON mi.match_id = or.match_id
            ORDER BY mi.match_time DESC, or.collect_time DESC
            """

            results = self._execute_query(query)
            data = [dict(row) for row in results]

            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            self.logger.info(f"数据导出成功: {filename}")
            return True

        except Exception as e:
            self.logger.error(f"数据导出失败: {str(e)}")
            return False

    def cleanup_old_data(self, days: int = 30) -> int:
        """
        清理过期数据

        Args:
            days: 保留天数

        Returns:
            删除的记录数
        """
        try:
            cutoff_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # 删除过期的赔率记录
            query1 = """
            DELETE FROM odds_record
            WHERE collect_time < datetime('now', ? || ' days')
            """

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(query1, (f'-{days}',))
                deleted_count = cursor.rowcount
                conn.commit()

            self.logger.info(f"清理过期数据完成，删除 {deleted_count} 条记录")
            return deleted_count

        except Exception as e:
            self.logger.error(f"清理数据失败: {str(e)}")
            return 0