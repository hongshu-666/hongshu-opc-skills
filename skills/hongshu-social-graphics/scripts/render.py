#!/usr/bin/env python3
"""Render social graphics."""
import argparse
from datetime import datetime, timedelta, timezone
import io
import json
import math
import os
import re
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, features
    PIL_OK = True
    RAQM = features.check('raqm')
except ImportError:
    Image = ImageDraw = ImageFilter = ImageFont = ImageOps = features = None
    PIL_OK = False
    RAQM = False

W, H = 2160, 2880
ROOT = Path(__file__).resolve().parent.parent
USER_FONTS = Path('~/.config/social-graphics/fonts').expanduser()
CLOSING, OPENING = '，。；：！？、）】》”’〉〕］｝,.!?;:%', '（【《“‘〈〔［｛('
WIN_FONTS = Path(os.environ.get('WINDIR', 'C:/Windows'))/'Fonts'
LINUX_FONT_DIRS = ('/usr/share/fonts', '/usr/local/share/fonts', '~/.local/share/fonts', '~/.fonts')


def find_font(candidates, globs=()):
    for item in candidates:
        p, idx = item if isinstance(item, tuple) else (item, 0)
        if p and Path(p).is_file():
            return str(p), idx
    for root, pattern, idx in globs:
        base = Path(root).expanduser()
        if base.is_dir():
            hit = next(iter(sorted(base.rglob(pattern))), None)
            if hit and hit.is_file():
                return str(hit), idx
    return None, 0


def discover_fonts(win_fonts=WIN_FONTS, linux_dirs=LINUX_FONT_DIRS, mac_root=Path('/System/Library'),
                   user_fonts=USER_FONTS):
    mac_pf = find_font([(mac_root/'Fonts/PingFang.ttc', 0)], [(mac_root/'AssetsV2', 'PingFang.ttc', 0)])[0]
    sans_reg = find_font(
        [(mac_pf, 3),
         (user_fonts/'SourceHanSansCN-Regular.otf', 0), (user_fonts/'SourceHanSansSC-Regular.otf', 0),
         (win_fonts/'msyh.ttc', 0), (win_fonts/'msyh.ttf', 0), (win_fonts/'simhei.ttf', 0)],
        [(d, pat, idx) for d in linux_dirs for pat, idx in (
            ('NotoSansCJK-Regular.ttc', 2), ('NotoSansCJKsc-Regular.otf', 0),
            ('SourceHanSansSC-Regular*.otf', 0), ('SourceHanSansCN-Regular*.otf', 0),
            ('wqy-microhei.ttc', 0), ('wqy-zenhei.ttc', 0))],
    )
    sans_med = find_font(
        [(mac_pf, 7),
         (user_fonts/'SourceHanSansCN-Medium.otf', 0), (user_fonts/'SourceHanSansSC-Medium.otf', 0),
         (win_fonts/'msyh.ttc', 0), (win_fonts/'msyh.ttf', 0)],
    )
    if not sans_med[0]:
        sans_med = sans_reg
    sans_bold = find_font(
        [(mac_pf, 11),
         (user_fonts/'SourceHanSansCN-Bold.otf', 0), (user_fonts/'SourceHanSansSC-Bold.otf', 0),
         (user_fonts/'SourceHanSansSC-Heavy.otf', 0),
         (win_fonts/'msyhbd.ttc', 0), (win_fonts/'msyhbd.ttf', 0), (win_fonts/'simhei.ttf', 0)],
        [(d, pat, idx) for d in linux_dirs for pat, idx in (
            ('NotoSansCJK-Bold.ttc', 2), ('NotoSansCJKsc-Bold.otf', 0),
            ('SourceHanSansSC-Heavy*.otf', 0), ('SourceHanSansSC-Bold*.otf', 0),
            ('SourceHanSansCN-Bold*.otf', 0), ('wqy-microhei.ttc', 0), ('wqy-zenhei.ttc', 0))],
    )
    serif_reg = find_font(
        [(mac_root/'Fonts/Supplemental/Songti.ttc', 6),
         (user_fonts/'SourceHanSerifCN-Regular.otf', 0), (user_fonts/'SourceHanSerifSC-Regular.otf', 0),
         (win_fonts/'simsun.ttc', 0), (win_fonts/'simsun.ttf', 0)],
        [(d, pat, idx) for d in linux_dirs for pat, idx in (
            ('NotoSerifCJK-Regular.ttc', 2), ('NotoSerifCJKsc-Regular.otf', 0),
            ('SourceHanSerifSC-Regular*.otf', 0), ('SourceHanSerifCN-Regular*.otf', 0))],
    )
    serif_bold = find_font(
        [(mac_root/'Fonts/Supplemental/Songti.ttc', 1),
         (user_fonts/'SourceHanSerifCN-Bold.otf', 0), (user_fonts/'SourceHanSerifSC-Bold.otf', 0),
         (win_fonts/'stzhongs.ttf', 0)],
        [(d, pat, idx) for d in linux_dirs for pat, idx in (
            ('NotoSerifCJK-Bold.ttc', 2), ('NotoSerifCJKsc-Bold.otf', 0),
            ('SourceHanSerifSC-Bold*.otf', 0), ('SourceHanSerifCN-Bold*.otf', 0))],
    )
    if not serif_bold[0] and serif_reg[0]:
        serif_bold = sans_bold if sans_bold[0] else serif_reg
    songti_path = str(mac_root/'Fonts/Supplemental/Songti.ttc')
    serif_black = (songti_path, 0) if serif_reg[0] == songti_path else serif_bold
    italic_num = find_font(
        [(mac_root/'Fonts/Supplemental/Times New Roman Italic.ttf', 0),
         (win_fonts/'timesi.ttf', 0), (win_fonts/'georgiai.ttf', 0)],
        [(d, pat, 0) for d in linux_dirs for pat in (
            'LiberationSerif-Italic.ttf', 'DejaVuSerif-Italic.ttf', 'FreeSerifItalic.ttf')],
    )
    num_bold = find_font(
        [(mac_root/'Fonts/Avenir Next.ttc', 2),
         (mac_pf, 11),
         (win_fonts/'segoeuib.ttf', 0), (win_fonts/'arialbd.ttf', 0)],
    )
    if not num_bold[0]:
        num_bold = sans_bold
    return dict(sans_reg=sans_reg, sans_med=sans_med, sans_bold=sans_bold,
                serif_reg=serif_reg, serif_bold=serif_bold, serif_black=serif_black,
                italic_num=italic_num, num_bold=num_bold)


SYS_FONTS = discover_fonts()

VALID_MODES = ('朋友圈', '字幕', '图解', '备忘录', '长文')

MEMO_CHROME = dict(
    bar_h=320, bar_cy=164, cap_r=96, bar_margin=104, right_pill_w=456,
    icon_col='#1C1C1E', pill_edge='#E8E8ED',
    date_size=56, date_color='#9A9AA0', date_baseline=372,
    quote_bar_w=10, quote_bar_gap=32, quote_bar_col='#C7C7CC',
    sel_pad_outer=15, handle_stem_w=4, handle_ball_r=9,
    footer_text_y=2744, footer_size=40, page_num_size=36, footer_color='#AEAEB2',
    end_limit_y=2220, end_gap=128,
)

PROFILES = {
    '备忘录': dict(x=208, right=1952, size=78, heading_size=88, step=132,
                heading_step=124, gap=172, before=180, after=86, top=368, bottom=2510,
                title_size=232, title_top=490, title_ratio=1.28, title_after=148,
                paper='#FFFFFF', ink='#232326', title_ink='#111113',
                muted='#8E8E93', accent='#DFAC06', mark_fill='#FBF0CC',
                rule='#EBEBF0', follow=1),
    '长文': dict(x=196, right=1964, size=64, heading_size=68, step=112,
                 heading_step=116, gap=88, before=108, after=76, top=404,
                 bottom=2512, paper='#FAF7F2', ink='#1D1C1A', muted='#858077',
                 rule='#DFD9CE', accent='#C85A32', mark_fill='#F1DFB8',
                 follow=2, number_indent=164),
}
ARTICLE_COVER = dict(photo_box=[180, 332, 1980, 1596], title_max=274,
                     accent_gap=82, accent_to_title=48, title_gap=64, subtitle_gap=84,
                     subtitle_size=48, subtitle='')
DIAGRAM_STYLE = dict(left=168, right=1992, paper='#FAF8F4', ink='#1E1E1C', body_ink='#262523',
                     muted='#847F76', rule='#DFDAD0', tray='#F1EEE7', tray_border='#E5E0D5',
                     card='#FFFFFF', card_border='#DFD9CE', accent='#C85028',
                     accent_soft='#FDF4F0', accent_border='#E5A892', mark_fill='#F2DFB8')


def canonical_mode(raw):
    text = str(raw).strip()
    if text not in VALID_MODES:
        raise ValueError('mode须为朋友圈/字幕/图解/备忘录/长文。')
    return text


def author_meta(spec):
    author = str(spec.get('footer') or '').strip()
    if not author:
        raise ValueError('缺少署名footer，请在spec或~/.config/social-graphics/personal.json中配置。')
    name = author.lstrip('@').strip() or author
    return author, name, str(spec.get('channel_label') or f'{name} · 图文笔记').strip()


def sans_font(spec, size, role='heavy'):
    return FontBook(spec, '字幕')(size, 'bold' if role == 'heavy' else role)


def load_image(path, crop=None):
    if Path(path).suffix.lower() in ('.heic', '.heif'):
        try:
            from pillow_heif import register_heif_opener
        except ImportError as exc:
            raise ValueError('检测到HEIC照片，请安装照片读取插件（pillow-heif）后重试。') from exc
        register_heif_opener()
    with Image.open(path) as source:
        im = ImageOps.exif_transpose(source).convert('RGB')
    if crop:
        l, t, r, b = crop
        if not (0 <= l < r <= im.width and 0 <= t < b <= im.height):
            raise ValueError(f'裁框超出原图: {crop}, image={im.size}')
        im = im.crop(tuple(crop))
    return im


def fit_image(path, size, crop=None):
    return ImageOps.fit(load_image(path, crop), size, method=Image.Resampling.LANCZOS)


def semantic_lines(lines, message):
    if not 1 <= len(lines) <= 2 or any(not t or '\n' in t for t in lines):
        raise ValueError(message)


def wrapped_rows(text, limit, measure, strict=False):
    pattern = r'\s*[A-Za-z0-9][A-Za-z0-9%/_.+\-]*\s*|.' if strict else r'[A-Za-z0-9][A-Za-z0-9%/_.+\-]*|.'
    rows, row = [], []
    for m in re.finditer(pattern, text):
        unit = (m.group(), m.start(), m.end())
        if row and measure(row[0][1], unit[2]) > limit:
            moved, reason = [], 'width'
            if unit[0].lstrip()[:1] in CLOSING and unit[0].lstrip():
                reason = 'kinsoku'
                moved.insert(0, row.pop())
                while strict and row and moved[0][0].lstrip()[:1] and moved[0][0].lstrip()[:1] in CLOSING:
                    moved.insert(0, row.pop())
            while row and row[-1][0].rstrip()[-1:] and row[-1][0].rstrip()[-1:] in OPENING:
                reason = 'kinsoku'
                moved.insert(0, row.pop())
            if not row:
                raise ValueError('版心容不下完整词组或标点禁则。' if strict else '字幕词组超宽，请调整断行。')
            rows.append((row[0][1], row[-1][2], reason))
            row = moved
        row.append(unit)
        if strict and measure(row[0][1], row[-1][2]) > limit:
            raise ValueError('单字或数值词组超过版心。')
    if row:
        rows.append((row[0][1], row[-1][2], 'paragraph_end'))
    return rows


def balanced_heading_rows(text, limit, measure):
    rows = wrapped_rows(text, limit, measure, strict=True)
    if len(rows) <= 1:
        return rows
    if '：' in text:
        pos = text.index('：') + 1
        if 0 < pos < len(text) and measure(0, pos) <= limit and measure(pos, len(text)) <= limit:
            return [(0, pos, 'heading_colon'), (pos, len(text), 'paragraph_end')]
    if len(rows) == 2 and (rows[-1][1] - rows[-1][0]) >= 6:
        return rows
    cands = [m.end() for m in re.finditer(r'[，、：]', text) if 3 <= m.end() <= len(text) - 4]
    for pos in sorted(cands, key=lambda k: abs(k - len(text) / 2)):
        if measure(0, pos) <= limit and measure(pos, len(text)) <= limit:
            return [(0, pos, 'heading_pause'), (pos, len(text), 'paragraph_end')]
    return rows


def explicit_rows(text, points, message):
    if (any(type(k) is not int or not 0 < k < len(text) for k in points)
            or points != sorted(set(points))):
        raise ValueError(message)
    bounds = [0]+points+[len(text)]
    return [(a, z, 'authorized_semantic_break' if z < len(text) else 'paragraph_end')
            for a, z in zip(bounds, bounds[1:])]


def render_moments(spec):
    canvas = tuple(spec.get('canvas', [W, H]))
    if canvas[0]*4 != canvas[1]*3:
        raise ValueError('朋友圈画布须为3:4。')
    im = fit_image(spec['background'], canvas, spec.get('background_crop'))
    crop = load_image(spec['screenshot'], spec['crop'])
    cfg = spec.get('placement', {})
    x = cfg.get('x', round(canvas[0]*176/W))
    margin = round(canvas[0]*100/1086)
    width = min(cfg.get('width', round(canvas[0]*1760/W)), canvas[0]-x-margin)
    height = round(crop.height*width/crop.width)
    y = cfg.get('y', min(round(canvas[0]*216/1086), canvas[1]-margin-height))
    if width <= 0 or not (0 <= x and margin <= y and x+width <= canvas[0] and y+height <= canvas[1]):
        raise ValueError('截图位置超出画布。')
    tile = crop.resize((width, height), Image.Resampling.LANCZOS)
    im.paste(tile, (x, y))
    return im, {'kind': 'content', 'placement': [x, y, width, height]}


