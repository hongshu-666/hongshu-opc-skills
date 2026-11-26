# 图库、朋友圈与字幕
配置`gallery`指`assets[].id/source`原片清单。朋友圈/字幕/图解封面/长文封面共用配置旁`gallery-state.json`：已配图库时默认用图即使已有`background`/`cover`也须按编号领取、循环；必填`gallery_request`=主记录路径:选图次数，同次复用、换图加1。仅本次用户明确指定图（含首次试做先发来1张照片）才设`user_selected_photo: true`并提供对应图片路径，不从旧记录继承该标记；备忘录/图解仅正文/指定图不推进。新用户尚无图库时，凭1张指定照片即可先出首稿，等做第2、第3篇确实想轮换照片时再建议补齐5～10张高清原片建图库。测试另设`gallery_state`；同原片保留裁切、换原片清除旧裁切，采用号回主记录。
朋友圈/字幕短文顶部216px（1086宽基准）；文案超高才缩至100，不缩字，仍不够则分页。原片优先全景，不适配顺延，真字重。
朋友圈保头像至正文末行/昵称/格式/白底，去配图/UI；偏左、左右约5%安全边，完整露头发/脸/手势，余景居中。单轴只动该轴，放大注明锚点；不足调取景/换照。扩图获准才做，含旧扩图均回贴原片核衔接。
字幕躯干可遮、头脸不可遮；最终画布真实头脸整数半开框`face_keepout`与白底字条零相交；不适配换图/分页，不扩背景。

## 最小 `spec.json` 字段速查（免翻源码）
- **朋友圈**：`{"mode":"朋友圈","theme":"主题","version":"初稿01","title":"标题","source_text":"完整原文","publish_copy":"发布文案","screenshot":"/截图路径","crop":[x0,y0,x1,y1],"gallery_request":"/输出目录:1"}`（可选`placement:{"x":176,"width":1760}`、`background_crop`）
- **字幕**：`{"mode":"字幕","theme":"主题","version":"初稿01","title":"标题","source_text":"完整原文","publish_copy":"发布文案","face_keepout":[[x0,y0,x1,y1]],"gallery_request":"/输出目录:1"}`（可选`image_text`、`line_breaks`、`background_crop`）
> 无图库指定单照时，把`gallery_request`改为`"user_selected_photo": true, "background": "/照片路径"`。
