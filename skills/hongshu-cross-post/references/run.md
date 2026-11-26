# 批次清单

单篇与多篇共用 items，每篇给 type、素材目录绝对路径和 targets。同一组目标可提到根部 targets，当篇提供的整组目标优先。小红书用 xhs，视频号用 channels，公众号贴图用 mp。脚本遵照清单顺序逐篇、逐端执行。

~~~json
{"items":[{"type":"photo","folder":"第一篇成品的绝对路径","targets":[{"platform":"douyin","scheduleAt":"YYYY-MM-DD HH:mm"},{"platform":"xhs","scheduleAt":"YYYY-MM-DD HH:mm"},{"platform":"mp","action":"draft"}]},{"type":"photo","folder":"第二篇成品的绝对路径","targets":[{"platform":"xhs"}]}]}
~~~

填北京时间的日期及分钟。可在整批、当篇或目标给 scheduleAt，按目标优先；预约目标需给有效日期。公众号没有预约，和预约混发时显式填 draft。立即发布省略时间，此时公众号默认直接发表（action 可省或填 publish/broadcast；已设 mp-photo 存草稿偏好或要存草稿则存草稿，额度用完转草稿，需扫码转可见窗续跑）。相同平台账号同一分钟不能安排两篇，相邻不足两小时会提醒。提交前会再读平台实际时间。

**图文**从制作记录及发布文案读标题、段落、顺序，无制作记录时取「发布文案.txt」首行为标题、其余行为正文，保留分段。正式图片按文件名末尾页码排序，排除总览；1–18 张，每张至多 10 MB，标题 20 字符以内，含话题正文 1000 字符以内。用当篇 title、body、topics 覆盖，topics 填裸话题数组。抖音默认无标题、无配乐、无声明；按清单填 includeTitle、declaration，music 可填歌名或含 title、artist、duration、source（search 或 favorites）的对象。小红书按作者授权使用 original。公众号存稿后从草稿箱重开核对，发表后查发表记录核对。

**视频**填当篇 title、body、topics、folder。文件夹内有多个视频或多套封面时填 video、portrait、landscape、wide。抖音用竖封面及 4:3；小红书、视频号用竖封面；B站用首页 4:3 和个人空间 16:9。B站保存后重开一次封面编辑器，分别比对两个比例的原图，退出后再核对主页面 4:3 封面。其他平台直接核对主页面对应槽位。任一必填封面不符，停止该项提交。视频号短标题填 shortTitle；小红书或视频号按授权填 declaration.value「原创声明」或「声明原创」，接受条款需作者授权后填 declaration.acceptOriginalTerms=true。B站独立填标签 topics、自制或转载及适用创作声明 declaration.category。简介可留空。

**执行**时从 Skill 目录运行 `sh scripts/run.sh run 任务.json`（Windows 用 `./scripts/run.ps1 run 任务.json`）。run 与 run --status 支持 --wait 0 至 60 秒，默认 55 秒。宿主超时短时可设 --wait 10。拿到 running 后按批次号续等；starting、running 表示后台尚在处理。扫码项延到批末，浏览器已关闭后用 run --resume 批次号集中验证。收到 login 时提醒本人在已打开的官网完成验证，再用 status 跟进。已提交未核实项只查，成功项自动跳过。批次行键形如 1-xhs-photo。查询示例为 query --batch 批次号 --item 1-xhs-photo 或 query --platform douyin --type photo --date YYYY-MM-DD；--local 仅读本机账本，官网提示需扫码才用 --login。后台清单按当前可见页报告。作品列表没见到时保持待核实。

## 偏好

| 平台与体裁 | 可记住的键及值 |
|---|---|
| `douyin-photo` | `includeTitle` 布尔值，`declaration` 为平台选项原文，`music` 为上文的歌名或配乐对象 |
| `xhs-photo` | `original` 布尔值 |
| `mp-photo` | `action` 仅接受 `"draft"` |

从 Skill 目录执行 `sh scripts/run.sh pref show` 查全部偏好，`sh scripts/run.sh pref set mp-photo '{"action":"draft"}'` 记住当前绑定账号的习惯，`sh scripts/run.sh pref clear mp-photo` 清除该账号的公众号贴图偏好。只按用户的明确指示保存，特别是小红书原创。仅对已授权使用该项的作品应用原创偏好，作者明确非原创时在目标写 original=false；若偏好开启小红书原创而页面未开放该开关，脚本自动按普通笔记发出并在结果中注明。每次命中要亮出具体值。更改对以后新批次生效，续跑沿用原批快照。明确需要再次分发已删除的稿件时，可在新清单增加不同的 batchTag 区分批次。CROSSPOST_HOME 存绑定、偏好、批次、提交账本和浏览器资料；CROSSPOST_DATA 只放本轮截图与缓存，换对话仍使用原 HOME。

## 只预览

预览使用旧单篇格式，由 start 启动，prepare 核对后 close。立即视频 mode=single-now，图文 mode=photo；定时格式 mode=scheduled 并使用 items。立即路径目标键是平台名，预约路径用平台-体裁。只预览时不要调用 submit。需测试清理时沿用对应测试会话和原始回执的散列。