def render_subtitle(spec):
    canvas = tuple(spec.get('canvas', [1086, 1448]))
    if canvas[0]*4 != canvas[1]*3 or min(canvas) <= 0:
        raise ValueError('字幕画布须为正数3:4。')
    px = lambda n: round(n*canvas[0]/1086)
    p = {k: px(v) for k, v in dict(size=33, step=52, gap=12, top=216,
         left=78, pad=10, bar_height=40, baseline=32).items()}
    p['right'] = canvas[0]-p['left']
    face = sans_font(spec, p['size'], 'regular')
    text = spec.get('image_text', spec['source_text'])
    if not spec['source_text'] or not text:
        raise ValueError('字幕缺完整原文或上图文案。')
    paragraphs = text.split(spec.get('paragraph_separator', '\n\n'))
    breaks = spec.get('line_breaks', [[] for _ in paragraphs])
    if len(breaks) != len(paragraphs) or any(not t or '\n' in t or '\r' in t for t in paragraphs):
        raise ValueError('字幕段落须非空无硬换行；line_breaks须逐段对应。')
    width = p['right']-p['left']-2*p['pad']
    im = fit_image(spec['background'], canvas, spec.get('background_crop'))
    mask = Image.new('L', canvas)
    draw, md = ImageDraw.Draw(im), ImageDraw.Draw(mask)
    planned = []
    for paragraph, points in zip(paragraphs, breaks):
        rows = (explicit_rows(paragraph, points, 'line_breaks须为段内递增字符偏移。') if points
                else wrapped_rows(paragraph, width, lambda a, z: face.getlength(paragraph[a:z])))
        planned.append([paragraph[a:z] for a, z, _ in rows])
    extent = sum(len(v)*p['step']+p['gap'] for v in planned)-p['gap']-p['step']+p['bar_height']
    y, actual = min(p['top'], canvas[1]-px(40)-extent), []
    if y < px(100):
        raise ValueError('文案超高请分页，不缩字。')
    p['top'] = y
    for bi, lines in enumerate(planned):
        for line in lines:
            w = math.ceil(face.getlength(line))
            if w > width:
                raise ValueError('字幕文字缺失或超宽，请调整断行。')
            bar = [p['left'], y, p['left']+w+2*p['pad'], y+p['bar_height']]
            x, base = p['left']+p['pad'], y+p['baseline']
            ink = draw.textbbox((x, base), line, font=face, anchor='ls')
            if not (bar[0] <= ink[0] <= ink[2] <= bar[2] and bar[1] <= ink[1] <= ink[3] <= bar[3]):
                raise ValueError('字幕字形超出白条。')
            rect = (bar[0], bar[1], bar[2]-1, bar[3]-1)
            draw.rectangle(rect, fill='white')
            md.rectangle(rect, fill=255)
            draw.text((x, base), line, font=face, fill='black', anchor='ls')
            actual.append(dict(text=line, paragraph=bi, strip=bar, baseline=base, ink_bounds=list(ink)))
            y += p['step']
        y += p['gap']
    if any(mask.crop(box).getbbox() for box in spec.get('face_keepout', [])):
        raise ValueError('字幕白底条进入脸部保护区。')
    return im, dict(kind='content', rows=actual, parameters=p,
                    font_file=str(face.path), font_weight=400,
                    text_coverage_exact=True, photo_outside_strips_unchanged=True)


def script_fragments(text):
    return list(re.finditer(r'[A-Za-z0-9][A-Za-z0-9%/_.+\-]*|[^A-Za-z0-9]+', text))


def visual_offset(font, text, lang):
    if not text or not text[0].isascii() or not text[0].isalnum():
        return 0
    sample = ''.join(c for c in text if c.isascii() and c.isalnum())
    if not sample:
        return 0
    cjk = font.getbbox('国', anchor='ls', **lang)
    latin = font.getbbox(sample, anchor='ls', **lang)
    return round((cjk[1]+cjk[3]-latin[1]-latin[3])/2)


def mixed_width(font, text, lang):
    return sum(font.getlength(m.group(), **lang) for m in script_fragments(text))


def draw_mixed(draw, x, baseline, text, font, fill, lang):
    for match in script_fragments(text):
        fragment = match.group()
        draw.text((x, baseline+visual_offset(font, fragment, lang)), fragment,
                  font=font, fill=fill, anchor='ls', **lang)
        x += font.getlength(fragment, **lang)


def draw_tracked(draw, face, text, x, y, spacing, fill, right=False):
    size = face.size
    tokens = []
    for part in re.split(r'(\s*·\s*)', text):
        if not part:
            continue
        if '·' in part:
            tokens.append(('dot', '', 0))
        else:
            for idx, c in enumerate(part):
                tokens.append(('char', c, spacing if idx < len(part)-1 else 0))
    dot_gap, dot_d = round(size*0.55), max(4, round(size*0.13))
    total_w = sum(dot_gap*2+dot_d if kind == 'dot' else face.getlength(c)+sp for kind, c, sp in tokens)
    if right:
        x -= total_w
    s_box = face.getbbox('国', anchor='lt')
    cy = y+(s_box[1]+s_box[3])/2
    for kind, c, sp in tokens:
        if kind == 'dot':
            x += dot_gap
            r = dot_d/2
            draw.ellipse((x, cy-r, x+dot_d, cy+r), fill=fill)
            x += dot_d+dot_gap
        else:
            draw.text((x, y), c, font=face, fill=fill, anchor='lt')
            x += face.getlength(c)+sp


def spans(text, phrases):
    found = []
    for phrase in phrases:
        if not phrase or phrase not in text:
            raise ValueError(f'强调短语不存在: {phrase!r}')
        found.extend(m.span() for m in re.finditer(re.escape(phrase), text))
    merged = []
    for a, b in sorted(set(found)):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return merged


class FontBook:
    def __init__(self, spec, mode='长文'):
        self.spec, self.mode, self.font_cache = spec, mode, {}
        self.engine = ImageFont.Layout.RAQM if RAQM else ImageFont.Layout.BASIC
        self.lang = {'language': 'zh-Hans'} if RAQM else {}

    def __call__(self, size, role='regular'):
        key = (size, role)
        if key not in self.font_cache:
            cfg = self.spec.get('fonts', {})

            def pick(*pairs):
                for p, i in pairs:
                    if p:
                        return p, i
                return None, None

            def custom(k, allow_songti=True):
                p = cfg.get(k)
                if not p or (not allow_songti and 'songti' in Path(str(p)).name.lower()):
                    return None, None
                return p, cfg.get(k + '_index')

            if role == 'num_bold':
                path, idx = pick(custom('num_bold'), SYS_FONTS['num_bold'], custom('bold', False), custom('heavy', False))
            elif self.mode in ('字幕', '备忘录', '图解'):
                if role in ('bold', 'heavy'):
                    path, idx = pick(custom(role, False), custom('bold', False), custom('heavy', False), SYS_FONTS['sans_bold'])
                elif role in ('medium', 'sans_medium'):
                    path, idx = pick(custom(role, False), SYS_FONTS['sans_med'], custom('sans', False), custom('regular', False))
                else:
                    path, idx = pick(custom(role, False), SYS_FONTS['sans_reg'], custom('sans', False), custom('regular', False))
            elif role in ('sans', 'sans_medium'):
                sys_key = 'sans_med' if role == 'sans_medium' else 'sans_reg'
                path, idx = pick(custom(role), SYS_FONTS[sys_key], custom('sans'), custom('regular'))
            elif role == 'number':
                path, idx = pick(custom('number'), SYS_FONTS['italic_num'], custom('bold'), SYS_FONTS['serif_bold'], SYS_FONTS['sans_bold'])
            else:
                ttc_bold = (cfg['regular'], cfg.get(role + '_index')) if role in ('bold', 'black') and str(cfg.get('regular', '')).lower().endswith('.ttc') else (None, None)
                sys_key = {'regular': 'serif_reg', 'bold': 'serif_bold', 'black': 'serif_black'}.get(role, 'serif_reg')
                path, idx = pick(custom(role), custom('bold') if role == 'black' else (None, None), ttc_bold, SYS_FONTS[sys_key])
            if not path:
                raise ValueError(f'缺少可用中文字体（fonts.{role}），请安装系统字体或在~/.config/social-graphics/personal.json的fonts中配置字体路径。')
            if idx is None:
                default_index = {'regular': 6, 'bold': 1, 'black': 0}.get(role, 0) if str(path).lower().endswith('.ttc') else 0
                idx = cfg.get(role+'_index', default_index)
            try:
                self.font_cache[key] = ImageFont.truetype(str(path), size, index=idx, layout_engine=self.engine)
            except OSError as exc:
                if role + '_index' not in cfg and idx:
                    try:
                        self.font_cache[key] = ImageFont.truetype(str(path), size, index=0, layout_engine=self.engine)
                        return self.font_cache[key]
                    except OSError:
                        pass
                raise ValueError(f'真实字体加载失败fonts.{role}: {path}') from exc
        return self.font_cache[key]


