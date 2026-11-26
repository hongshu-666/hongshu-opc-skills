# 图解
论证/案例能提炼清晰视觉模型且“盖住正文只看图形就能秒懂70%”才用`图解`；精髓在原话语感/故事复盘或拿不准时默认改用`长文`（中短口语用`备忘录`）。全套原生`2160×2880`暖米白（`#FAF8F4`）画布，系统无衬线（苹方/微软雅黑/思源黑体）。
封面：纯文字对称刊头（不加徽标胶囊装饰），`title_lines`为1–2行语义标题（去逗号感叹、首行深炭黑/次行赤陶橙，自动适配版心），可选单行`cover_subtitle`（空串关闭），下方高清内描边封面照。
内页：`pages[]`含`title`（可选正整数`number`，无编号标“前言”；同章续页沿用）、`upper`段数组、`diagram`图形、`lower`段数组及`marks`重点原句数组（文内半高暖杏荧光笔，不设底部结论条）。所有内页`upper`+`lower`须逐字承接完整原文（严禁未经同意删段、掐头去尾、跳过开场白或删去首句只留页标题；仅`diagram`框内短标签可提炼，仅获准精简才存`image_text`）。
内置多元`diagram.kind`（按页义选型，相邻两页默认不重复同一种`kind`，拒通篇单调方框）：`columns`（`items[].title/sub/highlight`无框大数字分栏，可选`caption`）、`versus`（`left`/`right`含`tag/title/sub`及`op`正反对账）、`funnel`（`layers[].title/note`倒梯形转化漏斗）、`timeline`（`items[].title/sub/highlight`横向圆点轨道）、`venn`（`items`两或三圆要素交集于`center`靶心）、`bars`（`cols[].header/value/sub/ratio/highlight`阶梯柱图，同单位真实数值由脚本按数值自动计算柱高，绝不把下降画成上升；无客观可比数值的内容严禁用`bars`，改用`columns`或`timeline`）、`cycle`（`items[].title/highlight`围绕`center`环形飞轮）、`branch`（`root`分叉至`branches[]`）；独立插图传`diagram.image`并记提示词。关系、对象、单位与数值须严格依原文，出图前用`scripts/render.py --check --spec 输入.json`做数字与对象回查。
排版按上下正文与图形高度自适应留白，按上4下6黄金视觉重心排布，严禁文字压线或底部悬空断层。

## 最小 `spec.json` 字段速查（免翻源码）
```json
{
  "mode": "图解", "theme": "主题", "version": "初稿01",
  "title": "完整标题", "publish_title": "完整标题", "title_lines": ["首行黑字", "次行橙字"],
  "source_text": "上段原句重点\n\n下段", "publish_copy": "≤1000字发布文案", "gallery_request": "/输出目录:1",
  "pages": [{"number": 1, "title": "章题", "upper": ["上段原句重点"], "diagram": {"kind": "versus", "op": "VS", "left": {"tag": "误区", "title": "旧做法", "sub": "简述"}, "right": {"tag": "正解", "title": "新做法", "sub": "简述"}}, "lower": ["下段"], "marks": ["原句重点"]}]
}
```
> 无图库指定封面照改为`"user_selected_photo": true, "cover": "/照片路径"`；无封面纯内页省去`gallery_request`/`cover`。
