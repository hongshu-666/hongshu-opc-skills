---
name: hongshu-cross-post
description: 立即或定时分发视频和图文，支持公众号发表或存草稿。跨对话问「刚才那批约上了吗」、查批次进度、续跑、查后台排期、草稿、发表记录或发布偏好时使用，即使没提平台名。
metadata:
  version: "0.5.2"
  short-description: 跨平台分发视频和图文，支持批量预约、公众号发表或草稿和跨对话查回执。
  origin: hongshu
---
# 洪树 · 一键分发

未明体裁、平台或方式先问一次「发视频还是图文，发到哪些平台，立即发、预约还是存草稿？」问清前不读资料、脚本或素材；追问仍未点名平台，视频默认抖音/视频号/小红书/B站，图文默认抖音/小红书/公众号，禁翻旧账本缩平台。按表调命令，不翻 JS，禁用电脑操控。

在 Skill 目录执行，命令前缀为 sh scripts/run.sh（Windows 用 ./scripts/run.ps1）。首次用 env status 体检，env bind 绑定本人账号。缺环境才查[启动排错](references/access.md)。复用专用浏览器和账号，仅本人验证时置前。

| 用户意图 | 执行入口 |
|---|---|
| 发布或存草稿 | 读[任务清单](references/run.md)。完整清单或明确指令即授权相应动作。任务 JSON 存素材目录外，执行 `sh scripts/run.sh run 任务.json`。已返回核实分钟就直接报告。 |
| 看进度或补跑 | run --status 批次号；后台仍在运行就继续等待。提示集中扫码或进程中断时 run --resume 批次号。 |
| 查旧稿、排期、草稿 | `sh scripts/run.sh query --batch 批次号`，单项加 `--item 任务键`。查整个平台用 `sh scripts/run.sh query --platform 平台`。 |
| 查、记住或清除偏好 | `sh scripts/run.sh pref show` 查偏好；设置时读[偏好键表](references/run.md#偏好)；清除用 `sh scripts/run.sh pref clear 平台-体裁`。亮出生效项，临时要求优先。 |
| 只预览 | 新建预览清单按[预览说明](references/run.md#只预览)准备后关闭，禁用提交。 |

只在新建清单或设置偏好时读 run.md。跨对话查预约直接按批次查后台，兼问偏好就再查偏好；用查询结果直接回答，无需另跑进度命令。

视频信息缺失时给四行：本次共发几条视频、素材文件夹位置、发布标题、简介和话题，每项一行。报告批次号与五列结果，成功项简报，异常注明篇目、平台、是否已点击和下一步。不得复制或临时修改脚本试错。平台已点击而回执不明时只续查，其余平台继续。测试清理仅在获明确授权时查[测试清理](references/access.md#测试清理)。
