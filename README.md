# Passive Feed Audit

一个在 Windows 本地运行的网页版被动采集工具。它通过**可见的 Microsoft Edge**浏览推荐内容，并把当前页面可见的信息保存为结构化数据。

| 平台 | 浏览方式 | 主要内容字段 |
|---|---|---|
| 抖音 | 推荐流自动翻页 | 内容 ID、作者、标题、文案、Tags、主题 |
| 小红书 / RedNote | 逐一打开笔记详情弹窗 | 内容 ID、标题、正文、Tags、图文/视频类型 |
| 哔哩哔哩 | 逐一打开首页推荐视频 | BV/av ID、标题、简介、Tags、视频类型 |

程序默认每条随机停留 3–15 秒，不截图。它不搜索、不点赞、不关注、不评论、不收藏、不分享，也不进入创作者主页。遇到登录失效、验证码或平台限制时会停止并保留已有数据。

## 快速开始

运行环境：Windows 10/11、Microsoft Edge、Python 3.10+、Node.js 20+。

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
```

首次运行建议先完成三条小规模测试：

| 平台 | 测试命令 | 正式运行命令 |
|---|---|---|
| 抖音 | `.\smoke_test.ps1` | `.\run.ps1 --duration-minutes 30` |
| 小红书 | `.\smoke_test_xiaohongshu.ps1` | `.\run_xiaohongshu.ps1 --duration-minutes 30` |
| 哔哩哔哩 | `.\smoke_test_bilibili.ps1` | `.\run_bilibili.ps1 --duration-minutes 30` |

首次运行会打开独立的 Edge 资料，需要使用者在可见窗口中自行登录。登录资料只保存在本机的 `runtime/`，不会上传到 GitHub。

详细参数、首次登录和验证方法见 [运行指南](docs/USAGE.md)。

## 输出

每次运行使用独立目录，主要产生：

- `observations.jsonl`：逐条完整原始记录
- `exposures.csv`：适合 Excel 和统计软件的表格
- `RESULT.md`：便于阅读的验收报告
- `progress.json` / `summary.json`：运行状态与汇总
- `failure.json`：失败或暂停时的错误信息

字段定义和文件说明见 [输出格式](docs/OUTPUTS.md)。采集数据、日志、截图和账号会话均已被 Git 忽略。

## 仓库结构

```text
audit/
  cli/          # 三个平台的命令入口与输出验证器
  platforms/    # Edge 页面控制和平台适配器
  collectors/   # 通用字段标准化
  experiment/   # 实验运行流程
  storage/      # 本地数据存储
config/         # 账号模板和实验配置
docs/           # 使用、输出和隐私说明
tests/          # 自动化测试
*.ps1           # Windows 用户入口
```

## 开发检查

```powershell
npm run check
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

请仅在你有权使用的账号、设备和场景中运行，并遵守平台条款、适用法律和研究伦理要求。完整边界见 [隐私与数据边界](docs/PRIVACY.md)。

MIT License，见 [LICENSE](LICENSE)。
