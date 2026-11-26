# 环境体检、首次配齐与桌面浏览器连接

面向用户全程用精炼白话解释（清单左列只展示正式软件／模型名，**严禁向用户抛出**内部路径、虚拟环境、端口、协议或脚本状态码，如 `~/.cache/...`、`Python 虚拟环境`、`REACH_CHROME_URL`、`DevToolsActivePort`、`CDP`、`env-ready.json`、`not_ready`、`就绪记录` 等，也禁止臆测“代理/Docker 环境”）。本技能标准环境覆盖 **Apple Silicon Mac（macOS arm64）** 与 **Windows x64**；其他架构如实说明不支持。**核心一致原则：首次验收通过的是哪套程序和模型，后续正式采集就统一复用 `env status --agent <当前Agent>` 返回的 `tools.node`（下称 `$NODE`）、`tools.python`（下称 `$PYTHON`）绝对路径与同一模型目录**（各端各自记录自己的 `$NODE` / `$PYTHON`，互不覆盖；若共享工具或模型变更则旧端自动触发轻量复验）。

**跨平台变量调用写法（全文及所有参考页共用相同参数）**：
- **macOS（`zsh`/`sh`）**：`"$PYTHON" "$SKILL_DIR/scripts/<脚本>.py" ...`、`"$NODE" "$SKILL_DIR/scripts/browser_collect.js" ...`
- **Windows PowerShell**：`& $PYTHON "$SKILL_DIR\scripts\<脚本>.py" ...`、`& $NODE "$SKILL_DIR\scripts\browser_collect.js" ...`

## 1. 首次触发全量体检与换端轻量复验

- **`needs_agent_verify`（同机换新 Agent）**：复用本机已装工具与模型，不重下模型也不重跑大模型散列；仅用当前会话实测 `$NODE` / `$PYTHON` 跑以下两步（凭证放 `$TMPDIR`／`%TEMP%`，通过后清理并继续原任务）：
  ```sh
  "$NODE" "$SKILL_DIR/scripts/browser_collect.js" verify "<临时浏览器凭证.json>"
  "$PYTHON" "$SKILL_DIR/scripts/media_common.py" env mark-ready --browser-proof "<临时浏览器凭证.json>" --reuse-machine-asr --agent "<当前Agent>" --chrome "<实测chrome路径>" --node "$NODE"
  ```
- **`not_ready`、尚无记录，或连 Python／Node 都没装时**，走**第 0 层零依赖全量体检**——用当前 Agent 原生系统命令一次摸清：① 系统与芯片架构；② 目标保存目录可写性；③ 官方 Google Chrome；④ 专用 Chrome 能否启动与连接（或宿主内置桌面浏览器是否可用）；⑤ Node.js 22+（WorkBuddy 优先探测 `~/.workbuddy/binaries/node/versions/...` 或 `%USERPROFILE%\.workbuddy\binaries\node\versions\...`，并以当前会话实测版本与 `typeof WebSocket === 'function'` 为准）；⑥ Python（macOS 3.11+，避开系统 3.9 开发者工具弹窗；Windows 固定 **x64 Python 3.12** 以匹配 `ctranslate2==4.6.0` 官方轮子，避开微软商店空壳 `python3.exe`）及 `Asia/Shanghai` 时区；⑦ `curl`（含 `--fail-with-body`）、`ffmpeg`、`ffprobe`、`yt-dlp`（先查 `~/.local/bin`、`~/.cache/reach-tools/*/bin`、`/opt/homebrew/bin` 与 `PATH`）；⑧ 完整 `large-v3-turbo` 本地 ASR 运行时（**macOS 必须先查 `~/.local/bin/mlx_whisper`、`~/.cache/reach-tools/mlx-whisper/bin/mlx_whisper`、`/opt/homebrew/bin/mlx_whisper` 与 `PATH`，已存在可用的直接复用，切勿因不在 `reach-tools` 目录下或不在当前 `python3` 里而误判缺失或重复安装**）与模型权重。

