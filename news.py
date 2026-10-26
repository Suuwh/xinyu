"""
心屿 · 资讯聚合模块
- 实时抓取中国网心理频道（要闻/心理访谈/政策信息）
- 实时抓取《心理月刊》最新目录
- 内存缓存 30 分钟，抓取失败自动回退到内置精选内容（保证演示永远可用）
"""
import re
import time
import urllib.request
from datetime import datetime
from html import unescape

CACHE = {}
CACHE_TTL = 1800  # 30 分钟
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _get(url, timeout=6):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="ignore")


def _norm_date(d):
    if not d:
        return ""
    return d.replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-").replace(".", "-").strip()


def _parse_links(html, base):
    """从列表页抽取 标题+链接+日期。优先按 <li>…<a>标题</a>…<span>日期</span>…</li> 块解析。"""
    items = []
    blocks = re.findall(r"<li[^>]*>(.*?)</li>", html, flags=re.S | re.I)
    for blk in blocks:
        anchors = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', blk, flags=re.S | re.I)
        if not anchors:
            continue
        # 一条 li 可能含图片链接+标题链接，取文本最长的那个
        href, raw_title = max(anchors, key=lambda a: len(re.sub(r"<[^>]+>", "", a[1])))
        title = unescape(re.sub(r"<[^>]+>", "", raw_title)).strip()
        title = re.sub(r"\s+", "", title)
        if len(title) < 8 or title in ("首页", "上一页", "下一页", "更多"):
            continue
        dm = re.search(r"(20\d{2}[-/年.]\d{1,2}[-/月.]\d{1,2})", blk)
        date = _norm_date(dm.group(1)) if dm else ""
        if not date:  # 治愈系等栏目日期在文章URL路径 /YYYY-MM/DD/ 中
            um = re.search(r"/(20\d{2})-(\d{1,2})/(\d{1,2})/content_", href)
            if um:
                date = "%s-%02d-%02d" % (um.group(1), int(um.group(2)), int(um.group(3)))
        # 只要文章内容页链接
        if "content_" not in href and not date:
            continue
        if href.startswith("/"):
            href = base.rstrip("/") + "/" + href.lstrip("/")
        elif not href.startswith("http"):
            href = base.rstrip("/") + "/" + href
        items.append({"title": title, "url": href, "date": date})

    # 兜底：li 结构取不到时用通用匹配
    if not items:
        pattern = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>([^<]{8,60})</a>(.{0,120}?)', re.S)
        for m in pattern.finditer(html):
            href, title, tail = m.group(1), unescape(m.group(2)).strip(), m.group(3)
            dm = re.search(r"(20\d{2}[-/年.]\d{1,2}[-/月.]\d{1,2})", tail)
            date = _norm_date(dm.group(1)) if dm else ""
            if not title or title in ("首页", "上一页", "下一页", "更多") or "content_" not in href:
                continue
            if href.startswith("/"):
                href = base.rstrip("/") + "/" + href.lstrip("/")
            elif not href.startswith("http"):
                href = base.rstrip("/") + "/" + href
            items.append({"title": title, "url": href, "date": date})

    seen, out = set(), []
    for it in items:
        if it["title"] not in seen:
            seen.add(it["title"]); out.append(it)
    return out[:12]


