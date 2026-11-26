# 微信公众号：桌面浏览器取源与解析

仅支持指定文章及多链接录入，沿用[共用文章流程](recording.md#文章正文公众号与知乎共用)。

## 桌面浏览器取 HTML 与解析准备

在桌面浏览器临时标签页打开目标公众号文章（免登已加载完整正文时直接保存，仅落入验证／登录页时弹到屏幕前提醒用户完成后回复“已登录”继续），将渲染后的完整页面 HTML（`document.documentElement.outerHTML`）保存至本地文件（单篇传 `--html`，多篇按序存至 `<过程目录>/item-01/article.html`、`item-02/article.html`…），再交确定性解析器处理：

```sh
"$PYTHON" "$SKILL_DIR/scripts/weixin_collect.py" prepare '文章链接' --output-dir '绝对路径' --work-dir '过程目录' [--html '单篇页面.html'] [--vault-root '授权查重根']
```

- 手头已有保存好的 `article.html` 时直接本地解析，不额外发网络请求；未预存 `article.html` 时脚本才回退命令行拉取（若返回 `status="needs_chrome"`，回到桌面浏览器补存 `article.html` 后带同一 `--work-dir` 复跑）。
- `existing` 命中后转入共用旧稿格式维护。解析器自动剔除重复标题、编辑栏及文末带明确引流动作的推广段，优先保留正文案例、个人署名及勘误说明。

## 标签确认与落盘

核读 `ready` 条目 `body.md` 与 `risk_flags` 后，写入标签决策 `{"items":[{"index":"01","tags":["主题"]}]}` 并完成保存回读：

```sh
"$PYTHON" "$SKILL_DIR/scripts/weixin_collect.py" finish --manifest 'manifest.json' --decisions 'decisions.json'
```

`finish` 校验正文 SHA-256 未被篡改并逐篇写入；受阻条目不阻塞就绪条目保存（返回码 `2` / `partial` 时如实汇报未完成项，不报整批完成）。
