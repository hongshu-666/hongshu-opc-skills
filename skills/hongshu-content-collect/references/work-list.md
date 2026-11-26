# 账号选题清单

沿账号作品栏顺序收选题与原链接，按 ID 去重。包含账号的图文和视频，排除推荐、收藏与平台广告。首页顺序含置顶；只有用户明确指定其他范围或排序才调整。点赞只用页面明确标注的数值；日期按需补读一次，保留原样。时间范围须有已核实的发布日期。

## 采集与输出

下方 `$NODE` / `$PYTHON` 复用 `env status` 实测路径（PowerShell 用 `& $NODE` / `& $PYTHON`）。抖音／小红书用专用 Chrome 活动任务页翻页（抖音分享短链由脚本自动落地，禁直接扔给浏览器）。**过程文件与 `run.json`／`batches/` 统一放 `~/.cache/reach-tools/work/lists/<平台-账号标识>`，用户交付目录只放最终 `.md` 清单**；续做可用 `account_data.py status --for-list "<清单.md>" --records`。**采全部作品时不传条数上限**（仅明确说「最近 N 条」才在末尾传 `N`）；连续翻页无新增且页面无总数或见底提示时，核对当前位置一次即如实交付「实收 N 条，全量未确认」（可直接续选高赞，勿加高上限重翻）。B站沿用投稿列表；链接保留访问参数。

```sh
"$NODE" "$SKILL_DIR/scripts/browser_collect.js" list "<主页 HTTPS 链接>" "<缓存目录/过程批次.json>" [--tab <tabId>]
"$NODE" "$SKILL_DIR/scripts/browser_collect.js" covers "<缓存目录/过程批次.json>" "<缓存目录/covers>" --ids "<缺题ID1,ID2,...>"
"$PYTHON" "$SKILL_DIR/scripts/account_data.py" init --dir "<缓存目录>" --platform <douyin|xiaohongshu|bilibili> --homepage "<已核实主页>" [--count N]
"$PYTHON" "$SKILL_DIR/scripts/account_data.py" save --dir "<缓存目录>" --input "<缓存目录/过程批次.json>"
"$PYTHON" "$SKILL_DIR/scripts/account_data.py" export --dir "<缓存目录>" --clean-titles --output "<用户交付目录/博主名称-平台-选题清单-YYYY-MM-DD.md>"
```

**先在 `<过程批次.json>` 里一次通读题名、给确认记录置 `title_reviewed=true`，再执行 `account_data.py save` 与 `export`**（避免先 `save` 再返工修改已校验批次）。正常完整标题直接采用（不因略长误伤）；仅对空题、明显截断或把大段正文当标题的少数条目，**严禁逐篇弹开详情页**，改用上方 `covers` 批量生成带作品 ID 绑定的封面拼图看图补题（封面无清晰大字且有明确文案依据时再提炼短题标 `〔生成〕`，依据不足留待补）。清单文件名优先采用 `browser_collect.js list` 同步返回的 `source.account_name`；偶发读不到昵称时直接按“平台-账号标识”命名交付，**绝不为此另开其他浏览器**。默认按主页顺序导出；有确证日期或点赞需要按它排序时用 `--select` 和 `--sort`。日期可加 `--with-date`，只有证明为发布日才填「发布日期」。缺发布日时可按已确认的 `selected_ids` 保留主页顺序，汇报实际选集依据。

已有采集通道生成的批次可直接用同一保存入口。批次含 `source`（`url、column、observed_at、evidence`）及 `records`（`id、url、title、title_reviewed`；按需加 `likes_display、evidence.likes、published_display、date_kind`）。`notes` 字符串为普通备注，点赞未显示可记 `notes.likes`。