# ---- 内置回退内容（来自实际抓取的真实文章，2026-10） ----
FALLBACK_CHINA = {
    "要闻": [
        {"title": "守正创新 中国员工帮助计划二十年探索与展望", "url": "http://psy.china.com.cn/", "date": "2026-09-24"},
        {"title": "提升老年人心理韧性，完善“预防-支持-服务”三位一体工作体系", "url": "http://psy.china.com.cn/", "date": "2026-09-24"},
        {"title": "中国中小学生心理健康状况调查 人际疏离感成重要风险因素", "url": "http://psy.china.com.cn/", "date": "2026-09-24"},
        {"title": "最新研究：慢性压力或通过“隐性炎症”损害心脏", "url": "http://psy.china.com.cn/", "date": "2026-09-23"},
        {"title": "当“情绪陪伴”成为商品，价值几许边界何在", "url": "http://psy.china.com.cn/", "date": "2026-09-23"},
        {"title": "失衡的人际关系、消极互动……隐性心理创伤，别忽视", "url": "http://psy.china.com.cn/", "date": "2026-09-22"},
        {"title": "心理研究：儿童能够利用对话节奏判断他人的社会意图", "url": "http://psy.china.com.cn/", "date": "2026-09-21"},
        {"title": "当AI叩响“心门”，社会心理学如何应答？", "url": "http://psy.china.com.cn/", "date": "2026-09-21"},
        {"title": "北京安定医院院长王刚：“智”愈抑郁 让治疗可量化", "url": "http://psy.china.com.cn/", "date": "2026-09-20"},
        {"title": "秋季抑郁高发期来临，心理医生提醒：持续低落超两周应及时就医", "url": "http://psy.china.com.cn/", "date": "2026-09-18"},
    ],
    "心理访谈": [
        {"title": "走近心理咨询师：深夜里接住一个“扛不住”的人", "url": "http://psy.china.com.cn/", "date": "2026-09-16"},
        {"title": "如何破解青春期亲子沟通困境？听听心理咨询师怎么说", "url": "http://psy.china.com.cn/", "date": "2026-09-16"},
        {"title": "高压时代的A型人 如何从紧绷到松弛｜心理公开课", "url": "http://psy.china.com.cn/", "date": "2026-09-18"},
        {"title": "守护教师心理健康：疲惫状态、焦虑情绪如何应对？", "url": "http://psy.china.com.cn/", "date": "2026-09-18"},
        {"title": "深耕心理学近60载 黄希庭：培养幸福的进取者", "url": "http://psy.china.com.cn/", "date": "2026-09-20"},
        {"title": "大学新生如何迈出社交第一步——超五成受访新生担忧社交", "url": "http://psy.china.com.cn/", "date": "2026-09-17"},
        {"title": "拒学、畏学、学不会——“学习困难”真的是一种“病”吗？", "url": "http://psy.china.com.cn/", "date": "2026-09-21"},
        {"title": "老人也要有成长型思维：寿命更长、心理更健康", "url": "http://psy.china.com.cn/", "date": "2026-09-18"},
        {"title": "用AI确诊“病娇”？心理师：别让标签定义你", "url": "http://psy.china.com.cn/", "date": "2026-09-20"},
        {"title": "抗抑郁，还护心！这种“黄金有氧运动”，推荐你试试", "url": "http://psy.china.com.cn/", "date": "2026-09-18"},
    ],
    "政策信息": [
        {"title": "谋定规划，“十五五”精神心理工作重点抓什么？", "url": "http://psy.china.com.cn/", "date": "2026-09-20"},
        {"title": "锚定青少年健康成长需求 山东济南：织密关爱网 守护“少年心”", "url": "http://psy.china.com.cn/", "date": "2026-09-20"},
        {"title": "江苏省中小学生心理健康工作咨询委员会成立 专家赋能、政学协同", "url": "http://psy.china.com.cn/", "date": "2026-09-16"},
        {"title": "让“心”干预守住平安底线 嘉峪关推动心理服务与基层治理深度融合", "url": "http://psy.china.com.cn/", "date": "2026-09-23"},
        {"title": "从“心”出发！贵州建设职院探索“一站式”社区心理育人新模式", "url": "http://psy.china.com.cn/", "date": "2026-09-23"},
        {"title": "生酮饮食意外写入精神科处方，催热“代谢精神病学”", "url": "http://psy.china.com.cn/", "date": "2026-09-17"},
        {"title": "中国舞蹈疗愈：全球视野下的行业发展与艺医融合思考", "url": "http://psy.china.com.cn/", "date": "2026-09-17"},
        {"title": "AI时代青少年心理健康遭遇三重挑战 如何应对？", "url": "http://psy.china.com.cn/", "date": "2026-09-16"},
        {"title": "世界阿尔茨海默病月｜重视早期识别与干预", "url": "http://psy.china.com.cn/", "date": "2026-09-21"},
        {"title": "心理应激如何治疗？精神障碍康复怎么做？", "url": "http://psy.china.com.cn/", "date": "2026-09-23"},
    ],
}

