# Douyin Passive Audit

一个可复现的 Windows 本地工具：通过**可见的 Microsoft Edge**被动浏览抖音网页版推荐流，保存当前可见内容的结构化字段，并在本地提取题目、文案、Tags 与主题。

它不调用私有接口，不读取 Cookie，不搜索、不点赞、不关注、不评论、不收藏、不分享，也不进入创作者主页。首次运行时，使用者需要在独立 Edge 资料中自行登录；登录状态只保存在本机。

## 功能

- 使用系统 Edge 和独立浏览器资料，运行过程始终可见。
- 按条数或时长采集，默认每条停留 3–15 秒。
- 保存 `content_id`、作者、题目、文案、Tags、主题、停留时间等字段。
- 默认不截图。
- 输出 JSONL、CSV、JSON 状态文件和 Markdown 报告。
- 每次翻页后以内容 ID 变化确认页面确实前进。
- 遇到登录失效、验证码或平台限制时停止并保留已采集数据。

## 运行要求

- Windows 10/11
- Microsoft Edge
- Python 3.10 或更高版本
- Node.js 20 或更高版本（包含 npm）

## 初始化

在 PowerShell 中进入仓库目录，然后运行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
```

脚本会创建本地 Python 虚拟环境、安装 Playwright Node 包（不会下载额外浏览器），并运行语法检查和单元测试。

## 首次少量测试

```powershell
.\smoke_test.ps1
```

这会打开一个独立的 Edge 窗口。若页面要求登录，请在 5 分钟内手动完成登录；之后程序自动采集 3 条并验收结果。浏览器资料保存在 `runtime/douyin-edge-profile/`，后续运行通常无需重复登录。

## 常用运行方式

采集 3 条：

```powershell
.\run.ps1 --items 3
```

连续运行 30 分钟：

```powershell
.\run.ps1 --duration-minutes 30 --min-dwell-seconds 3 --max-dwell-seconds 15
```

首次登录时延长等待：

```powershell
.\run.ps1 --items 3 --login-wait-seconds 300
```

默认输出目录为 `data_live_debug/<时间戳>/`。默认不截图；只有显式传入 `--screenshots` 才会保存截图。

## 输出文件

| 文件 | 用途 |
|---|---|
| `observations.jsonl` | 每条曝光的完整结构化记录 |
| `exposures.csv` | 便于 Excel 或统计软件读取的表格 |
| `progress.json` | 运行中的状态、条数和最后内容 ID |
| `summary.json` | 完成状态、时长、停留范围和禁止动作计数 |
| `failure.json` | 失败或暂停时的错误信息与已保存条数 |
| `RESULT.md` | 可直接阅读的验收报告 |

验证一个完成的输出目录：

```powershell
.\.venv\Scripts\python.exe .\verify_output.py .\data_live_debug\你的运行目录
```

30 分钟运行还可额外核对请求时长：

```powershell
.\.venv\Scripts\python.exe .\verify_output.py .\data_live_debug\你的运行目录 --expected-duration-minutes 30
```

## 可选路径覆盖

如果 Edge 或 Node.js 不在标准位置，可以设置：

```powershell
$env:DOUYIN_AUDIT_EDGE = "D:\Apps\Edge\msedge.exe"
$env:DOUYIN_AUDIT_NODE = "D:\Apps\Node\node.exe"
$env:DOUYIN_AUDIT_PYTHON = "D:\Apps\Python\python.exe"
```

## 数据与合规边界

采集程序只读取当前可见推荐卡片。请仅在你有权使用的账号、设备和场景中运行，并遵守平台条款、适用法律和研究伦理要求。不要提高频率、并发运行或把它改造成绕过验证码、访问控制或平台限制的工具。

仓库已忽略浏览器资料、账号会话、采集结果、日志和截图。详细边界见 [PRIVACY.md](PRIVACY.md)。

## 已知限制

- 抖音网页结构更新后，卡片识别规则可能需要同步更新。
- 主题分类采用本地关键词规则，是粗粒度标签，不等同于人工内容编码。
- 网页只显示 Tags 而没有独立题目时，题目字段会保留可见 Tags，避免制造不存在的标题。
- 工具不会自动处理验证码或登录挑战。

## 测试

```powershell
npm run check
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## License

MIT License，见 [LICENSE](LICENSE)。
