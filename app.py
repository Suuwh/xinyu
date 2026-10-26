"""心屿 · AI校园心理健康护航平台 — 应用主入口"""
import json
import os
import re
import uuid
from datetime import datetime, timedelta
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   session, jsonify, flash)
from werkzeug.utils import secure_filename
from sqlalchemy import or_ as sa_or

from models import db, User, Counselor, Assessment, ChatSession, ChatMessage, \
    Alert, TreePost, TreeComment, Appointment, Resource, MoodDiary
import engine
import news
import scale_meta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
# 数据库：默认 SQLite 开箱即用；如需 MySQL，设置环境变量 DATABASE_URL 即可，例如：
# DATABASE_URL=mysql+pymysql://root:你的密码@127.0.0.1:3306/xinyu?charset=utf8mb4
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "xinyu.db"))
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = "xinyu-secret-demo-key"
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024   # 头像上传上限 4MB
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_IMG = {"png", "jpg", "jpeg", "gif", "webp"}
db.init_app(app)


# ---------------- 工具 ----------------
def login_required(role=None):
    def decor(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            uid = session.get("uid")
            if not uid:
                return redirect(url_for("login", next=request.path))
            u = db.session.get(User, uid)
            if not u:
                session.clear()
                return redirect(url_for("login"))
            # 首次登录必须先完成基本信息填写
            if not u.profile_completed and request.endpoint not in (
                    "profile", "logout", "static", "avatar_upload"):
                flash("首次登录请先完善你的基本信息", "warn")
                return redirect(url_for("profile"))
            if role and u.role != role:
                flash("该页面需要相应权限", "warn")
                return redirect(url_for("index"))
            return f(u, *args, **kwargs)
        return wrapper
    return decor


@app.context_processor
def inject_globals():
    uid = session.get("uid")
    u = db.session.get(User, uid) if uid else None

    def avatar_html(usr, cls="", emoji_cls=""):
        """统一渲染头像：本地图片用 <img>，否则用 emoji。"""
        if usr and usr.avatar_type == "upload" and usr.avatar:
            return f'<img class="{cls}" src="{usr.avatar}" alt="头像">'
        return f'<span class="{emoji_cls}">{usr.avatar or "👤" if usr else "👤"}</span>'

    return {"now": datetime.now(), "u": u, "avatar_html": avatar_html}


# ---------------- 认证 ----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        real_name = request.form.get("real_name", "").strip()
        role = request.form.get("role", "student")
        if role not in ("student", "counselor"):
            role = "student"
        if not username or not password or not real_name:
            flash("用户名、昵称和密码不能为空", "err")
        elif User.query.filter_by(username=username).first():
            flash("用户名已存在", "err")
        elif role == "counselor":
            # 咨询师注册：须通过中国心理学会临床与咨询心理学注册系统认证（演示环境为模拟认证流程）
            chsi_no = request.form.get("chsi_no", "").strip()      # 注册系统账号（手机号/邮箱）
            cps_no = request.form.get("cps_no", "").strip()        # 注册心理师/助理心理师编号
            if not re.fullmatch(r"[\w.@+-]{4,64}", chsi_no):
                flash("请填写有效的注册系统账号（手机号或邮箱）", "err")
            elif not re.fullmatch(r"(?:X|C|D)?-?\d{2,6}-?\d{0,4}", cps_no.strip().upper()):
                flash("请填写有效的注册系统编号（如 X-22-001 或 注册编号）", "err")
            else:
                u = User(username=username, role="counselor", real_name=real_name,
                         gender=request.form.get("gender", ""),
                         teacher_title=request.form.get("teacher_title", "心理咨询师"),
                         department=request.form.get("department", ""),
                         qualification_no=cps_no.strip().upper(),
                         qualification_verified=True,   # 认证通过
                         intro=request.form.get("intro", ""))
                u.set_password(password)
                db.session.add(u)
                db.session.flush()
                db.session.add(Counselor(user_id=u.id, title=u.teacher_title or "心理咨询师",
                    specialty=request.form.get("specialty", ""),
                    bio=request.form.get("intro", ""),
                    location=request.form.get("location", "学校心理咨询中心"),
                    avatar=u.avatar or "🧑‍🏫", rating=4.8))
                db.session.commit()
                session["uid"] = u.id
                flash("资质认证通过，咨询师账号已注册，请完善执业信息", "ok")
                return redirect(url_for("profile"))
        else:
            u = User(username=username, role="student", real_name=real_name,
                     gender=request.form.get("gender", ""),
                     grade=request.form.get("grade", ""),
                     major=request.form.get("major", ""))
            u.set_password(password)
            db.session.add(u)
            db.session.commit()
            session["uid"] = u.id
            flash("注册成功，欢迎加入心屿，请完善你的学籍信息", "ok")
            return redirect(url_for("profile"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = User.query.filter_by(username=request.form.get("username", "")).first()
        if u and u.check_password(request.form.get("password", "")):
            session["uid"] = u.id
            if not u.profile_completed:
                flash("欢迎回来，请先完善基本信息（首次登录必填）", "warn")
                return redirect(url_for("profile"))
            return redirect(request.args.get("next") or url_for("index"))
        flash("用户名或密码错误", "err")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/login/chsi", methods=["POST"])
def login_chsi():
    """学信网统一身份认证（演示环境为模拟授权回调；正式部署对接学校统一身份认证/CHSI OAuth）。"""
    demo = User.query.filter_by(username="student1").first()
    if demo:
        session["uid"] = demo.id
        if not demo.profile_completed:
            flash("已通过学信网统一身份认证登录，请完善你的基本信息", "warn")
            return redirect(url_for("profile"))
        flash("已通过学信网统一身份认证登录（演示环境为模拟授权）。", "ok")
        return redirect(request.args.get("next") or url_for("index"))
    flash("统一认证暂不可用，请使用账号密码登录。", "err")
    return redirect(url_for("login"))


@app.route("/login/cps", methods=["POST"])
def login_cps():
    """中国心理学会临床与咨询心理学注册系统认证登录（演示环境为模拟认证回调）。

    正式部署时对接注册系统 OAuth：本路由接收注册系统账号+注册编号，
    校验编号格式并匹配本平台「已认证咨询师档案」（qualification_verified=True）后放行登录。
    """
    account = request.form.get("cps_account", "").strip()
    cps_no = request.form.get("cps_no", "").strip().upper()
    if not re.fullmatch(r"[\w.@+-]{4,64}", account):
        flash("请填写有效的注册系统账号（手机号或邮箱）", "err")
        return redirect(url_for("login"))
    if not re.fullmatch(r"(?:X|C|D)?-?\d{2,6}-?\d{0,4}", cps_no):
        flash("请填写有效的注册系统编号（如 X-22-001）", "err")
        return redirect(url_for("login"))
    u = User.query.filter_by(qualification_no=cps_no, role="counselor",
                             qualification_verified=True).first()
    if u:
        session["uid"] = u.id
        if not u.profile_completed:
            flash("已通过注册系统认证登录，请完善执业信息", "warn")
            return redirect(url_for("profile"))
        flash("已通过中国心理学会注册系统认证登录（演示环境为模拟认证）。", "ok")
        return redirect(request.args.get("next") or url_for("index"))
    flash("该注册编号尚未在本平台完成咨询师注册认证，请先以咨询师身份注册。", "err")
    return redirect(url_for("login"))


# ---------------- 首页（按角色分流） ----------------
@app.route("/")
@login_required()
def index(u):
    if u.role == "counselor":
        return redirect(url_for("teacher_home"))
    latest = Assessment.query.filter_by(user_id=u.id).order_by(Assessment.created_at.desc()).first()
    open_alerts = Alert.query.filter_by(user_id=u.id, status="open").count()
    stats = {
        "assess_cnt": Assessment.query.filter_by(user_id=u.id).count(),
        "mood_cnt": MoodDiary.query.filter_by(user_id=u.id).count(),
        "booking_cnt": Appointment.query.filter_by(student_id=u.id).count(),
        "post_cnt": TreePost.query.filter_by(user_id=u.id).count(),
    }
    return render_template("index.html", u=u, latest=latest, open_alerts=open_alerts, **stats)


# ---------------- AI 对话 ----------------
@app.route("/chat")
@login_required()
def chat(u):
    sessions = ChatSession.query.filter_by(user_id=u.id).order_by(ChatSession.last_at.desc()).all()
    sid = request.args.get("sid", type=int)
    msgs, cur = [], None
    if sid:
        cur = ChatSession.query.filter_by(id=sid, user_id=u.id).first()
    if not cur and sessions:
        cur = sessions[0]
    if cur:
        msgs = ChatMessage.query.filter_by(session_id=cur.id).order_by(ChatMessage.id).all()
    return render_template("chat.html", u=u, sessions=sessions, cur=cur, msgs=msgs)


@app.route("/api/chat/new", methods=["POST"])
@login_required()
def chat_new(u):
    s = ChatSession(user_id=u.id, title="新对话")
    db.session.add(s)
    db.session.commit()
    return jsonify({"ok": True, "sid": s.id})


@app.route("/api/chat", methods=["POST"])
@login_required()
def chat_api(u):
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    sid = data.get("sid")
    if not text:
        return jsonify({"ok": False, "error": "empty"})
    s = ChatSession.query.filter_by(id=sid, user_id=u.id).first() if sid else None
    if not s:
        s = ChatSession(user_id=u.id, title=text[:18] or "新对话")
        db.session.add(s); db.session.flush()
    emo = engine.detect_emotion(text)
    db.session.add(ChatMessage(session_id=s.id, role="user", content=text,
                                emotion=emo["emotion"], risk=emo["risk"]))
    res = engine.generate_reply(text, emo)
    am_text = res["reply"] + "\n" + "\n".join("· " + a for a in res["advice"])
    db.session.add(ChatMessage(session_id=s.id, role="assistant", content=am_text,
                               emotion=emo["emotion"], risk=emo["risk"]))
    s.last_at = datetime.now()
    if emo["risk"] == "high":
        db.session.add(Alert(user_id=u.id, source="chat", content=text,
                             trigger=",".join(emo["hits"]), level="high"))
    db.session.commit()
    return jsonify({"ok": True, "sid": s.id, "reply": am_text,
                    "emotion": emo["emotion"], "risk": emo["risk"]})


# ---------------- 测评 ----------------
@app.route("/assessment")
@login_required()
def assessments(u):
    # 按分类分组
    cats = {}
    history = {}
    for code, sc in engine.SCALES.items():
        history[code] = Assessment.query.filter_by(user_id=u.id, scale_code=code).order_by(
            Assessment.created_at.desc()).first()
        cats.setdefault(sc["category"], []).append((code, sc))
    return render_template("assessments.html", u=u, cats=cats, history=history)


@app.route("/assessment/<code>")
@login_required()
def assessment_intro(u, code):
    if code not in engine.SCALES:
        return redirect(url_for("assessments"))
    scale = engine.SCALES[code]
    meta = scale_meta.SCALE_META.get(code, {})
    last = Assessment.query.filter_by(user_id=u.id, scale_code=code).order_by(
        Assessment.created_at.desc()).first()
    return render_template("intro.html", u=u, code=code, scale=scale, meta=meta, last=last)


@app.route("/assessment/<code>/take", methods=["GET", "POST"])
@login_required()
def assessment_take(u, code):
    if code not in engine.SCALES:
        return redirect(url_for("assessments"))
    scale = engine.SCALES[code]
    if request.method == "POST":
        # 每题独立 radio name（q0,q1,...），避免同名 radio 组互斥丢答案
        answers = []
        for i in range(len(scale["questions"])):
            v = request.form.get("q%d" % i)
            if v is None:
                break
            answers.append(v)
        if len(answers) != len(scale["questions"]):
            flash("请完成所有题目后再提交", "warn")
            return render_template("take.html", u=u, code=code, scale=scale)
        r = engine.assess_scale(code, answers)
        a = Assessment(user_id=u.id, scale_code=code, answers=json.dumps(answers),
                       score=r["score"], level=r["level"], advice=r["advice"])
        db.session.add(a)
        if r["level"] in ("重度抑郁", "中重度抑郁", "重度焦虑", "重度失眠", "高度孤独感",
                          "高压力", "困扰严重", "重度"):
            db.session.add(Alert(user_id=u.id, source="assessment",
                                content=f"{scale['name']}={r['score']}分（{r['level']}）",
                                trigger=f"量表高危:{code}", level="high"))
        db.session.commit()
        return render_template("result.html", u=u, scale=scale, r=r)
    return render_template("take.html", u=u, code=code, scale=scale)


@app.route("/history")
@login_required()
def history(u):
    q = (request.args.get("q") or "").strip()
    page = request.args.get("page", 1, type=int)
    per = 10
    query = Assessment.query.filter_by(user_id=u.id)
    if q:
        codes = [c for c, sc in engine.SCALES.items() if q in sc["name"] or q in c]
        query = query.filter(Assessment.scale_code.in_(codes) if codes else Assessment.id == -1)
    total = query.count()
    pages = max(1, (total + per - 1) // per)
    page = min(max(1, page), pages)
    rows = query.order_by(Assessment.created_at.desc()).offset((page - 1) * per).limit(per).all()
    names = {code: sc["name"] for code, sc in engine.SCALES.items()}
    risks = {r.id: engine.scale_risk_index(r.scale_code, r.score) for r in rows}
    return render_template("history.html", u=u, rows=rows, names=names, risks=risks,
                           q=q, page=page, pages=pages, total=total)


# ---------------- 心情日记 / 情绪曲线 ----------------
@app.route("/mood", methods=["GET", "POST"])
@login_required()
def mood(u):
    if request.method == "POST":
        m = MoodDiary(user_id=u.id, mood=int(request.form.get("mood", 0)),
                      note=request.form.get("note", "").strip())
        db.session.add(m)
        db.session.commit()
        flash("今日心情已记录，继续观察自己的状态吧", "ok")
        return redirect(url_for("mood"))
    # 全部日记：前端负责按日期分组 / 往期查看 / 曲线按周月年筛选
    rows = MoodDiary.query.filter_by(user_id=u.id).order_by(MoodDiary.created_at.desc()).limit(200).all()
    return render_template("mood.html", u=u, rows=rows)


@app.route("/api/mood")
@login_required()
def mood_api(u):
    """心情曲线数据：只返回用户自己选择的心情记录（-5~+5），支持按时间范围筛选。
    range=week(近7天)/month(近30天)/year(近365天)/all(全部)
    """
    rng = request.args.get("range", "week")
    now = datetime.now()
    since = None
    if rng == "week":
        since = now - timedelta(days=7)
    elif rng == "month":
        since = now - timedelta(days=30)
    elif rng == "year":
        since = now - timedelta(days=365)
    q = MoodDiary.query.filter_by(user_id=u.id)
    if since:
        q = q.filter(MoodDiary.created_at >= since)
    rows = q.order_by(MoodDiary.created_at).all()
    return jsonify({
        "labels": [r.created_at.strftime("%m-%d") for r in rows],
        "vals": [r.mood for r in rows],
        "range": rng,
    })


# ---------------- 树洞 ----------------
SENSITIVE = ["自杀", "轻生", "自残"]

ALLOWED_MEDIA = {
    "image": {"jpg", "jpeg", "png", "gif", "webp"},
    "audio": {"mp3", "wav", "m4a", "ogg", "aac"},
    "video": {"mp4", "webm", "mov", "m4v"},
}
MAX_MEDIA_BYTES = 25 * 1024 * 1024  # 25MB


def _save_media(f):
    """保存树洞媒体文件，返回 (kind, url)；失败返回 ("", 错误信息)。"""
    if not f or not f.filename:
        return "", ""
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    kind = next((k for k, exts in ALLOWED_MEDIA.items() if ext in exts), "")
    if not kind:
        return "", "仅支持图片(jpg/png/gif/webp)、音频(mp3/wav/m4a/ogg)、视频(mp4/webm/mov)"
    data = f.read(MAX_MEDIA_BYTES + 1)
    if len(data) > MAX_MEDIA_BYTES:
        return "", "文件过大，请控制在 25MB 以内"
    up_dir = os.path.join(app.static_folder, "uploads")
    os.makedirs(up_dir, exist_ok=True)
    name = uuid.uuid4().hex + "." + ext
    with open(os.path.join(up_dir, name), "wb") as fp:
        fp.write(data)
    return kind, "/static/uploads/" + name


def _treehole_page(query, page, per):
    total = query.count()
    pages = max(1, (total + per - 1) // per)
    page = min(max(1, page), pages)
    rows = query.order_by(TreePost.created_at.desc()).offset((page - 1) * per).limit(per).all()
    return rows, total, pages, page


@app.route("/treehole", methods=["GET", "POST"])
@login_required()
def treehole(u):
    if u.role == "counselor":
        return redirect(url_for("teacher_treehole"))
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        tags = request.form.get("tags", "").strip()
        if not title or not content:
            flash("标题和内容不能为空", "err")
        else:
            mk, mu = _save_media(request.files.get("media"))
            if mk == "" and request.files.get("media") and request.files.get("media").filename:
                flash(mu or "媒体上传失败", "err")
            else:
                crisis = any(w in content for w in SENSITIVE)
                p = TreePost(user_id=u.id, nickname="匿名同学", title=title,
                             content=content, tags=tags, crisis_flag=crisis,
                             media_kind=mk, media_url=mu)
                db.session.add(p)
                if crisis:
                    db.session.add(Alert(user_id=u.id, source="treehole", content=content[:200],
                                        trigger="树洞敏感词", level="high"))
                db.session.commit()
                flash("已发布，谢谢你愿意说出来", "ok")
        return redirect(url_for("treehole"))
    q = (request.args.get("q") or "").strip()
    tag = (request.args.get("tag") or "").strip()
    page = request.args.get("page", 1, type=int)
    per = 12
    my = (request.args.get("my") or "") == "1"
    if my:
        # 我的树洞：只显示自己发布的帖子（含已隐藏的），便于管理
        query = TreePost.query.filter(TreePost.user_id == u.id)
        if q:
            query = query.filter(sa_or(TreePost.title.contains(q), TreePost.content.contains(q)))
        if tag:
            query = query.filter(TreePost.tags.contains(tag))
    else:
        # 公共流：隐藏的帖子不对外展示
        query = TreePost.query.filter(TreePost.hidden == False)
        if q:
            query = query.filter(sa_or(TreePost.title.contains(q), TreePost.content.contains(q)))
        if tag:
            query = query.filter(TreePost.tags.contains(tag))
    rows, total, pages, page = _treehole_page(query, page, per)
    # 热门话题
    counter = {}
    for p in TreePost.query.filter(TreePost.hidden == False).all():
        for t in (p.tags or "").split():
            counter[t] = counter.get(t, 0) + 1
    hot_tags = sorted(counter.items(), key=lambda x: -x[1])[:10]
    return render_template("treehole.html", u=u, posts=rows, q=q, tag=tag,
                           page=page, pages=pages, total=total, hot_tags=hot_tags,
                           my=my, is_teacher=False)


@app.route("/teacher/treehole")
@login_required(role="counselor")
def teacher_treehole(u):
    """教师端树洞：以查看、浏览学生发帖为主（不提供发帖），凸显社交动态。"""
    q = (request.args.get("q") or "").strip()
    tag = (request.args.get("tag") or "").strip()
    page = request.args.get("page", 1, type=int)
    per = 12
    # 教师端只浏览公共流（隐藏帖不出现在教师端）
    query = TreePost.query.filter(TreePost.hidden == False)
    if q:
        query = query.filter(sa_or(TreePost.title.contains(q), TreePost.content.contains(q),
                                   TreePost.tags.contains(q)))
    if tag:
        query = query.filter(TreePost.tags.contains(tag))
    rows, total, pages, page = _treehole_page(query, page, per)
    # 热门标签
    hot_tags = []
    for p in TreePost.query.all():
        for t in (p.tags or "").split():
            hot_tags.append(t)
    counter = {}
    for t in hot_tags:
        counter[t] = counter.get(t, 0) + 1
    hot_tags = sorted(counter.items(), key=lambda x: -x[1])[:10]
    # 发帖学生画像（匿名保护：仅显示统计信息）
    posts = TreePost.query.filter(TreePost.hidden == False).all()
    post_users = {p.user_id for p in posts}
    stats = {"posts": len(posts), "users": len(post_users),
             "crisis": sum(1 for p in posts if p.crisis_flag),
             "likes": sum(p.likes for p in posts)}
    return render_template("teacher_treehole.html", u=u, posts=rows, q=q, tag=tag,
                           page=page, pages=pages, total=total,
                           hot_tags=hot_tags, stats=stats)


@app.route("/treehole/<int:pid>", methods=["GET", "POST"])
@login_required()
def treehole_detail(u, pid):
    p = db.session.get(TreePost, pid)
    if not p:
        return redirect(url_for("treehole"))
    if p.hidden and p.user_id != u.id:
        # 已隐藏的帖子仅作者本人可访问
        return redirect(url_for("treehole"))
    if request.method == "POST":
        c = TreeComment(post_id=pid, nickname="匿名同学",
                        content=request.form.get("content", "").strip())
        db.session.add(c)
        db.session.commit()
        return redirect(url_for("treehole_detail", pid=pid))
    comments = TreeComment.query.filter_by(post_id=pid).order_by(TreeComment.id).all()
    return render_template("detail.html", u=u, p=p, comments=comments)


@app.route("/treehole/<int:pid>/edit", methods=["POST"])
@login_required()
def treehole_edit(u, pid):
    """编辑自己的树洞帖子（仅作者本人）。"""
    p = db.session.get(TreePost, pid)
    if not p or p.user_id != u.id:
        flash("只能编辑自己发布的帖子", "err")
        return redirect(url_for("treehole", my=1))
    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    tags = request.form.get("tags", "").strip()
    if not title or not content:
        flash("标题和内容不能为空", "err")
    else:
        p.title = title
        p.content = content
        p.tags = tags
        # 重新评估敏感词，更新危机标记（若触发预警则补记一条）
        crisis = any(w in content for w in SENSITIVE)
        if crisis and not p.crisis_flag:
            db.session.add(Alert(user_id=u.id, source="treehole", content=content[:200],
                                 trigger="树洞敏感词", level="high"))
        p.crisis_flag = crisis
        db.session.commit()
        flash("帖子已更新", "ok")
    return redirect(url_for("treehole", my=1))


@app.route("/treehole/<int:pid>/delete", methods=["POST"])
@login_required()
def treehole_delete(u, pid):
    """删除自己的树洞帖子（仅作者本人，级联删除评论）。"""
    p = db.session.get(TreePost, pid)
    if not p or p.user_id != u.id:
        flash("只能删除自己发布的帖子", "err")
        return redirect(url_for("treehole", my=1))
    TreeComment.query.filter_by(post_id=pid).delete()
    db.session.delete(p)
    db.session.commit()
    flash("帖子已删除", "ok")
    return redirect(url_for("treehole", my=1))


@app.route("/treehole/<int:pid>/hide", methods=["POST"])
@login_required()
def treehole_hide(u, pid):
    """隐藏/恢复自己的树洞帖子：隐藏后仅自己可见，公共流与教师端不再展示。"""
    p = db.session.get(TreePost, pid)
    if not p or p.user_id != u.id:
        flash("只能管理自己发布的帖子", "err")
        return redirect(url_for("treehole", my=1))
    p.hidden = not p.hidden
    db.session.commit()
    flash("帖子已隐藏，仅自己可见" if p.hidden else "帖子已恢复公开", "ok")
    return redirect(url_for("treehole", my=1))


@app.route("/treehole/<int:pid>/like")
@login_required()
def treehole_like(u, pid):
    p = db.session.get(TreePost, pid)
    if p:
        p.likes += 1
        db.session.commit()
    return redirect(url_for("treehole_detail", pid=pid))


# ---------------- 预约 ----------------
@app.route("/booking", methods=["GET", "POST"])
@login_required()
def booking(u):
    # 仅显示：资质认证通过、且未暂停预约的咨询师（暂停后学生端不再显示、不可预约）
    counselors = User.query.filter_by(role="counselor").all()
    infos = {}
    show = []
    for c in counselors:
        co = Counselor.query.filter_by(user_id=c.id).first()
        if co and co.is_pausing:
            continue
        infos[c.id] = co
        show.append(c)
    counselors = show
    if request.method == "POST":
        cid = request.form.get("counselor_id", type=int)
        co = Counselor.query.filter_by(user_id=cid).first()
        if not co or co.is_pausing:
            flash("该咨询师当前暂停预约，请选择其他老师", "err")
            return redirect(url_for("booking"))
        ap = Appointment(counselor_id=cid, student_id=u.id,
                         date=request.form.get("date", ""),
                         time_slot=request.form.get("time_slot", ""),
                         topic=request.form.get("topic", ""), status="pending")
        db.session.add(ap); db.session.commit()
        flash("预约已提交，等待咨询师确认", "ok")
        return redirect(url_for("my_booking"))
    return render_template("booking.html", u=u, counselors=counselors, infos=infos)


@app.route("/my_booking")
@login_required()
def my_booking(u):
    rows = Appointment.query.filter_by(student_id=u.id).order_by(Appointment.created_at.desc()).all()
    counselors = User.query.filter(User.role == "counselor").all()
    cinfo = {}
    for c in counselors:
        co = Counselor.query.filter_by(user_id=c.id).first()
        cinfo[c.id] = {"name": c.real_name or c.username,
                       "location": (co.location if co else "") or "学校心理咨询中心",
                       "title": (co.title if co else "") or "心理咨询师"}
    return render_template("my_booking.html", u=u, rows=rows, cinfo=cinfo)


@app.route("/my_booking/<int:aid>/cancel", methods=["POST"])
@login_required()
def my_booking_cancel(u, aid):
    """学生取消预约：仅本人且状态为待确认/已确认时可取消。"""
    a = db.session.get(Appointment, aid)
    if a and a.student_id == u.id and a.status in ("pending", "confirmed"):
        a.status = "cancelled"
        db.session.commit()
        flash("预约已取消，如需要可随时重新预约", "ok")
    else:
        flash("该预约当前状态不可取消", "err")
    return redirect(url_for("my_booking"))


# ---------------- 心理成长（科普/视频/书单） ----------------
LEARN_TABS = {"article": "心晴手札", "video": "疗愈影音", "book": "枕边书单"}


@app.route("/learn")
@app.route("/learn/<tab>")
@login_required()
def learn(u, tab="article"):
    if tab not in LEARN_TABS:
        tab = "article"
    db_rows = Resource.query.filter_by(kind=tab).order_by(Resource.created_at.desc()).all()
    live = news.get_learn_articles() if tab == "article" else []
    t, online = news.last_updated("learn") if tab == "article" else ("", False)
    # 主栏目页最多显示8个
    live_preview = live[:8]
    db_preview = db_rows[: max(0, 8 - len(live_preview))] if tab == "article" else db_rows[:8]
    total = len(live) + len(db_rows) if tab == "article" else len(db_rows)
    return render_template("learn.html", u=u, rows=db_preview, tab=tab,
                           tabs=LEARN_TABS, live=live_preview, news_t=t, online=online,
                           total=total, show_more=total > 6)


@app.route("/learn/<tab>/all")
@login_required()
def learn_all(u, tab):
    if tab not in LEARN_TABS:
        tab = "article"
    q = (request.args.get("q") or "").strip()
    page = request.args.get("page", 1, type=int)
    per = 24
    live = news.get_learn_articles() if tab == "article" else []
    db_rows = Resource.query.filter_by(kind=tab).order_by(Resource.created_at.desc()).all()

    # 统一成 dict 列表
    items = []
    if tab == "article":
        for it in live:
            items.append({"title": it["title"], "summary": "点击在站内阅读全文", "kind": "article",
                          "author": it["source"], "source": it["source"],
                          "date": it["date"], "url": it["url"], "is_live": True})
    for r in db_rows:
        items.append({"title": r.title, "summary": r.summary, "kind": r.kind,
                      "author": r.author, "source": r.source,
                      "date": r.created_at.strftime("%Y-%m-%d"), "rid": r.id,
                      "is_live": False, "url": r.url or "", "cover": r.cover or ""})
    if q:
        items = [x for x in items if q in x["title"] or q in (x["summary"] or "") or q in (x["source"] or "")]
    total = len(items)
    pages = max(1, (total + per - 1) // per)
    page = min(max(1, page), pages)
    page_items = items[(page - 1) * per: page * per]
    t, online = news.last_updated("learn") if tab == "article" else ("", False)
    return render_template("learn_all.html", u=u, tab=tab, tabs=LEARN_TABS,
                           items=page_items, q=q, page=page, pages=pages, total=total,
                           news_t=t, online=online)


@app.route("/learn/post/<int:rid>")
@login_required()
def learn_post(u, rid):
    r = db.session.get(Resource, rid)
    if not r:
        return redirect(url_for("learn"))
    return render_template("learn_post.html", u=u, r=r)


# ---------------- 咨询师工作台 ----------------
@app.route("/teacher_home")
@login_required(role="counselor")
def teacher_home(u):
    """教师工作台：以“待办与关注”为核心组织有用信息（不与数据看板的图表分析重复）。"""
    open_cnt = Alert.query.filter_by(status="open").count()
    today = datetime.now().strftime("%Y-%m-%d")
    today_appts = Appointment.query.filter_by(counselor_id=u.id, date=today).all()
    today_cnt = len(today_appts)
    pending_cnt = Appointment.query.filter_by(counselor_id=u.id, status="pending").count()
    # 本周新增预警（周一0点起）
    week_start = (datetime.now() - timedelta(days=datetime.now().weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0)
    week_alerts = Alert.query.filter(Alert.created_at >= week_start).count()
    # 重点学生：最近一次测评风险指数>=60
    latest = {}
    for a in Assessment.query.order_by(Assessment.created_at.desc()).all():
        latest.setdefault((a.user_id, a.scale_code), a)
    risk_rows = {}
    for (uid, code), a in latest.items():
        ri = engine.scale_risk_index(code, a.score)
        if ri is None:
            continue
        old = risk_rows.get(uid)
        if not old or ri > old["risk"]:
            risk_rows[uid] = {"risk": ri, "code": code, "level": a.level}
    focus = []
    for uid, r in risk_rows.items():
        if r["risk"] >= 60:
            s = db.session.get(User, uid)
            if s:
                focus.append({"name": s.real_name or s.username, "avatar": s.avatar or "🌻",
                              "scale": engine.SCALES.get(r["code"], {}).get("name", r["code"]),
                              "risk": r["risk"], "level": r["level"] or "—", "sid": uid})
    focus.sort(key=lambda x: -x["risk"])
    focus = focus[:6]
    # 最新发布的学生树洞（供巡查速览）
    latest_posts = TreePost.query.order_by(TreePost.created_at.desc()).limit(5).all()
    return render_template("teacher_home.html", u=u, open_cnt=open_cnt,
                           today_appts=today_appts, today_cnt=today_cnt,
                           pending_cnt=pending_cnt, week_alerts=week_alerts,
                           focus=focus, latest_posts=latest_posts)


@app.route("/dash")
@login_required(role="counselor")
def dash(u):
    return render_template("dash.html", u=u)


@app.route("/api/dash/overview")
@login_required(role="counselor")
def dash_overview(u):
    total = User.query.filter_by(role="student").count()
    open_alerts = Alert.query.filter_by(status="open").count()
    thirty = datetime.now() - timedelta(days=30)
    active = Assessment.query.filter(Assessment.created_at >= thirty).with_entities(
        Assessment.user_id).distinct().count()
    all_cnt = Assessment.query.count()

    # 每个学生每套量表只取最近一次
    latest = {}
    for a in Assessment.query.order_by(Assessment.created_at.desc()).all():
        latest.setdefault((a.user_id, a.scale_code), a)
    agg = {}
    for (uid, code), a in latest.items():
        ri = engine.scale_risk_index(code, a.score)
        if ri is None:
            continue
        agg.setdefault(code, []).append(ri)
    by_scale = {code: {"name": engine.SCALES[code]["name"],
                       "risk": round(sum(v) / len(v), 1),
                       "count": len(v)} for code, v in agg.items()}

    # 重点关注学生：最近一次测评中任一套量表风险指数 >= 60 的学生
    students = {x.id: x for x in User.query.filter_by(role="student").all()}
    risk_rows = {}
    for (uid, code), a in latest.items():
        ri = engine.scale_risk_index(code, a.score)
        if ri is None:
            continue
        old = risk_rows.get(uid)
        if not old or ri > old["risk"]:
            risk_rows[uid] = {"risk": ri, "code": code,
                              "score": a.score, "level": a.level,
                              "time": a.created_at.strftime("%Y-%m-%d")}
    high_risk = []
    for uid, r in risk_rows.items():
        if r["risk"] >= 60:
            s = students.get(uid)
            high_risk.append({
                "name": (s.real_name or s.username) if s else "—",
                "avatar": (s.avatar or "🌻") if s else "🌻",
                "scale": engine.SCALES.get(r["code"], {}).get("name", r["code"]),
                "risk": r["risk"], "score": r["score"], "level": r["level"] or "—",
                "time": r["time"], "sid": uid})
    high_risk.sort(key=lambda x: -x["risk"])

    # 各量表级别分布（最近一次测评），用于环形图
    level_dist = []
    for code, v in sorted(agg.items(), key=lambda kv: -len(kv[1])):
        counter = {}
        for (uid2, c2), a in latest.items():
            if c2 != code:
                continue
            counter[a.level or "未分级"] = counter.get(a.level or "未分级", 0) + 1
        level_dist.append({"name": engine.SCALES[code]["name"], "total": len(v),
                           "levels": counter})

    # 近30天测评人次趋势（折线）
    days, acounts, a_counts = [], [], []
    for i in range(29, -1, -1):
        d = (datetime.now() - timedelta(days=i)).date()
        days.append(d.strftime("%m-%d"))
        a_counts.append(Assessment.query.filter(db.func.date(Assessment.created_at) == d).count())
        acounts.append(Alert.query.filter(db.func.date(Alert.created_at) == d).count())

    # 预警来源分布（饼图）
    src_counter = {"chat": 0, "treehole": 0, "assessment": 0}
    for x in Alert.query.all():
        src_counter[x.source] = src_counter.get(x.source, 0) + 1
    alert_src = [{"name": {"chat": "AI倾诉", "treehole": "树洞", "assessment": "测评"}.get(k, k),
                  "value": v} for k, v in src_counter.items() if v > 0]

    # 最近测评（供明细表）
    recent = Assessment.query.order_by(Assessment.created_at.desc()).limit(20).all()
    return jsonify({
        "total": total, "open": open_alerts, "active": active, "all_cnt": all_cnt,
        "high_risk": high_risk, "level_dist": level_dist,
        "days": days, "acounts": acounts, "a_counts": a_counts,
        "alert_src": alert_src,
        "latest": [{"uid": a.user_id,
                    "scale": a.scale_code,
                    "name": engine.SCALES.get(a.scale_code, {}).get("name", a.scale_code),
                    "score": a.score, "level": a.level,
                    "risk": round(engine.scale_risk_index(a.scale_code, a.score) or 0, 1),
                    "user": (db.session.get(User, a.user_id).real_name or '')} for a in recent],
        "by_scale": by_scale,
    })


@app.route("/alerts")
@login_required(role="counselor")
def alerts(u):
    """预警中心：以「学生」为单位聚合综合评价（同一学生的多来源预警合并为一份档案）。"""
    q = (request.args.get("q") or "").strip()
    src = (request.args.get("src") or "").strip()
    lv = (request.args.get("lv") or "").strip()
    st = (request.args.get("st") or "").strip()
    page = max(1, request.args.get("page", 1, type=int))
    per = 10

    students = {x.id: x for x in User.query.filter_by(role="student").all()}
    groups = {}
    for a in Alert.query.order_by(Alert.created_at.desc()).all():
        s = students.get(a.user_id)
        if not s:
            continue
        if q and not (q in (s.real_name or "") or q in (s.username or "")):
            continue
        g = groups.setdefault(a.user_id, {
            "alerts": [], "max_level": "medium", "sources": set(),
            "open_n": 0, "latest": None, "total": 0, "summary_parts": [],
        })
        g["alerts"].append(a)
        g["total"] += 1
        if a.level == "high":
            g["max_level"] = "high"
        g["sources"].add(a.source)
        if a.status == "open":
            g["open_n"] += 1
        if g["latest"] is None:
            g["latest"] = a
        if len(g["summary_parts"]) < 3 and a.content:
            g["summary_parts"].append(a.content[:80])

    items = []
    for uid, g in groups.items():
        if src and src not in g["sources"]:
            continue
        if lv == "high" and g["max_level"] != "high":
            continue
        if lv == "medium" and g["max_level"] != "medium":
            continue
        if st == "open" and g["open_n"] == 0:
            continue
        if st == "handled" and g["open_n"] > 0:
            continue
        items.append((uid, g))
    # 排序：有待处理 > 高危 > 最近触发
    items.sort(key=lambda x: (x[1]["open_n"] == 0, x[1]["max_level"] != "high",
                              -x[1]["latest"].created_at.timestamp()))
    total = len(items)
    pages = max(1, (total + per - 1) // per)
    page = min(page, pages)
    page_items = items[(page - 1) * per: page * per]
    src_names = {"chat": "AI倾诉", "treehole": "匿名树洞", "assessment": "心理测评"}
    cards = []
    for uid, g in page_items:
        s = students[uid]
        cards.append({
            "sid": uid, "name": s.real_name or s.username, "avatar": s.avatar or "🌻",
            "grade": s.grade or "", "major": s.major or "",
            "max_level": g["max_level"], "open_n": g["open_n"], "total": g["total"],
            "sources": [src_names.get(x, x) for x in sorted(g["sources"])],
            "latest_time": g["latest"].created_at.strftime("%m-%d %H:%M"),
            "latest_content": (g["latest"].content or "")[:90],
            "summary": "；".join(g["summary_parts"]),
        })
    return render_template("alerts.html", u=u, cards=cards,
                           q=q, src=src, lv=lv, st=st, page=page, pages=pages, total=total)


@app.route("/alerts/student/<int:sid>/handle", methods=["POST"])
@login_required(role="counselor")
def alert_handle_student(u, sid):
    """按学生办结：一次性处理该学生全部待处理预警。"""
    note = request.form.get("note", "")
    rows = Alert.query.filter_by(user_id=sid, status="open").all()
    for a in rows:
        a.status = "handled"
        a.note = note
        a.handled_at = datetime.now()
    db.session.commit()
    flash("已办结该学生 %d 条待处理预警，并记录处理备注" % len(rows), "ok")
    return redirect(url_for("alerts"))


@app.route("/api/student_alert/<int:sid>")
@login_required(role="counselor")
def api_student_alert(u, sid):
    """学生预警聚合档案：基本信息 + 各来源触发证据 + 科学判定依据 + 综合评价与处置建议。"""
    s = db.session.get(User, sid)
    if not s or s.role != "student":
        return {"ok": False}, 404
    alerts_rows = Alert.query.filter_by(user_id=sid).order_by(Alert.created_at.desc()).all()
    src_names = {"chat": "AI倾诉", "treehole": "匿名树洞", "assessment": "心理测评"}
    level_map = {"high": "高危", "medium": "关注"}
    status_map = {"open": "待处理", "handled": "已处理"}

    # —— 触发证据（按来源聚合、去重）——
    evidence = []
    seen = set()
    if any(a.source == "chat" for a in alerts_rows):
        sid_ids = [x.id for x in ChatSession.query.filter_by(user_id=s.id).all()]
        msgs = []
        if sid_ids:
            msgs = ChatMessage.query.filter(ChatMessage.session_id.in_(sid_ids),
                                            ChatMessage.role == "user").order_by(
                ChatMessage.created_at.desc()).limit(10).all()
        for m in msgs:
            if m.risk == "high" or any(w in (m.content or "") for w in engine.CRISIS_WORDS):
                key = ("chat", m.content[:40])
                if key in seen:
                    continue
                seen.add(key)
                evidence.append({"type": "AI倾诉消息", "detail": m.content,
                                 "extra": "情绪识别：%s · 风险：高危" % (m.emotion or "—"),
                                 "time": m.created_at.strftime("%Y-%m-%d %H:%M")})
        for a in alerts_rows:
            if a.source == "chat" and ("chat", a.content[:40]) not in seen:
                seen.add(("chat", a.content[:40]))
                evidence.append({"type": "AI倾诉消息", "detail": a.content,
                                 "extra": "触发词：" + (a.trigger or "未记录"),
                                 "time": a.created_at.strftime("%Y-%m-%d %H:%M")})
    if any(a.source == "treehole" for a in alerts_rows):
        posts = TreePost.query.filter_by(user_id=s.id).order_by(TreePost.created_at.desc()).limit(10).all()
        for p in posts:
            if p.crisis_flag or any(w in (p.content or "") for w in engine.CRISIS_WORDS):
                key = ("treehole", p.id)
                if key in seen:
                    continue
                seen.add(key)
                evidence.append({"type": "树洞帖子", "detail": p.title + "：" + (p.content or "")[:180],
                                 "extra": "命中敏感词" if p.crisis_flag else "需要关注",
                                 "time": p.created_at.strftime("%Y-%m-%d %H:%M")})
        for a in alerts_rows:
            if a.source == "treehole" and ("treehole", a.content[:40]) not in seen:
                seen.add(("treehole", a.content[:40]))
                evidence.append({"type": "树洞帖子", "detail": a.content[:180],
                                 "extra": "触发词：" + (a.trigger or "敏感词"),
                                 "time": a.created_at.strftime("%Y-%m-%d %H:%M")})
    if any(a.source == "assessment" for a in alerts_rows):
        ass = Assessment.query.filter_by(user_id=s.id).order_by(Assessment.created_at.desc()).all()
        shown = 0
        for x in ass:
            sc = engine.SCALES.get(x.scale_code)
            if not sc or x.scale_code in engine.PROFILE_SCALES:
                continue
            ri = engine.scale_risk_index(x.scale_code, x.score)
            if ri is not None and ri >= 35:
                key = ("assessment", x.id)
                if key in seen:
                    continue
                seen.add(key)
                evidence.append({"type": "心理测评", "detail": "%s：%s分（%s）" % (
                    sc["name"], x.score, x.level or "—"),
                    "extra": "风险指数 %s（0-100，越高越需关注）" % ri,
                    "time": x.created_at.strftime("%Y-%m-%d %H:%M")})
                shown += 1
                if shown >= 6:
                    break

    # —— 判定依据（按来源引用科学文献/法规）——
    basis = []
    for a in alerts_rows:
        if a.source == "assessment":
            m = re.search(r"(phq9|gad7|sds|sas|cesd|ucla|iad|pss10|isi|swls|cdrisc10|psss|apgar|tai|ses|panas|scsq|erq)",
                          a.trigger or "")
            code = m.group(1) if m else None
            if code and code in engine.SCALE_EVIDENCE:
                item = {"title": engine.SCALES[code]["name"] + " · 分级依据（原始文献）",
                        "text": engine.SCALE_EVIDENCE[code]}
                if not any(b["title"] == item["title"] for b in basis):
                    basis.append(item)
        elif a.source in ("chat", "treehole"):
            item = {"title": "危机信号 · 认定依据（科学文献与法规）", "text": engine.CRISIS_BASIS}
            if not any(b["title"] == item["title"] for b in basis):
                basis.append(item)
    if not basis:
        basis.append({"title": "预警判定说明",
                      "text": "系统依据各量表标准阈值与危机信号清单自动识别，分级依据见《心理卫生评定量表手册》"
                              "（汪向东等，1999）及各量表原始文献。"})

    # —— 综合评价（按学生为单位）——
    max_level = "high" if any(a.level == "high" for a in alerts_rows) else "medium"
    open_n = sum(1 for a in alerts_rows if a.status == "open")
    src_set = sorted({src_names.get(a.source, a.source) for a in alerts_rows})
    if max_level == "high" and open_n > 0:
        conclusion = ("该同学近期在 %s 等 %d 个渠道出现 %d 条预警信号，其中包含高危信号且 %d 条尚未处理。"
                      "建议按三级预防流程 24 小时内联系本人/辅导员面谈评估，确认安全状况后制定跟进计划。" % (
                          "、".join(src_set), len(src_set), len(alerts_rows), open_n))
    elif open_n > 0:
        conclusion = ("该同学近期在 %s 出现 %d 条预警信号（关注级别），%d 条待处理。"
                      "建议本周内完成一次面谈或测评复核，观察情绪是否持续走低。" % (
                          "、".join(src_set), len(alerts_rows), open_n))
    else:
        conclusion = ("该同学历史预警 %d 条均已处理。建议纳入常态观察名单，每两周回访一次，"
                      "关注情绪曲线与测评得分变化。" % len(alerts_rows))

    tips = [
        "24小时内联系学生本人或其辅导员，了解当前处境与安全状况（不隔天处理）；",
        "高危工单建议当日完成电话或面谈评估，确认有无具体自伤/自杀计划；",
        "评估后视情况启动家校联动、24小时陪护，并转介学校心理中心或精神卫生专业机构；",
        "全程记录处置过程，结案前持续每周跟进一次，防止风险反复。",
    ]

    return {"ok": True, "student": {
        "name": s.real_name or s.username, "avatar": s.avatar or "🌻",
        "gender": s.gender or "—", "phone": s.phone or "—",
        "grade": s.grade or "—", "major": s.major or "—",
        "student_id": s.student_id or "—", "college": s.college or "—",
        "class_name": s.class_name or "—", "student_status": s.student_status or "—",
    }, "alert": {
        "total": len(alerts_rows), "open_n": open_n,
        "level": level_map.get(max_level, "关注"),
        "sources": src_set,
        "latest_time": alerts_rows[0].created_at.strftime("%Y-%m-%d %H:%M") if alerts_rows else "—",
    }, "conclusion": conclusion, "evidence": evidence, "basis": basis, "tips": tips}


@app.route("/alerts/<int:aid>/handle", methods=["POST"])
@login_required(role="counselor")
def alert_handle(u, aid):
    a = db.session.get(Alert, aid)
    if a:
        a.status = "handled"
        a.note = request.form.get("note", "")
        a.handled_at = datetime.now()
        db.session.commit()
        flash("预警工单已办结", "ok")
    return redirect(url_for("alerts"))


@app.route("/api/alert_detail/<int:aid>")
@login_required(role="counselor")
def api_alert_detail(u, aid):
    """预警详情抽屉：学生基本信息 + 触发证据 + 预警级别判定的科学依据。"""
    a = db.session.get(Alert, aid)
    if not a:
        return {"ok": False}, 404
    s = db.session.get(User, a.user_id)
    if not s:
        return {"ok": False, "error": "学生不存在"}, 404
    src_name = {"chat": "AI倾诉", "treehole": "匿名树洞", "assessment": "心理测评"}.get(a.source, a.source)

    # —— 触发证据 ——
    evidence = []
    if a.source == "chat":
        sid_ids = [x.id for x in ChatSession.query.filter_by(user_id=s.id).all()]
        msgs = []
        if sid_ids:
            msgs = ChatMessage.query.filter(ChatMessage.session_id.in_(sid_ids),
                                            ChatMessage.role == "user").order_by(
                ChatMessage.created_at.desc()).limit(10).all()
        for m in msgs:
            if m.risk == "high" or any(w in (m.content or "") for w in engine.CRISIS_WORDS):
                evidence.append({"type": "AI倾诉消息", "detail": m.content,
                                 "extra": f"情绪识别：{m.emotion} · 风险：高危",
                                 "time": m.created_at.strftime("%Y-%m-%d %H:%M")})
        if not evidence:
            evidence.append({"type": "AI倾诉消息", "detail": a.content,
                             "extra": "触发词：" + (a.trigger or "未记录"),
                             "time": a.created_at.strftime("%Y-%m-%d %H:%M")})
    elif a.source == "treehole":
        posts = TreePost.query.filter_by(user_id=s.id).order_by(TreePost.created_at.desc()).limit(10).all()
        for p in posts:
            if p.crisis_flag or any(w in (p.content or "") for w in engine.CRISIS_WORDS):
                evidence.append({"type": "树洞帖子", "detail": p.title + "：" + p.content[:180],
                                 "extra": "命中敏感词" if p.crisis_flag else "需要关注",
                                 "time": p.created_at.strftime("%Y-%m-%d %H:%M")})
        if not evidence:
            evidence.append({"type": "树洞帖子", "detail": a.content,
                             "extra": "触发词：" + (a.trigger or "敏感词"),
                             "time": a.created_at.strftime("%Y-%m-%d %H:%M")})
    else:  # assessment
        ass = Assessment.query.filter_by(user_id=s.id).order_by(Assessment.created_at.desc()).all()
        shown = 0
        for x in ass:
            sc = engine.SCALES.get(x.scale_code)
            if not sc or x.scale_code in engine.PROFILE_SCALES:
                continue
            ri = engine.scale_risk_index(x.scale_code, x.score)
            if ri is not None and ri >= 35:
                evidence.append({"type": "心理测评",
                                 "detail": f"{sc['name']}：{x.score}分（{x.level or '—'}）",
                                 "extra": f"风险指数 {ri}（0-100，越高越需关注）",
                                 "time": x.created_at.strftime("%Y-%m-%d %H:%M")})
                shown += 1
                if shown >= 6:
                    break
        if not evidence:
            evidence.append({"type": "心理测评", "detail": a.content,
                             "extra": "触发词：" + (a.trigger or "量表高危"),
                             "time": a.created_at.strftime("%Y-%m-%d %H:%M")})

    # —— 判定依据 ——
    basis = []
    if a.source == "assessment":
        m = re.search(r"(phq9|gad7|sds|sas|cesd|ucla|iad|pss10|isi|swls|cdrisc10|psss|apgar|tai|ses)",
                      a.trigger or "")
        code = m.group(1) if m else None
        if code and code in engine.SCALE_EVIDENCE:
            basis.append({"title": engine.SCALES[code]["name"] + " · 分级依据",
                          "text": engine.SCALE_EVIDENCE[code]})
        else:
            # 尝试从 content 里识别量表名
            for c2, ev in engine.SCALE_EVIDENCE.items():
                if engine.SCALES[c2]["name"] in (a.content or ""):
                    basis.append({"title": engine.SCALES[c2]["name"] + " · 分级依据", "text": ev})
                    break
        if not basis:
            basis.append({"title": "量表判定说明", "text": "系统按量表标准阈值判定分级，"
                          "各量表分级依据见《心理卫生评定量表手册》（汪向东等，1999）及各量表原始文献。"})
    else:
        basis.append({"title": "危机信号 · 认定依据（科学文献与法规）", "text": engine.CRISIS_BASIS})

    # —— 处置建议（高校心理危机三级预防通行做法）——
    tips = [
        "24小时内联系学生本人或其辅导员，了解当前处境与安全状况（不隔天处理）；",
        "高危工单建议当日完成电话或面谈评估，确认有无具体自伤/自杀计划；",
        "评估后视情况启动家校联动、24小时陪护，并转介学校心理中心或精神卫生专业机构；",
        "全程记录处置过程，结案前持续每周跟进一次，防止风险反复。",
    ]

    return {"ok": True, "student": {
        "name": s.real_name or s.username, "avatar": s.avatar or "🌻",
        "gender": s.gender or "—", "phone": s.phone or "—",
        "grade": s.grade or "—", "major": s.major or "—",
        "student_id": s.student_id or "—", "college": s.college or "—",
        "class_name": s.class_name or "—", "student_status": s.student_status or "—",
    }, "alert": {
        "source": src_name, "level": "高危" if a.level == "high" else "关注",
        "status": "已处理" if a.status == "handled" else "待处理",
        "trigger": a.trigger or "", "note": a.note or "",
        "time": a.created_at.strftime("%Y-%m-%d %H:%M"),
    }, "evidence": evidence, "basis": basis, "tips": tips}


@app.route("/manage_booking")
@login_required(role="counselor")
def manage_booking(u):
    rows = Appointment.query.filter_by(counselor_id=u.id).order_by(Appointment.created_at.desc()).all()
    users = {x.id: x for x in User.query.all()}
    co = Counselor.query.filter_by(user_id=u.id).first()
    is_pausing = bool(co and co.is_pausing)
    return render_template("manage_booking.html", u=u, rows=rows, users=users,
                           is_pausing=is_pausing)


@app.route("/manage_booking/pause", methods=["POST"])
@login_required(role="counselor")
def manage_booking_pause(u):
    """暂停/恢复预约：暂停期间学生端不再显示该教师、不可提交预约。"""
    co = Counselor.query.filter_by(user_id=u.id).first()
    if not co:
        co = Counselor(user_id=u.id, title="心理咨询师")
        db.session.add(co)
        co.is_pausing = False
        db.session.commit()
    co.is_pausing = not co.is_pausing
    db.session.commit()
    flash("已" + ("暂停" if co.is_pausing else "恢复") + "预约：学生端预约入口已"
          + ("隐藏" if co.is_pausing else "重新开放"), "ok")
    return redirect(url_for("manage_booking"))


@app.route("/manage_booking/<int:aid>/<action>")
@login_required(role="counselor")
def manage_booking_action(u, aid, action):
    a = db.session.get(Appointment, aid)
    if a and a.counselor_id == u.id and action in ("confirmed", "done", "cancelled"):
        a.status = action
        db.session.commit()
    return redirect(url_for("manage_booking"))


@app.route("/api/student_profile/<int:sid>")
@login_required(role="counselor")
def api_student_profile(u, sid):
    """右侧抽屉：预约学生的完整档案（基本信息/历史预约/预警处理/测评记录）。"""
    s = db.session.get(User, sid)
    if not s or s.role != "student":
        return {"ok": False}, 404
    counselors = {c.id: c for c in User.query.filter_by(role="counselor").all()}

    apps = Appointment.query.filter_by(student_id=sid).order_by(
        Appointment.created_at.desc()).all()
    appts = []
    for a in apps:
        c = counselors.get(a.counselor_id)
        appts.append({
            "date": a.date, "time": a.time_slot, "topic": a.topic or "—",
            "counselor": c.real_name or c.username if c else "—",
            "status": {"pending": "待确认", "confirmed": "已确认", "done": "已完成",
                       "cancelled": "已取消"}.get(a.status, a.status),
            "created": a.created_at.strftime("%Y-%m-%d"),
        })

    alerts = Alert.query.filter_by(user_id=sid).order_by(Alert.created_at.desc()).all()
    al = [{
        "source": {"chat": "AI倾诉", "treehole": "树洞", "assessment": "心理测评"}.get(x.source, x.source),
        "level": "高" if x.level == "high" else "中",
        "status": "已处理" if x.status == "handled" else "待处理",
        "content": (x.content or "")[:80],
        "note": x.note or "",
        "time": x.created_at.strftime("%Y-%m-%d %H:%M"),
    } for x in alerts]

    ass = Assessment.query.filter_by(user_id=sid).order_by(Assessment.created_at.desc()).all()
    ases = [{
        "name": engine.SCALES.get(x.scale_code, {}).get("name", x.scale_code),
        "score": x.score, "level": x.level or "—",
        "time": x.created_at.strftime("%Y-%m-%d"),
    } for x in ass]

    posts = TreePost.query.filter_by(user_id=sid).order_by(TreePost.created_at.desc()).limit(5).all()
    trees = [{"title": t.title, "flag": t.crisis_flag,
              "time": t.created_at.strftime("%Y-%m-%d")} for t in posts]

    return {"ok": True, "student": {
        "name": s.real_name or s.username, "avatar": s.avatar or "🌻",
        "gender": s.gender or "—", "phone": s.phone or "—",
        "student_id": s.student_id or "—", "school": s.school or "—",
        "college": s.college or "—", "major": s.major or "—",
        "class_name": s.class_name or "—", "grade": s.grade or "—",
        "education_level": s.education_level or "—",
        "student_status": s.student_status or "—",
    }, "appointments": appts, "alerts": al, "assessments": ases, "trees": trees}


# ---------------- 启动 ----------------
def init_db():
    db.create_all()



@app.route("/breath")
@login_required()
def breath(u):
    return render_template("breath.html")


# ---------------- 教师端：心理资讯与期刊 ----------------
@app.route("/teacher/news")
@app.route("/teacher/news/<section>")
@login_required(role="counselor")
def teacher_news(u, section="要闻"):
    sections = ["要闻", "心理访谈", "政策信息"]
    if section not in sections:
        section = "要闻"
    items = news.get_china(section)
    t, online = news.last_updated("china_" + section)
    return render_template("teacher_news.html", u=u, sections=sections,
                           active=section, items=items, news_t=t, online=online)


@app.route("/teacher/news/<section>/all")
@login_required(role="counselor")
def teacher_news_all(u, section):
    """栏目往期全部文章（多页抓取合并），支持在站内浏览历史信息。"""
    sections = ["要闻", "心理访谈", "政策信息"]
    if section not in sections:
        section = "要闻"
    page = max(1, request.args.get("page", 1, type=int))
    per = 20
    items = news.get_china_all(section)
    total = len(items)
    pages = max(1, (total + per - 1) // per)
    page = min(page, pages)
    rows = items[(page - 1) * per: page * per]
    t, online = news.last_updated("china_all_" + section)
    return render_template("teacher_news_all.html", u=u, sections=sections,
                           active=section, rows=rows, page=page, pages=pages,
                           total=total, news_t=t, online=online)


@app.route("/teacher/news/search", methods=["GET"])
@login_required(role="counselor")
def teacher_news_search(u):
    """资讯搜索：先搜索本网站内已聚合的文章；本地无命中时给出公网搜索入口与结果引导。"""
    q = (request.args.get("q") or "").strip()
    if not q:
        return redirect(url_for("teacher_news"))
    hits, found = news.search_china(q)
    # 公网搜索真实链接（site 限定信息来源站，保证最贴近、最可靠）
    from urllib.parse import quote
    baidu = "https://www.baidu.com/s?wd=" + quote("site:psy.china.com.cn " + q)
    bing = "https://www.bing.com/search?q=" + quote("site:psy.china.com.cn " + q)
    return render_template("teacher_news_search.html", u=u, q=q, hits=hits,
                           found=found, baidu=baidu, bing=bing)


@app.route("/teacher/journal")
@login_required(role="counselor")
def teacher_journal(u):
    items = news.get_journal()
    t, online = news.last_updated("journal")
    return render_template("journal.html", u=u, items=items, news_t=t, online=online)


@app.route("/teacher/journal/all")
@login_required(role="counselor")
def teacher_journal_all(u):
    """心理月刊往期：内置精选目录全量展示（含作者/刊期/DOI，可直接跳转官网查阅）。"""
    page = max(1, request.args.get("page", 1, type=int))
    per = 20
    items = news.FALLBACK_JOURNAL
    total = len(items)
    pages = max(1, (total + per - 1) // per)
    page = min(page, pages)
    rows = items[(page - 1) * per: page * per]
    return render_template("journal_all.html", u=u, rows=rows, page=page,
                           pages=pages, total=total)


@app.route("/teacher/journal/search", methods=["GET"])
@login_required(role="counselor")
def teacher_journal_search(u):
    q = (request.args.get("q") or "").strip()
    if not q:
        return redirect(url_for("teacher_journal"))
    hits, found = news.search_journal(q)
    from urllib.parse import quote
    baidu = "https://www.baidu.com/s?wd=" + quote("site:xlykzz.com " + q)
    bing = "https://www.bing.com/search?q=" + quote("site:xlykzz.com " + q)
    return render_template("journal_search.html", u=u, q=q, hits=hits,
                           found=found, baidu=baidu, bing=bing)



@app.route("/teacher/article")
@login_required(role="counselor")
def teacher_article(u):
    url = request.args.get("url", "")
    art = news.fetch_article(url) if url.startswith("http") else None
    return render_template("article.html", u=u, art=art, url=url)


@app.route("/help")
@login_required()
def help_page(u):
    return render_template("help.html")


# ---------------- 个人信息 ----------------
PROFILE_FIELDS = {
    "student": ["real_name", "gender", "student_id", "school", "college", "major",
                "class_name", "grade", "enrollment_year", "education_level",
                "student_status", "phone", "avatar"],
    "counselor": ["real_name", "gender", "employee_id", "teacher_title", "department",
                  "qualification", "phone", "intro", "avatar"],
}


@app.route("/profile", methods=["GET", "POST"])
@login_required()
def profile(u):
    fields = PROFILE_FIELDS.get(u.role, PROFILE_FIELDS["student"])
    if request.method == "POST":
        for f in fields:
            if f in request.form:
                setattr(u, f, request.form.get(f, "").strip())
        # 头像：radio 传的是 emoji
        if request.form.get("avatar"):
            u.avatar = request.form.get("avatar")
            u.avatar_type = "emoji"
            u.avatar_file = ""
        # 学号/工号填写后视为完成首次必填
        if u.role == "student" and u.real_name and (u.student_id or u.school):
            u.profile_completed = True
        elif u.role == "counselor" and u.real_name and u.department:
            u.profile_completed = True
        db.session.commit()
        flash("个人信息已保存", "ok")
        return redirect(url_for("profile"))
    return render_template("profile.html", u=u, fields=fields)


@app.route("/profile/avatar", methods=["POST"])
@login_required()
def avatar_upload(u):
    """本地图片头像上传：保存到 static/uploads，并更新用户头像。"""
    f = request.files.get("avatar_file")
    if not f or not f.filename:
        flash("请选择要上传的图片", "err")
        return redirect(url_for("profile"))
    ext = (f.filename.rsplit(".", 1)[-1] or "").lower()
    if ext not in ALLOWED_IMG:
        flash("仅支持 png/jpg/jpeg/gif/webp 格式的图片", "err")
        return redirect(url_for("profile"))
    # 清理旧的上传头像
    if u.avatar_type == "upload" and u.avatar_file:
        old = os.path.join(UPLOAD_DIR, u.avatar_file)
        if os.path.exists(old):
            try:
                os.remove(old)
            except OSError:
                pass
    name = f"{uuid.uuid4().hex}.{ext}"
    f.save(os.path.join(UPLOAD_DIR, name))
    u.avatar = f"/static/uploads/{name}"
    u.avatar_type = "upload"
    u.avatar_file = name
    db.session.commit()
    flash("头像已更新", "ok")
    return redirect(url_for("profile"))


# ---------------- 减压舱 ----------------
@app.route("/relax")
@login_required()
def relax(u):
    return render_template("relax.html")


@app.route("/relax/<method>")
@login_required()
def relax_method(u, method):
    methods = {
        "grounding": "grounding.html",
        "pmr": "pmr.html",
        "mindful": "mindful.html",
        "breath": None,
    }
    if method == "breath":
        return redirect(url_for("breath"))
    if method not in methods:
        return redirect(url_for("relax"))
    return render_template(methods[method])



@app.route("/reader")
@login_required()
def reader(u):
    url = request.args.get("url", "")
    art = news.fetch_article(url) if url.startswith("http") else None
    return render_template("article.html", u=u, art=art, url=url, back=url_for("learn"))


if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(host="127.0.0.1", port=5000, debug=False)