FALLBACK_JOURNAL = [
    {"title": "高职学生反刍思维对应对方式的影响：基于成就动机与积极心理资本的非对称中介模型",
     "meta": "罗丽等 · 心理月刊 2026, 21(16):1-6", "url": "https://doi.org/10.19738/j.cnki.psy.2026.16.001"},
    {"title": "初中生同伴依恋与社会适应的关系：依恋理论与补偿假说的视角",
     "meta": "张家燕等 · 心理月刊 2026, 21(16):7-12", "url": "https://doi.org/10.19738/j.cnki.psy.2026.16.002"},
    {"title": "老年人焦虑抑郁共病的潜在剖面分析及其与认知功能的关系",
     "meta": "戴迪等 · 心理月刊 2026, 21(16):105-110", "url": "https://doi.org/10.19738/j.cnki.psy.2026.16.024"},
    {"title": "基于VOSviewer的我国身体意象研究的可视化分析",
     "meta": "盛馨宁等 · 心理月刊 2026, 21(16):111-115", "url": "https://doi.org/10.19738/j.cnki.psy.2026.16.025"},
    {"title": "非自杀性自伤青少年住院期间家属沟通障碍及需求的质性研究",
     "meta": "丁晓睛等 · 心理月刊 2026, 21(16):116-119", "url": "https://doi.org/10.19738/j.cnki.psy.2026.16.026"},
    {"title": "维持性血液透析患者电子健康素养量表编制及信效度检验",
     "meta": "李晶等 · 心理月刊 2026, 21(16):120-124", "url": "https://doi.org/10.19738/j.cnki.psy.2026.16.027"},
    {"title": "冠心病患者PCI术后自我感受负担轨迹及其影响因素分析",
     "meta": "施菊萍等 · 心理月刊 2026, 21(16):125-129", "url": "https://doi.org/10.19738/j.cnki.psy.2026.16.028"},
    {"title": "基于行为事件访谈法的心理热线接线员胜任力特征质性研究",
     "meta": "古宝檎 · 心理月刊 2026, 21(16):130-133", "url": "https://doi.org/10.19738/j.cnki.psy.2026.16.029"},
    {"title": "下肢动脉硬化闭塞症患者静态行为潜在剖面及影响因素分析",
     "meta": "朱卓贤等 · 心理月刊 2026, 21(16):134-137", "url": "https://doi.org/10.19738/j.cnki.psy.2026.16.030"},
    {"title": "正念情绪强化护理对慢性心力衰竭患者心理弹性的影响",
     "meta": "赵净等 · 心理月刊 2026, 21(16):192-194", "url": "https://doi.org/10.19738/j.cnki.psy.2026.16.046"},
]


def _cached(key, fetcher, fallback):
    now = time.time()
    if key in CACHE and now - CACHE[key][0] < CACHE_TTL:
        return CACHE[key][1]
    try:
        data = fetcher()
        if data:
            CACHE[key] = (now, data, True)
            return data
    except Exception:
        pass
    CACHE[key] = (now, fallback, False)
    return fallback


CHINA_SECTIONS = {
    "要闻": "http://psy.china.com.cn/node_1013423.htm",
    "心理访谈": "http://psy.china.com.cn/node_1013426.htm",
    "政策信息": "http://psy.china.com.cn/node_1013428.htm",
}


def get_china(section):
    url = CHINA_SECTIONS.get(section, CHINA_SECTIONS["要闻"])

    def f():
        return _parse_links(_get(url), "http://psy.china.com.cn/")[:10]
    return _cached("china_" + section, f, FALLBACK_CHINA.get(section, FALLBACK_CHINA["要闻"]))


def _china_paged(section, max_pages=4):
    """抓取栏目多页列表（第1页 + 分页页），用于往期查看与全量搜索。"""
    base = CHINA_SECTIONS.get(section, CHINA_SECTIONS["要闻"])
    items = []
    for i in range(1, max_pages + 1):
        url = base
        if i > 1:
            # 中国网列表分页形如 node_1013423_2.htm
            url = re.sub(r"node_(\d+)\.htm", r"node_\1_%d.htm" % i, base)
        try:
            pg = _parse_links(_get(url), "http://psy.china.com.cn/")
        except Exception:
            break
        if not pg:
            break
        seen_t = {it["title"] for it in items}
        new = [it for it in pg if it["title"] not in seen_t]
        if not new:
            break
        items.extend(new)
        if len(new) < 8:  # 列表页内容少，视为已到底
            break
    return items[:40]


def get_china_all(section):
    """栏目往期全部（多页合并），失败回退到单页/内置精选。"""
    def f():
        items = _china_paged(section)
        return items or None
    return _cached("china_all_" + section, f, FALLBACK_CHINA.get(section, FALLBACK_CHINA["要闻"]))


def search_china(q):
    """资讯搜索：先在本地已抓取内容（多栏目多页 + 内置精选）中按标题匹配。

    返回 (hits, found)。found=False 表示本地无命中，由页面引导到公网搜索。
    """
    q = q.strip()
    if not q:
        return [], False
    hits = []
    seen = set()
    for section in CHINA_SECTIONS:
        for it in get_china_all(section):
            if q in it["title"] and it["title"] not in seen:
                seen.add(it["title"])
                hits.append({"title": it["title"], "url": it["url"], "date": it.get("date", ""),
                             "source": "中国网心理频道 · " + section})
    for section, arr in FALLBACK_CHINA.items():
        for it in arr:
            if q in it["title"] and it["title"] not in seen:
                seen.add(it["title"])
                hits.append({"title": it["title"], "url": it["url"], "date": it.get("date", ""),
                             "source": "中国网心理频道 · " + section + "（精选）"})
    return hits[:30], bool(hits)


