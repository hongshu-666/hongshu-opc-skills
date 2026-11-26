# 环境体检、首次字体配齐与跨工具交付

面向用户全程只说**日常白话**（严禁抛出 `Pillow`、`pillow-heif`、`PEP 668`、`venv`、`~/.config/...`、`~/.cache/...`、`env-ready.json`、`依赖`、`就绪记录` 等内部术语与路径）。覆盖 **macOS / Windows x64 / Linux**，**完全不依赖 Chrome 或任何浏览器**；首次验通哪套 `$PYTHON` 与字体，后续统一复用。

跨平台脚本命令：
- **macOS / Linux**：`"$PYTHON" "$SKILL_DIR/scripts/<脚本>.py" ...`
- **Windows PowerShell**（先设 `$env:PYTHONUTF8 = "1"`）：`& $PYTHON "$SKILL_DIR\scripts\<脚本>.py" ...`

## 1. 裸机只读体检与白话《环境准备清单》

默认按**全新裸机**标准自动完成只读探测：先查 `~/.cache/social-graphics-tools/env-ready.json`（Windows PowerShell 为 `$env:USERPROFILE\.cache\social-graphics-tools\env-ready.json`），记录有效且 `$PYTHON` 可执行、5 款共用必需字重已验通则直接放行。

- **第 0 步：探测真实可用 Python 3（≥ 3.10，零系统弹窗/零空壳）**：
  - **macOS**：依次检查 `~/.cache/social-graphics-tools/venv/bin/python` → `/Library/Frameworks/Python.framework/Versions/3.*/bin/python3` → `/opt/homebrew/bin/python3` → `/usr/local/bin/python3` → `~/.local/share/uv/python/*/bin/python3`；**仅 `xcode-select -p >/dev/null 2>&1` 返回 0 时**才测 `/usr/bin/python3`（防弹 Xcode 框）。
  - **Windows（PowerShell）**：依次检查 `$env:USERPROFILE\.cache\social-graphics-tools\venv\Scripts\python.exe` → `$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe` → `C:\Program Files\Python3*\python.exe` → `$env:APPDATA\uv\python\*\python.exe` → `py -3 -c "import sys; print(sys.executable)"`；**严禁采用含 `\WindowsApps\` 的微软商店空壳**。
  - 候选路径均须实测 `sys.version_info >= (3, 10)`。整机无可用 Python 3 时直接记“缺制图运行引擎（含基础运行环境）”，不强跑 `--env-check`；Windows/Linux 同时只读核查 `$env:USERPROFILE\.config\social-graphics\fonts\`（Linux 为 `~/.config/social-graphics/fonts/`），把缺的字体合并进下方一次白话清单。
- **第 1 步：引擎与字重自检**：有可用 Python 3 时运行 `--env-check`（macOS/Linux：`"$PYTHON" "$SKILL_DIR/scripts/render.py" --env-check`；Windows PowerShell：`& $PYTHON "$SKILL_DIR\scripts\render.py" --env-check`），一次校验制图引擎、5 款共用必需中文字重（3 黑体 + 2 宋体）及内存试排中文。
- **HEIC 按需处理**：新建虚拟环境时一并装 `pillow pillow-heif`；已有引擎仅缺苹果原照插件时，做纯文字或 JPG/PNG 直接放行，收到 `.heic` 再补装。

**确有缺项时，先甩下方白话《环境准备清单》一次说明缺项、用途与预计下载量并请用户同意（严禁静默安装），配齐验通后再请用户发内容**（已就绪项可标“已就绪”或只列缺项）：

| 分类 | 准备项 | 它是用来干嘛的 | 触发时机 |
|---|---|---|---|
| **必装 1** | 制图运行引擎（含基础运行环境） | 帮 AI 自动排版、裁图并导出高清图片（新配时自带苹果原照读取） | 缺基础环境或引擎时安装；收 `.heic` 时再按需补苹果原照插件 |
| **必装 2** | 五种版式共用中文字体 | 让中文排版清晰有粗细层次（Mac 自带免下载；Windows/Linux 免费下思源黑体 3 款 + 思源宋体 2 款约 47 MB，不入技能包） | 首次试排中文缺字重时一次配齐，后续切版式免再下 |
| **必装 3** | 成品输出能力 | 把做好的图片与 `发布文案.txt` 交给用户 | 按第 4 节当前工具能力自动适配 |
| **选配 1** | AI 生图工具 | 仅「扩图」或「图解配独立 AI 插画」用到 | 真正用到时再核验，首次不用装 |

## 2. 获准后标准一键安装与校验

1. **Python 3 + 独立虚拟环境（零 Homebrew / 避 PEP 668 与商店空壳）**：
   - **macOS 裸机无 Python 3**：优先用官方轻量 `uv`（免 Homebrew、零 Xcode 弹窗、当前会话即用且不依赖 venv 内置 `pip`）：
     1. `curl -LsSf https://astral.sh/uv/install.sh | sh`
     2. `"$HOME/.local/bin/uv" venv --python 3.12 "$HOME/.cache/social-graphics-tools/venv"`
     3. `"$HOME/.local/bin/uv" pip install --python "$HOME/.cache/social-graphics-tools/venv/bin/python" pillow pillow-heif -i https://pypi.tuna.tsinghua.edu.cn/simple`
     （网络不便再退选已有 `brew install python@3.12` 或 Python 官网安装包，再用该 Python `-m venv` + `-m pip install pillow pillow-heif`。）
   - **Windows 裸机无 Python 3（PowerShell）**：
     - 首选 `winget`：`winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements`；装完勿靠未刷新 `PATH` 敲 `python`，先将定位到的 `python.exe` 赋给 `$PY`：
       1. `$PY = if (Test-Path "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe") { "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" } else { "C:\Program Files\Python312\python.exe" }`
       2. `& "$PY" -m venv "$env:USERPROFILE\.cache\social-graphics-tools\venv"`
       3. `& "$env:USERPROFILE\.cache\social-graphics-tools\venv\Scripts\python.exe" -m pip install pillow pillow-heif -i https://pypi.tuna.tsinghua.edu.cn/simple`
     - 缺 `winget` 或商店源异常时改用官方 `uv` 备用方案（经用户同意后执行；`-ExecutionPolicy ByPass` 仅作用于该次安装进程，不改系统策略，且同会话直接可用、不依赖 venv 内置 `pip`）：
       1. `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
       2. `& "$env:USERPROFILE\.local\bin\uv.exe" venv --python 3.12 "$env:USERPROFILE\.cache\social-graphics-tools\venv"`
       3. `& "$env:USERPROFILE\.local\bin\uv.exe" pip install --python "$env:USERPROFILE\.cache\social-graphics-tools\venv\Scripts\python.exe" pillow pillow-heif -i https://pypi.tuna.tsinghua.edu.cn/simple`
   - 已有真实 Python 3 仅缺制图组件时，直接用该 Python 在 `~/.cache/social-graphics-tools/venv`（Windows PowerShell：`$env:USERPROFILE\.cache\social-graphics-tools\venv`）建虚拟环境并装 `pillow pillow-heif`；后续 `$PYTHON` 固定指向该虚拟环境绝对路径。
