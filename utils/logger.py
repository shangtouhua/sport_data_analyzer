"""
日志工具模块
封装Python logging标准库，提供统一的日志接口
"""

import logging
import os
from datetime import datetime
from typing import Optional


def setup_logger(log_dir: str, log_prefix: str, level: str = "INFO") -> logging.Logger:
    """
    设置日志记录器

    Args:
        log_dir: 日志目录
        log_prefix: 日志文件前缀
        level: 日志级别

    Returns:
        配置好的日志记录器
    """
    # 确保日志目录存在
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # 创建日志记录器
    logger = logging.getLogger(log_prefix)
    logger.setLevel(getattr(logging, level.upper()))

    # 避免重复添加处理器
    if logger.handlers:
        return logger

    # 创建格式化器
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 创建控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(getattr(logging, level.upper()))

    # 创建文件处理器
    log_filename = f"{log_prefix}_{datetime.now().strftime('%Y%m%d')}.log"
    log_filepath = os.path.join(log_dir, log_filename)

    file_handler = logging.FileHandler(log_filepath, encoding='utf-8')
    file_handler.setFormatter(formatter)
    file_handler.setLevel(getattr(logging, level.upper()))

    # 添加处理器
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger


class LoggerManager:
    """
    日志管理器
    提供统一的日志管理接口
    """

    def __init__(self, config: dict):
        """
        初始化日志管理器

        Args:
            config: 配置字典
        """
        self.config = config
        self.loggers = {}

    def get_logger(self, name: str) -> logging.Logger:
        """
        获取日志记录器

        Args:
            name: 日志器名称

        Returns:
            日志记录器
        """
        if name in self.loggers:
            return self.loggers[name]

        log_dir = self.config.get('log_dir', 'log')
        log_prefix = self.config.get('log_prefix', 'odds_spider')
        level = self.config.get('level', 'INFO')

        logger = setup_logger(log_dir, f"{log_prefix}_{name}", level)
        self.loggers[name] = logger

        return logger

    def cleanup_old_logs(self, days: int = 30):
        """
        清理过期日志文件

        Args:
            days: 保留天数
        """
        log_dir = self.config.get('log_dir', 'log')
        if not os.path.exists(log_dir):
            return

        cutoff_time = datetime.now().timestamp() - (days * 24 * 60 * 60)

        for filename in os.listdir(log_dir):
            filepath = os.path.join(log_dir, filename)
            if os.path.isfile(filepath):
                file_time = os.path.getctime(filepath)
                if file_time < cutoff_time:
                    try:
                        os.remove(filepath)
                        print(f"删除过期日志文件: {filepath}")
                    except Exception as e:
                        print(f"删除日志文件失败: {filepath}, 错误: {str(e)}")