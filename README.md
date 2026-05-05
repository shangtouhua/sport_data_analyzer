# 多平台体育赛事赔率实时爬虫 + 跨平台赔率对比 + 对冲套利计算工具

## ⚠️ 重要声明

**本工具仅用于技术学习、编程研究，不用于任何实际博彩投注、违规套利行为。开发过程严格遵守合规要求，禁止涉及任何自动下单、绕过平台风控的功能。**

## 📋 项目概述

本项目是一个多平台体育赛事赔率实时爬虫工具，具备以下核心功能：

1. **实时数据爬取**：支持2个不同赛事赔率平台的实时数据爬取
2. **跨平台对比**：自动匹配两个平台的同一场体育赛事，完成赔率横向对比分析
3. **对冲套利计算**：内置对冲套利数学模型，自动计算最优投注分配方案
4. **数据持久化**：本地SQLite数据库存储，支持历史数据回溯
5. **模块化设计**：代码结构清晰，便于扩展新平台

## 🏗️ 项目结构

```
odds_arbitrage_tool/          # 项目根目录
├── spider/                   # 爬虫模块
│   ├── __init__.py
│   ├── base_spider.py        # 通用爬虫基类
│   ├── platform_a_parser.py  # 平台A解析器
│   └── platform_b_parser.py  # 平台B解析器
├── db/                       # 数据库模块
│   ├── __init__.py
│   ├── db_init.py            # 数据库初始化
│   └── db_operate.py         # 数据库操作
├── matcher/                  # 赛事匹配模块
│   ├── __init__.py
│   └── match_core.py         # 匹配算法核心
├── arbitrage/                # 套利计算模块
│   ├── __init__.py
│   └── arbitrage_calc.py     # 套利计算逻辑
├── config/                   # 配置模块
│   ├── __init__.py
│   └── config.yaml           # 配置文件
├── utils/                    # 工具类模块
│   ├── __init__.py
│   ├── logger.py             # 日志封装
│   ├── time_utils.py         # 时间处理工具
│   └── str_utils.py          # 字符串处理工具
├── log/                      # 日志存储目录
├── data/                     # 数据导出目录
├── main.py                   # 程序入口
├── requirements.txt          # 依赖包列表
└── README.md                 # 使用说明
```

## 🚀 快速开始

### 环境要求

- Python 3.10+
- 支持Windows、macOS、Linux

### 安装步骤

1. **克隆项目**
```bash
git clone <项目地址>
cd sport_data_analyzer
```

2. **安装依赖**
```bash
pip install -r requirements.txt
```

3. **配置平台信息**
编辑 `config/config.yaml` 文件，配置目标平台的URL和解析参数：
```yaml
spider:
  platforms:
    platform_a:
      name: "平台A"
      base_url: "https://example-a.com"  # 修改为实际平台URL
      odds_endpoint: "/odds"
      timeout: 30
    platform_b:
      name: "平台B"
      base_url: "https://example-b.com"  # 修改为实际平台URL
      odds_endpoint: "/sports/odds"
      timeout: 30
```

4. **运行程序**
```bash
# 单次运行模式
python main.py --mode single

# 连续运行模式（默认1分钟轮询）
python main.py --mode continuous

# 导出数据
python main.py --mode export --format json

# 清理过期数据
python main.py --mode cleanup
```

## ⚙️ 配置说明

### 爬虫配置

```yaml
spider:
  polling_interval: 1              # 轮询间隔（分钟）
  min_delay: 0.5                   # 最小请求延时（秒）
  max_delay: 3.0                   # 最大请求延时（秒）
  max_retries: 3                   # 最大重试次数
  retry_delay: 1.0                 # 重试延时（秒）
```

### 匹配配置

```yaml
matching:
  similarity_threshold: 80         # 球队名称相似度阈值（0-100）
  time_tolerance: 5               # 时间匹配容差（分钟）
```

### 套利配置

```yaml
arbitrage:
  default_principal: 1000.0        # 默认总投入本金
  profit_threshold: 2.0            # 套利触发阈值（净利率%）
  odds_diff_threshold: 0.3         # 赔率差异阈值
```

