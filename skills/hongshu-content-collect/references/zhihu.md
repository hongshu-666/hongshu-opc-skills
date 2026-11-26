# 知乎：回答与文章录入

支持指定回答／文章直链、多链接及关键词高赞选录，沿用[共用文章流程](recording.md#文章正文公众号与知乎共用)。

## 选集规则

- **指定链接**：直接用内置直读入口通过已就绪的专用桌面 Chrome 后台静默读取指定回答（`/question/<问题ID>/answer/<回答ID>`）或专栏（`zhuanlan.zhihu.com/p/<ID>`），脚本会严格按目标 ID 锁定当前回答容器（多回答页绝不误抓其他回答），输出 `title`、`author`、`published`、`like_count`、`body` 到缓存 JSON；无需临场手写读取脚本（若给问题页 URL，先确认目标回答直链，禁用问题页 URL 冒充）：

```sh
"$NODE" "$SKILL_DIR/scripts/browser_collect.js" article "<知乎回答或专栏 HTTPS 直链>" "<缓存目录/zhihu-article.json>" [--tab <tabId>]
```

- **受限与登录处理**：按脚本返回的实际页面状态提示（`needs_login` 保留前台扫码页，用户确认后带 `--tab` 继续；`site_restricted` 如实报告错误码与限制，不把 `40362` 一律误判为未登录；若确需登录可引导用户打开返回里的 `signin_url` 扫码确认后复试，仍受限则记该篇受阻并继续其余条目）。
- **关键词高赞**：未另定范围时，从前 30 个相关可打开候选中按可核验赞同数降序选 5 篇（同赞保搜索顺序，保留原赞同显示值；已有或受限项在候选池内顺延并说明缺口）。

## 统一门禁落盘与旧稿处理

核对读取到的全文后，将缓存里的元数据与纯正文交给共用命令生成规范七字段成稿并回读校验：

```sh
"$PYTHON" "$SKILL_DIR/scripts/media_common.py" save-note --meta "<meta.json>" --body "<body.txt>" --output-dir "<正式目录>"
```

`meta.json` 包含 `url`、`platform: "知乎"`、`title`、`author`、`published`、`like_count`（赞同原值或空）、`content_type: "图文"`、`tags`（1–2 个主题词）。维护旧稿时，旧 `保存形式: 全文` 可作完整性依据之一（新稿不再写该字段）；摘要或纯链接稿仅在确认授权且备份原件后补齐全文。
