# 账号与环境

普通账号从本人创作后台扫码，按当前页面核对实名与投稿权限。公众号贴图网页扫码，免配 API 或白名单。企业代发需独立获批，本 Skill 走网页。

创作后台：[抖音](https://creator.douyin.com/)、[小红书](https://creator.xiaohongshu.com/new/home)、[B站](https://member.bilibili.com/platform/home)、[视频号助手](https://channels.weixin.qq.com/)。

开放能力依据：[抖音适用范围](https://developer.open-douyin.com/docs/resource/zh-CN/dop/operation-standard/platform-capabilities/usage-spec/)、[B站](https://openhome.bilibili.com/doc)、[小红书](https://agora.xiaohongshu.com/doc/js)、[视频号](https://developers.weixin.qq.com/doc/channels/api/channels/)。

## 启动排错

缺 Chrome 时给学员大陆官方中文页 https://www.google.cn/chrome/ ，同意后协助安装。CLI 优先复用 WorkBuddy 内置 Node（需 20 或以上）；依赖缺失时用 setup 按锁文件安装 playwright-core，官方源失败时回退国内镜像，然后重新 env status。macOS 与 Windows 首装均已实测。保留 CROSSPOST_HOME 的专用登录资料，避开日常浏览器。
WorkBuddy 若提示沙箱阻止启动，说明原因，获准后选「仅本次允许」在 WorkBuddy 沙箱外启动；Chrome 自身沙箱保持开启。macOS 若单列共享目录中的 RlzStore.plist，按当次获准范围处理。

## 测试清理

仅在明确授权留证后删测试稿时使用。用可区分的标题和唯一 testBatch，公众号测试只存草稿。立即视频在 job.cleanup 填 perPlatform=true、receiptDir（桌面绝对路径）、channelPlayerEvidence=true；若用户指定等全齐才删，用 afterAllReceipts=true。图文、定时任务把 receiptDir 放任务根。定时稿选留有撤回时间的合法时刻。
逐张打开 desktop 回执，核实非空白且包含本稿身份、时间和状态。视频号可用同稿列表和播放器两图核实时长。保留 approval，把 seen 中该目标的值换为 desktop 各图的 sha256 数组（按原顺序），运行 `clean 会话 目标 清理.json` 并刷新核对同稿消失。保护既有同名稿。B站如需本人验证，完成后用 clean 续查同一 BV 号。中断若产生本地草稿，仅在核实属本轮且已授权时处理。
