"""
时间处理工具类
提供时间格式转换、时间计算等功能
"""

from datetime import datetime, timedelta
import re
from typing import Optional, Union


class TimeUtils:
    """
    时间处理工具类
    封装常用的时间处理功能
    """

    @staticmethod
    def parse_datetime(time_str: str) -> Optional[datetime]:
        """
        解析时间字符串

        Args:
            time_str: 时间字符串

        Returns:
            datetime对象，解析失败返回None
        """
        if not time_str:
            return None

        # 常见的时间格式
        formats = [
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d %H:%M',
            '%Y/%m/%d %H:%M:%S',
            '%Y/%m/%d %H:%M',
            '%Y-%m-%dT%H:%M:%S.%fZ',
            '%Y-%m-%dT%H:%M:%S.%f',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M',
            '%d/%m/%Y %H:%M',
            '%m/%d/%Y %H:%M'
        ]

        for fmt in formats:
            try:
                return datetime.strptime(time_str.strip(), fmt)
            except ValueError:
                continue

        # 尝试解析相对时间
        relative_match = re.match(r'(\d+)\s*(分钟|小时|天|分钟|hour|hours|day|days)前', time_str)
        if relative_match:
            value = int(relative_match.group(1))
            unit = relative_match.group(2)

            if '分钟' in unit or 'minute' in unit:
                return datetime.now() - timedelta(minutes=value)
            elif '小时' in unit or 'hour' in unit:
                return datetime.now() - timedelta(hours=value)
            elif '天' in unit or 'day' in unit:
                return datetime.now() - timedelta(days=value)

        return None

    @staticmethod
    def format_datetime(dt: datetime, fmt: str = '%Y-%m-%d %H:%M:%S') -> str:
        """
        格式化datetime对象

        Args:
            dt: datetime对象
            fmt: 格式字符串

        Returns:
            格式化后的时间字符串
        """
        if not dt:
            return ''
        return dt.strftime(fmt)

    @staticmethod
    def get_time_difference(time1: Union[str, datetime], time2: Union[str, datetime]) -> Optional[timedelta]:
        """
        计算两个时间的差值

        Args:
            time1: 时间1
            time2: 时间2

        Returns:
            时间差，计算失败返回None
        """
        if isinstance(time1, str):
            dt1 = TimeUtils.parse_datetime(time1)
        else:
            dt1 = time1

        if isinstance(time2, str):
            dt2 = TimeUtils.parse_datetime(time2)
        else:
            dt2 = time2

        if not dt1 or not dt2:
            return None

        return abs(dt1 - dt2)

    @staticmethod
    def is_time_in_range(check_time: Union[str, datetime], start_time: Union[str, datetime],
                        end_time: Union[str, datetime]) -> bool:
        """
        检查时间是否在指定范围内

        Args:
            check_time: 待检查时间
            start_time: 开始时间
            end_time: 结束时间

        Returns:
            在范围内返回True，否则返回False
        """
        if isinstance(check_time, str):
            dt_check = TimeUtils.parse_datetime(check_time)
        else:
            dt_check = check_time

        if isinstance(start_time, str):
            dt_start = TimeUtils.parse_datetime(start_time)
        else:
            dt_start = start_time

        if isinstance(end_time, str):
            dt_end = TimeUtils.parse_datetime(end_time)
        else:
            dt_end = end_time

        if not dt_check or not dt_start or not dt_end:
            return False

        return dt_start <= dt_check <= dt_end

    @staticmethod
    def get_current_timestamp() -> str:
        """
        获取当前时间戳

        Returns:
            当前时间戳字符串
        """
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    @staticmethod
    def add_time(dt: datetime, **kwargs) -> datetime:
        """
        在指定时间上添加时间

        Args:
            dt: 基础时间
            **kwargs: timedelta参数（days, hours, minutes, seconds）

        Returns:
            计算后的时间
        """
        return dt + timedelta(**kwargs)

    @staticmethod
    def subtract_time(dt: datetime, **kwargs) -> datetime:
        """
        从指定时间减去时间

        Args:
            dt: 基础时间
            **kwargs: timedelta参数（days, hours, minutes, seconds）

        Returns:
            计算后的时间
        """
        return dt - timedelta(**kwargs)

    @staticmethod
    def is_weekend(dt: datetime) -> bool:
        """
        判断是否为周末

        Args:
            dt: 时间

        Returns:
            是周末返回True，否则返回False
        """
        return dt.weekday() >= 5

    @staticmethod
    def get_next_weekday(dt: datetime, weekday: int) -> datetime:
        """
        获取下一个指定星期几的日期

        Args:
            dt: 基础时间
            weekday: 星期几（0=周一，6=周日）

        Returns:
            下一个指定星期几的日期
        """
        days_ahead = weekday - dt.weekday()
        if days_ahead <= 0:  # 目标日期已经过去
            days_ahead += 7
        return dt + timedelta(days=days_ahead)

    @staticmethod
    def convert_timezone(dt: datetime, from_tz: str, to_tz: str) -> datetime:
        """
        转换时区（简化实现）

        Args:
            dt: 时间
            from_tz: 源时区
            to_tz: 目标时区

        Returns:
            转换后的时间
        """
        # 简化实现，实际使用时需要pytz库
        timezone_offsets = {
            'UTC': 0,
            'CST': 8,  # 中国标准时间
            'EST': -5,  # 美国东部时间
            'PST': -8,  # 美国太平洋时间
        }

        from_offset = timezone_offsets.get(from_tz, 0)
        to_offset = timezone_offsets.get(to_tz, 0)

        offset_diff = to_offset - from_offset
        return dt + timedelta(hours=offset_diff)