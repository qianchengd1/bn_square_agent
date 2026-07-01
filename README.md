# BN Square Agent

BN Square Agent 是一个本地自动运营控制台，用来采集 Binance Square 作者文章，自动打标、改写、配走势图，并通过远程 MCP 发布到 Binance Square。

## 功能

- 本地 FastAPI 服务，Vue 前端源码放在 `web/`，构建产物输出到 `dist/`
- 多账号 Cookie 管理，数据保存到本地 SQLite
- 监控 Binance Square 作者主页并采集文章
- 素材入库、打标、过期清理
- 后台自动循环运行，也支持前端手动立即运行
- 每个账号生成不同终稿
- LLM 自动审核与重写
- DashScope Embedding + Chroma 风格检索
- Playwright 自动截取 Binance 合约走势图
- 通过远程 MCP 工具 `publish_binance_square` 发布文章

## 安全说明

不要提交运行数据和密钥。仓库已忽略：

- `.env`
- `data/`
- `chroma_db/`
- 本地 agent / 工具缓存目录

Cookie、API Key、生成稿、采集样本都只应该保存在本地数据库或本地配置中，不要提交到 GitHub。

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m playwright install chromium
```

可以复制 `.env.example` 到 `.env` 使用文件配置，也可以直接在网页控制台里保存配置。

```powershell
copy .env.example .env
```

## 启动

首次构建前端：

```powershell
cd web
pnpm install
pnpm build
cd ..
```

```powershell
python -B run.py serve --host 127.0.0.1 --port 8787
```

打开：

```text
http://127.0.0.1:8787/
```

Windows 下如果 Playwright 采集或截图报 `WinError 5`，需要用更高权限启动服务。

## 网页配置

网页控制台会把这些配置保存到 SQLite：

- LLM API Key、Base URL、模型名
- DashScope API Key、Embedding 模型
- MCP 地址和发布配置
- 自动循环、自动发布、自动消费素材
- 采集间隔、成功后间隔、失败重试间隔、素材有效期

LLM 和 Embedding 有独立测试按钮，方便分别确认连接是否正常。

## 自动运行流程

1. 在账号管理里添加 Binance Cookie。
2. 在素材中心添加 Binance Square 作者主页链接。
3. 后台循环按配置间隔采集新文章。
4. 素材源文章进入本地素材库。
5. 打标器识别币种、方向、合约符号。
6. 过期素材会按 TTL 自动失效。
7. 自动消费器从可用素材中取一条。
8. Writer Agent 改写成账号对应的终稿。
9. Review Agent 自动审核，不合格则重写。
10. 发布前自动匹配合约图和 `coins` 参数。
11. 远程 MCP 使用 Cookie 发布文章。

## 前端页面

前端采用 Vue3/Vite/TypeScript 管理后台布局：

- 自动运行：查看状态、启动/暂停循环、立即运行、检查 MCP
- 账号管理：保存账号 Cookie
- 素材中心：管理采集源、查看素材库
- 系统设置：配置 LLM、Embedding、自动运行参数

## 项目结构

```text
ai/           LLM Agent、改写、审核、打标
core/         配置与环境变量
web/          Vue3/Vite 前端源码
dist/         前端构建产物，由 FastAPI 托管
knowledge/    Chroma / Embedding 风格检索
models/       Pydantic 数据结构
publishing/   MCP 发布、走势图截图、账号检测
sources/      素材源采集
storage/      SQLite 持久化
workflows/    LangGraph 工作流和自动运营编排
```
