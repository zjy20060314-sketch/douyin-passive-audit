# 运行指南

## 1. 初始化

在 PowerShell 中进入仓库目录：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\setup.ps1
```

初始化脚本会创建 `.venv`、安装 Node.js 依赖并运行语法检查与单元测试。Playwright 使用系统 Microsoft Edge，不额外下载浏览器。

## 2. 首次登录与小规模测试

| 平台 | 命令 | 本机浏览器资料 |
|---|---|---|
| 抖音 | `.\smoke_test.ps1` | `runtime/douyin-edge-profile/` |
| 小红书 | `.\smoke_test_xiaohongshu.ps1` | `runtime/xiaohongshu-edge-profile/` |
| 哔哩哔哩 | `.\smoke_test_bilibili.ps1` | `runtime/bilibili-edge-profile/` |

浏览器首次打开后，请在五分钟内手动完成登录。后续运行会复用该平台的独立资料。

## 3. 正式运行

采集三条：

```powershell
.\run.ps1 --items 3
.\run_xiaohongshu.ps1 --items 3
.\run_bilibili.ps1 --items 3
```

连续运行三十分钟：

```powershell
.\run.ps1 --duration-minutes 30 --min-dwell-seconds 3 --max-dwell-seconds 15
.\run_xiaohongshu.ps1 --duration-minutes 30 --min-dwell-seconds 3 --max-dwell-seconds 15
.\run_bilibili.ps1 --duration-minutes 30 --min-dwell-seconds 3 --max-dwell-seconds 15
```

默认不截图。只有显式传入 `--screenshots` 时才保存截图。

默认输出目录：

| 平台 | 目录 |
|---|---|
| 抖音 | `data_live_debug/<时间戳>/` |
| 小红书 | `data_xiaohongshu_debug/<时间戳>/` |
| 哔哩哔哩 | `data_bilibili_debug/<时间戳>/` |

## 4. 验证结果

```powershell
.\.venv\Scripts\python.exe -m audit.cli.verify_output .\data_live_debug\你的运行目录 --platform douyin
.\.venv\Scripts\python.exe -m audit.cli.verify_output .\data_xiaohongshu_debug\你的运行目录 --platform xiaohongshu
.\.venv\Scripts\python.exe -m audit.cli.verify_output .\data_bilibili_debug\你的运行目录 --platform bilibili
```

核对计划时长时增加 `--expected-duration-minutes 30`。

## 5. 自定义程序路径

如果 Edge、Node.js 或 Python 不在标准位置，可以设置：

```powershell
$env:DOUYIN_AUDIT_EDGE = "D:\Apps\Edge\msedge.exe"
$env:DOUYIN_AUDIT_NODE = "D:\Apps\Node\node.exe"
$env:DOUYIN_AUDIT_PYTHON = "D:\Apps\Python\python.exe"
```

## 6. 运行边界

程序只读取当前可见推荐内容。遇到验证码、登录失效或平台明确限制时应停止并保留数据，不会自动绕过这些限制。不要提高频率或并发运行。