**面向新手的首次体检／安装核查汇报模板（无论刚安装完本技能做环境核查，还是首次发起采集任务，只要本机未就绪或有缺项就必须原样使用下方 7 项表格，禁止改写为纯技术列表）**：
按“打开网页 → 自动读取 → 本地运行 → 音视频处理 → 语音转文字”的顺序，把全部 7 项必装逐一标清「已有」或「缺少」（第 6 项按用户当前系统只显示对应那一个：`Mac` 显示 `mlx-whisper`，`Windows` 显示 `faster-whisper`）：

| 需要准备的工具／组件 | 它是用来干嘛的 | 你的电脑当前状态 |
|---|---|---|
| 1. `Google Chrome` | 目前对主流 AI 智能体和插件兼容性最好的浏览器，用来稳定打开抖音、小红书、B站、知乎和公众号 | 已有 ／ 缺少 |
| 2. `Node.js`（22+） | 网页自动读取组件，帮 AI 自动翻页收齐博主选题清单、读取文章和获取视频地址 | 已有 ／ 缺少 |
| 3. `Python`（3.11+，Windows 为 3.12） | 本地脚本运行组件，驱动内容整理、校对校验与 Markdown 成稿保存 | 已有 ／ 缺少 |
| 4. `FFmpeg` | 音视频处理工具，负责从视频里提取声音、校验时长和核对画面字幕 | 已有 ／ 缺少 |
| 5. `yt-dlp` | 公开视频与字幕下载组件，用于获取 B 站等平台的公开视频和自带字幕 | 已有 ／ 缺少 |
| 6. `mlx-whisper`（Mac）／`faster-whisper`（Windows） | 本地语音转文字程序，在你电脑离线把视频口播转成中文逐字稿（不花接口费、不上传隐私） | 已有 ／ 缺少 |
| 7. `whisper-large-v3-turbo`（约 1.6 GB） | 离线中文语音包，配合上面的转文字程序高准确度识别中文口播 | 已有 ／ 缺少 |

表后按实际情况收尾，严禁静默安装：
- **有缺项且当前窗口可正常执行／申请本机权限**：**严禁给出「1. 直接用 / 2. 现在就装」等二选一分叉，也严禁暗示不配齐就能先直接用**；只给唯一明确建议与唯一确认动作——① 说明上面标**「缺少」**的项目必须全部配齐，否则这个采集技能无法正常使用；② 说明全部来自软件官方渠道、装在电脑常规工具目录（写清预计总下载量及可能弹出系统确认框或提示输入管理员密码）；③ 直接以唯一引导收尾：「**只需回复『确认』，我现在就自动帮你把缺少的几项一次全部搭建好并完成测试，配齐后直接就能用**」（用户回复「确认」或「同意」后立即一次配齐并完成两项实测，若有待办采集任务则自动续做）。
- **7 项全部已有、仅差首次小测试**：若当前窗口具备本机权限，无需打断用户询问确认，直接完成两项几秒钟的小测试并在首段简报结果后继续原任务；若因权限受限无法跑小测试，列出 7 项均已有的表格告知无需下载安装，按下方权限提示引导。
- **命令沙箱与目录写权限处理（macOS 桌面 Agent 必读）**：Codex / WorkBuddy 等桌面 Agent 的默认命令沙箱会拦截 **Mac Metal GPU（导致本地转写启动失败）**、**本机调试端口（`127.0.0.1` `EPERM`）** 以及 **工作区外目录写入（如桌面、`~/.cache`）**。遇拦截时**严禁误判为缺少硬件或程序损坏**，先按当前宿主机制主动发起本机执行授权；**若当前会话明确禁止沙箱提权（例如受限的无工作区会话），绝不要让用户白回复“同意安装”空跑一轮**，直接配合上方清单用白话讲清“工具是否齐全＋当前窗口缺少本机操作权限”，并给出清晰下一步（如切换到已打开本地文件夹且允许本机执行的窗口，或改用 WorkBuddy／Antigravity，或确认改存当前已授权目录）。

## 2. 标准环境安装规格（获准后执行，同会话实路径复检）

