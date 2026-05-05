"""
多平台体育赛事赔率实时爬虫 + 跨平台赔率对比 + 对冲套利计算工具
主程序入口

说明：本工具仅用于技术学习、编程研究，不用于任何实际博彩投注、违规套利行为。
"""

import asyncio
import yaml
import logging
import sys
import os
from datetime import datetime
from typing import Dict, List, Any, Optional

# 导入项目模块
from spider import BaseSpider, PlatformAParser, PlatformBParser
from db import DatabaseInitializer, DatabaseOperator
from matcher import MatchCore
from arbitrage import ArbitrageCalculator
from utils import setup_logger, TimeUtils, StringUtils


class OddsArbitrageTool:
    """
    赔率套利工具主类
    整合爬虫、匹配、套利计算等功能
    """

    def __init__(self, config_path: str = "config/config.yaml"):
        """
        初始化工具

        Args:
            config_path: 配置文件路径
        """
        self.config_path = config_path
        self.config = self._load_config()
        self.logger = self._setup_logging()

        # 初始化组件
        self.db_initializer = None
        self.db_operator = None
        self.match_core = None
        self.arbitrage_calculator = None
        self.spiders = {}

        self._initialize_components()

    def _load_config(self) -> Dict[str, Any]:
        """
        加载配置文件

        Returns:
            配置字典
        """
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            return config
        except Exception as e:
            print(f"加载配置文件失败: {str(e)}")
            # 返回默认配置
            return self._get_default_config()

    def _get_default_config(self) -> Dict[str, Any]:
        """
        获取默认配置

        Returns:
            默认配置字典
        """
        return {
            'spider': {
                'polling_interval': 1,
                'min_delay': 0.5,
                'max_delay': 3.0,
                'max_retries': 3,
                'retry_delay': 1.0
            },
            'matching': {
                'similarity_threshold': 80,
                'time_tolerance': 5
            },
            'arbitrage': {
                'default_principal': 1000.0,
                'profit_threshold': 2.0,
                'odds_diff_threshold': 0.3
            },
            'database': {
                'db_path': 'data/odds_data.db',
                'data_retention_days': 30
            },
            'logging': {
                'level': 'INFO',
                'log_dir': 'log',
                'log_prefix': 'odds_spider'
            }
        }

    def _setup_logging(self) -> logging.Logger:
        """
        设置日志

        Returns:
            日志记录器
        """
        log_config = self.config.get('logging', {})
        log_dir = log_config.get('log_dir', 'log')
        log_prefix = log_config.get('log_prefix', 'odds_spider')
        level = log_config.get('level', 'INFO')

        return setup_logger(log_dir, log_prefix, level)

    def _initialize_components(self):
        """初始化各个组件"""
        try:
            # 初始化数据库
            db_config = self.config.get('database', {})
            self.db_initializer = DatabaseInitializer(db_config['db_path'], self.logger)
            self.db_operator = DatabaseOperator(db_config['db_path'], self.logger)

            # 初始化数据库表
            if not self.db_initializer.check_tables_exist():
                self.logger.info("初始化数据库表...")
                success = self.db_initializer.init_database()
                if success:
                    self.db_initializer.create_indexes()
                else:
                    self.logger.error("数据库初始化失败")
                    sys.exit(1)

            # 初始化匹配器
            matching_config = self.config.get('matching', {})
            self.match_core = MatchCore(matching_config, self.logger)

            # 初始化套利计算器
            arbitrage_config = self.config.get('arbitrage', {})
            self.arbitrage_calculator = ArbitrageCalculator(arbitrage_config, self.logger)

            # 初始化爬虫
            spider_config = self.config.get('spider', {})
            platforms_config = spider_config.get('platforms', {})

            self.spiders['platform_a'] = PlatformAParser(spider_config, self.logger)
            self.spiders['platform_b'] = PlatformBParser(spider_config, self.logger)

            self.logger.info("组件初始化完成")

        except Exception as e:
            self.logger.error(f"组件初始化失败: {str(e)}")
            sys.exit(1)

    async def crawl_platform_data(self, platform_name: str) -> List[Dict[str, Any]]:
        """
        爬取指定平台的数据

        Args:
            platform_name: 平台名称

        Returns:
            赛事数据列表
        """
        if platform_name not in self.spiders:
            self.logger.error(f"未知平台: {platform_name}")
            return []

        spider = self.spiders[platform_name]
        platforms_config = self.config.get('spider', {}).get('platforms', {})

        if platform_name not in platforms_config:
            self.logger.error(f"平台配置缺失: {platform_name}")
            return []

        platform_config = platforms_config[platform_name]

        try:
            async with spider:
                matches = await spider.crawl_matches(platform_config)
                return matches
        except Exception as e:
            self.logger.error(f"爬取平台 {platform_name} 数据失败: {str(e)}")
            return []

    def save_matches_to_db(self, matches: List[Dict[str, Any]]) -> int:
        """
        保存赛事数据到数据库

        Args:
            matches: 赛事数据列表

        Returns:
            成功保存的记录数
        """
        saved_count = 0

        for match_data in matches:
            try:
                # 保存赛事基础信息
                match_info = {
                    'league_name': match_data.get('league_name', ''),
                    'home_team': match_data.get('home_team', ''),
                    'away_team': match_data.get('away_team', ''),
                    'match_time': match_data.get('match_time', ''),
                    'match_status': match_data.get('match_status', '')
                }

                match_id = self.db_operator.insert_match_info(match_info)
                if match_id:
                    # 保存赔率记录
                    odds_data = {
                        'platform': match_data.get('platform', ''),
                        'home_win_odds': match_data.get('home_win_odds'),
                        'draw_odds': match_data.get('draw_odds'),
                        'away_win_odds': match_data.get('away_win_odds'),
                        'big_ball_odds': match_data.get('big_ball_odds'),
                        'small_ball_odds': match_data.get('small_ball_odds'),
                        'handicap': match_data.get('handicap'),
                        'collect_time': match_data.get('collect_time', TimeUtils.get_current_timestamp())
                    }

                    if self.db_operator.insert_odds_record(match_id, odds_data):
                        saved_count += 1

            except Exception as e:
                self.logger.error(f"保存赛事数据失败: {str(e)}")

        return saved_count

    async def run_single_cycle(self) -> Dict[str, Any]:
        """
        运行单个采集周期

        Returns:
            运行结果统计
        """
        self.logger.info("开始新的数据采集周期")

        # 爬取两个平台的数据
        platform_a_matches = await self.crawl_platform_data('platform_a')
        platform_b_matches = await self.crawl_platform_data('platform_b')

        # 保存数据到数据库
        saved_a = self.save_matches_to_db(platform_a_matches)
        saved_b = self.save_matches_to_db(platform_b_matches)

        # 匹配赛事
        match_result = self.match_core.match_matches(platform_a_matches, platform_b_matches)

        # 计算套利机会
        arbitrage_opportunities = []
        for match_pair in match_result['matched_pairs']:
            # 验证匹配结果
            if self.match_core.validate_match_result(match_pair):
                opportunity = self.arbitrage_calculator.calculate_arbitrage_opportunity(match_pair)
                if opportunity:
                    arbitrage_opportunities.append(opportunity)

        # 统计结果
        result = {
            'timestamp': TimeUtils.get_current_timestamp(),
            'platform_a_matches': len(platform_a_matches),
            'platform_b_matches': len(platform_b_matches),
            'saved_a_records': saved_a,
            'saved_b_records': saved_b,
            'matched_pairs': len(match_result['matched_pairs']),
            'unmatched_a': len(match_result['unmatched_a']),
            'unmatched_b': len(match_result['unmatched_b']),
            'arbitrage_opportunities': len(arbitrage_opportunities),
            'opportunities': arbitrage_opportunities
        }

        self.logger.info(f"采集周期完成: 发现 {len(arbitrage_opportunities)} 个套利机会")

        return result

    async def run_continuous(self):
        """
        运行连续采集模式
        """
        polling_interval = self.config.get('spider', {}).get('polling_interval', 1)

        self.logger.info(f"启动连续采集模式，轮询间隔: {polling_interval} 分钟")

        try:
            while True:
                start_time = datetime.now()

                # 运行单个周期
                result = await self.run_single_cycle()

                # 输出统计信息
                self._print_cycle_summary(result)

                # 计算等待时间
                elapsed = (datetime.now() - start_time).total_seconds()
                wait_time = max(0, polling_interval * 60 - elapsed)

                if wait_time > 0:
                    self.logger.info(f"等待 {wait_time:.1f} 秒后开始下一轮采集...")
                    await asyncio.sleep(wait_time)

        except KeyboardInterrupt:
            self.logger.info("接收到中断信号，停止采集")
        except Exception as e:
            self.logger.error(f"连续采集运行失败: {str(e)}")

    def _print_cycle_summary(self, result: Dict[str, Any]):
        """
        打印周期摘要

        Args:
            result: 运行结果
        """
        summary = f"""
=== 采集周期摘要 ===
时间: {result['timestamp']}
平台A赛事: {result['platform_a_matches']} 场
平台B赛事: {result['platform_b_matches']} 场
保存记录: A平台 {result['saved_a_records']} 条, B平台 {result['saved_b_records']} 条
匹配成功: {result['matched_pairs']} 对
未匹配: A平台 {result['unmatched_a']} 场, B平台 {result['unmatched_b']} 场
套利机会: {result['arbitrage_opportunities']} 个
===================
        """.strip()

        print(summary)

        # 输出套利机会详情
        if result['opportunities']:
            print("\n套利机会详情:")
            for i, opp in enumerate(result['opportunities'][:5], 1):  # 最多显示5个
                match_info = opp['match_info']
                print(f"{i}. {match_info['league_name']} - {match_info['home_team']} vs {match_info['away_team']}")
                print(f"   类型: {opp['bet_type']}, 利润率: {opp['profit_rate']:.2f}%")
                print(f"   投注方案: {StringUtils.format_currency(opp['bet1_amount'])} @ {opp['bet1_odds']} vs "
                      f"{StringUtils.format_currency(opp['bet2_amount'])} @ {opp['bet2_odds']}")
                print()

    def export_data(self, format_type: str = "json") -> bool:
        """
        导出数据

        Args:
            format_type: 导出格式 (json/csv)

        Returns:
            导出成功返回True，失败返回False
        """
        export_config = self.config.get('export', {})
        export_dir = export_config.get('export_dir', 'data')

        if not os.path.exists(export_dir):
            os.makedirs(export_dir)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = os.path.join(export_dir, f"odds_data_{timestamp}.{format_type}")

        if format_type.lower() == "json":
            return self.db_operator.export_to_json(filename)
        else:
            self.logger.error(f"不支持的导出格式: {format_type}")
            return False

    def cleanup_data(self):
        """清理过期数据"""
        db_config = self.config.get('database', {})
        retention_days = db_config.get('data_retention_days', 30)

        self.logger.info(f"清理 {retention_days} 天前的数据...")
        deleted_count = self.db_operator.cleanup_old_data(retention_days)
        self.logger.info(f"清理完成，删除 {deleted_count} 条记录")


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="多平台赔率套利工具")
    parser.add_argument('--config', default='config/config.yaml', help='配置文件路径')
    parser.add_argument('--mode', choices=['single', 'continuous', 'export', 'cleanup'],
                       default='single', help='运行模式')
    parser.add_argument('--format', choices=['json', 'csv'], default='json', help='导出格式')

    args = parser.parse_args()

    # 创建工具实例
    tool = OddsArbitrageTool(args.config)

    # 根据模式运行
    if args.mode == 'single':
        asyncio.run(tool.run_single_cycle())
    elif args.mode == 'continuous':
        asyncio.run(tool.run_continuous())
    elif args.mode == 'export':
        tool.export_data(args.format)
    elif args.mode == 'cleanup':
        tool.cleanup_data()


if __name__ == "__main__":
    main()