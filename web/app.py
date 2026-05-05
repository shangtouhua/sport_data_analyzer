"""
Web监控界面后端API
提供赔率数据、套利机会和系统状态的RESTful接口
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import threading
import time
import logging
from datetime import datetime
import json
import asyncio
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入项目模块
from main import OddsArbitrageTool
from utils import setup_logger


class WebMonitorAPI:
    """
    Web监控API服务
    提供实时赔率监控和套利机会展示
    """

    def __init__(self, config_path: str = "config/config.yaml"):
        """
        初始化Web API服务

        Args:
            config_path: 配置文件路径
        """
        self.config_path = config_path
        self.app = Flask(__name__)
        self.socketio = SocketIO(self.app, cors_allowed_origins="*", async_mode='threading')
        CORS(self.app)

        # 初始化套利工具
        self.tool = OddsArbitrageTool(config_path)

        # 设置日志
        self.logger = setup_logger('web', 'web_monitor', 'INFO')

        # 实时数据缓存
        self.latest_data = {
            'odds_data': [],
            'arbitrage_opportunities': [],
            'system_status': {},
            'last_update': None
        }

        # 数据更新线程
        self.update_thread = None
        self.running = False

        self._setup_routes()
        self._setup_socket_events()

    def _setup_routes(self):
        """设置API路由"""

        @self.app.route('/api/status', methods=['GET'])
        def get_system_status():
            """获取系统状态"""
            return jsonify({
                'status': 'running' if self.running else 'stopped',
                'last_update': self.latest_data['last_update'],
                'platforms': list(self.tool.spiders.keys()) if self.tool.spiders else [],
                'database_connected': self._check_database_connection(),
                'active_opportunities': len(self.latest_data['arbitrage_opportunities']),
                'timestamp': datetime.now().isoformat()
            })

        @self.app.route('/api/odds', methods=['GET'])
        def get_latest_odds():
            """获取最新赔率数据"""
            platform = request.args.get('platform')
            limit = request.args.get('limit', 50, type=int)

            odds_data = self._get_odds_from_db(platform, limit)
            return jsonify({
                'data': odds_data,
                'total': len(odds_data),
                'timestamp': datetime.now().isoformat()
            })

        @self.app.route('/api/arbitrage', methods=['GET'])
        def get_arbitrage_opportunities():
            """获取套利机会"""
            min_profit = request.args.get('min_profit', 2.0, type=float)

            opportunities = self._get_arbitrage_opportunities(min_profit)
            return jsonify({
                'opportunities': opportunities,
                'count': len(opportunities),
                'timestamp': datetime.now().isoformat()
            })

        @self.app.route('/api/matches', methods=['GET'])
        def get_matched_matches():
            """获取已匹配的比赛"""
            limit = request.args.get('limit', 20, type=int)

            matches = self._get_matched_matches(limit)
            return jsonify({
                'matches': matches,
                'total': len(matches),
                'timestamp': datetime.now().isoformat()
            })

        @self.app.route('/api/history', methods=['GET'])
        def get_odds_history():
            """获取赔率历史数据"""
            match_id = request.args.get('match_id', type=int)
            hours = request.args.get('hours', 24, type=int)

            if not match_id:
                return jsonify({'error': 'match_id is required'}), 400

            history = self._get_odds_history(match_id, hours)
            return jsonify({
                'match_id': match_id,
                'history': history,
                'timestamp': datetime.now().isoformat()
            })

        @self.app.route('/api/control', methods=['POST'])
        def control_monitoring():
            """控制监控服务"""
            data = request.get_json()
            action = data.get('action') if data else None

            if action == 'start':
                success = self.start_monitoring()
                return jsonify({'success': success, 'message': '监控已启动' if success else '启动失败'})
            elif action == 'stop':
                success = self.stop_monitoring()
                return jsonify({'success': success, 'message': '监控已停止' if success else '停止失败'})
            elif action == 'refresh':
                success = self.manual_refresh()
                return jsonify({'success': success, 'message': '数据刷新完成' if success else '刷新失败'})
            else:
                return jsonify({'error': '未知操作'}), 400

    def _setup_socket_events(self):
        """设置WebSocket事件"""

        @self.socketio.on('connect')
        def handle_connect():
            self.logger.info(f"客户端连接: {request.sid}")
            emit('system_status', {
                'status': 'running' if self.running else 'stopped',
                'last_update': self.latest_data['last_update']
            })

        @self.socketio.on('disconnect')
        def handle_disconnect():
            self.logger.info(f"客户端断开: {request.sid}")

        @self.socketio.on('request_update')
        def handle_update_request():
            """客户端请求数据更新"""
            self._broadcast_latest_data()

    def _check_database_connection(self) -> bool:
        """检查数据库连接"""
        try:
            if hasattr(self.tool, 'db_operator') and self.tool.db_operator:
                result = self.tool.db_operator._execute_query("SELECT 1")
                return len(result) > 0
            return False
        except:
            return False

    def _get_odds_from_db(self, platform: str = None, limit: int = 50) -> list:
        """从数据库获取赔率数据"""
        try:
            if not hasattr(self.tool, 'db_operator') or not self.tool.db_operator:
                return []

            query = """
            SELECT
                mi.match_id, mi.league_name, mi.home_team, mi.away_team,
                mi.match_time, mi.match_status,
                or.platform, or.home_win_odds, or.draw_odds, or.away_win_odds,
                or.big_ball_odds, or.small_ball_odds, or.handicap, or.collect_time
            FROM match_info mi
            INNER JOIN odds_record or ON mi.match_id = or.match_id
            WHERE mi.match_status IN ('未开始', '进行中')
            """

            if platform:
                query += f" AND or.platform = '{platform}'"

            query += " ORDER BY mi.match_time DESC, or.collect_time DESC LIMIT ?"

            results = self.tool.db_operator._execute_query(query, (limit,))

            return [
                {
                    'match_id': row[0],
                    'league_name': row[1],
                    'home_team': row[2],
                    'away_team': row[3],
                    'match_time': row[4],
                    'match_status': row[5],
                    'platform': row[6],
                    'home_win_odds': row[7],
                    'draw_odds': row[8],
                    'away_win_odds': row[9],
                    'big_ball_odds': row[10],
                    'small_ball_odds': row[11],
                    'handicap': row[12],
                    'collect_time': row[13]
                }
                for row in results
            ]

        except Exception as e:
            self.logger.error(f"获取赔率数据失败: {str(e)}")
            return []

    def _get_arbitrage_opportunities(self, min_profit: float = 2.0) -> list:
        """获取套利机会"""
        try:
            if not hasattr(self.tool, 'db_operator') or not self.tool.db_operator:
                return []

            # 从数据库获取最新的匹配比赛
            query = """
            SELECT DISTINCT mi.match_id, mi.league_name, mi.home_team, mi.away_team, mi.match_time
            FROM match_info mi
            INNER JOIN odds_record or1 ON mi.match_id = or1.match_id AND or1.platform = 'platform_a'
            INNER JOIN odds_record or2 ON mi.match_id = or2.match_id AND or2.platform = 'platform_b'
            WHERE mi.match_status IN ('未开始', '进行中')
            ORDER BY mi.match_time DESC
            """

            matches = self.tool.db_operator._execute_query(query)

            opportunities = []
            for match_row in matches:
                match_id = match_row[0]

                # 获取两个平台的最新赔率
                odds_query = """
                SELECT platform, home_win_odds, away_win_odds
                FROM odds_record
                WHERE match_id = ? AND platform IN ('platform_a', 'platform_b')
                ORDER BY collect_time DESC
                """

                odds_data = self.tool.db_operator._execute_query(odds_query, (match_id,))

                if len(odds_data) >= 2:
                    # 构建匹配对进行套利计算
                    platform_a_odds = next((row for row in odds_data if row[0] == 'platform_a'), None)
                    platform_b_odds = next((row for row in odds_data if row[0] == 'platform_b'), None)

                    if platform_a_odds and platform_b_odds:
                        match_pair = {
                            'platform_a': {
                                'home_win_odds': platform_a_odds[1],
                                'away_win_odds': platform_a_odds[2]
                            },
                            'platform_b': {
                                'home_win_odds': platform_b_odds[1],
                                'away_win_odds': platform_b_odds[2]
                            }
                        }

                        # 计算套利机会
                        opportunity = self.tool.arbitrage_calculator.calculate_arbitrage_opportunity(match_pair)
                        if opportunity and opportunity['profit_rate'] >= min_profit:
                            opportunity['match_info'] = {
                                'match_id': match_id,
                                'league_name': match_row[1],
                                'home_team': match_row[2],
                                'away_team': match_row[3],
                                'match_time': match_row[4]
                            }
                            opportunities.append(opportunity)

            return opportunities

        except Exception as e:
            self.logger.error(f"获取套利机会失败: {str(e)}")
            return []

    def _get_matched_matches(self, limit: int = 20) -> list:
        """获取已匹配的比赛"""
        try:
            if not hasattr(self.tool, 'db_operator') or not self.tool.db_operator:
                return []

            query = """
            SELECT DISTINCT mi.match_id, mi.league_name, mi.home_team, mi.away_team,
                   mi.match_time, mi.match_status
            FROM match_info mi
            INNER JOIN odds_record or1 ON mi.match_id = or1.match_id AND or1.platform = 'platform_a'
            INNER JOIN odds_record or2 ON mi.match_id = or2.match_id AND or2.platform = 'platform_b'
            ORDER BY mi.match_time DESC
            LIMIT ?
            """

            results = self.tool.db_operator._execute_query(query, (limit,))

            return [
                {
                    'match_id': row[0],
                    'league_name': row[1],
                    'home_team': row[2],
                    'away_team': row[3],
                    'match_time': row[4],
                    'match_status': row[5]
                }
                for row in results
            ]

        except Exception as e:
            self.logger.error(f"获取匹配比赛失败: {str(e)}")
            return []

    def _get_odds_history(self, match_id: int, hours: int = 24) -> list:
        """获取指定比赛的赔率历史"""
        try:
            if not hasattr(self.tool, 'db_operator') or not self.tool.db_operator:
                return []

            query = """
            SELECT platform, home_win_odds, draw_odds, away_win_odds,
                   big_ball_odds, small_ball_odds, handicap, collect_time
            FROM odds_record
            WHERE match_id = ? AND collect_time >= datetime('now', ? || ' hours')
            ORDER BY collect_time ASC
            """

            results = self.tool.db_operator._execute_query(query, (match_id, f'-{hours}'))

            return [
                {
                    'platform': row[0],
                    'home_win_odds': row[1],
                    'draw_odds': row[2],
                    'away_win_odds': row[3],
                    'big_ball_odds': row[4],
                    'small_ball_odds': row[5],
                    'handicap': row[6],
                    'collect_time': row[7]
                }
                for row in results
            ]

        except Exception as e:
            self.logger.error(f"获取赔率历史失败: {str(e)}")
            return []

    def _data_update_worker(self):
        """数据更新工作线程"""
        while self.running:
            try:
                # 执行单次数据采集周期
                result = asyncio.run(self.tool.run_single_cycle())

                # 更新缓存数据
                self.latest_data.update({
                    'odds_data': self._get_odds_from_db(limit=100),
                    'arbitrage_opportunities': self._get_arbitrage_opportunities(),
                    'system_status': {
                        'platform_a_matches': result.get('platform_a_matches', 0),
                        'platform_b_matches': result.get('platform_b_matches', 0),
                        'matched_pairs': result.get('matched_pairs', 0),
                        'arbitrage_opportunities': result.get('arbitrage_opportunities', 0)
                    },
                    'last_update': datetime.now().isoformat()
                })

                # 广播更新到所有连接的客户端
                self._broadcast_latest_data()

                # 等待下一次更新
                time.sleep(30)  # 30秒更新间隔

            except Exception as e:
                self.logger.error(f"数据更新失败: {str(e)}")
                time.sleep(10)

    def _broadcast_latest_data(self):
        """广播最新数据到所有客户端"""
        try:
            self.socketio.emit('data_update', self.latest_data)
        except Exception as e:
            self.logger.error(f"数据广播失败: {str(e)}")

    def start_monitoring(self) -> bool:
        """启动监控服务"""
        if self.running:
            return True

        try:
            self.running = True
            self.update_thread = threading.Thread(target=self._data_update_worker, daemon=True)
            self.update_thread.start()

            self.logger.info("监控服务已启动")
            return True

        except Exception as e:
            self.logger.error(f"启动监控服务失败: {str(e)}")
            self.running = False
            return False

    def stop_monitoring(self) -> bool:
        """停止监控服务"""
        try:
            self.running = False
            if self.update_thread:
                self.update_thread.join(timeout=5)

            self.logger.info("监控服务已停止")
            return True

        except Exception as e:
            self.logger.error(f"停止监控服务失败: {str(e)}")
            return False

    def manual_refresh(self) -> bool:
        """手动刷新数据"""
        try:
            result = asyncio.run(self.tool.run_single_cycle())

            # 更新缓存数据
            self.latest_data.update({
                'odds_data': self._get_odds_from_db(limit=100),
                'arbitrage_opportunities': self._get_arbitrage_opportunities(),
                'last_update': datetime.now().isoformat()
            })

            # 广播更新
            self._broadcast_latest_data()

            self.logger.info("手动数据刷新完成")
            return True

        except Exception as e:
            self.logger.error(f"手动刷新失败: {str(e)}")
            return False

    def run(self, host: str = '0.0.0.0', port: int = 5001, debug: bool = False):
        """启动Web服务"""
        self.logger.info(f"启动Web监控界面: http://{host}:{port}")

        # 启动监控服务
        self.start_monitoring()

        # 启动Flask应用
        self.socketio.run(self.app, host=host, port=port, debug=debug)


if __name__ == "__main__":
    # 创建并启动Web监控服务
    web_api = WebMonitorAPI()
    web_api.run(debug=True)