- **官方 Google Chrome**：始终提供大陆免翻墙官方页 `https://www.google.cn/chrome/`；获准后可代装——macOS 已有 Homebrew 用 `brew install --cask google-chrome`（无 Homebrew 时可直接从官网下 `.dmg` 拖入“应用程序”，或提前说明装 Homebrew 需管理员密码），Windows 用 `winget install --id Google.Chrome -e`。
- **Node.js 22+**：已有实测通过的 WorkBuddy 内置 Node 直接复用其绝对路径；否则 macOS 用 `brew install node`，Windows 用 `winget install --id OpenJS.NodeJS.LTS -e`（装完直接定位 `%ProgramFiles%\nodejs\node.exe`，不依赖未刷新 `PATH`）。
- **Apple Silicon Mac（Python + 工具 + 完整 `mlx-whisper`）**：
  - 安装 `python@3.12` 与 `ffmpeg`（`brew install python@3.12 ffmpeg`）；
  - 若 `~/.local/bin/mlx_whisper` 或 `PATH` 尚无可用转写程序，建独立虚拟环境 `~/.cache/reach-tools/mlx-whisper` 安装 `mlx-whisper` 与 `yt-dlp`（避开 Homebrew PEP 668；慢则加 `-i https://pypi.tuna.tsinghua.edu.cn/simple`）；已有可用程序直接复用；
  - 下载 `mlx-community/whisper-large-v3-turbo`（约 1.6 GB）至 `~/.cache/reach-models/whisper-large-v3-turbo`（网络受限设 `HF_ENDPOINT=https://hf-mirror.com`）。
- **Windows x64（固定 Python 3.12 + 工具 + 完整 `faster-whisper` + `tzdata`）**：
  - 安装 **x64 Python 3.12**（`winget install --id Python.Python.3.12 -e`）与 `Gyan.FFmpeg`（`winget install --id Gyan.FFmpeg -e`），装完直接定位实际 `python.exe`、`ffmpeg.exe` 与 `ffprobe.exe` 绝对路径；
  - 建独立虚拟环境 `%USERPROFILE%\.cache\reach-tools\faster-whisper`，安装 `faster-whisper==1.2.1 ctranslate2==4.6.0 huggingface_hub yt-dlp tzdata`（慢则加清华源）；**主脚本 `$PYTHON` 统一使用该环境的 `python.exe`**，并在当前会话实测 `ZoneInfo("Asia/Shanghai")` 加载通过；
  - 下载 `mobiuslabsgmbh/faster-whisper-large-v3-turbo`（固定 revision `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`，约 1.6 GB，校验大小与 SHA-256）至 `%USERPROFILE%\.cache\reach-models\faster-whisper-large-v3-turbo`（网络受限设 `HF_ENDPOINT=https://hf-mirror.com`）。
- **可选声纹（不纳入首次必装）**：`~/.cache/reach-tools/pyannote-community-1` 与 `~/.cache/reach-models/pyannote-community-1` 为多人声纹选配项；未配不影响单人转写或多人问答语义分段交付。

## 3. 桌面浏览器（统一入口、三态探测与独立持久配置）

抖音／小红书批量清单和视频取源优先用 `"$NODE" "$SKILL_DIR/scripts/browser_collect.js"`（需 Node.js 22+；内置协议级静音、拦截 `bytedance://` 等外链弹窗，并在单次访问内同步带回主页昵称、详情页作者、发布日期与点赞）。**WorkBuddy 严禁改用宿主内置浏览器打开抖音页面**（会触发系统协议弹窗且可能残留标签页）；普通文章用能读正文的现有连接。**任何浏览器打开抖音前必须先落地为桌面页 `https://www.douyin.com/...`（`browser_collect.js` 会自动落地），严禁直接打开 `v.douyin.com`／`iesdouyin.com` 分享短链**。