## 📊 核心功能

### 1. 数据采集
- 支持HTTP静态页面和JS动态渲染页面
- 异步并发爬取，提升效率
- 自动反爬防护（随机User-Agent、请求延时）
- 完善的异常处理和重试机制

### 2. 赛事匹配
- 基于「联赛+主队+客队+时间」的匹配算法
- 支持球队名称相似度匹配
- 自动处理不同平台的命名差异

### 3. 套利计算
- 标准跨平台对冲套利数学模型
- 自动计算最优投注分配
- 支持胜平负、大小球等多种套利类型
- 实时计算固定净利润和净利率

### 4. 数据存储
- SQLite轻量数据库
- 完整的赛事信息和赔率历史记录
- 支持数据导出（JSON/CSV格式）

## 🔧 自定义平台

### 添加新平台解析器

1. 在 `spider/` 目录下创建新的解析器文件，如 `platform_c_parser.py`
2. 继承 `BaseSpider` 类，实现 `extract_match_info` 方法
3. 在配置文件中添加新平台配置
4. 在主程序中注册新爬虫

```python
# 示例：新平台解析器
class PlatformCParser(BaseSpider):
    def __init__(self, config, logger):
        super().__init__(config, logger)
        self.platform_name = "platform_c"

    def extract_match_info(self, soup):
        # 实现针对平台C的页面解析逻辑
        matches = []
        # ... 解析代码
        return matches
```

## 📈 使用示例

### 单次运行
```bash
python main.py --mode single
```

### 连续监控
```bash
python main.py --mode continuous
```

### 数据导出
```bash
python main.py --mode export --format json
```

## 🐛 常见问题

### 1. 爬虫失败
**问题**：无法获取页面内容或解析失败
**解决方案**：
- 检查目标平台URL是否正确
- 确认网络连接正常
- 调整请求延时和反爬参数
- 更新页面解析规则

### 2. 匹配失败
**问题**：赛事无法正确匹配
**解决方案**：
- 调整相似度阈值
- 检查球队名称标准化规则
- 确认时间格式解析正确

### 3. 数据库连接失败
**问题**：无法连接或操作数据库
**解决方案**：
- 检查数据库文件路径权限
- 确认SQLite版本兼容
- 重新初始化数据库

### 4. 内存占用过高
**问题**：长时间运行内存占用过大
**解决方案**：
- 定期清理过期数据
- 调整轮询间隔
- 优化数据处理逻辑

## 📝 开发规范

### 代码规范
- 所有函数、类必须添加中文详细注释
- 变量命名使用小写字母+下划线
- 统一使用4个空格缩进
- 避免冗余代码

### 配置规范
- 所有可配置参数必须抽离到配置文件
- 支持热更新配置
- 提供合理的默认值

### 日志规范
- 使用标准logging库
- 按日期分割日志文件
- 记录关键操作和异常信息

## 🔄 性能优化

### 爬虫优化
- 异步并发请求
- 智能请求延时
- 连接池复用

### 数据处理优化
- 批量数据库操作
- 内存数据缓存
- 增量更新策略

### 存储优化
- 数据库索引优化
- 定期数据清理
- 压缩历史数据

## 📊 监控与维护

### 运行状态监控
- 实时日志输出
- 采集统计信息
- 异常报警机制

### 数据质量检查
- 数据完整性验证
- 赔率合理性检查
- 匹配准确率统计

### 定期维护
- 清理过期日志
- 优化数据库性能
- 更新解析规则

## 📄 许可证

本项目采用 MIT 许可证。详见 [LICENSE](LICENSE) 文件。

## 🤝 贡献指南

1. Fork 项目
2. 创建特性分支
3. 提交更改
4. 推送到分支
5. 创建 Pull Request

## 📞 联系方式

如有问题或建议，请提交 Issue 或联系项目维护者。

---

**最后更新时间**: 2024年1月
**版本**: v1.0.0