2. **中文字体（SIL OFL 1.1 免费商用、免管理员权限）**：
   - **macOS**：系统自带 `PingFang.ttc` + `Songti.ttc`，免下载。
   - **Windows / Linux**（或 `required_fonts_missing` 非空）：下至 `~/.config/social-graphics/fonts/`（Windows PowerShell：`$env:USERPROFILE\.config\social-graphics\fonts\`），**下载后必须逐个核对下表 SHA-256** 再试排中文：
     - macOS/Linux：`curl -fsSL --create-dirs "<直链>" -o "<目标>"` + `shasum -a 256 "<目标>"`（Linux 用 `sha256sum`）。
     - Windows PowerShell：优先 `curl.exe -fsSL --create-dirs "<直链>" -o "$env:USERPROFILE\.config\social-graphics\fonts\<文件名>"` + `(Get-FileHash "$env:USERPROFILE\.config\social-graphics\fonts\<文件名>" -Algorithm SHA256).Hash.ToLower()`；无 `curl.exe` 则用 `$PYTHON` 建目录并下载校验。
   - 清华镜像（大陆直连）：`https://mirrors.tuna.tsinghua.edu.cn/adobe-fonts/`；上游备源：`https://raw.githubusercontent.com/adobe-fonts/{source-han-sans,source-han-serif}/release/SubsetOTF/CN/<文件名>`。