**复用电脑现有 Chrome＋独立持久资料目录（桌面零图标，与 Skill 安装和缓存分离）**：
- 优先沿用本机已有的专用配置目录（如历史 `~/.cache/chrome-devtools-mcp/chrome-profile`）；新环境自动保存在系统持久应用目录——macOS 用 `~/Library/Application Support/HongshuCollect/chrome-profile`，Windows 用 `%LOCALAPPDATA%\HongshuCollect\chrome-profile`，清理缓存或升级 Skill 不丢登录态；启动器也放在该目录内，**绝不放桌面**。
- 首次配环境及需要拉起专用浏览器时，统一调用同一脚本入口（保留 Chrome 完整安全保护、默认静音、独立配置；**严禁擅自改用 `--headless`、`--no-sandbox` 或反复换参数试错**）：
  - 生成/更新启动器（首次配齐时随手执行一次）：`"$PYTHON" "$SKILL_DIR/scripts/media_common.py" env browser-launcher --chrome "<实测chrome路径>"`
  - 获用户同意后代开一次：`"$PYTHON" "$SKILL_DIR/scripts/media_common.py" env browser-launcher --chrome "<实测chrome路径>" --launch`

**先探测三态，再按三步呈现给用户**：先运行 `"$NODE" "$SKILL_DIR/scripts/browser_collect.js" probe`（已知调试地址可设 `REACH_CHROME_URL`）：
1. **`connected`（已连对专用实例）**：直接开工；**任务完结只关闭本次新建的临时标签页，绝不关闭或杀掉采集浏览器进程**，方便用户紧接着录清单里的视频时直接复用同一窗口。
2. **`needs_launch`（专用浏览器确实未开）**：先用白话征得用户同意一次（参考话术：“这次采集需要打开一个独立的 Chrome 窗口，可以帮你打开吗？采集期间可以最小化。如果接下来还要把清单里的视频转成文字，先留着这个窗口，两项都完成后就可以关了。”），获准后只调一次 `env browser-launcher --launch`；若仍返 `needs_manual_launch`，直接把返回的启动器路径做成对话内可点击链接请用户点开一次，不让用户翻文件夹或复制终端命令。
3. **`needs_permission`（窗口已开但当前助手缺连接权限）**：明确说明需要哪一项本机权限，**绝不再重复启动 Chrome 窗口**。

访问平台时，仅在明确跳至登录／验证页或出现遮挡目标内容的可见控件时，才返回 `needs_login` 或 `needs_verification`（**不把滑块验证误报为未登录**）并保留前台标签页与 `tab_id`；用户完成后带 `--tab <tab_id>` 从该页继续原链接并在完结后关闭。公开页免登可读时直接继续，`platform_logged_in` 保留 `null`（未知）；空白页、平台限制页或未加载按真实原因报错并关闭临时页。

## 4. 两项最小实跑验收与写入就绪记录（两项全过才标就绪）

首次配置完成后（**无论首单是列选题清单还是录视频，`list`/`media` 均会核验本机两项就绪状态**），在同一会话用实测确定的 `$NODE` 与 `$PYTHON` 逐条执行以下三步（两份临时凭证放系统临时目录如 `$TMPDIR`／`%TEMP%`，不建在桌面；若需访问本机端口、GPU 或写 `~/.cache`，按宿主正常机制说明用途一次申请）；若 Codex／Antigravity 等宿主已内置可用桌面 Chrome 通道，第 1 步也可用宿主桌面浏览器实际打开页面读回标题并写入同等校验凭证（`"channel":"host-browser"`，含 `status:"verified"`、`browser_connected:true`、`page_read_ok:true`、`file_write_ok:true`、`url_checked`、`page_title`）。三步通过后清理临时凭证并直接继续用户原任务：
```sh
"$NODE" "$SKILL_DIR/scripts/browser_collect.js" verify "<临时浏览器凭证.json>"
"$PYTHON" "$SKILL_DIR/scripts/media_common.py" env check --output-dir "<保存目录或临时测试目录>" --smoke --asr-proof "<临时转写凭证.json>"
"$PYTHON" "$SKILL_DIR/scripts/media_common.py" env mark-ready --browser-proof "<临时浏览器凭证.json>" --asr-proof "<临时转写凭证.json>" --agent "<当前Agent>" --chrome "<实测chrome路径>" --node "$NODE"
```
