# 视频与图文采集细则（抖音／B站／小红书）

**免登可读直采、受阻再扫码、本地脚本处理**：先直取元数据、完整字幕或同篇播放流（免登可读可下即直接处理，仅被登录／验证拦停无数据时弹扫码页提醒“已登录”续跑）；已有本地媒体、字幕或草稿直接续做。获取预算最多 4 次（每路最多 2 次，支持 `B→A→B→A`）；仅付费／会员／404 删除标 `blocked`。

下方 `$NODE` / `$PYTHON` 复用 `env status` 实测路径（PowerShell 用 `& $NODE` / `& $PYTHON`）。**过程文件、凭证、分片与草稿统一落 `~/.cache/reach-tools/work/`，用户交付目录只放最终 `.md` 成稿**。抖音／小红书用 `"$NODE" "$SKILL_DIR/scripts/browser_collect.js" media "<作品 HTTPS 链接>" "<缓存目录/媒体凭证.json>" [--tab <tabId>]` 静音一次取齐 ID、主播放器、时长、播放流与可见元数据（`title`、`author`、`published`/`published_display`/`date_kind`、`like_count`），合入同篇 `source.json` 交 `prepare`——**元数据已齐勿在可见浏览器二次播片**；详情页缺字段时优先保留同篇清单证据；媒体二进制不进模型。

## 抖音

优先直接用上方 `browser_collect.js media` 静音一次取齐播放流与标题／作者／发布日期／点赞数（支持 `/video/<id>` 与 `/note/<id>`；免登已能播放取流则直接处理，仅被登录墙拦住无流时再提醒扫码）。**严禁对抖音网页链接跑裸 `yt-dlp`（必返 403），也不要对 `blob:` `<video>` 调 `downloadMedia()`**。

将同篇凭证 `videos、duration、audioUrls` 与 `id、url、title、description、author、published、like_count、content_type、output_dir` 写入 `source.json`；可信本地输入填 `media`，图文可带 `image_texts`。

```sh
"$PYTHON" "$SKILL_DIR/scripts/douyin_collect.py" prepare --source "<source.json>" [--work-dir "<过程目录>"] [--output-dir "<正式目录>"] [--speakers]
"$PYTHON" "$SKILL_DIR/scripts/douyin_collect.py" diarize --manifest "<manifest.json>"
"$PYTHON" "$SKILL_DIR/scripts/douyin_collect.py" retry-excerpt --manifest "<manifest.json>" --clip <起秒> <止秒>
"$PYTHON" "$SKILL_DIR/scripts/douyin_collect.py" finalize --manifest "<manifest.json>" --reviewed "<reviewed.txt>" [--output-dir "<正式目录>"] [--verified-silence] --tags "<主题>"
```

- **归属优先与单页快车道**：`prepare` 先对目标目录按 ID 查重（过程文件默认存于 `~/.cache/reach-douyin/<id>`），再锁定唯一主播放器、剔除 `__vid` / `video_id` 冲突源，优先拉取主播放器归属源，干净单页回退同源独立音轨（强制 `ffprobe` 校验含音轨且 `≤0.6s` 时长一致）。
- **页内导出备选**：仅当直链均返回 `status="needs_media" (route="B")`、且宿主支持工具侧将返回值直接写盘不进模型上下文时，执行 `media_common.py acquisition begin <manifest.json> --route B`，运行已自动生成的 `media.js` 直存 `browser-media.json`（不支持文件直存则 `acquisition skip` 记缺口），再运行 `douyin_collect.py import-media --payload "<browser-media.json>" --output "<import_target>"` 后复跑 `prepare`。

## B站

仅采集投稿视频（自动解析 `b23.tv` 短链并规范化 `BV/av + p`，无 p 为 P1）。单条视频可直接运行 `prepare`（免登自动走现成字幕快车道与 `yt-dlp` 公开拉取；也可传入桌面浏览器核实的字幕或播放流）：

```sh
"$PYTHON" "$SKILL_DIR/scripts/bilibili_collect.py" prepare [--work-dir "<缓存过程目录>"] --output-dir "<正式目录>" [--subtitle "<字幕文件>"] [--media "<本地音视频>"] [--info-json "<同篇元数据.json>"] [--speakers] "<本篇链接>"
"$PYTHON" "$SKILL_DIR/scripts/bilibili_collect.py" diarize --manifest "<manifest.json>"
"$PYTHON" "$SKILL_DIR/scripts/bilibili_collect.py" retry-excerpt --manifest "<manifest.json>" --clip <起秒> <止秒>
"$PYTHON" "$SKILL_DIR/scripts/bilibili_collect.py" finalize --manifest "<manifest.json>" --reviewed "<reviewed.txt>" [--verified-silence] --tags "<主题>"
```

- **字幕优先与按需补音**：完整中文字幕（优先人工 `zh-CN` 等 `.srt / .vtt / .json3`）直出 `asr.json` 与 `draft.txt` 免转写；仅当后续需 `diarize` 声纹或字幕存在长缺口需 `retry-excerpt` 时按需取同篇原音。`--work-dir` 省略时默认落入 `~/.cache/reach-tools/work/bilibili`。

## 小红书

在桌面浏览器读取笔记页元数据与内容写入缓存目录里的 `source.json`（含 `url`、`title`、`author`、`text`、`published`／`published_display`／`date_kind`［小红书 `编辑于` 视为发布日期，去掉前缀与 IP 属地写入 `published`：有年份写 `YYYY-MM-DD` 并用于文件名，无年份原样留 `MM-DD`、禁猜年份、文件名用录入日；过程记录保留原文与 `date_kind`］、`like_count`、`content_type`、`output_dir`），核实 24 位 ID（兼容 `/explore/`、`/discovery/item/`、`/user/profile/<uid>/<id>`）。即使页面浮出登录遮罩，只要页面 DOM、主播放器或同篇 `performance` 资源已含完整正文／媒体地址就直接免登采集（视频填 `stream_urls` 或 `media`，图文可附 `image_texts` 与 `expected_image_count`）：

```sh
"$PYTHON" "$SKILL_DIR/scripts/xiaohongshu_collect.py" prepare --source "<缓存目录/source.json>" [--work-dir "<缓存过程目录>"] [--speakers]
"$PYTHON" "$SKILL_DIR/scripts/xiaohongshu_collect.py" diarize --manifest "<manifest.json>"
"$PYTHON" "$SKILL_DIR/scripts/xiaohongshu_collect.py" retry-excerpt --manifest "<manifest.json>" --clip <起秒> <止秒>
"$PYTHON" "$SKILL_DIR/scripts/xiaohongshu_collect.py" finalize --manifest "<manifest.json>" --reviewed "<reviewed.txt>" [--verified-silence] --tags "<主题>"
```

## 共用浏览器直链落盘工具

在桌面浏览器确认同 ID 作品播放流地址后，也可直接整文件下载校验并写入对应状态文件（**抖音与小红书传 `source.json`，B站传 `<过程目录>/<BV>-p<P>/manifest.json`**；支持首次即记 `--route B`），随后交各平台 `prepare` / `retry-excerpt` / `diarize` 接着处理：

```sh
"$PYTHON" "$SKILL_DIR/scripts/media_common.py" fetch-media \
  --url "<主直链>" [--url "<备直链>"] --platform <xiaohongshu|bilibili|douyin> --route B \
  --output "<过程目录>/media.mp4" --state "<抖音/小红书 source.json 或 B站 manifest.json>" [--info-json "<同篇元数据.json>"] --require-audio [--expected-duration <秒>]
```
