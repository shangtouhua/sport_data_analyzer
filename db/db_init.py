"""
数据库初始化模块
创建和管理SQLite数据库表结构
"""

import sqlite3
import logging
from typing import Optional
import os

class DatabaseInitializer:
    """
    数据库初始化器
    负责创建和维护数据库表结构
    """

    def __init__(self, db_path: str, logger: logging.Logger):
        """
        初始化数据库

        Args:
            db_path: 数据库文件路径
            logger: 日志记录器
        """
        self.db_path = db_path
        self.logger = logger
        self._ensure_directory()

    def _ensure_directory(self):
        """确保数据库目录存在"""
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
            self.logger.info(f"创建数据库目录: {db_dir}")

    def init_database(self) -> bool:
        """
        初始化数据库，创建必要的表

        Returns:
            初始化成功返回True，失败返回False
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # 创建赛事基础信息表
                self._create_match_info_table(cursor)

                # 创建赔率历史记录表
                self._create_odds_record_table(cursor)

                # 创建未匹配赛事表
                self._create_unmatched_matches_table(cursor)

                # 创建套利历史记录表
                self._create_arbitrage_history_table(cursor)

                conn.commit()
                self.logger.info("数据库初始化成功")
                return True

        except Exception as e:
            self.logger.error(f"数据库初始化失败: {str(e)}")
            return False

    def _create_match_info_table(self, cursor: sqlite3.Cursor):
        """
        创建赛事基础信息表

        Args:
            cursor: 数据库游标
        """
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS match_info (
            match_id INTEGER PRIMARY KEY AUTOINCREMENT,
            league_name TEXT NOT NULL,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            match_time TEXT NOT NULL,
            match_status TEXT NOT NULL,
            create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(league_name, home_team, away_team, match_time)
        )
        """

        cursor.execute(create_table_sql)
        self.logger.debug("创建match_info表")

    def _create_odds_record_table(self, cursor: sqlite3.Cursor):
        """
        创建赔率历史记录表

        Args:
            cursor: 数据库游标
        """
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS odds_record (
            record_id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER NOT NULL,
            platform TEXT NOT NULL,
            home_win_odds REAL,
            draw_odds REAL,
            away_win_odds REAL,
            big_ball_odds REAL,
            small_ball_odds REAL,
            handicap REAL,
            collect_time TIMESTAMP NOT NULL,
            FOREIGN KEY (match_id) REFERENCES match_info (match_id),
            UNIQUE(match_id, platform, collect_time)
        )
        """

        cursor.execute(create_table_sql)
        self.logger.debug("创建odds_record表")

    def _create_unmatched_matches_table(self, cursor):
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS unmatched_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            league_name TEXT NOT NULL,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            match_time TEXT NOT NULL,
            match_status TEXT NOT NULL,
            record_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

    def _create_arbitrage_history_table(self, cursor):
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS arbitrage_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER,
            bet_type TEXT NOT NULL,
            total_principal REAL,
            bet1_amount REAL,
            bet2_amount REAL,
            bet1_odds REAL,
            bet2_odds REAL,
            fixed_profit REAL,
            profit_rate REAL,
            odds_difference REAL,
            record_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

    def create_indexes(self) -> bool:
        """
        创建数据库索引，提高查询性能

        Returns:
            创建成功返回True，失败返回False
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # 为match_info表创建索引
                cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_match_info_teams
                ON match_info (home_team, away_team)
                """)

                cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_match_info_time
                ON match_info (match_time)
                """)

                # 为odds_record表创建索引
                cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_odds_record_match_platform
                ON odds_record (match_id, platform)
                """)

                cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_odds_record_collect_time
                ON odds_record (collect_time)
                """)

                conn.commit()
                self.logger.info("数据库索引创建成功")
                return True

        except Exception as e:
            self.logger.error(f"创建数据库索引失败: {str(e)}")
            return False

    def check_tables_exist(self) -> bool:
        """
        检查必要的表是否存在

        Returns:
            表存在返回True，否则返回False
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # 检查match_info表
                cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='match_info'
                """)
                if not cursor.fetchone():
                    return False

                # 检查odds_record表
                cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='odds_record'
                """)
                if not cursor.fetchone():
                    return False

                return True

        except Exception as e:
            self.logger.error(f"检查表存在性失败: {str(e)}")
            return False

    def get_table_info(self) -> dict:
        """
        获取数据库表结构信息

        Returns:
            包含表结构信息的字典
        """
        table_info = {}
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                # 获取所有表名
                cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' ORDER BY name
                """)

                tables = cursor.fetchall()
                for table in tables:
                    table_name = table[0]

                    # 获取表结构
                    cursor.execute(f"PRAGMA table_info({table_name})")
                    columns = cursor.fetchall()

                    table_info[table_name] = [
                        {
                            'cid': col[0],
                            'name': col[1],
                            'type': col[2],
                            'notnull': col[3],
                            'dflt_value': col[4],
                            'pk': col[5]
                        }
                        for col in columns
                    ]

        except Exception as e:
            self.logger.error(f"获取表信息失败: {str(e)}")

        return table_info