| 文件名 | 版式 | 版本 | 字节 | SHA-256 校验值 | 清华镜像直链 |
|---|---|---|---:|---|---|
| `SourceHanSansCN-Regular.otf` | 全部 | 2.005 | 8429224 | `e2bc8a2e7f37474b774fff8db758681ece40bb6947a90d571bce9dd60671a8e4` | `https://mirrors.tuna.tsinghua.edu.cn/adobe-fonts/source-han-sans/SubsetOTF/CN/SourceHanSansCN-Regular.otf` |
| `SourceHanSansCN-Medium.otf` | 全部 | 2.005 | 8406556 | `a94e558a2fe972bee4f46bce0843abff37063fd68c33f1e7d9058f6f09432b01` | `https://mirrors.tuna.tsinghua.edu.cn/adobe-fonts/source-han-sans/SubsetOTF/CN/SourceHanSansCN-Medium.otf` |
| `SourceHanSansCN-Bold.otf` | 全部 | 2.005 | 8569308 | `62383707c086a32f3afd5e293f34c7eff64c7fea31f579fdc6cbe34d920519a6` | `https://mirrors.tuna.tsinghua.edu.cn/adobe-fonts/source-han-sans/SubsetOTF/CN/SourceHanSansCN-Bold.otf` |
| `SourceHanSerifCN-Regular.otf` | 长文 | 2.003 | 11626108 | `3754ea669c530e2473354f8f6d9f79680a44d7e26ec7d00eeabee4a7e0753c5d` | `https://mirrors.tuna.tsinghua.edu.cn/adobe-fonts/source-han-serif/SubsetOTF/CN/SourceHanSerifCN-Regular.otf` |
| `SourceHanSerifCN-Bold.otf` | 长文 | 2.003 | 12094680 | `4ee555ae58b3d22f6a95c2c494f2c36b7cccfc1d2224635f6461a03756f0e3c1` | `https://mirrors.tuna.tsinghua.edu.cn/adobe-fonts/source-han-serif/SubsetOTF/CN/SourceHanSerifCN-Bold.otf` |

## 3. 试排验收与写入就绪记录

安装后运行自检（macOS/Linux：`"$PYTHON" "$SKILL_DIR/scripts/render.py" --env-check`；Windows PowerShell：`& $PYTHON "$SKILL_DIR\scripts\render.py" --env-check`），确认 `ready=true`、`chinese_trial_ok=true` 且 `required_fonts_missing=[]` 后，将 `$PYTHON`、字体目录及当前工具名写入 `~/.cache/social-graphics-tools/env-ready.json`（Windows PowerShell：`$env:USERPROFILE\.cache\social-graphics-tools\env-ready.json`）并立即开工。

## 4. 跨工具与沙箱交付适配

- **可写本地目录**：默认保存到桌面（或 `personal.json` 的 `output_dir`），交付 PNG、多图 `总览.png` 与 `发布文案.txt`。
- **桌面沙箱拦截**：先按宿主申请权限；若仅能写工作区或云端容器，直接交付可下载 PNG 与 `发布文案.txt`，**未写桌面绝不宣称“已保存到桌面”**。
- **纯聊天框无 Python**：白话说明不支持本地画图，建议换支持代码执行的桌面或云端工具。
