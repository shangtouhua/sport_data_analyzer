"""
对冲套利计算模块
实现跨平台对冲套利的数学模型和计算逻辑
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
from decimal import Decimal, getcontext
import math

# 设置高精度计算
getcontext().prec = 10

class ArbitrageCalculator:
    """
    对冲套利计算器
    实现标准的跨平台对冲套利数学公式和计算逻辑
    """

    def __init__(self, config: Dict[str, Any], logger: logging.Logger):
        """
        初始化套利计算器

        Args:
            config: 配置字典
            logger: 日志记录器
        """
        self.config = config
        self.logger = logger
        self.default_principal = Decimal(str(config.get('default_principal', 1000.0)))
        self.profit_threshold = Decimal(str(config.get('profit_threshold', 2.0)))
        self.odds_diff_threshold = Decimal(str(config.get('odds_diff_threshold', 0.3)))

    def calculate_implied_probability(self, odds: float) -> Decimal:
        """
        计算隐含概率

        Args:
            odds: 赔率

        Returns:
            隐含概率
        """
        if not odds or odds <= 1:
            return Decimal('0')

        return Decimal('1') / Decimal(str(odds))

    def calculate_payout_rate(self, home_odds: float, draw_odds: float, away_odds: float) -> Decimal:
        """
        计算赔付率

        Args:
            home_odds: 主胜赔率
            draw_odds: 平局赔率
            away_odds: 客胜赔率

        Returns:
            赔付率
        """
        home_prob = self.calculate_implied_probability(home_odds)
        draw_prob = self.calculate_implied_probability(draw_odds)
        away_prob = self.calculate_implied_probability(away_odds)

        total_prob = home_prob + draw_prob + away_prob

        if total_prob == 0:
            return Decimal('0')

        return Decimal('1') / total_prob

    def calculate_arbitrage_opportunity(self, match_pair: Dict[str, Any],
                                       principal: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """
        计算套利机会

        Args:
            match_pair: 匹配的赛事对
            principal: 总投入本金，如果为None则使用默认值

        Returns:
            套利机会数据，无套利机会返回None
        """
        if principal is None:
            principal = self.default_principal
        else:
            principal = Decimal(str(principal))

        platform_a = match_pair['platform_a']
        platform_b = match_pair['platform_b']

        # 检查是否有有效的赔率数据
        if not self._has_valid_odds(platform_a) or not self._has_valid_odds(platform_b):
            return None

        # 计算胜平负套利机会
        opportunities = []

        # 主胜-客胜套利
        if platform_a.get('home_win_odds') and platform_b.get('away_win_odds'):
            opp = self._calculate_two_way_arbitrage(
                principal,
                platform_a['home_win_odds'],
                platform_b['away_win_odds'],
                'home_away'
            )
            if opp:
                opportunities.append(opp)

        # 主胜-平局套利
        if platform_a.get('home_win_odds') and platform_b.get('draw_odds'):
            opp = self._calculate_two_way_arbitrage(
                principal,
                platform_a['home_win_odds'],
                platform_b['draw_odds'],
                'home_draw'
            )
            if opp:
                opportunities.append(opp)

        # 平局-客胜套利
        if platform_a.get('draw_odds') and platform_b.get('away_win_odds'):
            opp = self._calculate_two_way_arbitrage(
                principal,
                platform_a['draw_odds'],
                platform_b['away_win_odds'],
                'draw_away'
            )
            if opp:
                opportunities.append(opp)

        # 大小球套利
        if (platform_a.get('big_ball_odds') and platform_b.get('small_ball_odds')):
            opp = self._calculate_two_way_arbitrage(
                principal,
                platform_a['big_ball_odds'],
                platform_b['small_ball_odds'],
                'big_small'
            )
            if opp:
                opportunities.append(opp)

        if not opportunities:
            return None

        # 返回最佳套利机会
        best_opportunity = max(opportunities, key=lambda x: x['profit_rate'])

        # 检查是否达到阈值
        if best_opportunity['profit_rate'] < self.profit_threshold:
            return None

        # 添加赛事信息
        best_opportunity.update({
            'match_info': {
                'league_name': platform_a.get('league_name'),
                'home_team': platform_a.get('home_team'),
                'away_team': platform_a.get('away_team'),
                'match_time': platform_a.get('match_time'),
                'match_status': platform_a.get('match_status')
            },
            'platform_a_info': platform_a,
            'platform_b_info': platform_b
        })

        self.logger.info(f"发现套利机会: {best_opportunity['match_info']['home_team']} vs "
                        f"{best_opportunity['match_info']['away_team']}, "
                        f"利润率: {best_opportunity['profit_rate']:.2f}%")

        return best_opportunity

    def _calculate_two_way_arbitrage(self, principal: Decimal, odds1: float, odds2: float,
                                   bet_type: str) -> Optional[Dict[str, Any]]:
        """
        计算双向套利机会

        Args:
            principal: 总投入本金
            odds1: 赔率1
            odds2: 赔率2
            bet_type: 投注类型

        Returns:
            套利数据，无套利机会返回None
        """
        if not odds1 or not odds2 or odds1 <= 1 or odds2 <= 1:
            return None

        odds1_decimal = Decimal(str(odds1))
        odds2_decimal = Decimal(str(odds2))

        # 计算隐含概率
        prob1 = Decimal('1') / odds1_decimal
        prob2 = Decimal('1') / odds2_decimal

        # 检查是否存在套利空间
        if prob1 + prob2 >= Decimal('1'):
            return None

        # 计算最优投注分配
        # 设投注1金额为x，投注2金额为principal - x
        # x * odds1 = (principal - x) * odds2
        # x = principal * odds2 / (odds1 + odds2)

        bet1_amount = (principal * odds2_decimal) / (odds1_decimal + odds2_decimal)
        bet2_amount = principal - bet1_amount

        # 计算固定收益
        fixed_return = bet1_amount * odds1_decimal
        fixed_profit = fixed_return - principal
        profit_rate = (fixed_profit / principal) * Decimal('100')

        # 计算赔率差异
        odds_diff = abs(odds1_decimal - odds2_decimal)

        # 检查赔率差异阈值
        if odds_diff < self.odds_diff_threshold:
            return None

        return {
            'bet_type': bet_type,
            'total_principal': float(principal),
            'bet1_amount': float(bet1_amount),
            'bet2_amount': float(bet2_amount),
            'bet1_odds': float(odds1_decimal),
            'bet2_odds': float(odds2_decimal),
            'fixed_return': float(fixed_return),
            'fixed_profit': float(fixed_profit),
            'profit_rate': float(profit_rate),
            'odds_difference': float(odds_diff),
            'breakeven_threshold': self._calculate_breakeven_threshold(odds1_decimal, odds2_decimal)
        }

    def _calculate_breakeven_threshold(self, odds1: Decimal, odds2: Decimal) -> Dict[str, float]:
        """
        计算保本临界点

        Args:
            odds1: 赔率1
            odds2: 赔率2

        Returns:
            保本临界点数据
        """
        # 当其中一个赔率变动到临界值时，套利机会消失
        # prob1 + prob2 = 1
        # 1/odds1_new + 1/odds2 = 1
        # odds1_new = 1 / (1 - 1/odds2)

        critical_odds1 = Decimal('1') / (Decimal('1') - (Decimal('1') / odds2))
        critical_odds2 = Decimal('1') / (Decimal('1') - (Decimal('1') / odds1))

        return {
            'critical_odds1': float(critical_odds1),
            'critical_odds2': float(critical_odds2),
            'current_odds1': float(odds1),
            'current_odds2': float(odds2)
        }

    def _has_valid_odds(self, match_data: Dict[str, Any]) -> bool:
        """
        检查赛事是否有有效的赔率数据

        Args:
            match_data: 赛事数据

        Returns:
            有有效赔率返回True，否则返回False
        """
        required_odds = [
            'home_win_odds', 'draw_odds', 'away_win_odds',
            'big_ball_odds', 'small_ball_odds'
        ]

        for odds_field in required_odds:
            odds = match_data.get(odds_field)
            if odds and odds > 1:
                return True

        return False

    def calculate_portfolio_arbitrage(self, opportunities: List[Dict[str, Any]],
                                    total_capital: float) -> Dict[str, Any]:
        """
        计算投资组合套利策略

        Args:
            opportunities: 套利机会列表
            total_capital: 总投资本金

        Returns:
            投资组合策略
        """
        if not opportunities:
            return {}

        # 按利润率排序
        sorted_opportunities = sorted(opportunities, key=lambda x: x['profit_rate'], reverse=True)

        # 简单的等权重分配策略
        capital_per_opportunity = Decimal(str(total_capital)) / Decimal(str(len(sorted_opportunities)))

        portfolio = {
            'total_capital': total_capital,
            'opportunity_count': len(sorted_opportunities),
            'capital_per_opportunity': float(capital_per_opportunity),
            'allocations': [],
            'expected_total_profit': 0,
            'expected_profit_rate': 0
        }

        total_profit = Decimal('0')

        for opportunity in sorted_opportunities:
            allocation = {
                'match_info': opportunity['match_info'],
                'bet_type': opportunity['bet_type'],
                'allocated_capital': float(capital_per_opportunity),
                'bet1_amount': (capital_per_opportunity * Decimal(str(opportunity['bet1_amount']))) / Decimal(str(opportunity['total_principal'])),
                'bet2_amount': (capital_per_opportunity * Decimal(str(opportunity['bet2_amount']))) / Decimal(str(opportunity['total_principal'])),
                'expected_profit': (capital_per_opportunity * Decimal(str(opportunity['fixed_profit']))) / Decimal(str(opportunity['total_principal']))
            }
            allocation['bet1_amount'] = float(allocation['bet1_amount'])
            allocation['bet2_amount'] = float(allocation['bet2_amount'])
            allocation['expected_profit'] = float(allocation['expected_profit'])

            portfolio['allocations'].append(allocation)
            total_profit += Decimal(str(allocation['expected_profit']))

        portfolio['expected_total_profit'] = float(total_profit)
        portfolio['expected_profit_rate'] = float(total_profit / Decimal(str(total_capital)) * Decimal('100'))

        return portfolio

    def validate_arbitrage_data(self, opportunity: Dict[str, Any]) -> bool:
        """
        验证套利数据的有效性

        Args:
            opportunity: 套利机会数据

        Returns:
            有效返回True，无效返回False
        """
        required_fields = [
            'bet_type', 'total_principal', 'bet1_amount', 'bet2_amount',
            'profit_rate', 'fixed_profit'
        ]

        for field in required_fields:
            if field not in opportunity:
                return False

        # 验证基本逻辑
        if opportunity['bet1_amount'] + opportunity['bet2_amount'] != opportunity['total_principal']:
            return False

        if opportunity['profit_rate'] < 0:
            return False

        if opportunity['fixed_profit'] < 0:
            return False

        return True