# 洪树 OPC AI Skills

聚焦 AI 超级个体，一个人在家用 AI 赚点小钱。—— 洪树自研自媒体工作流 AI 技能库

5 项原创开源 Skill · MIT License · [官网一键下载](https://hongshuskill.pages.dev/)

> [!TIP]
> **如果你不熟悉 Git / 命令行，或者因为网络环境不方便稳定访问 GitHub**：
> 请直接前往官网 **[https://hongshuskill.pages.dev/](https://hongshuskill.pages.dev/)** 一键下载单项或全部 29 项技能的 ZIP 压缩包，无需登录 GitHub，直连即可顺畅下载。

---

## 技能总览

本仓库收录洪树已打磨完成并公开开源的 **5 项自研自媒体核心 Skill**：

| 技能名称 | 目录与说明 | 版本 | 核心用途 | 适用平台 / 输入 |
|---|---|---|---|---|
| **洪树 · 口喷式写作** | [skills/hongshu-talk-to-write](skills/hongshu-talk-to-write/SKILL.md) | `0.0.5` | 保住原汁原味口语感，去啰嗦、顺逻辑并单独列核查结果 | 语音转写稿 / 口述文字 |
| **洪树 · 一键采集** | [skills/hongshu-content-collect](skills/hongshu-content-collect/SKILL.md) | `0.5.4` | 采集作品选题清单，并将视频/图文/文章转为干净 Markdown | 抖音 / B站 / 小红书 / 微信公众号 / 知乎 |
| **洪树 · 一键拆号** | [skills/hongshu-account-analysis](skills/hongshu-account-analysis/SKILL.md) | `0.0.5` | 深度分析单账号内容主题、产品、用户反馈、人群与人设 | 公开自媒体账号（搭配一键采集或已有文稿） |
| **洪树 · 一键图文** | [skills/hongshu-social-graphics](skills/hongshu-social-graphics/SKILL.md) | `0.11.9` | 自动匹配 5 种版式，先出预览图再导出 2160×2880 高清图文与文案 | 小红书 / 小绿书 / 抖音 |
| **洪树 · 一键分发** | [skills/hongshu-cross-post](skills/hongshu-cross-post/SKILL.md) | `0.5.2` | 跨平台批量发布视频和图文、定时预约、公众号发表或存草稿 | 抖音 / 视频号 / 小红书 / B站 / 微信公众号 |

---

## 推荐组合工作流

```text
【选题与对标研究】
  一键采集 (hongshu-content-collect) ──▶ 一键拆号 (hongshu-account-analysis)
     采集主页前100条清单 + 高赞正文/逐字稿        输出账号结构、产品、人群与人设拆解报告

【内容生产与多平台发布】
  口喷式写作 (hongshu-talk-to-write) ──▶ 一键图文 (hongshu-social-graphics) ──▶ 一键分发 (hongshu-cross-post)
     语音转写稿去重顺逻辑 + 事实核查             自动选版式预览并生成高清多页图文           批量预约/分发 + 公众号草稿或发表
```

---

## 安装方式

支持 Codex、Claude Code、Antigravity、WorkBuddy、豆包等支持本地文件与 Skill 规范的智能体工具。

### 方式一：官网下载压缩包（最适合非技术创作者）

1. 打开 **[https://hongshuskill.pages.dev/](https://hongshuskill.pages.dev/)**，选择单项技能或整包下载 ZIP 压缩包。
2. 将压缩包完整解压到容易找到的目录（例如桌面）。
3. 打开你的智能体软件，把解压后的文件夹拖进对话框（或告诉它文件夹路径），直接发送下面这句话：

```text
请读取这个文件夹里的安装说明，帮我把Skill安装到你能使用的位置。需要我操作的地方，请告诉我。
```

### 方式二：CLI 一行命令安装（开发者 / 终端用户）

安装仓库内全部 5 项技能：

```sh
npx skills add hongshu-666/hongshu-opc-skills
```

或按需安装单个技能：

```sh
npx skills add hongshu-666/hongshu-opc-skills --skill hongshu-talk-to-write
npx skills add hongshu-666/hongshu-opc-skills --skill hongshu-content-collect
npx skills add hongshu-666/hongshu-opc-skills --skill hongshu-account-analysis
npx skills add hongshu-666/hongshu-opc-skills --skill hongshu-social-graphics
npx skills add hongshu-666/hongshu-opc-skills --skill hongshu-cross-post
```

### 方式三：Git Clone 手动安装

```sh
git clone https://github.com/hongshu-666/hongshu-opc-skills.git
```

将 `skills/` 下需要的技能目录复制到你的 Agent 用户级技能目录中即可（`hongshu-account-analysis` 如需现场采集，请同步安装 `hongshu-content-collect`）。

> [!NOTE]
> **关于 Chrome 浏览器准备**：`一键采集`、`一键拆号` 和 `一键分发` 需要配合**官方原版 Google Chrome** 运行。请务必从官方入口安装，避免使用第三方捆绑安装包：
> - 官方中文入口：[https://www.google.cn/chrome/](https://www.google.cn/chrome/)
> - 官方国际入口：[https://www.google.com/chrome/](https://www.google.com/chrome/)

---

## 分项技能介绍与使用示例

### 1. 洪树 · 口喷式写作（`hongshu-talk-to-write`）

📄 完整说明：[skills/hongshu-talk-to-write/SKILL.md](skills/hongshu-talk-to-write/SKILL.md)

直接把想法用语音说出来，它帮你删掉啰嗦、顺一下逻辑、核查拿不准的数据，原汁原味保住你自己的口语感，绝不改出一股 AI 味，写完直接就能拍口播。

- **只做 4 件事**：去重复啰嗦、纠错字错词、顺倒置逻辑、补标点分段。
- **严格克制**：不做额外书面润色、不随便改掉口播习惯用语、不替作者强加观点；默认不打断追问。
- **核查与补全分离**：如正文涉及可疑数据、专有名词或口述中提到需要查证的内容，会在正文下方单独按编号列出权威来源多方核对结论与口播建议改法，不直接篡改原稿。

**直接对 AI 这样说：**

> 我来说，你帮我整理成一篇保留我语气的口播稿。

**使用前准备：** 需要 Agent 能读取文本或你发送的语音转写稿。

---

### 2. 洪树 · 一键采集（`hongshu-content-collect`）

📄 完整说明：[skills/hongshu-content-collect/SKILL.md](skills/hongshu-content-collect/SKILL.md)

自动把抖音、B站、小红书、公众号和知乎的视频图文提炼成干净的逐字稿和文稿，顺手打好标签，批量存进你的素材库或知识库，平时攒灵感特别好用。

- **两类任务**：
  - **作品选题清单**：沿账号作品栏采集、去重并导出汇总表（记录标题、点赞、形式与链接）。
  - **内容录入成稿**：提取视频音频并本地语音转写为完整逐字稿（支持按需开启多人对话声纹识别），或忠实抓取图文、公众号文章与知乎回答，统一输出含 7 项属性的标准化 Markdown 文件。
- **去重与增量**：按平台 + 作品 ID 自动判重，支持按批指定最新或新增篇数，也支持维护已有文稿元数据。

**直接对 AI 这样说：**

> 把这条B站视频采集、转写并保存为Markdown到我指定的目录。

**使用前准备：** 覆盖 Apple Silicon Mac 与 Windows x64（OpenAI 桌面端请使用 Codex 模式）。需要官方原版 Chrome；首次触发时 Agent 会列出环境准备清单并引导配齐本地 Python / Node 与转写依赖（多人声纹识别按需选配）。

---

### 3. 洪树 · 一键拆号（`hongshu-account-analysis`）

📄 完整说明：[skills/hongshu-account-analysis/SKILL.md](skills/hongshu-account-analysis/SKILL.md)

遇到想学的对标账号，发给它就能把对方的主页、高频选题、目标人群、人设和卖的产品摸透，直接出完整拆解报告。非常适合搭配「一键采集」一起用，研究同行特别省时间。

- **结构化五部分报告**：固定按「账号信息 → 产品分析 → 用户反馈 → 人群分析 → 人设分析」输出，可追踪到具体作品和原始位置。
- **扎实样本口径**：整理主页信息、默认近 100 条作品清单统计占比与点赞中位数，并通读至少 10 篇完整作品正文/逐字稿，再补查公开产品页与用户反馈，不凭标题猜结论。

**直接对 AI 这样说：**

> 用一键拆号分析这个账号，整理主页、近100条作品、至少10篇完整内容，以及产品、用户反馈、人群和人设。

**使用前准备：** 如需新采集账号数据，请一并安装 `hongshu-content-collect` 并准备对应平台登录好的浏览器；已有完整文稿可直接开始分析。作品点赞统计需要 Python 3；如需写入飞书文档与电子表格，需已配置对应飞书能力。

---

### 4. 洪树 · 一键图文（`hongshu-social-graphics`）

📄 完整说明：[skills/hongshu-social-graphics/SKILL.md](skills/hongshu-social-graphics/SKILL.md)

把文案发给它，会自动看懂内容帮你匹配合适的图文风格，也能展示多种风格样图让你挑。先出预览图确认，再导高清图并配好发布文案，非常适合搭配「一键分发」一起用。

- **5 种实用版式自动匹配**：朋友圈截图风、电影字幕风、对比/流程/数值图解风、手机备忘录纯文字风、深度长文分页风。
- **先预览、再出高清**：首轮先生成轻量总览预览图确认版式、封面照和文案，确认后再导出 2160×2880 高清 PNG 与配套发布文案，且全程不改动你原本的核心文字语感。
- **免浏览器纯本地渲染**：不依赖 Chrome，发来文字、文档或清晰截图即可开始。

**直接对 AI 这样说：**

> 把这段内容做成适合小红书或抖音的图文，按内容帮我选最合适的版式，先出预览图给我看。

**使用前准备：** 支持 macOS、Windows x64 与 Linux。需要 Python 3、Pillow 及必需中文字体（macOS 自动复用系统字体；Windows/Linux 缺失时按提示获取思源字体；处理 HEIC 照片按需补 `pillow-heif`）；仅需要 AI 扩图或生成配图时才需另配生图能力。

---

### 5. 洪树 · 一键分发（`hongshu-cross-post`）

📄 完整说明：[skills/hongshu-cross-post/SKILL.md](skills/hongshu-cross-post/SKILL.md)

自动帮你把视频或图文发到抖音、小红书、B站、视频号和公众号，支持多条批量发、也能设定时。如果你每天要发的内容比较多，这个会非常省事。

- **覆盖视频与图文**：支持多条视频发往抖音、视频号、小红书、B站；支持按页排序的图文发往抖音、小红书以及微信公众号（支持直接发表或存草稿箱）。
- **批量、定时与跨对话追踪**：可设定时预约排期、支持只预览不提交确认画面，执行中断或扫码后可按批次号续跑，并支持随时查询后台排期、草稿和发表回执。

**直接对 AI 这样说：**

> 把这两篇图文分别预约到明天和后天中午十二点发小红书，两篇也都存进公众号草稿箱。

**使用前准备：** 准备已完成创作者后台登录的官方原版 Chrome、Node.js 20+ 与可运行本地脚本的 Agent；首次使用时按引导绑定本机环境与平台账号即可。

---

## 更多技能与关注洪树

- **完整 29 项技能工具箱**：前往 **[https://hongshuskill.pages.dev/](https://hongshuskill.pages.dev/)** 下载完整技能包，除上述 5 项自研核心技能外，还收录了精选的飞书办公、Obsidian 知识库、PPT 生成、文案去 AI 味、网页正文提取与效率工具，以及对应第三方原始许可证。
- **关注洪树获取教程与更新**：
  - 抖音：[洪树的抖音主页](https://www.douyin.com/user/MS4wLjABAAAAJkMFatR9HAnpypRQCs3P5xOeGZjfCGys5IvUeAzTpWbHND7EVPjtEcfMKWkj3fTs)
  - 小红书：[洪树的小红书主页](https://www.xiaohongshu.com/user/profile/62cadf51000000000303fe09)
  - 视频号：搜索“洪树同学”
  - B站：[洪树的 B 站空间](https://space.bilibili.com/21124495)

---

## 开源协议与合规说明

- 本仓库采用 **[MIT License](LICENSE)** 开源（`Copyright (c) 2026 洪树 (Hongshu)`），你可以自由使用、修改与分发，请保留原始版权与许可声明。
- 使用采集或自动分发类 Skill 时，请仅用于本人合规授权账号及公开可见资料整理，遵守各内容平台服务协议与相关法律法规。
