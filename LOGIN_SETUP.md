# 平台A登录功能配置指南

本文档说明如何配置和使用平台A（https://www.uompld.vip:7988）的登录和验证码识别功能。

## 1. 环境准备

### 安装依赖
首先确保已安装所有必需的依赖包：

```bash
pip install -r requirements.txt
```

### 安装OCR依赖
验证码识别功能需要Tesseract OCR引擎：

#### macOS
```bash
brew install tesseract
```

#### Ubuntu/Debian
```bash
sudo apt-get install tesseract-ocr
```

#### Windows
从 [Tesseract官方GitHub](https://github.com/UB-Mannheim/tesseract/wiki) 下载安装程序

## 2. 配置文件设置

### 编辑配置文件
打开 `config/config.yaml` 文件，找到 `platform_a` 配置部分：

```yaml
platform_a:
  name: "平台A"
  base_url: "https://www.uompld.vip:7988"
  odds_endpoint: "/odds"
  login_url: "/login"
  timeout: 30
  # 登录凭证（请替换为实际的登录信息）
  credentials:
    username: "your_username"  # 替换为实际用户名
    password: "your_password"  # 替换为实际密码
  # 验证码配置
  captcha:
    type: "image"  # image/slide/other
    retry_limit: 5
    ocr_enabled: true
    preprocess: true
    ocr_config: "--psm 8 --oem 3 -c tessedit_char_whitelist=0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
```

### 配置说明

- **username**: 您的平台A登录用户名
- **password**: 您的平台A登录密码
- **retry_limit**: 验证码识别失败时的重试次数
- **ocr_enabled**: 是否启用OCR验证码识别
- **preprocess**: 是否启用图像预处理（提高识别率）
- **ocr_config**: Tesseract OCR配置参数

## 3. 功能测试

### 运行测试脚本
使用提供的测试脚本来验证登录和爬虫功能：

```bash
python test_login.py
```

### 预期输出

- ✅ 登录测试成功
- ✅ 登录状态检查正常
- ✅ 成功爬取比赛数据

### 故障排除

如果测试失败，请检查：

1. **网络连接**: 确保可以访问目标网站
2. **登录凭证**: 确认用户名和密码正确
3. **验证码识别**: 检查Tesseract是否正确安装
4. **页面结构**: 目标网站的页面结构可能已变更

## 4. 常见问题

### 验证码识别失败

1. **检查Tesseract安装**: 确保Tesseract OCR已正确安装
2. **调整OCR配置**: 修改 `ocr_config` 参数
3. **禁用预处理**: 设置 `preprocess: false`
4. **手动识别**: 对于复杂验证码，可能需要集成第三方验证码识别服务

### 登录失败

1. **检查凭证**: 确认用户名和密码正确
2. **检查URL**: 确认 `base_url` 和 `login_url` 正确
3. **检查网络**: 确保可以访问目标网站
4. **检查反爬**: 目标网站可能有反爬虫机制

### 数据爬取失败

1. **检查登录状态**: 确保登录成功
2. **调整解析逻辑**: 根据实际页面结构调整数据提取逻辑
3. **增加延时**: 调整请求延时避免被限制

## 5. 高级配置

### 自定义验证码识别

如果需要更高级的验证码识别功能，可以：

1. **集成第三方服务**: 如2Captcha、Anti-Captcha等
2. **训练自定义模型**: 使用机器学习训练专门的验证码识别模型
3. **手动干预**: 对于识别失败的验证码，提供手动输入接口

### 代理设置

为防止IP被封禁，可以添加代理支持：

```yaml
platform_a:
  # ... 其他配置
  proxy:
    enabled: true
    url: "http://username:password@proxy.example.com:8080"
```

## 6. 安全注意事项

1. **保护登录凭证**: 不要在代码中硬编码用户名和密码
2. **使用环境变量**: 考虑将敏感信息存储在环境变量中
3. **定期更换密码**: 定期更新登录密码
4. **监控异常**: 监控登录失败和验证码识别失败的情况

## 7. 性能优化

### 提高验证码识别率

1. **图像预处理**: 启用图像预处理功能
2. **调整OCR参数**: 根据验证码特点调整OCR配置
3. **缓存识别结果**: 对相同验证码图片缓存识别结果

### 减少请求频率

1. **合理设置延时**: 调整 `min_delay` 和 `max_delay`
2. **批量处理**: 合并多个请求减少连接数
3. **连接复用**: 复用HTTP连接

## 8. 扩展功能

### 添加新的平台

参考平台A的实现，可以为其他需要登录的平台创建类似的解析器：

1. 继承 `BaseSpider` 类
2. 实现登录逻辑
3. 实现数据提取逻辑
4. 在配置文件中添加平台配置

### 集成到主程序

修改 `main.py` 以支持新的登录功能：

```python
# 在主程序中初始化爬虫时，传递完整的配置
spider_config = config  # 包含登录和验证码配置
```

## 9. 联系和支持

如果遇到问题，请：

1. 查看日志文件获取详细错误信息
2. 检查配置文件是否正确
3. 运行测试脚本进行诊断
4. 参考项目的README.md文件

---

**注意**: 本工具仅用于技术学习和研究目的，请遵守相关法律法规和网站使用条款。