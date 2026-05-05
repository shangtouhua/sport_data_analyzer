# 平台A登录功能配置指南

本文档说明如何配置和使用平台A（https://www.uompld.vip:7988）的登录功能。

## 背景说明

平台A使用Next.js前端框架，登录时：
- 密码经过AES-CBC加密后传输（密钥和IV存储在页面`__NEXT_DATA__`和`sessionStorage`中）
- 包含`X-API-FINGER`浏览器指纹检测头
- API接口：`/site/api/v1/user/login`（JSON格式POST）

由于客户端的AES加密逻辑复杂且依赖运行时状态，**推荐使用cookie登录方式**。

## 两种登录方式

### 方式一：Cookie登录（推荐）

#### 第1步：在浏览器中正常登录
1. 打开 Chrome/Firefox 浏览器
2. 访问 https://www.uompld.vip:7988
3. 输入用户名和密码，正常完成登录

#### 第2步：导出Cookie

**Chrome 开发者工具方式：**
1. 登录后按 F12 打开开发者工具
2. 切换到 Network 标签页，刷新页面
3. 点击任意请求，在 Request Headers 中找到 Cookie 字段
4. 复制完整的 Cookie 字符串

**EditThisCookie 扩展方式（推荐）：**
1. 安装 EditThisCookie Chrome 扩展
2. 登录后点击扩展图标
3. 点击 Export 导出 JSON
4. 保存到 `data/platform_a_cookies.json`

运行验证工具：
```bash
python tools/extract_cookies.py
```

#### 第3步：验证Cookie
```bash
python test_login.py
```

### 方式二：API直接登录（备选）

如果不想使用浏览器导出cookie，也可以在 `config/config.yaml` 中配置用户名和密码：

```yaml
platform_a:
  credentials:
    username: "your_username"
    password: "your_password"
  cookie_login:
    enabled: false  # 关闭cookie登录，使用API登录
```

**注意**：API直接登录的成功率取决于平台是否修改了AES加密逻辑，如果登录失败请切换回cookie方式。

## 配置文件

相关配置项说明（`config/config.yaml`）：

```yaml
platform_a:
  base_url: "https://www.uompld.vip:7988"
  login_api: "/site/api/v1/user/login"
  odds_endpoint: "/site/api/v1/odds"
  cookie_login:
    enabled: true
    cookie_file: "data/platform_a_cookies.json"
  credentials:
    username: "your_username"
    password: "your_password"
```

## 测试

```bash
python test_login.py
```

正常输出：
```
==================================================
开始平台A登录和爬虫功能测试
==================================================
... 检测到cookie文件，将使用cookie登录 ...
... 登录测试成功！ ...
==================================================
测试完成
==================================================
```

## 常见问题

### cookie过期了怎么办？
Cookie有效期由平台控制，过期后需要重新在浏览器登录并重新导出cookie。

### API直接登录失败（status_code: 6008）
平台使用了AES加密密码，普通POST无法直接登录。请切换为cookie登录方式。

### 如何更新cookie？
重新执行导出步骤，用新的cookie覆盖 `data/platform_a_cookies.json` 即可。

---

**注意**: 本工具仅用于技术学习和研究目的，请遵守相关法律法规和网站使用条款。
