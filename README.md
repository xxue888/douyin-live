# 🎙️ 抖音直播间智能自动回复与活跃助手 (Douyin Live Assistant)

这是一个专为抖音主播和运营团队打造的**直播间智能助手**。系统通过高效的浏览器自动化引擎（Playwright）实时监听直播间弹幕，并结合**自定义关键词规则**与**大语言模型（LLM）**实现秒级自动回复。同时，系统还配备了**定时公告发送**和**智能冷场活跃算法**，帮助提升直播间的互动率与活跃度。

系统提供了一个基于 **霓虹玻璃拟态（Glassmorphism）** 设计的现代暗黑风 Web 网页后台，方便随时调整策略、查看日志。

---

## ✨ 核心功能

1. **实时弹幕监控**
   * 基于双向 DOM 节点搜索的高性能 `MutationObserver` 弹幕监听机制，在 React 虚拟列表频繁重构时仍能实现 100% 稳定捕获。
   * 自动过滤系统提示（如点赞、进入直播间、送礼等），专注于提取真实的用户发言。
2. **多层级智能回复引擎**
   * **规则优先**：用户匹配自定义关键词时，优先执行精准的快捷回复（如“多少钱” $\rightarrow$ “今天直播间99元！”）。
   * **AI 兜底**：未匹配规则的发言可无缝投递给大语言模型（支持 Gemini、DeepSeek、OpenAI 等任意兼容接口），自动在 **20字以内** 给出富有亲和力的回复，且确保**安全合规、不重复**。
3. **自动化消息发送**
   * 模拟真实键盘逐字键入与回车发送，规避平台的机械化检测。
   * 支持持久化会话（Cookies & Profile 缓存），**只需首次扫码登录**，后续启动直接免签密进入。
4. **定时与智能活跃策略**
   * **定时发送**：可在后台配置多条公告（如欢迎语、关注引导等），带有 10% 时间随机抖动防止平台风控。
   * **智能冷场应对**：当直播间一定时间内（如 5/10 分钟）无人发言或点赞达到特定阀值时，自动抛出话题（如“大家来自哪里呀？”）活跃公屏气氛。

---

## 📂 项目目录结构

```
douyin-live/
├── backend/                  # 后端 FastAPI 引擎
│   ├── app/
│   │   ├── core/             # 核心逻辑 (自动化、AI、调度器等)
│   │   │   ├── automation.py    # Playwright 网页自动化与弹幕监听
│   │   │   ├── llm.py           # 大模型 API 调用与安全过滤
│   │   │   ├── reply_engine.py  # 规则匹配与回复去重引擎
│   │   │   └── scheduler.py     # 定时公告与冷场活跃调度
│   │   ├── schemas/          # Pydantic 校验模型
│   │   ├── config.py         # 配置项与路径定义
│   │   ├── database.py       # 本地 JSON 配置读写
│   │   └── main.py           # FastAPI 接口及 WebSocket 路由
│   ├── tests/                # 自动化单元测试
│   └── run.py                # 统一的启动引导脚本
├── frontend/                 # 前端后台管理系统
│   ├── css/                  # 玻璃拟态 UI 样式文件
│   ├── js/                   # 后台数据通信与 WS 日志联调
│   └── index.html            # 仪表盘单页面
├── data/                     # 用户本地数据（Git 已忽略，自动创建）
│   ├── browser_profile/      # 浏览器缓存及登录 cookies 会话
│   ├── config.json           # 助手运行参数及关键词回复规则
│   └── backend.log           # 系统运行日志
├── assistant.spec            # PyInstaller 编译打包配置文件
├── .gitignore                # Git 提交过滤配置
└── .env.example              # 环境变量配置模板
```

---

## 🚀 快速上手指南

### 1. 准备环境
确保你已安装 **Python 3.10** 或更高版本。

### 2. 克隆与安装依赖
```bash
# 复制配置文件
cp .env.example .env

# 创建并激活 Python 虚拟环境
python3 -m venv .venv
source .venv/bin/activate  # Windows 用户运行: .venv\Scripts\activate

# 安装依赖
pip install -r backend/requirements.txt
```

### 3. 运行助手
直接执行启动引导脚本，它将自动检查并安装 Playwright 所需的 Chromium 浏览器：
```bash
python backend/run.py
```
启动成功后，在浏览器中打开：[http://127.0.0.1:8000](http://127.0.0.1:8000)

### 4. 开始使用
1. 在网页后台的**大模型设置**中填写你的 API Key 以及模型参数（如使用 DeepSeek / Gemini / OpenAI 兼容接口）。
2. 输入你的**抖音直播间地址**（如 `https://live.douyin.com/73335207613`），点击 **[启动助手]**。
3. 首次启动时，程序会拉起一个非无头的 Chrome 浏览器，**请在拉起的浏览器中手动扫码完成登录**。
4. 登录完成后，会话将自动保存。助手随即开始实时抓取弹幕并自动管理直播间！

---

## 📦 打包为单文件 `.exe` 可执行程序

如果你需要将程序发给没有 Python 编程基础的普通用户使用，可以使用 PyInstaller 将其打包。

由于跨平台限制，**打包 Windows `.exe` 程序必须在 Windows 操作系统下执行**：

1. 拷贝本源码目录至 Windows 电脑上。
2. 打开 CMD 终端，创建并激活虚拟环境，安装依赖及打包工具：
   ```cmd
   python -m venv .venv
   call .venv\Scripts\activate
   pip install -r backend/requirements.txt
   pip install pyinstaller
   ```
3. 在根目录下执行打包命令：
   ```cmd
   pyinstaller assistant.spec --clean
   ```
4. 打包完成后，你将在 `dist/` 文件夹下获得可独立运行的 **`DouyinLiveAssistant.exe`**。
   * *注：用户双击运行时，若检测到无浏览器驱动，会自动把 Chromium 浏览器静默安装在程序旁边的 `data/playwright-browsers` 下，彻底开箱即用。*

---

## 🧪 运行测试

运行测试套件以验证配置读写、回复规则匹配、AI 兜底及字数去重等逻辑：
```bash
python -m unittest backend/tests/test_assistant.py
```

---

## 🛡️ 安全合规提醒

本助手在设计时遵循了以下原则以保障直播间安全：
1. **真实模拟**：发送弹幕采用模拟物理键盘键入，控制在正常人的打字速度（带随机延迟）。
2. **字数限制**：AI 生成的回复默认强制截断在 20 个字以内，符合抖音短评生态。
3. **内容安全**：提示词中强制植入了敏感词过滤与安全红线（严禁违法违规、诱导消费、未成年充值等话题），保证助手回复符合监管要求。