class InfographicLayout:
    def __init__(self, spec):
        self.spec = spec
        self.p = dict(DIAGRAM_STYLE)
        self.font = FontBook(spec, '图解')
        self.lang = self.font.lang

    def center_text(self, draw, cx, cy, text, face, fill):
        bx = face.getbbox(text, anchor='lt', **self.lang)
        w, h = bx[2]-bx[0], bx[3]-bx[1]
        draw.text((round(cx-w/2-bx[0]), round(cy-h/2-bx[1])), text, font=face, fill=fill, anchor='lt', **self.lang)

    def fit_font(self, text, role, max_size, max_width, min_size=26):
        for s in range(max_size, min_size-1, -2):
            face = self.font(s, role)
            if mixed_width(face, text, self.lang) <= max_width:
                return face
        return self.font(min_size, role)

    def smooth_arrow(self, im, x0, y0, x1, y1, color, width=6, head=18):
        S, pad = 4, 40
        lx, rx = min(x0, x1)-pad, max(x0, x1)+pad
        ty, by = min(y0, y1)-pad, max(y0, y1)+pad
        hi = Image.new('RGBA', ((rx-lx)*S, (by-ty)*S))
        d = ImageDraw.Draw(hi)
        ax0, ay0, ax1, ay1 = (x0-lx)*S, (y0-ty)*S, (x1-lx)*S, (y1-ty)*S
        d.line([(ax0, ay0), (ax1, ay1)], fill=color, width=width*S)
        ang, hs = math.atan2(ay1-ay0, ax1-ax0), head*S
        p1 = (ax1-hs*math.cos(ang-0.52), ay1-hs*math.sin(ang-0.52))
        p2 = (ax1-hs*math.cos(ang+0.52), ay1-hs*math.sin(ang+0.52))
        d.line([p1, (ax1, ay1), p2], fill=color, width=width*S, joint='curve')
        sm = hi.resize((rx-lx, by-ty), Image.Resampling.LANCZOS)
        im.paste(sm, (lx, ty), sm)

    def frame(self, draw, physical, total, cover=False):
        p = self.p
        author, name, label = author_meta(self.spec)
        l, r = p['left'], p['right']
        if cover:
            draw_tracked(draw, self.font(34, 'sans'), label, l, 182, 6, p['muted'])
            draw.text((r, 178), author, font=self.font(38, 'medium'), fill='#3D3B37', anchor='rt', **self.lang)
            draw.line((l, 256, r, 256), fill=p['rule'], width=2)
        else:
            draw_tracked(draw, self.font(32, 'sans'), label, l, 154, 5, p['muted'])
            draw.text((r, 150), author, font=self.font(36, 'medium'), fill='#5E5A52', anchor='rt', **self.lang)
        fy = 2700 if cover else 2690
        draw.line((l, fy, r, fy), fill=p['rule'], width=2)
        draw_tracked(draw, self.font(32, 'sans'), name, l, fy+42, 7, p['muted'])
        draw_tracked(draw, self.font(32, 'sans'), f'{physical:02d} / {total:02d}', r, fy+42, 5, p['muted'], right=True)

    def cover_page(self, total):
        p, spec = self.p, self.spec
        lines = spec['title_lines']
        semantic_lines(lines, '图解封面title_lines须为1至2行非空语义标题。')
        im = Image.new('RGB', (W, H), p['paper'])
        d = ImageDraw.Draw(im)
        self.frame(d, 1, total, cover=True)
        l, r = p['left'], p['right']
        for size in range(262, 90, -2):
            face = self.font(size, 'bold')
            if max(mixed_width(face, t, self.lang) for t in lines) <= r-l:
                break
        step = round(308*size/262)
        base = 340-face.getbbox(lines[0], anchor='ls', **self.lang)[1]
        bottom = base
        for i, text in enumerate(lines):
            b = base+i*step
            draw_mixed(d, l, b, text, face, p['ink'] if i == 0 else p['accent'], self.lang)
            bottom = b+face.getbbox(text, anchor='ls', **self.lang)[3]
        subtitle = spec.get('cover_subtitle', '')
        if not isinstance(subtitle, str):
            raise ValueError('cover_subtitle须为文字；空字符串关闭副题。')
        if subtitle:
            sub_face = self.fit_font(subtitle, 'regular', 46, r-l, 30)
            d.text((l, bottom+58), subtitle, font=sub_face, fill='#68645C', anchor='lt', **self.lang)
            pt = max(1060, bottom+168)
        else:
            pt = max(960, bottom+96)
        pb = 2644
        im.paste(fit_image(spec['cover'], (r-l, pb-pt), spec.get('cover_crop')), (l, pt))
        d.rectangle((l, pt, r-1, pb-1), outline='#DFD9CE', width=2)
        return im, dict(kind='cover', physical_page=1, title_size=size, photo_box=[l, pt, r, pb], photo_source=spec['cover'])

    def wrap_paragraphs(self, paragraphs, width, size, step, p_gap):
        face = self.font(size, 'regular')
        g_box = face.getbbox('国', anchor='ls', **self.lang)
        wrapped = []
        for para in paragraphs:
            if not para or '\n' in para or '\r' in para:
                raise ValueError('图解段落须为非空单段文字。')
            rows = wrapped_rows(para, width, lambda a, z: mixed_width(face, para[a:z], self.lang), strict=True)
            wrapped.append([(a, z) for a, z, _ in rows])
        if not wrapped:
            return [], 0
        lines_n = sum(len(v) for v in wrapped)
        height = (-g_box[1])+(lines_n-1)*step+(len(wrapped)-1)*p_gap+g_box[3]
        return wrapped, height

    def draw_paragraphs(self, im, wrapped, paragraphs, marks, x, y, size, step, p_gap):
        if not wrapped:
            return y
        d = ImageDraw.Draw(im)
        face = self.font(size, 'regular')
        g_box = face.getbbox('国', anchor='ls', **self.lang)
        base = y-g_box[1]
        for pi, (rows, text) in enumerate(zip(wrapped, paragraphs)):
            mark_spans = spans(text, [m for m in marks if m in text])
            if pi > 0:
                base += step+p_gap
            for li, (a, z) in enumerate(rows):
                if li > 0:
                    base += step
                line = text[a:z]
                for m0, m1 in mark_spans:
                    lo, hi = max(a, m0), min(z, m1)
                    if lo < hi:
                        px0 = x+mixed_width(face, text[a:lo], self.lang)-4
                        sub = text[a:hi]
                        last_ch = sub[-1]
                        if last_ch in CLOSING:
                            px1 = x+mixed_width(face, sub[:-1], self.lang)+face.getbbox(last_ch, anchor='ls', **self.lang)[2]+6
                        else:
                            px1 = x+mixed_width(face, sub, self.lang)+4
                        if hi < z:
                            px1 = min(px1, x+mixed_width(face, sub, self.lang)-2)
                        rect = (round(px0), base+round(g_box[1]*0.42), round(px1), base+g_box[3]+8)
                        d.rounded_rectangle(rect, radius=9, fill=self.p['mark_fill'])
                draw_mixed(d, x, base, line, face, self.p['body_ink'], self.lang)
        return base+g_box[3]

    def text_size(self, text, face):
        bx = face.getbbox(text, anchor='lt', **self.lang)
        return bx[2]-bx[0], bx[3]-bx[1]

    def draw_vector_mark(self, im, kind, cx, cy, color):
        S, sz = 4, 44
        hi = Image.new('RGBA', (sz*S, sz*S))
        d = ImageDraw.Draw(hi)
        c, r = (sz//2)*S, 18*S
        if kind == 'cross':
            d.ellipse((c-r, c-r, c+r, c+r), fill='#EAE6DE')
            k = 7*S
            d.line([(c-k, c-k), (c+k, c+k)], fill=color, width=4*S)
            d.line([(c-k, c+k), (c+k, c-k)], fill=color, width=4*S)
        else:
            d.ellipse((c-r, c-r, c+r, c+r), fill='#F8E3DA')
            d.line([(c-8*S, c+1*S), (c-2*S, c+7*S), (c+9*S, c-6*S)], fill=color, width=4*S, joint='curve')
        sm = hi.resize((sz, sz), Image.Resampling.LANCZOS)
        im.paste(sm, (cx-sz//2, cy-sz//2), sm)

    @staticmethod
    def canonical_diagram_kind(raw):
        mapped = {
            'columns': 'columns', 'pillars': 'columns',
            'versus': 'versus', 'compare': 'versus',
            'funnel': 'funnel',
            'timeline': 'timeline', 'flow': 'timeline',
            'venn': 'venn',
            'bars': 'bars', 'matrix': 'bars',
            'cycle': 'cycle',
            'branch': 'branch',
            'image': 'image',
        }.get(raw)
        if not mapped:
            raise ValueError(f'不支持的diagram.kind: {raw!r}')
        return mapped

    def draw_diagram(self, im, diag, x, right, top, tray_h, base_dir):
        p, d = self.p, ImageDraw.Draw(im)
        kind = self.canonical_diagram_kind(diag['kind'])
        caption = diag.get('caption', '')
        w, cy = right-x, top+tray_h//2

        if kind == 'columns':
            items = diag['items']
            if not items:
                raise ValueError('diagram.items不能为空。')
            n = len(items)
            d.line((x, top+12, right, top+12), fill='#2C2A27', width=3)
            d.line((x, top+tray_h-16, right, top+tray_h-16), fill=p['rule'], width=2)
            col_w = w//n
            for i, it in enumerate(items):
                cx0 = x+i*col_w
                if i > 0:
                    d.line((cx0, top+56, cx0, top+tray_h-58), fill=p['rule'], width=2)
                pad_x = cx0+(24 if i == 0 else 44)
                max_tw = col_w-(52 if i == 0 else 72)
                hl = bool(it.get('highlight'))
                d.text((pad_x, top+138), f'{i+1:02d}', font=self.font(92, 'num_bold'),
                       fill=p['accent'] if hl else '#C8BFB2', anchor='ls')
                tf = self.fit_font(it['title'], 'bold', 54, max_tw, 30)
                draw_mixed(d, pad_x, top+234, it['title'], tf, p['accent'] if hl else p['ink'], self.lang)
                if it.get('sub'):
                    sf = self.fit_font(it['sub'], 'regular', 36, max_tw, 22)
                    draw_mixed(d, pad_x, top+302, it['sub'], sf, p['muted'], self.lang)
            if caption:
                cf = self.fit_font(caption, 'bold', 36, w-120, 26)
                cw_txt, _ = self.text_size(caption, cf)
                pw, mx, by = cw_txt+68, (x+right)//2, top+tray_h-16
                d.rounded_rectangle((mx-pw//2, by-28, mx+pw//2, by+28),
                                    radius=28, fill=p['paper'], outline=p['accent_border'], width=2)
                self.center_text(d, mx, by, caption, cf, p['accent'])

        elif kind == 'versus':
            d.line((x, top+10, right, top+10), fill='#2C2A27', width=3)
            d.line((x, top+tray_h-10, right, top+tray_h-10), fill=p['rule'], width=2)
            mid = x+round(w*0.47)
            d.rounded_rectangle((mid+48, top+34, right, top+tray_h-34), radius=24, fill='#F6EFE8')
            S, sw, sh = 4, 120, tray_h-60
            hi = Image.new('RGBA', (sw*S, sh*S))
            hd = ImageDraw.Draw(hi)
            hd.line([(78*S, 16*S), (42*S, (sh-16)*S)], fill='#D5CEC2', width=3*S)
            hd.ellipse(((60-36)*S, (sh//2-36)*S, (60+36)*S, (sh//2+36)*S),
                       fill=p['paper'], outline='#D5CEC2', width=2*S)
            sm = hi.resize((sw, sh), Image.Resampling.LANCZOS)
            im.paste(sm, (mid-60, top+30), sm)
            self.center_text(d, mid, cy, diag.get('op', '≠'), self.font(48, 'bold'), p['accent'])

            left, rt = diag['left'], diag['right']
            lx, lw = x+16, mid-x-86
            self.draw_vector_mark(im, 'cross', lx+20, top+84, '#8E887E')
            d.text((lx+54, top+96), left.get('tag', '传统误区'), font=self.font(36, 'bold'),
                   fill='#8E887E', anchor='ls', **self.lang)
            ltf = self.fit_font(left['title'], 'bold', 60, lw, 32)
            draw_mixed(d, lx, cy+20, left['title'], ltf, '#7A756D', self.lang)
            tw_l = min(lw, round(mixed_width(ltf, left['title'], self.lang)))
            d.line((lx, cy-2, lx+tw_l, cy-2), fill='#B0A99E', width=4)
            if left.get('sub'):
                lsf = self.fit_font(left['sub'], 'regular', 36, lw, 22)
                draw_mixed(d, lx, cy+96, left['sub'], lsf, '#9A948A', self.lang)

            rx, rw = mid+92, right-(mid+92)-36
            self.draw_vector_mark(im, 'check', rx+20, top+84, p['accent'])
            d.text((rx+54, top+96), rt.get('tag', '核心正解'), font=self.font(36, 'bold'),
                   fill=p['accent'], anchor='ls', **self.lang)
            rtf = self.fit_font(rt['title'], 'bold', 64, rw, 34)
            draw_mixed(d, rx, cy+20, rt['title'], rtf, p['ink'], self.lang)
            tw_r = min(rw, round(mixed_width(rtf, rt['title'], self.lang)))
            d.rounded_rectangle((rx, cy+36, rx+tw_r, cy+46), radius=4, fill=p['accent'])
            if rt.get('sub'):
                rsf = self.fit_font(rt['sub'], 'regular', 38, rw, 22)
                draw_mixed(d, rx, cy+102, rt['sub'], rsf, '#5E5A52', self.lang)

        elif kind == 'funnel':
            layers = diag['layers']
            n = len(layers)
            if n < 2:
                raise ValueError('funnel至少需要2层layers。')
            S, fw, fh = 4, round(w*0.53), tray_h-36
            hi = Image.new('RGBA', (w*S, fh*S))
            hd = ImageDraw.Draw(hi)
            fcx, gap_y = round(fw*0.50), 18
            lh = (fh-gap_y*(n-1))//n
            taper = 0.52/n
            for i in range(n):
                y0, y1 = i*(lh+gap_y), i*(lh+gap_y)+lh
                w_top = round(fw*(0.96-i*taper))
                w_bot = round(fw*(0.96-(i+1)*taper))
                pts = [((fcx-w_top//2)*S, y0*S), ((fcx+w_top//2)*S, y0*S),
                       ((fcx+w_bot//2)*S, y1*S), ((fcx-w_bot//2)*S, y1*S)]
                is_last = (i == n-1)
                fill_c = '#C85028' if is_last else ('#EAE5DC' if i == 0 else '#F3E0D6')
                out_c = '#C85028' if is_last else ('#D8D1C5' if i == 0 else '#E4B8A5')
                hd.polygon(pts, fill=fill_c, outline=out_c, width=2*S)
                ly_mid = (y0+y1)//2
                rx_edge = fcx+(w_top+w_bot)//4
                hd.line([((rx_edge+14)*S, ly_mid*S), ((fw+44)*S, ly_mid*S)],
                        fill='#C85028' if is_last else '#C5BEB2', width=3*S)
                r_dot = 7*S
                hd.ellipse(((fw+44-7)*S, ly_mid*S-r_dot, (fw+44+7)*S, ly_mid*S+r_dot),
                           fill='#C85028' if is_last else '#9A948A')
            sm = hi.resize((w, fh), Image.Resampling.LANCZOS)
            im.paste(sm, (x, top+18), sm)

            for i, lay in enumerate(layers):
                ly_mid = top+18+i*(lh+gap_y)+lh//2
                is_last = (i == n-1)
                txt_col = '#FFFFFF' if is_last else (p['ink'] if i == 0 else '#9E3B1C')
                w_mid = round(fw*(0.96-(i+0.5)*taper))-44
                tf = self.fit_font(lay['title'], 'bold', 46, w_mid, 26)
                self.center_text(d, x+fcx, ly_mid, lay['title'], tf, txt_col)
                note = lay.get('note') or lay.get('sub', '')
                if note:
                    nf = self.fit_font(note, 'medium' if is_last else 'regular', 40, w-(fw+78), 24)
                    draw_mixed(d, x+fw+74, ly_mid+14, note, nf, p['accent'] if is_last else '#5E5A52', self.lang)

        elif kind == 'timeline':
            items = diag['items']
            if not items:
                raise ValueError('diagram.items不能为空。')
            n = len(items)
            S = 4
            if n == 1:
                xs = [x+w//2]
            elif n == 2:
                xs = [x+320, right-320]
            else:
                step_x = (w-240)//(n-1)
                xs = [x+120+i*step_x for i in range(n)]
            hi = Image.new('RGBA', (w*S, tray_h*S))
            hd = ImageDraw.Draw(hi)
            ty_rel = tray_h//2
            if n > 1:
                hd.line([((xs[0]-x)*S, ty_rel*S), ((xs[-1]-x)*S, ty_rel*S)], fill='#D8D2C7', width=6*S)
                for i in range(n-1):
                    mx_seg = ((xs[i]+xs[i+1])//2-x)*S
                    hs = 13*S
                    acol = p['accent'] if items[i+1].get('highlight') else '#A69F94'
                    hd.line([(mx_seg-hs, ty_rel*S-round(hs*0.65)), (mx_seg+4*S, ty_rel*S),
                             (mx_seg-hs, ty_rel*S+round(hs*0.65))], fill=acol, width=5*S, joint='curve')
            for i, it in enumerate(items):
                nx = (xs[i]-x)*S
                hl = bool(it.get('highlight'))
                if hl:
                    hd.ellipse((nx-50*S, (ty_rel-50)*S, nx+50*S, (ty_rel+50)*S), fill=(200, 80, 40, 38))
                r_n = 35*S
                hd.ellipse((nx-r_n, ty_rel*S-r_n, nx+r_n, ty_rel*S+r_n),
                           fill=p['accent'] if hl else '#FFFFFF',
                           outline=p['accent'] if hl else '#8F897E', width=4*S)
            sm = hi.resize((w, tray_h), Image.Resampling.LANCZOS)
            im.paste(sm, (x, top), sm)

            max_cw = (xs[1]-xs[0]-28) if n > 1 else w-160
            for i, it in enumerate(items):
                hl = bool(it.get('highlight'))
                self.center_text(d, xs[i], cy-1, f'{i+1}', self.font(38, 'num_bold'),
                                 '#FFFFFF' if hl else '#5E5A52')
                tf = self.fit_font(it['title'], 'bold', 50, max_cw, 28)
                self.center_text(d, xs[i], cy-94, it['title'], tf, p['accent'] if hl else p['ink'])
                if it.get('sub'):
                    sf = self.fit_font(it['sub'], 'regular', 34, max_cw+20, 22)
                    self.center_text(d, xs[i], cy+90, it['sub'], sf, p['muted'])

        elif kind == 'venn':
            raw_items = [it['title'] if isinstance(it, dict) else str(it) for it in diag['items']]
            if len(raw_items) not in (2, 3):
                raise ValueError('venn仅支持2或3个交集要素items。')
            S = 4
            hi = Image.new('RGBA', (w*S, tray_h*S))
            hd = ImageDraw.Draw(hi)
            vcx, vcy = (w//2)*S, (tray_h//2+(12 if len(raw_items) == 3 else 0))*S
            cx_abs, cy_abs = x+w//2, top+tray_h//2+(12 if len(raw_items) == 3 else 0)
            if len(raw_items) == 2:
                r_c = 178*S
                for dx, fc, sc in [(-round(r_c*0.56), (232, 224, 210, 155), (186, 176, 160, 255)),
                                   (round(r_c*0.56), (235, 184, 166, 155), (200, 80, 40, 220))]:
                    hd.ellipse((vcx+dx-r_c, vcy-r_c, vcx+dx+r_c, vcy+r_c), fill=fc, outline=sc, width=3*S)
                l_dot, r_dot = vcx-round(r_c*1.28), vcx+round(r_c*1.28)
                hd.line([((w//2-440)*S, vcy), (l_dot, vcy)], fill='#B8B0A4', width=3*S)
                hd.ellipse((l_dot-6*S, vcy-6*S, l_dot+6*S, vcy+6*S), fill='#8E887E')
                hd.line([(r_dot, vcy), ((w//2+440)*S, vcy)], fill='#C85028', width=3*S)
                hd.ellipse((r_dot-6*S, vcy-6*S, r_dot+6*S, vcy+6*S), fill='#C85028')
                sm = hi.resize((w, tray_h), Image.Resampling.LANCZOS)
                im.paste(sm, (x, top), sm)
                tf0 = self.fit_font(raw_items[0], 'bold', 48, 410, 28)
                tw0, _ = self.text_size(raw_items[0], tf0)
                draw_mixed(d, cx_abs-464-tw0, cy_abs+16, raw_items[0], tf0, p['ink'], self.lang)
                tf1 = self.fit_font(raw_items[1], 'bold', 48, 410, 28)
                draw_mixed(d, cx_abs+464, cy_abs+16, raw_items[1], tf1, p['accent'], self.lang)
            else:
                r_c = 166*S
                offsets = [(0, -round(r_c*0.48)), (-round(r_c*0.54), round(r_c*0.40)), (round(r_c*0.54), round(r_c*0.40))]
                fills = [(232, 224, 210, 150), (244, 214, 188, 155), (235, 184, 166, 155)]
                strokes = [(186, 176, 160, 255), (214, 160, 114, 255), (200, 80, 40, 220)]
                for (dx, dy), fc, sc in zip(offsets, fills, strokes):
                    hd.ellipse((vcx+dx-r_c, vcy+dy-r_c, vcx+dx+r_c, vcy+dy+r_c), fill=fc, outline=sc, width=3*S)
                l_dot_x, l_dot_y = vcx-round(r_c*1.32), vcy+round(r_c*0.42)
                hd.line([((w//2-430)*S, l_dot_y), (l_dot_x, l_dot_y)], fill='#B8B0A4', width=3*S)
                hd.ellipse((l_dot_x-6*S, l_dot_y-6*S, l_dot_x+6*S, l_dot_y+6*S), fill='#8E887E')
                r_dot_x, r_dot_y = vcx+round(r_c*1.32), vcy+round(r_c*0.42)
                hd.line([(r_dot_x, r_dot_y), ((w//2+430)*S, r_dot_y)], fill='#C85028', width=3*S)
                hd.ellipse((r_dot_x-6*S, r_dot_y-6*S, r_dot_x+6*S, r_dot_y+6*S), fill='#C85028')
                t_dot_x, t_dot_y = vcx-round(r_c*0.82), vcy-round(r_c*0.78)
                hd.line([((w//2-430)*S, t_dot_y), (t_dot_x, t_dot_y)], fill='#B8B0A4', width=3*S)
                hd.ellipse((t_dot_x-6*S, t_dot_y-6*S, t_dot_x+6*S, t_dot_y+6*S), fill='#8E887E')
                sm = hi.resize((w, tray_h), Image.Resampling.LANCZOS)
                im.paste(sm, (x, top), sm)
                r_px = 166
                ty_lbl, ly_lbl = cy_abs-round(r_px*0.78), cy_abs+round(r_px*0.42)
                tf0 = self.fit_font(raw_items[0], 'bold', 46, 420, 28)
                tw0, _ = self.text_size(raw_items[0], tf0)
                draw_mixed(d, cx_abs-454-tw0, ty_lbl+15, raw_items[0], tf0, p['ink'], self.lang)
                tf1 = self.fit_font(raw_items[1], 'bold', 46, 420, 28)
                tw1, _ = self.text_size(raw_items[1], tf1)
                draw_mixed(d, cx_abs-454-tw1, ly_lbl+15, raw_items[1], tf1, p['ink'], self.lang)
                tf2 = self.fit_font(raw_items[2], 'bold', 46, 420, 28)
                draw_mixed(d, cx_abs+454, ly_lbl+15, raw_items[2], tf2, p['accent'], self.lang)

            core = diag['center']
            cf = self.fit_font(core, 'bold', 44, 280, 26)
            cw_t, _ = self.text_size(core, cf)
            pw = cw_t+64
            d.rounded_rectangle((cx_abs-pw//2, cy_abs+6-40, cx_abs+pw//2, cy_abs+6+40), radius=40, fill=p['accent'])
            self.center_text(d, cx_abs, cy_abs+6, core, cf, '#FFFFFF')

        elif kind == 'bars':
            cols = diag['cols']
            n = len(cols)
            if not cols:
                raise ValueError('bars.cols不能为空。')
            base_y = top+tray_h-102
            d.line((x+60, base_y, right-60, base_y), fill='#2C2A27', width=3)
            slot_w = (w-200)//n
            bar_w = min(260, slot_w-100)
            max_bh = tray_h-260
            ratios = resolve_bar_ratios(cols)
            tops = []
            for i, (col, rat) in enumerate(zip(cols, ratios)):
                scx = x+100+i*slot_w+slot_w//2
                bh = max(40, round(max_bh*rat))
                by0 = base_y-bh
                hl = bool(col.get('highlight'))
                fill_c = p['accent'] if hl or (not any(c.get('highlight') for c in cols) and i == n-1) else ('#E9B5A3' if hl else '#DED8CE')
                d.rounded_rectangle((scx-bar_w//2, by0, scx+bar_w//2, base_y-2), radius=14, fill=fill_c)
                tops.append((scx, by0))
                vf = self.fit_font(col['value'], 'bold', 64, slot_w-24, 34)
                self.center_text(d, scx, by0-44, col['value'], vf, p['accent'] if hl else p['ink'])
                hf = self.fit_font(col['header'], 'bold', 38, slot_w-20, 24)
                self.center_text(d, scx, base_y+36, col['header'], hf, p['ink'])
                if col.get('sub'):
                    sf = self.fit_font(col['sub'], 'regular', 32, slot_w-16, 20)
                    self.center_text(d, scx, base_y+80, col['sub'], sf, p['muted'])
            if len(tops) >= 2 and ratios[-1] > ratios[0] and all(ratios[i] <= ratios[i+1] for i in range(len(ratios)-1)):
                self.smooth_arrow(im, tops[0][0]+40, tops[0][1]-106, tops[-1][0]-88, tops[-1][1]-92,
                                  p['accent'], width=5, head=18)

        elif kind == 'cycle':
            nodes = diag['items']
            n = len(nodes)
            if n not in (3, 4):
                raise ValueError('cycle仅支持3或4个环形节点items。')
            cx_mid = (x+right)//2
            rx_orb, ry_orb = 440, min(182, tray_h//2-58)
            S = 4
            hi = Image.new('RGBA', (w*S, tray_h*S))
            hd = ImageDraw.Draw(hi)
            rcx, rcy = (cx_mid-x)*S, (tray_h//2)*S
            hd.ellipse((rcx-rx_orb*S, rcy-ry_orb*S, rcx+rx_orb*S, rcy+ry_orb*S), outline='#EAE4DA', width=3*S)
            hw, hh = 132*S, 58*S
            hd.rounded_rectangle((rcx-hw, rcy-hh, rcx+hw, rcy+hh),
                                 radius=58*S, fill='#F5EFE6', outline='#DED7CA', width=2*S)
            arc_defs = ([(-46, 0, True), (58, 122, True), (180, 226, False)] if n == 3
                        else [(-62, -22, True), (22, 62, True), (118, 158, True), (202, 242, False)])
            for a0, a1, hl_arc in arc_defs:
                pts = [((cx_mid-x+rx_orb*math.cos(math.radians(a0+(a1-a0)*k/24)))*S,
                        (tray_h//2+ry_orb*math.sin(math.radians(a0+(a1-a0)*k/24)))*S) for k in range(25)]
                col_a = p['accent'] if hl_arc else '#9A948A'
                hd.line(pts, fill=col_a, width=5*S, joint='curve')
                ex, ey = pts[-1]
                px_prev, py_prev = pts[-3]
                tang = math.atan2(ey-py_prev, ex-px_prev)
                hs = 17*S
                hd.line([(ex-hs*math.cos(tang-0.55), ey-hs*math.sin(tang-0.55)), (ex, ey),
                         (ex-hs*math.cos(tang+0.55), ey-hs*math.sin(tang+0.55))],
                        fill=col_a, width=5*S, joint='curve')
            sm = hi.resize((w, tray_h), Image.Resampling.LANCZOS)
            im.paste(sm, (x, top), sm)
            center_lbl = diag.get('center', '商业闭环')
            self.center_text(d, cx_mid, cy, center_lbl, self.fit_font(center_lbl, 'bold', 38, 220, 26), '#6E6960')
            angles = [-90, 26, 154] if n == 3 else [-90, 0, 90, 180]
            for ang_deg, nd in zip(angles, nodes):
                rad = math.radians(ang_deg)
                nx, ny = round(cx_mid+rx_orb*math.cos(rad)), round(cy+ry_orb*math.sin(rad))
                hl = bool(nd.get('highlight'))
                tf = self.fit_font(nd['title'], 'bold', 48, 340, 30)
                tw_n, _ = self.text_size(nd['title'], tf)
                pw, ph = max(246, tw_n+84), 94
                d.rounded_rectangle((nx-pw//2, ny-ph//2, nx+pw//2, ny+ph//2),
                                    radius=47, fill=p['accent'] if hl else '#FFFFFF',
                                    outline=p['accent'] if hl else '#D6CFC3', width=3)
                self.center_text(d, nx, ny, nd['title'], tf, '#FFFFFF' if hl else p['ink'])

        elif kind == 'branch':
            branches = [b if isinstance(b, dict) else {'title': str(b), 'highlight': idx == 0}
                        for idx, b in enumerate(diag['branches'])]
            nb = len(branches)
            d.line((x, top+10, right, top+10), fill=p['rule'], width=2)
            d.line((x, top+tray_h-10, right, top+tray_h-10), fill=p['rule'], width=2)
            lw, rw = round(w*0.36), round(w*0.44)
            lx0, rx0 = x+24, right-24-rw
            rh = min(132, (tray_h-88-(nb-1)*30)//nb)
            ry_start = cy-(nb*rh+(nb-1)*30)//2
            l_box = (lx0, cy-72, lx0+lw, cy+72)
            d.rounded_rectangle(l_box, radius=72, fill='#F2EFE8', outline='#D6CFC3', width=3)
            self.center_text(d, (l_box[0]+l_box[2])/2, cy, diag['root'],
                             self.fit_font(diag['root'], 'bold', 50, lw-56, 28), p['ink'])
            mid_x = (l_box[2]+rx0)//2
            centers = []
            for idx, br in enumerate(branches):
                by0 = ry_start+idx*(rh+30)
                by1 = by0+rh
                bcy = (by0+by1)//2
                hl = bool(br.get('highlight'))
                centers.append((bcy, hl))
                d.rounded_rectangle((rx0, by0, rx0+rw, by1), radius=rh//2,
                                    fill=p['accent_soft'] if hl else '#FFFFFF',
                                    outline=p['accent'] if hl else '#D6CFC3', width=3 if hl else 2)
                tf = self.fit_font(br['title'], 'bold', 46, rw-60, 28)
                if br.get('sub'):
                    sf = self.fit_font(br['sub'], 'regular', 30, rw-60, 20)
                    self.center_text(d, rx0+rw/2, bcy-20, br['title'], tf, p['accent'] if hl else p['ink'])
                    self.center_text(d, rx0+rw/2, bcy+26, br['sub'], sf, p['muted'])
                else:
                    self.center_text(d, rx0+rw/2, bcy, br['title'], tf, p['accent'] if hl else p['ink'])
            d.line([(l_box[2]+16, cy), (mid_x, cy)], fill='#9A948A', width=5)
            d.line([(mid_x, centers[0][0]), (mid_x, centers[-1][0])], fill='#9A948A', width=5)
            for bcy, hl in centers:
                self.smooth_arrow(im, mid_x, bcy, rx0-16, bcy, p['accent'] if hl else '#9A948A', width=5)

        elif kind == 'image':
            img_path = resolved(base_dir, diag['image'])
            pic = load_image(img_path)
            cy_img = top+(round((tray_h-68)/2) if caption else tray_h//2)
            max_w, max_h = w-40, tray_h-(96 if caption else 36)
            scale = min(max_w/pic.width, max_h/pic.height)
            nw, nh = max(1, round(pic.width*scale)), max(1, round(pic.height*scale))
            resized = pic.resize((nw, nh), Image.Resampling.LANCZOS)
            ix, iy = round((x+right-nw)/2), round(cy_img-nh/2)
            im.paste(resized, (ix, iy))
            d.rectangle((ix, iy, ix+nw-1, iy+nh-1), outline='#DFD9CE', width=2)
            if caption:
                cf = self.fit_font(caption, 'bold', 38, w-80, 26)
                self.center_text(d, (x+right)/2, top+tray_h-32, caption, cf, p['accent'])

    def body_page(self, page, physical, total, base_dir):
        p = self.p
        im = Image.new('RGB', (W, H), p['paper'])
        d = ImageDraw.Draw(im)
        self.frame(d, physical, total, cover=False)
        l, r = p['left'], p['right']
        width = r-l

        raw_title = page.get('title') or ''.join(page.get('title_lines', []))
        if not raw_title or '\n' in raw_title:
            raise ValueError('图解内页须提供单行章节标题title。')
        if page.get('number') is not None:
            num_val = int(page['number'])
            if num_val < 1:
                raise ValueError('图解章节number须为正整数。')
            num_str = f'{num_val:02d}'
            nf = self.font(128, 'num_bold')
            nb = nf.getbbox(num_str, anchor='ls')
            d.text((l, 344), num_str, font=nf, fill=p['accent'], anchor='ls')
            nx_end = l+nb[2]+36
            d.line((nx_end, 240, nx_end, 348), fill=p['rule'], width=3)
            tf = self.fit_font(raw_title, 'bold', 92, r-(nx_end+36), 48)
            draw_mixed(d, nx_end+36, 336, raw_title, tf, p['ink'], self.lang)
        else:
            tag = page.get('tag', '前言')
            d.rounded_rectangle((l, 260, l+148, 338), radius=14, fill=p['tray'], outline=p['card_border'], width=2)
            self.center_text(d, l+74, 299, tag, self.font(40, 'bold'), p['muted'])
            tf = self.fit_font(raw_title, 'bold', 84, r-(l+178), 46)
            tb = tf.getbbox('国', anchor='ls', **self.lang)
            draw_mixed(d, l+178, round(299-(tb[1]+tb[3])/2), raw_title, tf, p['ink'], self.lang)
        d.line((l, 404, r, 404), fill=p['rule'], width=2)

        upper = page.get('upper', [])
        lower = page.get('lower', [])
        marks = page.get('marks', [])
        for phrase in marks:
            if not any(phrase in para for para in upper+lower):
                raise ValueError(f'强调短语不存在: {phrase!r}')
        diag = page.get('diagram')
        if diag is None and page.get('image'):
            diag = {'kind': 'image', 'image': page['image']}

        zone_top, zone_bot = 404, 2690
        usable = zone_bot-zone_top
        dkind = self.canonical_diagram_kind(diag['kind']) if diag else None
        h_map = {'versus': 390, 'columns': 390, 'timeline': 380, 'branch': 430,
                 'funnel': 470, 'cycle': 510, 'venn': 520, 'bars': 520, 'image': 460}
        base_diag_h = 0 if not dkind else h_map[dkind]

        chosen = None
        for size in range(84, 58, -2):
            step = round(150*size/84)
            p_gap = round(58*size/84)
            sec_gap = round(96*size/84)
            up_wrap, up_h = self.wrap_paragraphs(upper, width, size, step, p_gap)
            lo_wrap, lo_h = self.wrap_paragraphs(lower, width, size, step, p_gap)
            gaps = (sec_gap if upper and diag else 0)+(sec_gap if diag and lower else (sec_gap if upper and lower else 0))
            min_total = up_h+lo_h+base_diag_h+gaps
            if min_total <= usable-140:
                chosen = (size, step, p_gap, sec_gap, up_wrap, up_h, lo_wrap, lo_h, gaps)
                break
        if chosen is None:
            raise ValueError('图解单页文字过长超出阅读区，请拆分为续页。')

        size, step, p_gap, sec_gap, up_wrap, up_h, lo_wrap, lo_h, gaps = chosen
        extra_diag = max(0, min(80, round((usable-(up_h+lo_h+gaps)-base_diag_h-240)*0.40))) if diag else 0
        diag_h = base_diag_h+extra_diag
        total_h = up_h+lo_h+diag_h+gaps
        spare = max(120, usable-total_h)
        y = zone_top+round(spare*0.40)

        if upper:
            y = self.draw_paragraphs(im, up_wrap, upper, marks, l, y, size, step, p_gap)
            if diag or lower:
                y += sec_gap
        if diag:
            self.draw_diagram(im, diag, l, r, y, diag_h, base_dir)
            y += diag_h
            if lower:
                y += sec_gap
        if lower:
            y = self.draw_paragraphs(im, lo_wrap, lower, marks, l, y, size, step, p_gap)

        return im, dict(kind='body', physical_page=physical, number=page.get('number'),
                        title=raw_title, body_size=size, diagram_kind=dkind,
                        body_bottom=y, body_limit=zone_bot)


class TextLayout:
    def __init__(self, spec, mode):
        self.spec, self.mode = spec, mode
        self.p, self.blocks = dict(PROFILES[self.mode]), spec.get('blocks', [])
        self.title_record = {}
        self.font = FontBook(spec, self.mode)
        self.lang = self.font.lang
        self.metric_cache, self.width_cache = {}, {}
        self.separator = spec.get('paragraph_separator', '\n\n')
        for block in self.blocks:
            text = block['text']
            if not text or '\n' in text or '\r' in text:
                raise ValueError('block须为非空、无硬换行的原文段落。')
        reconstructed = self.separator.join(b['text'] for b in self.blocks)
        if self.blocks and reconstructed != spec['source_text']:
            raise ValueError('blocks按paragraph_separator连接须逐字等于source_text。')
        self.bold = [spans(b['text'], b.get('bold', [])) for b in self.blocks]
        self.marks = [spans(b['text'], b.get('marks', [])) if not b.get('heading') else []
                      for b in self.blocks]
        raw_date = spec.get('memo_date')
        if raw_date is None:
            self.memo_date = datetime.now(timezone(timedelta(hours=8))).strftime('%Y年%m月%d日 %H:%M')
        elif isinstance(raw_date, str):
            self.memo_date = raw_date
        else:
            raise ValueError('memo_date须为文字；空字符串关闭时间。')

    def runs(self, bi, start, end):
        block, p = self.blocks[bi], self.p
        if block.get('heading'):
            styled = [(start, end, 'bold', p['heading_size'])]
        else:
            cuts = sorted({start, end} | {k for span in self.bold[bi] for k in span if start < k < end})
            styled = [(a, b, 'bold' if any(x <= a < y for x, y in self.bold[bi]) else 'regular', p['size'])
                      for a, b in zip(cuts, cuts[1:])]
        return [(a+m.start(), a+m.end(), role, size) for a, b, role, size in styled
                for m in script_fragments(block['text'][a:b])]

    def width(self, bi, start, end):
        key = (bi, start, end)
        if key not in self.width_cache:
            text = self.blocks[bi]['text']
            self.width_cache[key] = sum(self.font(n, role).getlength(text[a:b], **self.lang)
                                       for a, b, role, n in self.runs(bi, start, end))
        return self.width_cache[key]

    def numbered(self, bi):
        return self.blocks[bi].get('number') is not None

    def block_x(self, bi):
        if self.mode == '备忘录' and self.blocks[bi].get('heading'):
            return self.p['x'] + MEMO_CHROME['quote_bar_w'] + MEMO_CHROME['quote_bar_gap']
        return self.p['x'] + (self.p['number_indent'] if self.mode == '长文' and self.numbered(bi) else 0)

    def natural_lines(self, bi):
        text = self.blocks[bi]['text']
        width = self.p['right']-self.block_x(bi)
        measure = lambda a, z: self.width(bi, a, z)
        breaks = self.blocks[bi].get('line_breaks', [])
        if breaks:
            if not self.spec.get('user_requested_line_breaks'):
                raise ValueError('正文按版心自然换行；仅用户指定分行可覆盖。')
            rows = explicit_rows(text, breaks, 'Invalid line breaks')
            if any(measure(a, z) > width for a, z, _ in rows):
                raise ValueError('Line exceeds text area')
        elif self.mode == '备忘录' and self.blocks[bi].get('heading'):
            rows = balanced_heading_rows(text, width, measure)
        else:
            rows = wrapped_rows(text, width, measure, strict=True)
        return [dict(block=bi, offset=a, end=z,
                     para_start=(idx == 0), para_end=(idx == len(rows)-1),
                     heading=bool(self.blocks[bi].get('heading')), break_reason=reason)
                for idx, (a, z, reason) in enumerate(rows)]

    def row_layer(self, row):
        bi, start, end = row['block'], row['offset'], row['end']
        text, x = self.blocks[bi]['text'], self.block_x(bi)
        layer = Image.new('RGBA', (W, 420))
        draw, base = ImageDraw.Draw(layer), 220
        runs = []
        for lo, hi, role, size in self.runs(bi, start, end):
            face = self.font(size, role)
            runs.append((lo, hi, x, face))
            x += face.getlength(text[lo:hi], **self.lang)

        def position(offset):
            for r_lo, r_hi, origin, face in runs:
                if r_hi >= offset:
                    return origin+face.getlength(text[r_lo:offset], **self.lang)
            return x

        def ink_edge(offset, right_side=False):
            for r_lo, r_hi, origin, face in runs:
                if (r_lo < offset <= r_hi) if right_side else (r_lo <= offset < r_hi):
                    if right_side:
                        return origin+face.getbbox(text[r_lo:offset], anchor='ls', **self.lang)[2]
                    prefix = origin+face.getlength(text[r_lo:offset], **self.lang)
                    return prefix+face.getbbox(text[offset], anchor='ls', **self.lang)[0]
            return position(offset)

        marks = self.marks[bi] if self.mode == '长文' else []
        rectangles = []
        glyph = self.font(self.p['size']).getbbox('国', anchor='ls', **self.lang)
        for lo, hi in marks:
            lo, hi = max(start, lo), min(end, hi)
            if lo < hi:
                rx0 = max(round(position(lo)), round(ink_edge(lo)-6)) if lo > start else round(ink_edge(lo)-6)
                rx1 = min(round(ink_edge(hi, True)+6), round(position(hi)-2 if hi < end else ink_edge(hi, True)+6))
                rect = (rx0, base+round(glyph[1]*0.42), rx1, base+glyph[3]+8)
                draw.rounded_rectangle(rect, radius=8, fill=self.p['mark_fill'])
                rectangles.append(rect)
        for lo, hi, origin, face in runs:
            fragment = text[lo:hi]
            fill = self.p['title_ink'] if (self.mode == '备忘录' and row['heading']) else self.p['ink']
            draw.text((origin, base+visual_offset(face, fragment, self.lang)), fragment,
                      font=face, fill=fill, anchor='ls', **self.lang)
        bbox = layer.getbbox()
        if bbox is None:
            bbox = (self.p['x'], base+glyph[1], self.p['x']+1, base+glyph[3])
        return layer, [bbox[0], bbox[1]-base, bbox[2], bbox[3]-1-base], rectangles

    def metric(self, row):
        key = (row['block'], row['offset'], row['end'])
        if key not in self.metric_cache:
            self.metric_cache[key] = self.row_layer(row)[1]
        return self.metric_cache[key]

    def place(self, rows, top):
        p, placed = self.p, []
        if self.mode == '备忘录':
            body_g = self.font(p['size']).getbbox('国', anchor='ls', **self.lang)
            head_g = self.font(p['heading_size'], 'bold').getbbox('国', anchor='ls', **self.lang)
            for i, row in enumerate(rows):
                g = head_g if row['heading'] else body_g
                if i == 0:
                    base = top - g[1]
                else:
                    prev = rows[i-1]
                    if prev['block'] == row['block']:
                        base += p['heading_step'] if row['heading'] else p['step']
                    elif prev['heading']:
                        base += p['after'] - g[1] + head_g[3]
                    elif row['heading']:
                        base += p['before'] - g[1] + body_g[3]
                    else:
                        base += p['gap'] - g[1] + body_g[3]
                placed.append(dict(row, baseline=base,
                                   ink_bounds=[self.block_x(row['block']), base+g[1], p['right'], base+g[3]]))
            return dict(rows=placed, bottom=placed[-1]['ink_bounds'][3])
        base = top-self.metric(rows[0])[1]
        if self.mode == '长文' and self.numbered(rows[0]['block']):
            base += 40
        for i, row in enumerate(rows):
            box = self.metric(row)
            if i:
                prev = rows[i-1]
                if prev['block'] == row['block']:
                    base += p['heading_step'] if row['heading'] else p['step']
                else:
                    numbered = self.numbered(row['block'])
                    boundary = self.numbered(prev['block']) != numbered
                    gap = p['gap'] if boundary else p['after'] if prev['heading'] else p['before'] if row['heading'] else p['gap']
                    clearance = 40 if boundary else 0
                    base += self.metric(prev)[3]+gap+clearance+1-box[1]
            placed.append(dict(row, baseline=base,
                               ink_bounds=[box[0], base+box[1], box[2], base+box[3]]))
        bottom = placed[-1]['ink_bounds'][3]
        if self.mode == '长文' and self.numbered(rows[-1]['block']):
            bottom += 40
        return dict(rows=placed, bottom=bottom)

    def legal_end(self, rows, i, j):
        chosen = rows[i:j]
        if chosen[-1]['heading']:
            return False
        last_heading = next((k for k in range(len(chosen)-1, -1, -1) if chosen[k]['heading']), None)
        if last_heading is not None and sum(not r['heading'] for r in chosen[last_heading+1:]) < self.p['follow']:
            return False
        return True

    def fit(self, rows, i, top, stop=None):
        limit = len(rows) if stop is None else stop
        if self.mode == '备忘录':
            k = i
            for t in range(i+1, limit+1):
                if self.place(rows[i:t], top)['bottom'] > self.p['bottom']:
                    break
                k = t
            if k == i:
                raise ValueError('阅读区容不下标题及后文或合法续行。')
            if k < limit:
                while k > i and not self.legal_end(rows, i, k):
                    k -= 1
                if k == i:
                    raise ValueError('阅读区容不下标题及后文或合法续行。')
                def splits(pos):
                    lr, nr = rows[pos-1], rows[pos]
                    return lr['block'] == nr['block'] and any(a < lr['end'] < b for a, b in self.marks[lr['block']])
                def end_score(r):
                    if r['para_end']:
                        return 3
                    ch = self.blocks[r['block']]['text'][r['end']-1]
                    return 2 if ch in '。！？…”》）】' else 1 if ch in '；，：、' else 0
                next_r = rows[k]
                widow = (not next_r['para_start'] and next_r['para_end'] and (next_r['end']-next_r['offset']) <= 4)
                if (splits(k) or widow) and k-1 > i and self.legal_end(rows, i, k-1):
                    k -= 1
                if end_score(rows[k-1]) == 0:
                    best_k, best_sc, cur_blk = k, 0, rows[k-1]['block']
                    for d in (1, 2):
                        cand = k-d
                        if cand-i < 5 or not self.legal_end(rows, i, cand) or splits(cand) or rows[cand-1]['block'] != cur_blk:
                            continue
                        sc = end_score(rows[cand-1])
                        if sc > best_sc:
                            best_sc, best_k = sc, cand
                            if sc >= 2:
                                break
                    k = best_k
            return dict(self.place(rows[i:k], top), stop=k)
        best, clean = None, None
        for j in range(i+1, limit+1):
            page = self.place(rows[i:j], top)
            if page['bottom'] > self.p['bottom']:
                break
            if self.legal_end(rows, i, j):
                best = dict(page, stop=j)
                widow = j < limit and rows[j]['para_end'] and not rows[j]['para_start'] and (rows[j]['end']-rows[j]['offset']) <= 6
                orphan = j < limit and rows[j-1]['para_start'] and not rows[j-1]['para_end'] and (j-i) >= 4
                if not widow and not orphan:
                    clean = best
        if best is None:
            raise ValueError('阅读区容不下标题及后文或合法续行。')
        return clean or best

    def pages(self, cover_only=False):
        if self.mode == '长文' and cover_only:
            return [dict(kind='cover', rows=[], gaps=[])]
        rows = [r for bi in range(len(self.blocks)) for r in self.natural_lines(bi)]
        if not rows:
            raise ValueError('缺少正文blocks。')
        pages = [dict(kind='cover', rows=[], gaps=[])] if self.mode == '长文' else []
        first_top = self.p['top']
        if self.mode == '备忘录':
            probe = Image.new('RGB', (W, H), self.p['paper'])
            self.titles(probe)
            first_top = self.title_record['body_top']
        i = 0
        while i < len(rows):
            page = self.fit(rows, i, first_top if not pages else self.p['top'])
            pages.append(dict(page, kind='body'))
            i = page['stop']
            if cover_only:
                break
        return pages

    def toolbar(self, im, show_date=False):
        c, S = MEMO_CHROME, 4
        bar_h, cy, r = c['bar_h'], c['bar_cy'], c['cap_r']
        lcx = c['bar_margin'] + r
        rx1 = W - c['bar_margin']
        rx0 = rx1 - c['right_pill_w']
        layer = Image.new('RGBA', (W, bar_h), (0, 0, 0, 0))
        sh = Image.new('RGBA', (W, bar_h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sh)
        sd.ellipse((lcx-r, cy-r+10, lcx+r, cy+r+10), fill=(0, 0, 0, 20))
        sd.rounded_rectangle((rx0, cy-r+10, rx1, cy+r+10), radius=r, fill=(0, 0, 0, 20))
        layer.alpha_composite(sh.filter(ImageFilter.GaussianBlur(18)))

        hi = Image.new('RGBA', (W*S, bar_h*S), (0, 0, 0, 0))
        hd = ImageDraw.Draw(hi)
        hd.ellipse(((lcx-r)*S, (cy-r)*S, (lcx+r)*S, (cy+r)*S),
                   fill=(255, 255, 255, 250), outline=c['pill_edge'], width=2*S)
        hd.rounded_rectangle((rx0*S, (cy-r)*S, rx1*S, (cy+r)*S), radius=r*S,
                             fill=(255, 255, 255, 250), outline=c['pill_edge'], width=2*S)
        col = c['icon_col']

        def stroke(points, w):
            hd.line(points, fill=col, width=w, joint='curve')
            for px, py in points:
                hd.ellipse((px-w//2, py-w//2, px+w//2, py+w//2), fill=col)

        stroke([((lcx+17)*S, (cy-39)*S), ((lcx-22)*S, cy*S), ((lcx+17)*S, (cy+39)*S)], 11*S)
        scx, sw = (rx0+124)*S, 9*S
        box_top, box_bot = (cy-14)*S, (cy+48)*S
        hd.rounded_rectangle((scx-38*S, box_top, scx+38*S, box_bot), radius=15*S, outline=col, width=sw)
        hd.rectangle((scx-16*S, box_top-4*S, scx+16*S, box_top+14*S), fill=(255, 255, 255, 255))
        tip = (cy-48)*S
        stroke([(scx, (cy+16)*S), (scx, tip)], sw)
        stroke([(scx-22*S, tip+22*S), (scx, tip), (scx+22*S, tip+22*S)], sw)
        mcx, dr = (rx1-124)*S, round(7.5*S)
        for dx in (-34, 0, 34):
            hd.ellipse((mcx+dx*S-dr, cy*S-dr, mcx+dx*S+dr, cy*S+dr), fill=col)
        layer.alpha_composite(hi.resize((W, bar_h), Image.Resampling.LANCZOS))
        im.paste(layer, (0, 0), layer)
        if show_date and self.memo_date:
            d = ImageDraw.Draw(im)
            tf = self.font(c['date_size'], 'regular')
            tw = mixed_width(tf, self.memo_date, self.lang)
            draw_mixed(d, round((W-tw)/2), c['date_baseline'], self.memo_date, tf, c['date_color'], self.lang)

    def frame(self, im, physical, total, body_page=None, body_bottom=None):
        d, p = ImageDraw.Draw(im), self.p
        author, name, label = author_meta(self.spec)
        if self.mode == '备忘录':
            c = MEMO_CHROME
            if physical == total and body_bottom is not None and body_bottom < c['end_limit_y']:
                sy = body_bottom+c['end_gap']
                d.rounded_rectangle((p['x'], sy, p['x']+56, sy+5), radius=3, fill=p['accent'])
                draw_tracked(d, self.font(36, 'medium'), f'END · {author}', p['x'], sy+28, 6, c['footer_color'])
            d.text((p['x'], c['footer_text_y']), author, font=self.font(c['footer_size'], 'medium'),
                   fill=c['footer_color'], anchor='lt', **self.lang)
            draw_tracked(d, self.font(c['page_num_size'], 'regular'), f'{body_page:02d} / {total:02d}',
                         p['right'], c['footer_text_y']+4, 5, c['footer_color'], right=True)
            return

        if physical > 1:
            draw_tracked(d, self.font(34, 'sans'), label, p['x'], 206, 6, p['muted'])
            d.text((p['right'], 202), author, font=self.font(38, 'sans_medium'), fill='#5A564F', anchor='rt', **self.lang)
            d.line((p['x'], 284, p['right'], 284), fill=p['rule'], width=2)
            if physical == total and body_bottom is not None and body_bottom < 1850:
                sy = body_bottom+150
                d.rounded_rectangle((p['x'], sy, p['x']+56, sy+5), radius=2, fill=p['accent'])
                draw_tracked(d, self.font(32, 'sans'), f'END · {author}', p['x'], sy+32, 6, '#9A948A')
        fy = 2690 if physical == 1 else 2616
        lx, rx = (180, 1980) if physical == 1 else (p['x'], p['right'])
        d.line((lx, fy, rx, fy), fill=p['rule'], width=2)
        draw_tracked(d, self.font(32, 'sans'), name, lx, fy+42, 7, p['muted'])
        draw_tracked(d, self.font(32, 'sans'), f'{physical:02d} / {total:02d}', rx, fy+42, 5, p['muted'], right=True)

    def title_layer(self, text, size, role):
        face = self.font(size, role)
        layer = Image.new('RGBA', (W, size*3))
        draw_mixed(ImageDraw.Draw(layer), 0, size*2, text, face, '#161513' if self.mode == '长文' else self.p['title_ink'], self.lang)
        return layer, layer.getbbox(), mixed_width(face, text, self.lang)

    def titles(self, im):
        lines, p = self.spec['title_lines'], self.p
        semantic_lines(lines, 'title_lines须为按语义准备的1至2行非空标题。')
        d = ImageDraw.Draw(im)
        if self.mode == '备忘录':
            for size in range(p['title_size'], 0, -2):
                face = self.font(size, 'bold')
                if max(mixed_width(face, t, self.lang) for t in lines) <= p['right']-p['x']:
                    break
            else:
                raise ValueError('标题超出版心。')
            step = round(size * p['title_ratio'])
            base = p['title_top']-face.getbbox(lines[0], anchor='ls', **self.lang)[1]
            bottom = base
            for i, text in enumerate(lines):
                b = base+i*step
                draw_mixed(d, p['x'], b, text, face, p['title_ink'], self.lang)
                bottom = b+face.getbbox(text, anchor='ls', **self.lang)[3]
            self.title_record = dict(size=size, top=p['title_top'], step=step, body_top=bottom+p['title_after'],
                                     body_gap=p['title_after'], date=self.memo_date)
            return

        cfg, spec, font = ARTICLE_COVER, self.spec, self.font
        author, _, label = author_meta(spec)
        draw_tracked(d, font(34, 'sans'), label, 180, 198, 6, p['muted'])
        d.text((1980, 194), author, font=font(38, 'sans_medium'), fill='#3D3B37', anchor='rt', **self.lang)
        d.line((180, 268, 1980, 268), fill=p['rule'], width=2)

        l, t, r, b = cfg['photo_box']
        im.paste(fit_image(spec['cover'], (r-l, b-t), spec.get('cover_crop')), (l, t))
        d.rectangle((l, t, r-1, b-1), outline='#E0DBD0', width=2)

        subtitle = spec.get('cover_subtitle', cfg['subtitle'])
        if not isinstance(subtitle, str):
            raise ValueError('cover_subtitle须为文字；空字符串关闭副题。')
        sub_face = font(cfg['subtitle_size'], 'sans')
        subtitle_height = sub_face.getbbox(subtitle, anchor='lt', **self.lang)[3] if subtitle else 0
        sizes = spec.get('cover_title_sizes')
        if sizes is not None and (not isinstance(sizes, list) or len(sizes) != len(lines)
                                  or any(type(n) is not int or not 0 < n <= H for n in sizes)):
            raise ValueError('cover_title_sizes须逐行提供1至画布高度的整数字号。')
        accent_y = b+cfg['accent_gap']
        for size in ([sizes[0]] if sizes is not None else range(cfg['title_max'], 0, -1)):
            layers = [self.title_layer(text, n, 'bold')
                      for text, n in zip(lines, sizes if sizes is not None else [size]*len(lines))]
            heights = [box[3]-box[1] for _, box, _ in layers]
            top = accent_y+8+cfg['accent_to_title']
            gap = round(cfg['title_gap']*size/cfg['title_max'])
            title_bottom = top+sum(heights)+gap*(len(lines)-1)
            subtitle_top = title_bottom+(cfg['subtitle_gap'] if subtitle else 0)
            block_bottom = subtitle_top+subtitle_height if subtitle else title_bottom
            if max(width for _, _, width in layers) <= r-l and block_bottom < 2670:
                break
        else:
            raise ValueError('两行标题超出版心。')
        offset = spec.get('cover_title_offset_y', 0)
        if type(offset) is not int:
            raise ValueError('cover_title_offset_y须为整数像素，负数上移、正数下移。')
        if accent_y+offset < b+16 or block_bottom+offset >= 2690:
            raise ValueError('标题偏移后进入照片或页脚，请减小偏移量。')
        accent_y += offset
        top += offset
        subtitle_top += offset
        d.rounded_rectangle((l, accent_y, l+88, accent_y+8), radius=4, fill=p['accent'])
        for layer, box, _ in layers:
            im.paste(layer, (l, top-box[1]), layer)
            top += box[3]-box[1]+gap
        if subtitle:
            if mixed_width(sub_face, subtitle, self.lang) > r-l:
                raise ValueError('固定副题超出版心。')
            d.text((l, subtitle_top), subtitle, font=sub_face, fill='#68645C', anchor='lt', **self.lang)
        self.title_record = dict(size=size, sizes=sizes or [size]*len(lines), gap=gap, subtitle_top=subtitle_top if subtitle else None,
                                 subtitle=subtitle, photo_box=cfg['photo_box'])

    def draw_memo_selection(self, im, rows):
        c, p = MEMO_CHROME, self.p
        ranges = {}
        for r in rows:
            if r['heading'] or not self.marks[r['block']]:
                continue
            bi = r['block']
            ranges[bi] = (min(ranges.get(bi, (10**9, 0))[0], r['offset']),
                          max(ranges.get(bi, (10**9, 0))[1], r['end']))
        selected = next(((bi, a, z) for bi, (lo, hi) in ranges.items()
                         for a, z in self.marks[bi] if lo <= a and z <= hi), None)
        if selected is None:
            selected = next(((r['block'], a, z) for r in rows if not r['heading']
                             for a, z in self.marks[r['block']]
                             if a < r['end'] and z > r['offset']), None)
        if not selected:
            return None
        sel_bi, m0, m1 = selected
        sel_rows = [(r, max(r['offset'], m0), min(r['end'], m1)) for r in rows
                    if r['block'] == sel_bi and max(r['offset'], m0) < min(r['end'], m1)]
        if not sel_rows:
            return None
        glyph = self.font(p['size']).getbbox('国', anchor='ls', **self.lang)
        pad_outer = c['sel_pad_outer']
        pad_inner = round((p['step'] - (glyph[3] - glyph[1])) / 2) + 2
        d, rects = ImageDraw.Draw(im), []
        for idx, (r, lo, hi) in enumerate(sel_rows):
            base = r['baseline']
            top_y = rects[-1][3] if idx > 0 else base + glyph[1] - pad_outer
            bot_y = base + glyph[3] + (pad_outer if idx == len(sel_rows) - 1 else pad_inner)
            x0 = round(p['x'] + self.width(sel_bi, r['offset'], lo)) if idx == 0 else p['x']
            if idx == len(sel_rows) - 1:
                x1 = round(p['x'] + self.width(sel_bi, r['offset'], hi))
            else:
                x1 = max(round(p['x'] + self.width(sel_bi, r['offset'], r['end'])), p['right'] - 8)
            rects.append((x0, top_y, x1, bot_y))
            d.rectangle((x0, top_y, x1, bot_y), fill=p['mark_fill'])
        return rects[0], rects[-1]

    def draw_memo_handles(self, im, bounds):
        if not bounds:
            return
        first_r, last_r = bounds
        c, pad, S = MEMO_CHROME, 40, 4
        min_x, max_x = max(0, min(first_r[0], last_r[2]) - pad), min(W, max(first_r[0], last_r[2]) + pad)
        min_y, max_y = max(0, first_r[1] - pad), min(H, last_r[3] + pad)
        hi = Image.new('RGBA', ((max_x - min_x) * S, (max_y - min_y) * S), (0, 0, 0, 0))
        hd = ImageDraw.Draw(hi)
        col, sw, br = self.p['accent'], c['handle_stem_w'] * S, c['handle_ball_r'] * S
        sx, sy0, sy1 = (first_r[0] - min_x) * S, (first_r[1] - min_y) * S, (first_r[3] - min_y) * S
        hd.line((sx, sy0 - 2 * S, sx, sy1), fill=col, width=sw)
        hd.ellipse((sx - br, sy0 - br * 2 + 2 * S, sx + br, sy0 + 2 * S), fill=col)
        ex, ey0, ey1 = (last_r[2] - min_x) * S, (last_r[1] - min_y) * S, (last_r[3] - min_y) * S
        hd.line((ex, ey0, ex, ey1 + 2 * S), fill=col, width=sw)
        hd.ellipse((ex - br, ey1 - 2 * S, ex + br, ey1 + br * 2 - 2 * S), fill=col)
        sm = hi.resize((max_x - min_x, max_y - min_y), Image.Resampling.LANCZOS)
        im.paste(sm, (min_x, min_y), sm)

    def page_image(self, plan, physical, total, body_page=None):
        cover, p = plan['kind'] == 'cover', self.p
        im = Image.new('RGB', (W, H), p['paper'])
        if not cover and self.mode == '备忘录':
            self.toolbar(im, show_date=(body_page == 1))
        if cover or (self.mode == '备忘录' and body_page == 1):
            self.titles(im)
        memo_handles = None
        if self.mode == '备忘录' and not cover:
            d, c = ImageDraw.Draw(im), MEMO_CHROME
            h_groups = {}
            for r in plan['rows']:
                if r['heading']:
                    h_groups.setdefault(r['block'], []).append(r)
            for hr in h_groups.values():
                d.rounded_rectangle((p['x'], hr[0]['ink_bounds'][1] - 3,
                                     p['x'] + c['quote_bar_w'], hr[-1]['ink_bounds'][3] + 5),
                                    radius=5, fill=c['quote_bar_col'])
            memo_handles = self.draw_memo_selection(im, plan['rows'])
        for row in plan['rows']:
            layer, _, _ = self.row_layer(row)
            im.paste(layer, (0, row['baseline'] - 220), layer)
        if memo_handles:
            self.draw_memo_handles(im, memo_handles)
        if self.mode == '长文' and not cover:
            draw = ImageDraw.Draw(im)
            for bi, block in enumerate(self.blocks):
                rows = [row for row in plan['rows'] if row['block'] == bi]
                if not rows or not self.numbered(bi):
                    continue
                number = block['number']
                if type(number) is not int or number < 1:
                    raise ValueError('number must be a positive integer')
                numeral, face = f'{number:02d}', self.font(44, 'number')
                top, bottom = rows[0]['ink_bounds'][1], rows[-1]['ink_bounds'][3]
                box = face.getbbox(numeral, anchor='lt')
                ny = round((top+bottom-(box[3]-box[1]))/2)
                draw.text((p['x'], ny), numeral, font=face, fill=p['accent'], anchor='lt')
                rules = [bottom+40] if bi and self.numbered(bi-1) else [top-40, bottom+40]
                for y in rules:
                    draw.line((p['x'], y, p['right'], y), fill=p['rule'], width=2)
        self.frame(im, physical, total, body_page, plan.get('bottom'))
        return im, dict(kind=plan['kind'], physical_page=physical, body_page=body_page,
                        body_bottom=plan.get('bottom'), body_limit=p['bottom'])


def resolved(base, name):
    return str((base/Path(name).expanduser()).resolve())


def font_paths(fonts, base):
    return {k: v if k.endswith('_index') else resolved(base, v) for k, v in fonts.items()}


def load_personal(spec, base):
    config = Path(resolved(base, spec.get('personal_config', '~/.config/social-graphics/personal.json')))
    return config, (json.loads(config.read_text(encoding='utf-8-sig')) if config.is_file() else {})


def apply_personal(spec, mode, config, personal):
    p_fonts = personal.get('fonts')
    if isinstance(p_fonts, dict) and p_fonts:
        merged = font_paths(p_fonts, config.parent)
        if 'fonts' in spec:
            merged.update(spec['fonts'])
        spec['fonts'] = merged
    if not spec.get('footer') and personal.get('footer'):
        spec['footer'] = personal['footer']
    if mode in ('图解', '备忘录', '长文'):
        author, _, default_label = author_meta(spec)
        spec['footer'] = author
        if mode in ('图解', '长文') and not spec.get('channel_label'):
            spec['channel_label'] = str(personal.get('channel_label') or default_label).strip()
        if mode == '长文' and 'cover_subtitle' not in spec:
            spec['cover_subtitle'] = personal.get('cover_subtitle', '')


def _read_preview_lock(lock_path):
    if not lock_path or not lock_path.is_file():
        return None
    try:
        data = json.loads(lock_path.read_text(encoding='utf-8-sig'))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _write_preview_lock(lock_path, payload):
    if not lock_path:
        return
    temp = lock_path.with_suffix('.tmp')
    temp.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    temp.replace(lock_path)


def select_photo(spec, mode, base, config=None, personal=None, commit_gallery=True, preview_lock_path=None):
    if mode == '备忘录' or (mode == '图解' and not spec.get('gallery_request') and 'cover' not in spec):
        return
    key = 'background' if mode in ('朋友圈', '字幕') else 'cover'
    if spec.get('user_selected_photo') is True and key in spec:
        spec.pop('gallery_id', None)
        return
    if config is None or personal is None:
        config, personal = load_personal(spec, base)
    bundled = ROOT/'assets/private/gallery/制作记录.json'
    gallery = spec.get('gallery', personal.get('gallery', str(bundled) if bundled.is_file() else None))
    if not gallery or not spec.get('gallery_request'):
        raise ValueError('默认用图须配置gallery并提供gallery_request；仅本次用户指定图可设user_selected_photo: true并提供图片路径。')
    catalog = Path(resolved(base if 'gallery' in spec else config.parent, gallery))
    images = json.loads(catalog.read_text(encoding='utf-8-sig'))['assets']
    state = Path(resolved(base, spec.get('gallery_state', str(config.parent/'gallery-state.json'))))
    request = spec['gallery_request']
    req_match = re.match(r'^(.*):(\d+)$', request)
    lock_data = _read_preview_lock(preview_lock_path)
    locked_photo = None
    locked_crop = None
    if lock_data and lock_data.get('gallery_request') == request and lock_data.get('catalog') == str(catalog):
        locked_photo = next((img for img in images if img['id'] == lock_data.get('gallery_id')), None)
        if locked_photo and lock_data.get('key') == key and lock_data.get('crop') is not None:
            locked_crop = lock_data['crop']
    if not commit_gallery:
        if locked_photo is not None:
            photo = locked_photo
        else:
            data = json.loads(state.read_text(encoding='utf-8-sig')) if state.exists() else []
            if request in data:
                idx = data.index(request)
            else:
                offset = 0
                if req_match and int(req_match.group(2)) > 1:
                    prefix, attempt = req_match.group(1), int(req_match.group(2))
                    offset = sum(1 for k in range(1, attempt) if f'{prefix}:{k}' not in data)
                idx = len(data) + offset
            photo = images[idx % len(images)]
        selected = resolved(catalog.parent, photo['source'])
        if key in spec and resolved(base, spec[key]) != selected:
            spec.pop(key+'_crop', None)
        spec[key] = selected
        if key+'_crop' not in spec and locked_crop is not None:
            spec[key+'_crop'] = locked_crop
        spec['gallery_id'] = photo['id']
        _write_preview_lock(preview_lock_path, {
            'gallery_request': request, 'catalog': str(catalog), 'key': key,
            'gallery_id': photo['id'], 'photo': selected, 'crop': spec.get(key+'_crop'),
        })
        return
    state.parent.mkdir(parents=True, exist_ok=True)
    with state.with_suffix('.lock').open('a+', encoding='utf-8') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.write('0'); lock.flush(); lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        data = json.loads(state.read_text(encoding='utf-8-sig')) if state.exists() else []
        if request not in data:
            if req_match and int(req_match.group(2)) > 1:
                prefix, attempt = req_match.group(1), int(req_match.group(2))
                for k in range(1, attempt):
                    prior = f'{prefix}:{k}'
                    if prior not in data:
                        data.append(prior)
            data.append(request)
        photo = locked_photo if locked_photo is not None else images[data.index(request) % len(images)]
        selected = resolved(catalog.parent, photo['source'])
        if key in spec and resolved(base, spec[key]) != selected:
            spec.pop(key+'_crop', None)
        spec[key] = selected
        if key+'_crop' not in spec and locked_crop is not None:
            spec[key+'_crop'] = locked_crop
        temp = state.with_suffix('.tmp')
        temp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        temp.replace(state)
    spec['gallery_id'] = photo['id']


_SCALE_MAP = {'百': 1e2, '千': 1e3, 'k': 1e3, 'K': 1e3, '万': 1e4, 'w': 1e4, 'W': 1e4, '亿': 1e8}
_UNIT_ALIAS = {
    '%': '%', '％': '%', '倍': '倍', 'x': '倍', 'X': '倍', '×': '倍',
    '元': '元', '块': '元', '¥': '元', '￥': '元', 'rmb': '元', 'RMB': '元', '人民币': '元',
    '$': '$', '美元': '$', '美金': '$',
    '小时': '小时', '个小时': '小时', 'h': '小时', 'H': '小时', '时': '小时',
    '分钟': '分钟', '分': '分钟', 'min': '分钟', '秒': '秒',
    '天': '天', '日': '天', '周': '周', '月': '月', '个月': '月', '年': '年',
    '人': '人', '个人': '人', '位': '人', '名': '人',
    '次': '次', '篇': '篇', '条': '条', '单': '单', '粉': '粉',
    '家': '家', '件': '件', '张': '张', '页': '页', '步': '步', '个': '个',
}
_CN_DIGITS = {'零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
_CN_UNITS = {'十': 10, '百': 100, '千': 1000, '万': 10000, '亿': 100000000}
_UNIT_PAT = r'(?:%|％|人民币|rmb|RMB|美元|美金|个小时|小时|分钟|个月|个人|元|块|倍|天|日|周|月|年|人|位|名|次|篇|条|单|粉|家|件|张|页|步|个|秒|分|时|x|X|×|h|H)'
_NUM_TOK = r'-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?'
_BAR_VAL_RE = re.compile(
    r'^\s*[~≈约超近+]?\s*(¥|￥|\$)?\s*(' + _NUM_TOK + r')\s*(?:([百千万亿kKwW])(\d)?)?\s*\+?\s*(' + _UNIT_PAT + r')?\s*$'
)
_ARABIC_MENTION_RE = re.compile(
    r'(¥|￥|\$)?[ \t]*(' + _NUM_TOK + r')(?:[ \t]*([百千万亿kKwW])(\d)?)?\+?[ \t]*(' + _UNIT_PAT + r')?'
)
_CN_PCT_RE = re.compile(r'百分之([零〇一二两三四五六七八九十百千万点]+)')
_CN_NUM_RE = re.compile(r'([一二两三四五六七八九十百千万亿]{1,8})[ \t]*(' + _UNIT_PAT + r')?')
_HEADER_UNIT_RE = re.compile(r'[（(]\s*(' + _UNIT_PAT + r')\s*[）)]')


def _norm_unit(prefix_sym, unit_str):
    if unit_str:
        return _UNIT_ALIAS.get(unit_str, _UNIT_ALIAS.get(unit_str.lower(), unit_str))
    if prefix_sym in ('¥', '￥'):
        return '元'
    if prefix_sym == '$':
        return '$'
    return ''


def parse_bar_value(raw):
    m = _BAR_VAL_RE.match(str(raw or ''))
    if not m:
        return None
    sym, num_s, scale, tail_digit, unit_s = m.groups()
    val = float(num_s.replace(',', ''))
    if scale:
        mult = _SCALE_MAP[scale]
        if tail_digit and '.' not in num_s:
            val = (val + int(tail_digit) / 10.0) * mult
        else:
            val *= mult
    return val, _norm_unit(sym, unit_s)


def resolve_bar_ratios(cols):
    if not cols:
        raise ValueError('bars.cols不能为空。')
    parsed = [parse_bar_value(c.get('value', '')) for c in cols]
    if not all(p is not None for p in parsed):
        raise ValueError('bars仅用于同单位可比数值，当前各柱缺少可比数值，请改用columns（分栏）或timeline（流程图）。')
    units = {u for _, u in parsed}
    if len(units) > 1:
        raise ValueError(f'bars各柱单位不一致（{sorted(units)}），无法按同一标尺画柱高，请统一单位或改用columns。')
    vals = [v for v, _ in parsed]
    if any(v < 0 for v in vals) or max(vals) <= 0:
        raise ValueError('bars数值须为非负且至少有一项大于0，否则请改用columns或versus。')
    vmax = max(vals)
    auto = [0.06 if v == 0 else round(0.14 + 0.86 * (v / vmax), 4) for v in vals]
    has_manual = [c.get('ratio') is not None for c in cols]
    if any(has_manual):
        if not all(has_manual):
            return auto
        manual = [max(0.06, min(1.0, float(c['ratio']))) for c in cols]
        for i in range(len(cols)):
            for j in range(len(cols)):
                if vals[i] > vals[j] and manual[i] <= manual[j]:
                    raise ValueError(
                        f'bars柱高比例与数值方向矛盾：{cols[i]["value"]}(ratio={manual[i]}) 与 '
                        f'{cols[j]["value"]}(ratio={manual[j]})，请删除手动ratio由脚本按数值自动计算。'
                    )
        return manual
    return auto


def cn_to_num(text):
    if not text:
        return None
    if '点' in text:
        head, tail = text.split('点', 1)
        iv = cn_to_num(head) if head else 0.0
        if iv is None or not tail or any(ch not in _CN_DIGITS for ch in tail):
            return None
        frac = ''.join(str(_CN_DIGITS[ch]) for ch in tail)
        return iv + float('0.' + frac)
    total, section, num = 0, 0, 0
    for ch in text:
        if ch in _CN_DIGITS:
            num = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            u = _CN_UNITS[ch]
            if u >= 10000:
                section = (section + num) if (section or num) else 1
                total += section * u
                section, num = 0, 0
            else:
                if num == 0 and u == 10 and section == 0:
                    num = 1
                section += num * u
                num = 0
        else:
            return None
    val = total + section + num
    return float(val) if val > 0 or '零' in text or '〇' in text else None


def extract_numeric_mentions(text):
    mentions = []
    s = str(text or '')
    for m in _CN_PCT_RE.finditer(s):
        v = cn_to_num(m.group(1))
        if v is not None:
            mentions.append((m.group(0), v, '%', m.start(), m.end()))
    for m in _ARABIC_MENTION_RE.finditer(s):
        sym, num_s, scale, tail_digit, unit_s = m.groups()
        val = float(num_s.replace(',', ''))
        if scale:
            mult = _SCALE_MAP[scale]
            val = (val + int(tail_digit) / 10.0) * mult if (tail_digit and '.' not in num_s) else val * mult
        mentions.append((m.group(0), val, _norm_unit(sym, unit_s), m.start(), m.end()))
    for m in _CN_NUM_RE.finditer(s):
        raw_cn, unit_s = m.group(1), m.group(2)
        if m.start() > 0 and s[max(0, m.start()-3):m.start()].endswith('百分之'):
            continue
        if len(raw_cn) == 1 and not unit_s and raw_cn in ('十', '百', '千', '万', '亿'):
            continue
        v = cn_to_num(raw_cn)
        if v is not None:
            mentions.append((m.group(0), v, _norm_unit(None, unit_s), m.start(), m.end()))
    return mentions


def _units_compatible(unit, su):
    if unit == '%':
        return su == '%'
    if unit and su:
        return unit == su
    return True


def _mention_matches_source(val, unit, src_mentions):
    mismatched_units = []
    for raw_s, sv, su, _, _ in src_mentions:
        if abs(sv - val) <= max(1e-6, abs(val) * 1e-6):
            if _units_compatible(unit, su):
                return True, []
            mismatched_units.append(raw_s.strip())
    return False, list(dict.fromkeys(mismatched_units))


_ORDINAL_UNITS = {'', '步', '条', '页', '张', '个', '篇'}


def check_diagram_numbers(spec):
    errors = []
    source_text = str(spec.get('source_text') or '').strip()
    if not source_text:
        return errors
    src_mentions = extract_numeric_mentions(source_text)

    def walk_fields(obj, prefix):
        out = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ('kind', 'ratio', 'highlight', 'image', 'op', 'number'):
                    continue
                out.extend(walk_fields(v, f'{prefix}.{k}' if prefix else k))
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                out.extend(walk_fields(v, f'{prefix}[{i}]'))
        elif isinstance(obj, str) and obj.strip():
            out.append((prefix, obj))
        return out

    for p_idx, page in enumerate(spec.get('pages', []), 1):
        diag = page.get('diagram') or {}
        dkind = diag.get('kind')
        cols = diag.get('cols', []) if dkind == 'bars' else []
        fields = walk_fields(diag, 'diagram')
        for idx, para in enumerate(page.get('upper', [])):
            fields.append((f'upper[{idx}]', para))
        for idx, para in enumerate(page.get('lower', [])):
            fields.append((f'lower[{idx}]', para))

        for label, txt in fields:
            is_bar_val = (dkind == 'bars' and label.endswith('.value'))
            inferred_unit = ''
            if is_bar_val:
                cm = re.match(r'^diagram\.cols\[(\d+)\]\.value$', label)
                if cm and int(cm.group(1)) < len(cols):
                    hm = _HEADER_UNIT_RE.search(str(cols[int(cm.group(1))].get('header') or ''))
                    if hm:
                        inferred_unit = _norm_unit(None, hm.group(1))
            for raw_tok, val, unit, pos, _ in extract_numeric_mentions(txt):
                eff_unit = unit or inferred_unit
                if not is_bar_val:
                    prev = txt[max(0, pos-2):pos]
                    if 0 < val <= 9 and val.is_integer():
                        if prev.endswith('第') and eff_unit in _ORDINAL_UNITS:
                            continue
                        if eff_unit == '' and (raw_tok.isdigit() or raw_tok in _CN_DIGITS):
                            continue
                ok, mismatches = _mention_matches_source(val, eff_unit, src_mentions)
                if not ok:
                    if mismatches:
                        shown = f'{raw_tok}（表头单位:{inferred_unit}）' if (not unit and inferred_unit) else raw_tok
                        errors.append(
                            f'图解第{p_idx}页 {label} 数值单位与原文不符：{shown!r}（原文对应为 {", ".join(mismatches[:3])}），请核对原文或改写。'
                        )
                    else:
                        errors.append(f'图解第{p_idx}页 {label} 出现原文未找到的数值 {raw_tok!r}，请核对原文或改写。')

        if dkind == 'bars':
            bar_info = []
            for col in cols:
                hdr = str(col.get('header') or '').strip()
                pv = parse_bar_value(col.get('value', ''))
                if len(hdr) >= 2 and pv is not None:
                    hm = _HEADER_UNIT_RE.search(hdr)
                    eff_u = pv[1] or (_norm_unit(None, hm.group(1)) if hm else '')
                    h_pos = [m.start() for m in re.finditer(re.escape(hdr), source_text)]
                    v_pos = [sp for _, sv, su, sp, _ in src_mentions
                             if abs(sv - pv[0]) <= max(1e-6, abs(pv[0]) * 1e-6) and _units_compatible(eff_u, su)]
                    if h_pos and v_pos:
                        bar_info.append((hdr, col['value'], pv[0], h_pos, v_pos))
            for i in range(len(bar_info)):
                for j in range(i+1, len(bar_info)):
                    hi, vi_str, vi, hpi, vpi = bar_info[i]
                    hj, vj_str, vj, hpj, vpj = bar_info[j]
                    if abs(vi - vj) <= 1e-6 or hi == hj:
                        continue
                    d_ii = min(abs(a - b) for a in hpi for b in vpi)
                    d_ij = min(abs(a - b) for a in hpi for b in vpj)
                    d_jj = min(abs(a - b) for a in hpj for b in vpj)
                    d_ji = min(abs(a - b) for a in hpj for b in vpi)
                    if d_ij < d_ii and d_ji < d_jj:
                        errors.append(
                            f'图解第{p_idx}页柱图对象与数值疑似错配：{hi}→{vi_str} 与 {hj}→{vj_str}，请对照原文核实。'
                        )
    return errors


def prepare_spec(spec_file, apply_gallery=True, commit_gallery=True):
    spec_file = Path(spec_file).resolve()
    spec = json.loads(spec_file.read_text(encoding='utf-8-sig'))
    mode = canonical_mode(spec['mode'])
    spec['mode'] = mode
    resolve = lambda name: resolved(spec_file.parent, name)
    for key in ('screenshot', 'background', 'cover', 'reuse_body', 'reuse_record'):
        if key in spec:
            spec[key] = [resolve(v) for v in spec[key]] if isinstance(spec[key], list) else resolve(spec[key])
    if 'fonts' in spec:
        spec['fonts'] = font_paths(spec['fonts'], spec_file.parent)
    reuse = spec.get('reuse_body', [])
    if reuse and mode == '备忘录':
        raise ValueError('备忘录不支持reuse_body，须按当前原文整套重排。')
    if reuse:
        record = Path(spec.get('reuse_record', Path(reuse[0]).parent/'制作记录.json'))
        if record.is_file():
            old = json.loads(record.read_text(encoding='utf-8-sig'))
            for key in ('source_text', 'blocks', 'paragraph_separator', 'fonts', 'cover', 'cover_crop',
                        'cover_title_offset_y', 'footer', 'channel_label', 'cover_subtitle'):
                if key == 'cover_crop' and ('cover' not in old or spec.get('cover') != resolved(record.parent, old['cover'])):
                    continue
                if key not in spec and key in old:
                    value = old[key]
                    if key == 'cover':
                        value = resolved(record.parent, value)
                    elif key == 'fonts':
                        value = font_paths(value, record.parent)
                    spec[key] = value
            spec['reuse_record'] = str(record.resolve())
        elif mode == '长文' and not spec.get('blocks'):
            raise ValueError('复用正文请提供原制作记录reuse_record。')
    config, personal = load_personal(spec, spec_file.parent)
    apply_personal(spec, mode, config, personal)
    if apply_gallery:
        preview_lock = spec_file.parent/f'.{spec_file.stem}.preview-lock.json'
        select_photo(spec, mode, spec_file.parent, config, personal, commit_gallery=commit_gallery, preview_lock_path=preview_lock)
    return spec_file, spec, mode, reuse


def _validate_diagram_spec(spec):
    errors, warnings = [], []
    pages = spec.get('pages', [])
    prev_kind = None
    for idx, page in enumerate(pages, 1):
        upper = page.get('upper', [])
        lower = page.get('lower', [])
        for phrase in page.get('marks', []):
            if not any(phrase in para for para in upper+lower):
                errors.append(f'图解第{idx}页强调短语不存在: {phrase!r}')
        diag = page.get('diagram')
        if diag is None and page.get('image'):
            diag = {'kind': 'image', 'image': page['image']}
        if diag:
            dkind = InfographicLayout.canonical_diagram_kind(diag['kind'])
            if prev_kind and dkind == prev_kind:
                warnings.append(f'图解第{idx-1}页与第{idx}页连续使用同一种图形（{dkind}），可考虑换型增强节奏。')
            prev_kind = dkind
            if dkind == 'bars':
                try:
                    resolve_bar_ratios(diag.get('cols', []))
                except ValueError as e:
                    errors.append(f'图解第{idx}页: {e}')
        else:
            prev_kind = None
    errors.extend(check_diagram_numbers(spec))
    return errors, warnings


def check_spec(spec_file):
    if not PIL_OK:
        return dict(ok=False, mode=None, total_pages=0,
                    errors=['缺少制图组件（Pillow），请按 references/environment.md 配齐后重试。'], warnings=[])
    errors, warnings, total_pages, mode = [], [], 0, None
    try:
        _, spec, mode, reuse = prepare_spec(spec_file, apply_gallery=False)
        if mode in ('朋友圈', '字幕'):
            total_pages = 1
        elif mode == '图解':
            info = InfographicLayout(spec)
            pages = spec.get('pages', [])
            has_cover = 'cover' in spec or bool(spec.get('gallery_request'))
            total_pages = (1 if has_cover else 0) + len(pages) + len(reuse)
            if not total_pages:
                errors.append('图解缺封面cover或内页pages。')
            d_errs, d_warns = _validate_diagram_spec(spec)
            errors.extend(d_errs)
            warnings.extend(d_warns)
            h_map = {'versus': 390, 'columns': 390, 'timeline': 380, 'branch': 430,
                     'funnel': 470, 'cycle': 510, 'venn': 520, 'bars': 520, 'image': 460}
            width, usable = (W - 144) - 144, 2690 - 404
            for idx, page in enumerate(pages, 1):
                diag = page.get('diagram') or ({'kind': 'image', 'image': page['image']} if page.get('image') else None)
                dkind = InfographicLayout.canonical_diagram_kind(diag['kind']) if diag else None
                base_h = 0 if not dkind else h_map[dkind]
                upper, lower = page.get('upper', []), page.get('lower', [])
                fits = False
                for size in range(84, 58, -2):
                    step, p_gap, sec_gap = round(150*size/84), round(58*size/84), round(96*size/84)
                    _, up_h = info.wrap_paragraphs(upper, width, size, step, p_gap)
                    _, lo_h = info.wrap_paragraphs(lower, width, size, step, p_gap)
                    gaps = (sec_gap if upper and diag else 0) + (sec_gap if diag and lower else (sec_gap if upper and lower else 0))
                    if up_h + lo_h + base_h + gaps <= usable - 140:
                        fits = True
                        break
                if not fits:
                    errors.append(f'图解第{idx}页文字过长超出阅读区，请拆分为续页。')
        else:
            text = TextLayout(spec, mode)
            plans = text.pages(cover_only=bool(reuse))
            total_pages = len(plans) + len(reuse)
        if total_pages > 18:
            warnings.append(f'共 {total_pages} 页，已超过小红书单篇 18 张上限，发布小红书建议精简或拆分。')
    except Exception as e:
        errors.append(str(e))
    return dict(ok=not errors, mode=mode, total_pages=total_pages, errors=errors, warnings=warnings)


def build_overview_image(images, mode):
    if len(images) == 1:
        return images[0].resize((1080, 1440), Image.Resampling.LANCZOS)
    cols = 4 if len(images) in (7, 8) or len(images) >= 10 else min(3, len(images))
    rows_n, pad = math.ceil(len(images)/cols), 20
    overview = Image.new('RGB', (cols*540+(cols+1)*pad, rows_n*720+(rows_n+1)*pad),
                         '#E6E6EA' if mode == '备忘录' else '#E8E5DE')
    for i, im in enumerate(images):
        overview.paste(im.resize((540, 720), Image.Resampling.LANCZOS),
                       (pad+(i%cols)*(540+pad), pad+(i//cols)*(720+pad)))
    return overview


def render(spec_file, output, preview=False):
    if not PIL_OK:
        raise ValueError('缺少制图组件（Pillow），请按 references/environment.md 配齐后重试。')
    spec_file, spec, mode, reuse = prepare_spec(spec_file, apply_gallery=True, commit_gallery=not preview)
    output = Path(output).resolve()
    warnings = []
    if mode == '图解':
        d_errs, d_warns = _validate_diagram_spec(spec)
        if d_errs:
            raise ValueError('；'.join(d_errs))
        warnings.extend(d_warns)
    result, produced = dict(state='待确认', adopted=[], pages=[]), []
    def add(pair):
        produced.append((f'{len(produced)+1:02d}', *pair))
    if mode in ('朋友圈', '字幕'):
        add(render_subtitle(spec) if mode == '字幕' else render_moments(spec))
    elif mode == '图解':
        info = InfographicLayout(spec)
        pages = spec.get('pages', [])
        has_cover = 'cover' in spec
        total = (1 if has_cover else 0)+len(pages)+len(reuse)
        if not total:
            raise ValueError('图解缺封面cover或内页pages。')
        if has_cover:
            add(info.cover_page(total))
        start_no = 2 if has_cover else 1
        for idx, page in enumerate(pages, start_no):
            add(info.body_page(page, idx, total, spec_file.parent))
        result.update(profile=mode, font_engine='RAQM' if RAQM else 'BASIC')
    else:
        text = TextLayout(spec, mode)
        plans = text.pages(cover_only=bool(reuse))
        total, body_page = len(plans)+len(reuse), 0
        for n, plan in enumerate(plans, 1):
            if plan['kind'] == 'body':
                body_page += 1
            add(text.page_image(plan, n, total, body_page if plan['kind'] == 'body' else None))
        result.update(paragraph_separator=text.separator,
                      body_size=text.p['size'], profile=mode, parameters=text.p, title=text.title_record,
                      font_engine='RAQM' if RAQM else 'BASIC')
    if preview:
        images = [im for _, im, _ in produced] + [load_image(path) for path in reuse]
        if len(images) > 18:
            warnings.append(f'共 {len(images)} 页，已超过小红书单篇 18 张上限，发布小红书建议精简或拆分。')
        preview_im = build_overview_image(images, mode)
        preview_path = output if output.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp'} else output/'预览.png'
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        preview_im.save(preview_path)
        photo_key = 'background' if mode in ('朋友圈', '字幕') else 'cover'
        return dict(
            preview=str(preview_path), mode=mode, total_pages=len(images), pixels=list(preview_im.size),
            gallery_id=spec.get('gallery_id'), photo=spec.get(photo_key), body_size=result.get('body_size'),
            warnings=warnings,
        )
    output.mkdir(parents=True, exist_ok=False)
    theme = re.sub(r'[/\\:\x00]', '-', spec.get('theme', '图文'))
    version = re.sub(r'[/\\:\x00]', '-', spec.get('version', '初稿01'))
    images = []
    for suffix, im, actual in produced:
        target = output/f'{theme}-{mode}-{version}-{suffix}.png'
        im.save(target)
        result['pages'].append(dict(actual, file=str(target), pixels=list(im.size)))
        images.append(im)
    for path in reuse:
        im = load_image(path)
        result['pages'].append(dict(kind='body', file=path, pixels=list(im.size), reused=True,
                                    source_record=spec.get('reuse_record')))
        images.append(im)
    if len(images) > 1:
        build_overview_image(images, mode).save(output/'总览.png')
    copy_body = str(spec.get('publish_copy') or spec.get('source_text') or '').strip()
    if copy_body:
        copy_title = str(
            spec.get('publish_title')
            or ' '.join(str(spec.get('title') or '').split())
            or spec.get('theme')
            or ''
        ).strip()
        copy_text = f'{copy_title}\n\n{copy_body}\n' if copy_title else f'{copy_body}\n'
        copy_path = output/'发布文案.txt'
        copy_path.write_text(copy_text, encoding='utf-8')
        result['copy_file'] = str(copy_path)
    if len(images) > 18:
        warnings.append(f'共 {len(images)} 页，已超过小红书单篇 18 张上限，发布小红书建议精简或拆分。')
    result['warnings'] = warnings
    spec['result'] = result
    (output/'制作记录.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return dict(
        output=str(output), mode=mode, images_written=len(produced), total_pages=len(images),
        body_size=result.get('body_size'), copy_file=result.get('copy_file'), warnings=warnings,
    )


def env_check(fonts=None, platform_name=None, user_fonts=USER_FONTS, mode=None):
    found = fonts if fonts is not None else discover_fonts(user_fonts=user_fonts)
    plat = platform_name or sys.platform
    target_mode = canonical_mode(mode) if mode else None
    try:
        import pillow_heif  # noqa: F401
        heif_ok = True
    except ImportError:
        heif_ok = False
    png_ok = False
    if PIL_OK:
        buf = io.BytesIO()
        Image.new('RGB', (16, 16), '#FFFFFF').save(buf, format='PNG')
        png_ok = buf.getvalue()[:8] == bytes.fromhex('89504e470d0a1a0a')
    roles = ('sans_reg', 'sans_med', 'sans_bold', 'serif_reg', 'serif_bold')
    req_roles = roles
    loaded, load_errors, trial_errors = {}, [], []
    for k in roles:
        p, idx = found[k]
        loaded[k] = p
        if not p:
            load_errors.append(k)
        elif PIL_OK:
            try:
                face = ImageFont.truetype(str(p), 32, index=idx)
                canvas = Image.new('L', (360, 64), 0)
                ImageDraw.Draw(canvas).text((8, 12), '测试中文排版 2026', font=face, fill=255)
                if canvas.getbbox() is None:
                    trial_errors.append(k)
            except OSError:
                load_errors.append(k)
    rec_files = dict(
        sans_reg='SourceHanSansCN-Regular.otf', sans_med='SourceHanSansCN-Medium.otf',
        sans_bold='SourceHanSansCN-Bold.otf',
        serif_reg='SourceHanSerifCN-Regular.otf', serif_bold='SourceHanSerifCN-Bold.otf',
    )
    high_sans = ('pingfang', 'sourcehansans', 'notosanscjk')
    high_serif = ('songti', 'sourcehanserif', 'notoserifcjk')
    rec_missing, req_missing = [], []
    for k, fname in rec_files.items():
        p = (loaded.get(k) or '').lower()
        ok_keys = high_sans if k.startswith('sans_') else high_serif
        med_fallback = (k == 'sans_med' and 'pingfang' not in p and p == (loaded.get('sans_reg') or '').lower())
        if k in load_errors or k in trial_errors or not any(tok in p for tok in ok_keys) or med_fallback:
            rec_missing.append(fname)
            if k in req_roles:
                req_missing.append(fname)
    chinese_trial_ok = bool(PIL_OK and not any(k in load_errors or k in trial_errors for k in req_roles))
    return dict(
        ready=bool(png_ok and chinese_trial_ok and not req_missing),
        heic_ready=bool(heif_ok),
        chinese_trial_ok=chinese_trial_ok,
        mode=target_mode,
        platform=plat, python=sys.executable,
        pillow=png_ok, pillow_heif=heif_ok,
        fonts_dir=str(user_fonts), fonts=loaded,
        font_load_errors=load_errors, font_trial_errors=trial_errors,
        required_fonts_missing=req_missing, recommended_fonts_missing=rec_missing,
    )


def main():
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, 'reconfigure'):
            _stream.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-check', action='store_true', help='只读检查运行环境、插件与中文字体试排')
    parser.add_argument('--mode', help='可选，记录本次检查关注的版式（必需字重统一按全套 5 款检查）')
    parser.add_argument('--check', action='store_true', help='只读预检 spec：总页数、18页红线、柱图方向与图解数字回查')
    parser.add_argument('--preview', action='store_true', help='只生成 1 张轻量总览预览图，不写全套高清 PNG、不推进图库序号')
    parser.add_argument('--spec', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if args.env_check:
        print(json.dumps(env_check(mode=args.mode), ensure_ascii=False))
        return
    if args.check:
        if not args.spec:
            parser.error('--check 需要提供 --spec。')
        report = check_spec(args.spec)
        print(json.dumps(report, ensure_ascii=False))
        if not report['ok']:
            sys.exit(1)
        return
    if not args.spec or not args.out:
        parser.error('--spec 与 --out 为必填参数（或使用 --env-check / --check）。')
    print(json.dumps(render(args.spec, args.out, preview=args.preview), ensure_ascii=False))


if __name__ == '__main__':
    main()