def search_journal(q):
    """心理月刊搜索：本地已抓取/精选目录按标题匹配。"""
    q = q.strip()
    if not q:
        return [], False
    hits = [it for it in get_journal() if q in it["title"]]
    if not hits:
        hits = [it for it in FALLBACK_JOURNAL if q in it["title"]]
    return hits[:30], bool(hits)


def get_journal():
    def f():
        html = _get("https://www.xlykzz.com/CN/home")
        out = []
        for m in re.finditer(r'title="([^"]{10,80})"', html):
            t = unescape(m.group(1)).strip()
            if t and ("心理" in t or "患者" in t or "青少年" in t or "护理" in t or "焦虑" in t):
                out.append({"title": t, "meta": "《心理月刊》2026年第16期", "url": "https://www.xlykzz.com/CN/home"})
        return out[:10] or None
    return _cached("journal", f, FALLBACK_JOURNAL)


# ---- 学生端：心理成长科普（心理百科 + 治愈系） ----
LEARN_SOURCES = {
    "心理百科": "http://psy.china.com.cn/node_1013431.htm",
    "治愈系": "http://psy.china.com.cn/node_1013435.htm",
}

FALLBACK_LEARN = [
    {"title": "总忍不住反复检查？认识强迫症与缓解方法", "date": "2026-09-22",
     "url": "http://psy.china.com.cn/", "source": "中国网心理频道 · 心理百科"},
    {"title": "如何科学地睡个好觉：给大学生的睡眠指南", "date": "2026-09-21",
     "url": "http://psy.china.com.cn/", "source": "中国网心理频道 · 心理百科"},
    {"title": "社交恐惧只是内向吗？两者的区别与应对", "date": "2026-09-20",
     "url": "http://psy.china.com.cn/", "source": "中国网心理频道 · 心理百科"},
    {"title": "拖延不是懒：理解拖延背后的情绪机制", "date": "2026-09-19",
     "url": "http://psy.china.com.cn/", "source": "中国网心理频道 · 治愈系"},
    {"title": "写给容易内耗的你：停止自我攻击的三步", "date": "2026-09-18",
     "url": "http://psy.china.com.cn/", "source": "中国网心理频道 · 治愈系"},
    {"title": "高敏感是一种天赋吗？学会与敏感共处", "date": "2026-09-17",
     "url": "http://psy.china.com.cn/", "source": "中国网心理频道 · 治愈系"},
]


def get_learn_articles():
    def f():
        out = []
        for name, url in LEARN_SOURCES.items():
            for it in _parse_links(_get(url), "http://psy.china.com.cn/")[:5]:
                out.append({"title": it["title"], "date": it["date"] or "近期",
                            "url": it["url"], "source": "中国网心理频道 · " + name})
        return out[:10] or None
    return _cached("learn", f, FALLBACK_LEARN)


# ---- 更新时间与在线状态 ----
def last_updated(key):
    """返回某栏目的缓存时间字符串；在线=True 表示本次为实时抓取，False 为内置回退。"""
    if key not in CACHE:
        return "尚未更新", False
    ts, online = CACHE[key][0], CACHE[key][2] if len(CACHE[key]) > 2 else True
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M"), online


# ---- 站内文章正文抓取 ----
def fetch_article(url):
    """抓取文章正文，返回 {title, paragraphs, source}；失败返回 None。"""
    try:
        html = _get(url)
        # 去脚本样式
        html = re.sub(r"<script.*?</script>", "", html, flags=re.S | re.I)
        html = re.sub(r"<style.*?</style>", "", html, flags=re.S | re.I)
        title_m = re.search(r"<title>([^<]+)</title>", html)
        title = unescape(title_m.group(1)).strip() if title_m else "文章"
        # 取 <p> 段落
        paras = []
        for pm in re.finditer(r"<p[^>]*>(.*?)</p>", html, flags=re.S | re.I):
            txt = re.sub(r"<[^>]+>", "", pm.group(1))
            txt = unescape(txt).strip()
            if len(txt) > 15:
                paras.append(txt)
        if not paras:
            return None
        return {"title": title, "paragraphs": paras[:40], "source": url}
    except Exception:
        return None
