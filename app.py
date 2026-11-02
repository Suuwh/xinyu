"""主入口"""

import os
import sys
import json
import re
import uuid
import engine
import engine_irt
import rag_counselor
import news
import scale_meta
from datetime import datetime, timedelta
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for,session, jsonify, flash)
from werkzeug.utils import secure_filename
from sqlalchemy import or_ as sa_or
from models import db, User, Counselor, Assessment, ChatSession, ChatMessage, Alert, TreePost, TreeComment, Appointment, \
Resource, MoodDiary, IRTTest, RAGSession, RAGMessage

_PYLIBS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pylibs")
if os.path.isdir(_PYLIBS) and _PYLIBS not in sys.path:
    sys.path.insert(0, _PYLIBS)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "xinyu.db"))
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = "xinyu-secret-demo-key"
app.config["MAX_CONTENT_LENGTH"] = 4*1024*1024   #设置头像上传上限4mb
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_IMG = {"png", "jpg", "jpeg", "gif", "webp"}
db.init_app(app)

#首次登陆权限验证
def login_required(role=None):
    def decor(f):
        @wraps(f)
        def wrapper(*args,**kwargs):
            uid = session.get("uid")
            if not uid:
                return redirect(url_for("login", next=request.path))
            u = db.session.get(User, uid)
            if not u:
                session.clear()
                return redirect(url_for("login"))
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

#读取登录用户
@app.context_processor
def inject_globals():
    uid = session.get("uid")
    u = db.session.get(User, uid) if uid else None
    def avatar_html(usr, cls="", emoji_cls=""):
        if usr and usr.avatar_type == "upload" and usr.avatar:
            return f'<img class="{cls}" src="{usr.avatar}" alt="头像">'
        return f'<span class="{emoji_cls}">{usr.avatar or "👤" if usr else "👤"}</span>'
    
    return {"now": datetime.now(), "u": u, "avatar_html": avatar_html}


#学生/教师端资格注册/验证
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
            chsi_no = request.form.get("chsi_no", "").strip()    
            cps_no = request.form.get("cps_no", "").strip()        
            if not re.fullmatch(r"[\w.@+-]{4,64}", chsi_no):
                flash("请填写有效的注册系统账号（手机号或邮箱）", "err")
            elif not re.fullmatch(r"(?:X|C|D)?-?\d{2,6}-?\d{0,4}", cps_no.strip().upper()):
                flash("请填写有效的注册系统编号（如 X-22-001 或 注册编号）", "err")
            else:
                u = User(username=username, role="counselor", real_name=real_name,gender=request.form.get("gender", ""),
                         teacher_title=request.form.get("teacher_title", "心理咨询师"),department=request.form.get("department", ""),
                         qualification_no=cps_no.strip().upper(),qualification_verified=True,   intro=request.form.get("intro", ""))
                u.set_password(password)
                db.session.add(u)
                db.session.flush()
                db.session.add(Counselor(user_id=u.id, title=u.teacher_title or "心理咨询师",specialty=request.form.get("specialty", ""),
                    bio=request.form.get("intro", ""),location=request.form.get("location", "学校心理咨询中心"),avatar=u.avatar or "🧑‍🏫", rating=4.8))
                db.session.commit()
                session["uid"] = u.id
                flash("资质认证通过，咨询师账号已注册，请完善执业信息", "ok")
                return redirect(url_for("profile"))
        else:
            u = User(username=username, role="student", real_name=real_name,gender=request.form.get("gender", ""),grade=request.form.get("grade", ""),
                     major=request.form.get("major", ""))
            u.set_password(password)
            db.session.add(u)
            db.session.commit()
            session["uid"] = u.id
            flash("注册成功，欢迎加入心隅，请完善你的学籍信息", "ok")
            return redirect(url_for("profile"))
        
    return render_template("register.html")


#登录校验
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        role = request.form.get("role", "student")
        u = User.query.filter_by(username=request.form.get("username", "")).first()
        #校验登录选择身份和账号角色是否匹配
        if u and u.check_password(request.form.get("password", "")):
            if role == "student" and u.role != "student":
                flash("该账号为心理咨询师账号，请切换到【心理咨询师登录】标签登录", "err")
                return redirect(url_for("login"))
            if role == "counselor" and u.role != "counselor":
                flash("该账号为学生账号，请切换到【学生登录】标签登录", "err")
                return redirect(url_for("login"))
            session["uid"] = u.id
            if not u.profile_completed:
                flash("欢迎回来，请先完善基本信息（首次登录必填）", "warn")
                return redirect(url_for("profile"))
            return redirect(request.args.get("next") or url_for("index"))
        flash("用户名或密码错误", "err")

    return render_template("login.html")

#退出登录
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

#学生可通过学信网账号登录
@app.route("/login/chsi", methods=["POST"])
def login_chsi():
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

#教师可通过心理学会认证登录
@app.route("/login/cps", methods=["POST"])
def login_cps():
    #教师心理资质认证，演示过程中模拟认证回调
    account = request.form.get("cps_account", "").strip()
    cps_no = request.form.get("cps_no", "").strip().upper()
    if not re.fullmatch(r"[\w.@+-]{4,64}", account):
        flash("请填写有效的注册系统账号（手机号或邮箱）", "err")
        return redirect(url_for("login"))
    
    if not re.fullmatch(r"(?:X|C|D)?-?\d{2,6}-?\d{0,4}", cps_no):
        flash("请填写有效的注册系统编号（如 X-22-001）", "err")
        return redirect(url_for("login"))
    
    u = User.query.filter_by(qualification_no=cps_no, role="counselor", qualification_verified=True).first()
    if u:
        session["uid"] = u.id
        if not u.profile_completed:
            flash("已通过注册系统认证登录，请完善执业信息", "warn")
            return redirect(url_for("profile"))
        flash("已通过中国心理学会注册系统认证登录（演示环境为模拟认证）。", "ok")
        return redirect(request.args.get("next") or url_for("index"))
    flash("该注册编号尚未在本平台完成咨询师注册认证，请先以咨询师身份注册。", "err")

    return redirect(url_for("login"))


#首页
@app.route("/")
@login_required()
def index(u):
    if u.role == "counselor":
        return redirect(url_for("teacher_home"))
    latest = Assessment.query.filter_by(user_id=u.id).order_by(Assessment.created_at.desc()).first()
    latest_irt = IRTTest.query.filter_by(user_id=u.id).order_by(IRTTest.created_at.desc()).first()
    open_alerts = Alert.query.filter_by(user_id=u.id, status="open").count()
    stats = {"assess_cnt": Assessment.query.filter_by(user_id=u.id).count()+IRTTest.query.filter_by(user_id=u.id).count(),
        "mood_cnt": MoodDiary.query.filter_by(user_id=u.id).count(),"booking_cnt": Appointment.query.filter_by(student_id=u.id).count(),
        "post_cnt": TreePost.query.filter_by(user_id=u.id).count(),}

    return render_template("index.html", u=u, latest=latest, latest_irt=latest_irt,open_alerts=open_alerts, **stats)



#AI对话模块
@app.route("/chat")
@login_required()
def chat(u):
    #加载用户全部对话会话
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

#新建空白对话
@app.route("/api/chat/new", methods=["POST"])
@login_required()
def chat_new(u):
    s = ChatSession(user_id=u.id, title="新对话")
    db.session.add(s)
    db.session.commit()
    return jsonify({"ok": True, "sid": s.id})

#AI聊天接口
@app.route("/api/chat", methods=["POST"])
@login_required()
def chat_api(u):
    data = request.get_json(force=True)    #接收用户消息
    text = (data.get("text") or "").strip()
    sid = data.get("sid")
    if not text:
        return jsonify({"ok": False, "error": "empty"})
    s = ChatSession.query.filter_by(id=sid, user_id=u.id).first() if sid else None
    if not s:
        s = ChatSession(user_id=u.id, title=text[:18] or "新对话")
        db.session.add(s); db.session.flush()

    emo = engine.detect_emotion(text)   #识别情绪风险
    db.session.add(ChatMessage(session_id=s.id, role="user", content=text,emotion=emo["emotion"], risk=emo["risk"]))
    res = engine.generate_reply(text, emo)
    am_text = res["reply"] + "\n" + "\n".join("· " + a for a in res["advice"])
    db.session.add(ChatMessage(session_id=s.id, role="assistant", content=am_text, emotion=emo["emotion"], risk=emo["risk"]))
    s.last_at = datetime.now()
    if emo["risk"] == "high":     #高风险情况生成预警工单
        db.session.add(Alert(user_id=u.id, source="chat", content=text,trigger=",".join(emo["hits"]), level="high"))
    db.session.commit()

    return jsonify({"ok": True, "sid": s.id, "reply": am_text,"emotion": emo["emotion"], "risk": emo["risk"]})



#心理测评模块
@app.route("/assessment")
@login_required()
def assessments(u):
    #按测评类型分组
    cats = {}
    history = {}
    for code, sc in engine.SCALES.items():
        history[code] = Assessment.query.filter_by(user_id=u.id, scale_code=code).order_by(Assessment.created_at.desc()).first()
        cats.setdefault(sc["category"], []).append((code, sc))
    return render_template("assessments.html", u=u, cats=cats, history=history)

#展示量表介绍、适用说明、你上一次测这个量表的结果
@app.route("/assessment/<code>")
@login_required()
def assessment_intro(u, code):
    if code not in engine.SCALES:
        return redirect(url_for("assessments"))
    scale = engine.SCALES[code]
    meta = scale_meta.SCALE_META.get(code, {})
    last = Assessment.query.filter_by(user_id=u.id, scale_code=code).order_by(Assessment.created_at.desc()).first()
    return render_template("intro.html", u=u, code=code, scale=scale, meta=meta, last=last)

#量表答题、提交答卷、算分、保存测评结果、高危评估预警
@app.route("/assessment/<code>/take", methods=["GET", "POST"])
@login_required()
def assessment_take(u, code):
    if code not in engine.SCALES:   #量表答题
        return redirect(url_for("assessments"))
    scale = engine.SCALES[code]
    if request.method == "POST":   
        answers = []     
        for i in range(len(scale["questions"])):  #提交答卷
            v = request.form.get("q%d" % i)
            if v is None:
                break
            answers.append(v)

        if len(answers) != len(scale["questions"]):   #完成度校验
            flash("请完成所有题目后再提交", "warn")
            return render_template("take.html", u=u, code=code, scale=scale)
        
        r = engine.assess_scale(code, answers)  #算分
        a = Assessment(user_id=u.id, scale_code=code, answers=json.dumps(answers),score=r["score"], level=r["level"], advice=r["advice"])
        db.session.add(a)    #结果保存
        if r["level"] in ("重度抑郁", "中重度抑郁", "重度焦虑", "重度失眠", "高度孤独感","高压力", "困扰严重", "重度"):   #高危预警
            db.session.add(Alert(user_id=u.id, source="assessment",content=f"{scale['name']}={r['score']}分（{r['level']}）",
                                trigger=f"量表高危:{code}", level="high"))
        db.session.commit()
        return render_template("result.html", u=u, scale=scale, r=r)
    
    return render_template("take.html", u=u, code=code, scale=scale)


#测评历史记录
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
    return render_template("history.html", u=u, rows=rows, names=names, risks=risks,q=q, page=page, pages=pages, total=total)


#心情日记模块
@app.route("/mood", methods=["GET", "POST"])
@login_required()
def mood(u):
    if request.method == "POST":
        m = MoodDiary(user_id=u.id, mood=int(request.form.get("mood", 0)),note=request.form.get("note", "").strip())
        db.session.add(m)
        db.session.commit()
        flash("今日心情已记录，继续观察自己的状态吧", "ok")
        return redirect(url_for("mood"))
    
    rows = MoodDiary.query.filter_by(user_id=u.id).order_by(MoodDiary.created_at.desc()).limit(200).all()
    return render_template("mood.html", u=u, rows=rows)

 #心情记录曲线，可按周/月/年查看日记数量
@app.route("/api/mood")
@login_required()
def mood_api(u):
    rng = request.args.get("range", "week")
    today = datetime.now().date()
    if rng == "week":
        start = today - timedelta(days=6)
    elif rng == "month":
        start = today - timedelta(days=29)
    elif rng == "year":
        start = today - timedelta(days=364)
    else:
        start = None

    q = MoodDiary.query.filter_by(user_id=u.id)
    if start is not None:
        q = q.filter(MoodDiary.created_at >= datetime.combine(start, datetime.min.time()))
    rows = q.order_by(MoodDiary.created_at).all()
    day_sum, day_cnt = {}, {}
    for r in rows:
        k = r.created_at.strftime("%Y-%m-%d")
        day_sum[k] = day_sum.get(k, 0) + r.mood
        day_cnt[k] = day_cnt.get(k, 0) + 1
    if rng == "all":
        start = today
        if day_sum:
            start = min(datetime.strptime(k, "%Y-%m-%d").date() for k in day_sum)

    labels, vals, dates = [], [], []
    cur = start
    while cur <= today:
        full = cur.strftime("%Y-%m-%d")
        dates.append(full)
        labels.append(full if rng == "all" else cur.strftime("%m-%d"))
        if full in day_sum:
            vals.append(round(day_sum[full] / day_cnt[full], 1))
        else:
            vals.append(None)
        cur += timedelta(days=1)
    return jsonify({"labels": labels,"vals": vals,"dates": dates,"range": rng,})



#匿名树洞模块
ALLOWED_MEDIA = {"image": {"jpg", "jpeg", "png", "gif", "webp"},"audio": {"mp3", "wav", "m4a", "ogg", "aac"},"video": {"mp4", "webm", "mov", "m4v"},}
MAX_MEDIA_BYTES = 25*1024*1024  #最大25MB上传限制
SENSITIVE = ["自杀", "轻生", "自残"]

#上传树洞文件判断
def _save_media(f):
    if not f or not f.filename:
        return "", ""
    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    kind = next((k for k, exts in ALLOWED_MEDIA.items() if ext in exts), "")
    if not kind:
        return "", "仅支持图片(jpg/png/gif/webp)、音频(mp3/wav/m4a/ogg)、视频(mp4/webm/mov)"
    data = f.read(MAX_MEDIA_BYTES + 1)
    if len(data) > MAX_MEDIA_BYTES:
        return "", "文件过大，请控制在25MB以内"
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

#学生端的树洞：提供发帖以及查看树洞帖子功能，自己的帖子可隐藏
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
                p = TreePost(user_id=u.id, nickname="匿名同学", title=title,content=content, tags=tags, crisis_flag=crisis,media_kind=mk, media_url=mu)
                db.session.add(p)
                if crisis:
                    db.session.add(Alert(user_id=u.id, source="treehole", content=content[:200],trigger="树洞敏感词", level="high"))
                db.session.commit()
                flash("已发布，谢谢你愿意说出来", "ok")
        return redirect(url_for("treehole"))
    
    q = (request.args.get("q") or "").strip()
    tag = (request.args.get("tag") or "").strip()
    page = request.args.get("page", 1, type=int)
    per = 12
    my = (request.args.get("my") or "") == "1"   #树洞权限分类，我的树洞和公共树洞
    if my:
        query = TreePost.query.filter(TreePost.user_id == u.id)
        if q:
            query = query.filter(sa_or(TreePost.title.contains(q), TreePost.content.contains(q)))
        if tag:
            query = query.filter(TreePost.tags.contains(tag))
    else:
        #隐藏的帖子不对外展示
        query = TreePost.query.filter(TreePost.hidden == False)
        if q:
            query = query.filter(sa_or(TreePost.title.contains(q), TreePost.content.contains(q)))
        if tag:
            query = query.filter(TreePost.tags.contains(tag))
    rows, total, pages, page = _treehole_page(query, page, per)
    #热门话题
    counter = {}
    for p in TreePost.query.filter(TreePost.hidden == False).all():
        for t in (p.tags or "").split():
            counter[t] = counter.get(t, 0) + 1
    hot_tags = sorted(counter.items(), key=lambda x: -x[1])[:10]

    return render_template("treehole.html", u=u, posts=rows, q=q, tag=tag,page=page, pages=pages, total=total, hot_tags=hot_tags,my=my, is_teacher=False)


#教师端树洞，浏览公开树洞帖子、检索、查看统计、热门标签等
#只能查看、浏览学生的发帖子，没有发帖功能
@app.route("/teacher/treehole")
@login_required(role="counselor")
def teacher_treehole(u):
    q = (request.args.get("q") or "").strip()
    tag = (request.args.get("tag") or "").strip()
    page = request.args.get("page", 1, type=int)
    per = 12
    query = TreePost.query.filter(TreePost.hidden == False)
    if q:
        query = query.filter(sa_or(TreePost.title.contains(q), TreePost.content.contains(q),TreePost.tags.contains(q)))
    if tag:
        query = query.filter(TreePost.tags.contains(tag))
    rows, total, pages, page = _treehole_page(query, page, per)

    hot_tags = []
    for p in TreePost.query.all():
        for t in (p.tags or "").split():
            hot_tags.append(t)

    counter = {}
    for t in hot_tags:
        counter[t] = counter.get(t, 0) + 1
    hot_tags = sorted(counter.items(), key=lambda x: -x[1])[:10]
    posts = TreePost.query.filter(TreePost.hidden == False).all()
    post_users = {p.user_id for p in posts}
    stats = {"posts": len(posts), "users": len(post_users),"crisis": sum(1 for p in posts if p.crisis_flag),"likes": sum(p.likes for p in posts)}
    
    return render_template("teacher_treehole.html", u=u, posts=rows, q=q, tag=tag,page=page, pages=pages, total=total,hot_tags=hot_tags, stats=stats)

#查看树洞帖子详情页，可以评论
@app.route("/treehole/<int:pid>", methods=["GET", "POST"])
@login_required()
def treehole_detail(u, pid):
    p = db.session.get(TreePost, pid)
    if not p:
        return redirect(url_for("treehole"))
    #对于已隐藏的帖子仅作者本人可以访问
    if p.hidden and p.user_id != u.id:
        return redirect(url_for("treehole"))
    if request.method == "POST":
        c = TreeComment(post_id=pid, nickname="匿名同学",content=request.form.get("content", "").strip())
        db.session.add(c)
        db.session.commit()
        return redirect(url_for("treehole_detail", pid=pid))
    comments = TreeComment.query.filter_by(post_id=pid).order_by(TreeComment.id).all()
    return render_template("detail.html", u=u, p=p, comments=comments)


#学生修改自己发布的树洞帖子
@app.route("/treehole/<int:pid>/edit", methods=["POST"])
@login_required()
def treehole_edit(u, pid):
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

        #评估敏感词，出现高危词汇则触发预警
        crisis = any(w in content for w in SENSITIVE)
        if crisis and not p.crisis_flag:
            db.session.add(Alert(user_id=u.id, source="treehole", content=content[:200],trigger="树洞敏感词", level="high"))
        p.crisis_flag = crisis
        db.session.commit()
        flash("帖子已更新", "ok")

    return redirect(url_for("treehole", my=1))


#学生删除自己的树洞帖子
@app.route("/treehole/<int:pid>/delete", methods=["POST"])
@login_required()
def treehole_delete(u, pid):
    p = db.session.get(TreePost, pid)
    if not p or p.user_id != u.id:
        flash("只能删除自己发布的帖子", "err")
        return redirect(url_for("treehole", my=1))
    TreeComment.query.filter_by(post_id=pid).delete()
    db.session.delete(p)
    db.session.commit()
    flash("帖子已删除", "ok")

    return redirect(url_for("treehole", my=1))

#学生切换帖子查看权限（隐藏/公开）
@app.route("/treehole/<int:pid>/hide", methods=["POST"])
@login_required()
def treehole_hide(u, pid):
    p = db.session.get(TreePost, pid)
    if not p or p.user_id != u.id:
        flash("只能管理自己发布的帖子", "err")
        return redirect(url_for("treehole", my=1))
    p.hidden = not p.hidden
    db.session.commit()
    flash("帖子已隐藏，仅自己可见" if p.hidden else "帖子已恢复公开", "ok")
    return redirect(url_for("treehole", my=1))

#点赞功能
@app.route("/treehole/<int:pid>/like")
@login_required()
def treehole_like(u, pid):
    p = db.session.get(TreePost, pid)
    if p:
        p.likes += 1
        db.session.commit()
    return redirect(url_for("treehole_detail", pid=pid))



#学生预约咨询模块
@app.route("/booking", methods=["GET", "POST"])
@login_required()
def booking(u):
    #仅显示有资质且未暂停预约的咨询师（咨询师可暂停预约，暂停后学生端不再显示、不可预约）
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
        ap = Appointment(counselor_id=cid, student_id=u.id,date=request.form.get("date", ""),time_slot=request.form.get("time_slot", ""),
                         topic=request.form.get("topic", ""), status="pending")
        db.session.add(ap); db.session.commit()
        flash("预约已提交，等待咨询师确认", "ok")
        return redirect(url_for("my_booking"))
    
    return render_template("booking.html", u=u, counselors=counselors, infos=infos)

#学生查看预约记录
@app.route("/my_booking")
@login_required()
def my_booking(u):
    rows = Appointment.query.filter_by(student_id=u.id).order_by(Appointment.created_at.desc()).all()
    counselors = User.query.filter(User.role == "counselor").all()
    cinfo = {}
    for c in counselors:
        co = Counselor.query.filter_by(user_id=c.id).first()
        cinfo[c.id] = {"name": c.real_name or c.username,"location": (co.location if co else "") or "学校心理咨询中心","title": (co.title if co else "") or "心理咨询师"}
        
    return render_template("my_booking.html", u=u, rows=rows, cinfo=cinfo)


#学生取消预约
@app.route("/my_booking/<int:aid>/cancel", methods=["POST"])
@login_required()
def my_booking_cancel(u, aid):
    a = db.session.get(Appointment, aid)
    #取消权限限制：设置只有待确认和已确认状态才可取消
    if a and a.student_id == u.id and a.status in ("pending", "confirmed"):
        a.status = "cancelled"
        db.session.commit()
        flash("预约已取消，如需要可随时重新预约", "ok")
    else:
        flash("该预约当前状态不可取消", "err")
    return redirect(url_for("my_booking"))


#心理成长模块
LEARN_TABS = {"article": "心晴手札", "video": "疗愈影音", "book": "枕边书单"}   #三个子栏目
@app.route("/learn")
@app.route("/learn/<tab>")
@login_required()
#心理成长栏目首页
def learn(u, tab="article"):
    if tab not in LEARN_TABS:
        tab = "article"
    db_rows = Resource.query.filter_by(kind=tab).order_by(Resource.created_at.desc()).all()
    live = news.get_learn_articles() if tab == "article" else []
    t, online = news.last_updated("learn") if tab == "article" else ("", False)

    #文章按日期倒序排序
    merged = []
    if tab == "article":
        for it in live:
            merged.append({"title": it["title"], "summary": "点击在站内阅读全文", "kind": "article","author": it["source"], "source": it["source"],
                           "date": it["date"], "url": it["url"], "is_live": True})
    for r in db_rows:
        merged.append({"title": r.title, "summary": r.summary, "kind": r.kind,"author": r.author, "source": r.source,"date": r.created_at.strftime("%Y-%m-%d"), 
                       "rid": r.id,"is_live": False, "url": r.url or "", "cover": r.cover or ""})
    merged.sort(key=lambda x: x.get("date") or "", reverse=True)

    #设置每个栏目页最多显示8条内容
    preview = merged[:8]
    total = len(merged)
    return render_template("learn.html", u=u, rows=preview, tab=tab,tabs=LEARN_TABS, news_t=t, online=online,total=total, show_more=total > 8)

#栏目资源设置分页查看、关键词搜索
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

    #dict列表存放
    items = []
    if tab == "article":
        for it in live:
            items.append({"title": it["title"], "summary": "点击在站内阅读全文", "kind": "article","author": it["source"], "source": it["source"],
                          "date": it["date"], "url": it["url"], "is_live": True})
    for r in db_rows:
        items.append({"title": r.title, "summary": r.summary, "kind": r.kind,"author": r.author, "source": r.source,"date": r.created_at.strftime("%Y-%m-%d"), 
                      "rid": r.id,"is_live": False, "url": r.url or "", "cover": r.cover or ""})
    if q:
        items = [x for x in items if q in x["title"] or q in (x["summary"] or "") or q in (x["source"] or "")]

    #按日期倒序
    items.sort(key=lambda x: x.get("date") or "", reverse=True)
    total = len(items)
    pages = max(1, (total + per - 1) // per)
    page = min(max(1, page), pages)
    page_items = items[(page - 1) * per: page * per]
    t, online = news.last_updated("learn") if tab == "article" else ("", False)
    return render_template("learn_all.html", u=u, tab=tab, tabs=LEARN_TABS,items=page_items, q=q, page=page, pages=pages, total=total,
                           news_t=t, online=online)

#查看站内自有资源详情页
@app.route("/learn/post/<int:rid>")
@login_required()
def learn_post(u, rid):
    r = db.session.get(Resource, rid)
    if not r:
        return redirect(url_for("learn"))
    return render_template("learn_post.html", u=u, r=r)




'''教师/咨询师端'''

#教师端首页
@app.route("/teacher_home")
@login_required(role="counselor")
def teacher_home(u):
    open_cnt = Alert.query.filter_by(status="open").count()
    today = datetime.now().strftime("%Y-%m-%d")
    today_appts = Appointment.query.filter_by(counselor_id=u.id, date=today).all()
    today_cnt = len(today_appts)
    pending_cnt = Appointment.query.filter_by(counselor_id=u.id, status="pending").count()

    #待办预警统计
    week_start = (datetime.now() - timedelta(days=datetime.now().weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    week_alerts = Alert.query.filter(Alert.created_at >= week_start).count()

    #重点关注学生名单
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
                focus.append({"name": s.real_name or s.username, "avatar": s.avatar or "🌻","scale": engine.SCALES.get(r["code"], {}).get("name", r["code"]),
                              "risk": r["risk"], "level": r["level"] or "—", "sid": uid})
    focus.sort(key=lambda x: -x["risk"])
    focus = focus[:6]

    #最新发布的学生树洞速览
    latest_posts = TreePost.query.order_by(TreePost.created_at.desc()).limit(5).all()

    return render_template("teacher_home.html", u=u, open_cnt=open_cnt,today_appts=today_appts, today_cnt=today_cnt,pending_cnt=pending_cnt, week_alerts=week_alerts,
                           focus=focus, latest_posts=latest_posts)


#数据看板页面入口
@app.route("/dash")
@login_required(role="counselor")
def dash(u):
    return render_template("dash.html", u=u)

#看板页面数据源
@app.route("/api/dash/overview")
@login_required(role="counselor")
def dash_overview(u):
    total = User.query.filter_by(role="student").count()
    open_alerts = Alert.query.filter_by(status="open").count()
    thirty = datetime.now() - timedelta(days=30)
    active = Assessment.query.filter(Assessment.created_at >= thirty).with_entities(Assessment.user_id).distinct().count()
    all_cnt = Assessment.query.count()

    #每个学生每套量表只取最近一次
    latest = {}
    for a in Assessment.query.order_by(Assessment.created_at.desc()).all():
        latest.setdefault((a.user_id, a.scale_code), a)
    agg = {}
    for (uid, code), a in latest.items():
        ri = engine.scale_risk_index(code, a.score)
        if ri is None:
            continue
        agg.setdefault(code, []).append(ri)
    by_scale = {code: {"name": engine.SCALES[code]["name"],"risk": round(sum(v) / len(v), 1),"count": len(v)} for code, v in agg.items()}

    #需重点关注的学生：最近一次测评中任一套量表风险指数>=60的学生
    students = {x.id: x for x in User.query.filter_by(role="student").all()}
    risk_rows = {}
    for (uid, code), a in latest.items():
        ri = engine.scale_risk_index(code, a.score)
        if ri is None:
            continue
        old = risk_rows.get(uid)
        if not old or ri > old["risk"]:
            risk_rows[uid] = {"risk": ri, "code": code,"score": a.score, "level": a.level,"time": a.created_at.strftime("%Y-%m-%d")}
    high_risk = []
    for uid, r in risk_rows.items():
        if r["risk"] >= 60:
            s = students.get(uid)
            high_risk.append({"name": (s.real_name or s.username) if s else "—","avatar": (s.avatar or "🌻") if s else "🌻",
                "scale": engine.SCALES.get(r["code"], {}).get("name", r["code"]),"risk": r["risk"], "score": r["score"], "level": r["level"] or "—",
                "time": r["time"], "sid": uid})
    high_risk.sort(key=lambda x: -x["risk"])

    #各量表级别分布（最近一次测评），环形图展示
    level_dist = []
    for code, v in sorted(agg.items(), key=lambda kv: -len(kv[1])):
        counter = {}
        for (uid2, c2), a in latest.items():
            if c2 != code:
                continue
            counter[a.level or "未分级"] = counter.get(a.level or "未分级", 0) + 1
        level_dist.append({"name": engine.SCALES[code]["name"], "total": len(v),"levels": counter})

    #近30天测评人次趋势（折线图）
    days, acounts, a_counts = [], [], []
    for i in range(29, -1, -1):
        d = (datetime.now() - timedelta(days=i)).date()
        days.append(d.strftime("%m-%d"))
        a_counts.append(Assessment.query.filter(db.func.date(Assessment.created_at) == d).count())
        acounts.append(Alert.query.filter(db.func.date(Alert.created_at) == d).count())

    #预警来源分布（饼图）
    src_counter = {"chat": 0, "treehole": 0, "assessment": 0}
    for x in Alert.query.all():
        src_counter[x.source] = src_counter.get(x.source, 0) + 1
    alert_src = [{"name": {"chat": "AI倾诉", "treehole": "树洞", "assessment": "测评"}.get(k, k),"value": v} for k, v in src_counter.items() if v > 0]

    #最近测评（明细表）
    recent = Assessment.query.order_by(Assessment.created_at.desc()).limit(20).all()

    #以学生为单位聚合（专业量表和IRT量表）
    all_students = User.query.filter_by(role="student").order_by(User.id).all()
    students_overview = []
    for st in all_students:
        n_ass = Assessment.query.filter_by(user_id=st.id).order_by(
            Assessment.created_at.desc()).limit(4).all()
        normal_rows = []
        max_risk = 0
        for x in n_ass:
            ri = engine.scale_risk_index(x.scale_code, x.score)
            if ri is not None and ri > max_risk:
                max_risk = ri
            normal_rows.append({"scale": engine.SCALES.get(x.scale_code, {}).get("name", x.scale_code),"score": x.score, 
                                "risk": round(ri, 1) if ri is not None else None,"level": x.level or "—","time": x.created_at.strftime("%Y-%m-%d %H:%M"),})
        i_ass = IRTTest.query.filter_by(user_id=st.id).order_by(IRTTest.created_at.desc()).limit(3).all()
        irt_rows_s = []
        _bank_scales = engine_irt.load_bank()["scales"]
        for x in i_ass:
            bm = _bank_scales.get(x.scale_code, {})
            irt_rows_s.append({"scale": bm.get("name", x.scale_code.upper()),"t_score": x.t_score, "theta": round(x.theta, 2),
                                "n_items": x.n_items, "level": x.level or "—","time": x.created_at.strftime("%Y-%m-%d %H:%M"),})
        #综合等级设置
        if max_risk >= 60:
            olv, ocolor = "重点关注", "red"
        elif max_risk >= 35:
            olv, ocolor = "需要留意", "orange"
        else:
            olv, ocolor = "状态平稳", "green"
        students_overview.append({"sid": st.id, "name": st.real_name or st.username,"avatar": st.avatar or "🌻","grade": st.grade or "", 
                                  "major": st.major or "","max_risk": round(max_risk, 1), "overall": olv, "ocolor": ocolor,"normal": normal_rows, 
                                  "irt": irt_rows_s,"n_normal": Assessment.query.filter_by(user_id=st.id).count(),
                                  "n_irt": IRTTest.query.filter_by(user_id=st.id).count(),})
    #IRT自适应测评统计
    irt_all = IRTTest.query.order_by(IRTTest.created_at.desc()).all()
    irt_cnt = len(irt_all)
    #按时间倒序遍历，每个学生保留的第一条即最近一次
    irt_latest_by_user = {}
    for t in irt_all:
        if t.user_id not in irt_latest_by_user:
            irt_latest_by_user[t.user_id] = t

    #严重等级判定：3=重度/危险，2=中度，1=轻度，0=正常
    def _irt_sev(t):
        lv = t.level or ""
        if ("重" in lv) or ("危险" in lv) or ("严重" in lv):
            return 3
        if "中" in lv:
            return 2
        if "轻" in lv:
            return 1
        return 0

    irt_high_users = sum(1 for t in irt_latest_by_user.values() if _irt_sev(t) == 3)
    irt_mid_users = sum(1 for t in irt_latest_by_user.values() if _irt_sev(t) == 2)
    irt_recent = IRTTest.query.order_by(IRTTest.created_at.desc()).limit(10).all()
    irt_bank = engine_irt.load_bank()["scales"]
    irt_recent_rows = [{"uid": t.user_id,"name": irt_bank.get(t.scale_code, {}).get("name", t.scale_code.upper()),"code": t.scale_code,
                        "t_score": t.t_score, "theta": round(t.theta, 2),"level": t.level or "—", "n_items": t.n_items,"time": t.created_at.strftime("%Y-%m-%d %H:%M"),
                        "user": (db.session.get(User, t.user_id).real_name or '')} for t in irt_recent]

    return jsonify({"total": total, "open": open_alerts, "active": active, "all_cnt": all_cnt,"high_risk": high_risk, "level_dist": level_dist,
                    "days": days, "acounts": acounts, "a_counts": a_counts,"alert_src": alert_src,
                    "latest": [{"uid": a.user_id,"scale": a.scale_code,"name": engine.SCALES.get(a.scale_code, {}).get("name", a.scale_code),
                                "score": a.score, "level": a.level,"risk": round(engine.scale_risk_index(a.scale_code, a.score) or 0, 1),
                                "user": (db.session.get(User, a.user_id).real_name or '')} for a in recent],
                    "by_scale": by_scale,"irt": {"cnt": irt_cnt, "high_users": irt_high_users, "mid_users": irt_mid_users,
                    "covered_users": len(irt_latest_by_user), "recent": irt_recent_rows},"students": students_overview,})


#学生风险总览
#以学生为单位聚合综合评价，同一学生的多来源预警合并为一份档案
@app.route("/alerts")
@login_required(role="counselor")
def alerts(u):
    """预警中心：。"""
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
        g = groups.setdefault(a.user_id, {"alerts": [], "max_level": "medium", "sources": set(),"open_n": 0, "latest": None, "total": 0, "summary_parts": [],})
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

    #排序：有待处理>高危>最近触发
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
        cards.append({"sid": uid, "name": s.real_name or s.username, "avatar": s.avatar or "🌻","grade": s.grade or "", "major": s.major or "",
            "max_level": g["max_level"], "open_n": g["open_n"], "total": g["total"],"sources": [src_names.get(x, x) for x in sorted(g["sources"])],
            "latest_time": g["latest"].created_at.strftime("%m-%d %H:%M"),"latest_content": (g["latest"].content or "")[:90],"summary": "；".join(g["summary_parts"]),})
    
    return render_template("alerts.html", u=u, cards=cards,q=q, src=src, lv=lv, st=st, page=page, pages=pages, total=total)


#按学生办结、处理该学生全部待处理预警
@app.route("/alerts/student/<int:sid>/handle", methods=["POST"])
@login_required(role="counselor")
def alert_handle_student(u, sid):
    note = request.form.get("note", "")
    rows = Alert.query.filter_by(user_id=sid, status="open").all()
    for a in rows:
        a.status = "handled"
        a.note = note
        a.handled_at = datetime.now()
    db.session.commit()
    flash("已办结该学生 %d 条待处理预警，并记录处理备注" % len(rows), "ok")

    return redirect(url_for("alerts"))


#调取学生档案
@app.route("/api/student_alert/<int:sid>")
@login_required(role="counselor")
def api_student_alert(u, sid):
    s = db.session.get(User, sid)
    if not s or s.role != "student":
        return {"ok": False}, 404
    alerts_rows = Alert.query.filter_by(user_id=sid).order_by(Alert.created_at.desc()).all()
    src_names = {"chat": "AI倾诉", "treehole": "匿名树洞", "assessment": "心理测评"}
    level_map = {"high": "高危", "medium": "关注"}
    status_map = {"open": "待处理", "handled": "已处理"}

    #触发证据聚合
    evidence = []
    seen = set()
    #AI倾诉
    if any(a.source == "chat" for a in alerts_rows):
        sid_ids = [x.id for x in ChatSession.query.filter_by(user_id=s.id).all()]
        msgs = []
        if sid_ids:
            msgs = ChatMessage.query.filter(ChatMessage.session_id.in_(sid_ids),ChatMessage.role == "user").order_by(ChatMessage.created_at.desc()).limit(10).all()
        for m in msgs:
            if m.risk == "high" or any(w in (m.content or "") for w in engine.CRISIS_WORDS):
                key = ("chat", m.content[:40])
                if key in seen:
                    continue
                seen.add(key)
                evidence.append({"type": "AI倾诉消息", "detail": m.content,"extra": "情绪识别：%s · 风险：高危" % (m.emotion or "—"),"time": m.created_at.strftime("%Y-%m-%d %H:%M")})
        for a in alerts_rows:
            if a.source == "chat" and ("chat", a.content[:40]) not in seen:
                seen.add(("chat", a.content[:40]))
                evidence.append({"type": "AI倾诉消息", "detail": a.content,"extra": "触发词：" + (a.trigger or "未记录"),"time": a.created_at.strftime("%Y-%m-%d %H:%M")})
    #树洞帖子
    if any(a.source == "treehole" for a in alerts_rows):
        posts = TreePost.query.filter_by(user_id=s.id).order_by(TreePost.created_at.desc()).limit(10).all()
        for p in posts:
            if p.crisis_flag or any(w in (p.content or "") for w in engine.CRISIS_WORDS):
                key = ("treehole", p.id)
                if key in seen:
                    continue
                seen.add(key)
                evidence.append({"type": "树洞帖子", "detail": p.title + "：" + (p.content or "")[:180],"extra": "命中敏感词" if p.crisis_flag else "需要关注",
                                 "time": p.created_at.strftime("%Y-%m-%d %H:%M")})
        for a in alerts_rows:
            if a.source == "treehole" and ("treehole", a.content[:40]) not in seen:
                seen.add(("treehole", a.content[:40]))
                evidence.append({"type": "树洞帖子", "detail": a.content[:180],"extra": "触发词：" + (a.trigger or "敏感词"),"time": a.created_at.strftime("%Y-%m-%d %H:%M")})
    #心理测评（专业量表）
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
                evidence.append({"type": "心理测评", "detail": "%s：%s分（%s）" % (sc["name"], x.score, x.level or "—"),"extra": "风险指数 %s（0-100，越高越需关注）" % ri,
                    "time": x.created_at.strftime("%Y-%m-%d %H:%M")})
                shown += 1
                if shown >= 6:
                    break

    #IRT自适应测评记录
    irt_rows = IRTTest.query.filter_by(user_id=s.id).order_by(IRTTest.created_at.desc()).limit(6).all()
    irt_bank_meta = engine_irt.load_bank()["scales"]
    irts = []
    for t in irt_rows:
        meta = irt_bank_meta.get(t.scale_code, {})
        irts.append({"name": meta.get("name", t.scale_code.upper()),"code": t.scale_code,"t_score": t.t_score, "theta": round(t.theta, 2),"se": round(t.se, 2), "level": t.level or "—",
            "n_items": t.n_items,"time": t.created_at.strftime("%Y-%m-%d %H:%M"),})
        sev_word = t.level or ""
        if ("中" in sev_word) or ("重" in sev_word) or ("危险" in sev_word):
            key = ("irt", t.id)
            if key not in seen:
                seen.add(key)
                evidence.append({"type": "IRT自适应测评","detail": "%s：T%s分（θ%+.2f，%s）" % (meta.get("name", t.scale_code.upper()), t.t_score, t.theta, t.level or "—"),
                    "extra": "自适应作答 %d 题 · 测量标准误 %s" % (t.n_items, round(t.se, 2)),"time": t.created_at.strftime("%Y-%m-%d %H:%M"),})

    #判定依据，按来源引用科学文献、法规
    basis = []
    for a in alerts_rows:
        if a.source == "assessment":
            m = re.search(r"(phq9|gad7|sds|sas|cesd|ucla|iad|pss10|isi|swls|cdrisc10|psss|apgar|tai|ses|panas|scsq|erq)",
                          a.trigger or "")
            code = m.group(1) if m else None
            if code and code in engine.SCALE_EVIDENCE:
                item = {"title": engine.SCALES[code]["name"] + " · 分级依据（原始文献）","text": engine.SCALE_EVIDENCE[code]}
                if not any(b["title"] == item["title"] for b in basis):
                    basis.append(item)
        elif a.source in ("chat", "treehole"):
            item = {"title": "危机信号 · 认定依据（科学文献与法规）", "text": engine.CRISIS_BASIS}
            if not any(b["title"] == item["title"] for b in basis):
                basis.append(item)
    if not basis:
        basis.append({"title": "预警判定说明","text": "系统依据各量表标准阈值与危机信号清单自动识别，分级依据见《心理卫生评定量表手册》"
                    "（汪向东等，1999）及各量表原始文献。"})

    #整合综合评价（按学生为单位）
    max_level = "high" if any(a.level == "high" for a in alerts_rows) else "medium"
    open_n = sum(1 for a in alerts_rows if a.status == "open")
    src_set = sorted({src_names.get(a.source, a.source) for a in alerts_rows})
    if max_level == "high" and open_n > 0:
        conclusion = ("该同学近期在 %s 等 %d 个渠道出现 %d 条预警信号，其中包含高危信号且 %d 条尚未处理。"
                      "建议按三级预防流程 24 小时内联系本人/辅导员面谈评估，确认安全状况后制定跟进计划。" % (
                          "、".join(src_set), len(src_set), len(alerts_rows), open_n))
    elif open_n > 0:
        conclusion = ("该同学近期在 %s 出现 %d 条预警信号（关注级别），%d 条待处理。""建议本周内完成一次面谈或测评复核，观察情绪是否持续走低。" % (
                          "、".join(src_set), len(alerts_rows), open_n))
    else:
        conclusion = ("该同学历史预警 %d 条均已处理。建议纳入常态观察名单，每两周回访一次，""关注情绪曲线与测评得分变化。" % len(alerts_rows))

    tips = ["24小时内联系学生本人或其辅导员，了解当前处境与安全状况（不隔天处理）；","高危工单建议当日完成电话或面谈评估，确认有无具体自伤/自杀计划；",
        "评估后视情况启动家校联动、24小时陪护，并转介学校心理中心或精神卫生专业机构；","全程记录处置过程，结案前持续每周跟进一次，防止风险反复。",]

    return {"ok": True, "student": {"name": s.real_name or s.username, "avatar": s.avatar or "🌻","gender": s.gender or "—", "phone": s.phone or "—",
        "grade": s.grade or "—", "major": s.major or "—","student_id": s.student_id or "—", "college": s.college or "—","class_name": s.class_name or "—", 
        "student_status": s.student_status or "—",}, "alert": {"total": len(alerts_rows), "open_n": open_n,"level": level_map.get(max_level, "关注"),
        "sources": src_set,"latest_time": alerts_rows[0].created_at.strftime("%Y-%m-%d %H:%M") if alerts_rows else "—",}, 
        "conclusion": conclusion, "evidence": evidence, "basis": basis,"irts": irts, "tips": tips}

#预警单条办结
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

#预警详情抽屉：包括学生基本信息、触发证据、预警级别判定的科学依据
@app.route("/api/alert_detail/<int:aid>")
@login_required(role="counselor")
def api_alert_detail(u, aid):
    a = db.session.get(Alert, aid)
    if not a:
        return {"ok": False}, 404
    s = db.session.get(User, a.user_id)
    if not s:
        return {"ok": False, "error": "学生不存在"}, 404
    src_name = {"chat": "AI倾诉", "treehole": "匿名树洞", "assessment": "心理测评"}.get(a.source, a.source)

    #触发证据
    evidence = []
    if a.source == "chat":
        sid_ids = [x.id for x in ChatSession.query.filter_by(user_id=s.id).all()]
        msgs = []
        if sid_ids:
            msgs = ChatMessage.query.filter(ChatMessage.session_id.in_(sid_ids),ChatMessage.role == "user").order_by(
                ChatMessage.created_at.desc()).limit(10).all()
        for m in msgs:
            if m.risk == "high" or any(w in (m.content or "") for w in engine.CRISIS_WORDS):
                evidence.append({"type": "AI倾诉消息", "detail": m.content,"extra": f"情绪识别：{m.emotion} · 风险：高危","time": m.created_at.strftime("%Y-%m-%d %H:%M")})
        if not evidence:
            evidence.append({"type": "AI倾诉消息", "detail": a.content,"extra": "触发词：" + (a.trigger or "未记录"),
                             "time": a.created_at.strftime("%Y-%m-%d %H:%M")})
    elif a.source == "treehole":
        posts = TreePost.query.filter_by(user_id=s.id).order_by(TreePost.created_at.desc()).limit(10).all()
        for p in posts:
            if p.crisis_flag or any(w in (p.content or "") for w in engine.CRISIS_WORDS):
                evidence.append({"type": "树洞帖子", "detail": p.title + "：" + p.content[:180],"extra": "命中敏感词" if p.crisis_flag else "需要关注",
                                 "time": p.created_at.strftime("%Y-%m-%d %H:%M")})
        if not evidence:
            evidence.append({"type": "树洞帖子", "detail": a.content,"extra": "触发词：" + (a.trigger or "敏感词"),
                             "time": a.created_at.strftime("%Y-%m-%d %H:%M")})
    else:  
        ass = Assessment.query.filter_by(user_id=s.id).order_by(Assessment.created_at.desc()).all()
        shown = 0
        for x in ass:
            sc = engine.SCALES.get(x.scale_code)
            if not sc or x.scale_code in engine.PROFILE_SCALES:
                continue
            ri = engine.scale_risk_index(x.scale_code, x.score)
            if ri is not None and ri >= 35:
                evidence.append({"type": "心理测评","detail": f"{sc['name']}：{x.score}分（{x.level or '—'}）","extra": f"风险指数 {ri}（0-100，越高越需关注）",
                                 "time": x.created_at.strftime("%Y-%m-%d %H:%M")})
                shown += 1
                if shown >= 6:
                    break
        if not evidence:
            evidence.append({"type": "心理测评", "detail": a.content,"extra": "触发词：" + (a.trigger or "量表高危"),"time": a.created_at.strftime("%Y-%m-%d %H:%M")})

    #判定依据
    basis = []
    if a.source == "assessment":
        m = re.search(r"(phq9|gad7|sds|sas|cesd|ucla|iad|pss10|isi|swls|cdrisc10|psss|apgar|tai|ses)",
                      a.trigger or "")
        code = m.group(1) if m else None
        if code and code in engine.SCALE_EVIDENCE:
            basis.append({"title": engine.SCALES[code]["name"] + " · 分级依据","text": engine.SCALE_EVIDENCE[code]})
        else:
            #从content里识别量表名
            for c2, ev in engine.SCALE_EVIDENCE.items():
                if engine.SCALES[c2]["name"] in (a.content or ""):
                    basis.append({"title": engine.SCALES[c2]["name"] + " · 分级依据", "text": ev})
                    break
        if not basis:
            basis.append({"title": "量表判定说明", "text": "系统按量表标准阈值判定分级，"
                          "各量表分级依据见《心理卫生评定量表手册》（汪向东等，1999）及各量表原始文献。"})
    else:
        basis.append({"title": "危机信号 · 认定依据（科学文献与法规）", "text": engine.CRISIS_BASIS})

    #处置建议：高校心理危机三级预防通行做法
    tips = ["24小时内联系学生本人或其辅导员，了解当前处境与安全状况（不隔天处理）；","高危工单建议当日完成电话或面谈评估，确认有无具体自伤/自杀计划；",
        "评估后视情况启动家校联动、24小时陪护，并转介学校心理中心或精神卫生专业机构；","全程记录处置过程，结案前持续每周跟进一次，防止风险反复。",]

    return {"ok": True, "student": {"name": s.real_name or s.username, "avatar": s.avatar or "🌻","gender": s.gender or "—", "phone": s.phone or "—",
        "grade": s.grade or "—", "major": s.major or "—","student_id": s.student_id or "—", "college": s.college or "—",
        "class_name": s.class_name or "—", "student_status": s.student_status or "—",}, "alert": {"source": src_name, "level": "高危" if a.level == "high" else "关注",
        "status": "已处理" if a.status == "handled" else "待处理","trigger": a.trigger or "", "note": a.note or "","time": a.created_at.strftime("%Y-%m-%d %H:%M"),
        }, "evidence": evidence, "basis": basis, "tips": tips}


#教师/咨询师预约管理模块
@app.route("/manage_booking")
@login_required(role="counselor")
def manage_booking(u):
    rows = Appointment.query.filter_by(counselor_id=u.id).order_by(Appointment.created_at.desc()).all()
    users = {x.id: x for x in User.query.all()}
    co = Counselor.query.filter_by(user_id=u.id).first()
    is_pausing = bool(co and co.is_pausing)

    return render_template("manage_booking.html", u=u, rows=rows, users=users,is_pausing=is_pausing)

#预约状态设置（暂停/恢复）
@app.route("/manage_booking/pause", methods=["POST"])
@login_required(role="counselor")
def manage_booking_pause(u):
    #暂停期间学生端不再显示该教师、不可提交预约
    co = Counselor.query.filter_by(user_id=u.id).first()
    if not co:
        co = Counselor(user_id=u.id, title="心理咨询师")
        db.session.add(co)
        co.is_pausing = False
        db.session.commit()
    co.is_pausing = not co.is_pausing
    db.session.commit()
    flash("已" + ("暂停" if co.is_pausing else "恢复") + "预约：学生端预约入口已" + ("隐藏" if co.is_pausing else "重新开放"), "ok")

    return redirect(url_for("manage_booking"))

#预约状态变更操作
@app.route("/manage_booking/<int:aid>/<action>", methods=["GET", "POST"])
@login_required(role="counselor")
def manage_booking_action(u, aid, action):
    a = db.session.get(Appointment, aid)
    if a and a.counselor_id == u.id and action in ("confirmed", "done", "cancelled"):
        a.status = action
        db.session.commit()   
    return redirect(url_for("manage_booking"))


#教师端学生工单接口
#设计抽屉弹窗展示学生完整档案
@app.route("/api/student_profile/<int:sid>")
@login_required(role="counselor")
def api_student_profile(u, sid):
    s = db.session.get(User, sid)
    if not s or s.role != "student":   #身份校验
        return {"ok": False}, 404
    counselors = {c.id: c for c in User.query.filter_by(role="counselor").all()}

    apps = Appointment.query.filter_by(student_id=sid).order_by(Appointment.created_at.desc()).all()  #查询预约记录
    appts = []
    for a in apps:
        c = counselors.get(a.counselor_id)
        appts.append({"date": a.date, "time": a.time_slot, "topic": a.topic or "—","counselor": c.real_name or c.username if c else "—",
            "status": {"pending": "待确认", "confirmed": "已确认", "done": "已完成","cancelled": "已取消"}.get(a.status, a.status),
            "created": a.created_at.strftime("%Y-%m-%d"),})

    alerts = Alert.query.filter_by(user_id=sid).order_by(Alert.created_at.desc()).all()  #查询预警记录
    al = [{"source": {"chat": "AI倾诉", "treehole": "树洞", "assessment": "心理测评"}.get(x.source, x.source),"level": "高" if x.level == "high" else "中",
        "status": "已处理" if x.status == "handled" else "待处理","content": (x.content or "")[:80],"note": x.note or "",
        "time": x.created_at.strftime("%Y-%m-%d %H:%M"),} for x in alerts]

    ass = Assessment.query.filter_by(user_id=sid).order_by(Assessment.created_at.desc()).all()  #查询普通量表测评记录
    ases = [{"name": engine.SCALES.get(x.scale_code, {}).get("name", x.scale_code),"score": x.score, "level": x.level or "—",
             "time": x.created_at.strftime("%Y-%m-%d"),} for x in ass]

    irt_rows = IRTTest.query.filter_by(user_id=sid).order_by(IRTTest.created_at.desc()).limit(10).all()  #查询irt自适应测评记录
    irts = [{"scale": x.scale_code.upper(),"theta": round(x.theta, 2),"t_score": x.t_score,"level": x.level,"n": x.n_items,"time": x.created_at.strftime("%Y-%m-%d"),} for x in irt_rows]

    posts = TreePost.query.filter_by(user_id=sid).order_by(TreePost.created_at.desc()).limit(5).all()   #查询学生树洞帖子
    trees = [{"title": t.title, "flag": t.crisis_flag,"time": t.created_at.strftime("%Y-%m-%d")} for t in posts]
    #返回包含学生基本信息
    return {"ok": True, "student": {"name": s.real_name or s.username, "avatar": s.avatar or "🌻","gender": s.gender or "—", "phone": s.phone or "—",
        "student_id": s.student_id or "—", "school": s.school or "—","college": s.college or "—", "major": s.major or "—","class_name": s.class_name or "—", 
        "grade": s.grade or "—","education_level": s.education_level or "—","student_status": s.student_status or "—",}, "appointments": appts, "alerts": al, 
        "assessments": ases, "irts": irts, "trees": trees}


#初始化数据库，创建数据表
def init_db():
    db.create_all()


#呼吸放松页面展示
@app.route("/breath")
@login_required()
def breath(u):
    return render_template("breath.html")


#教师端
#心理资讯与期刊首页
@app.route("/teacher/news")
@app.route("/teacher/news/<section>")
@login_required(role="counselor")
def teacher_news(u, section="要闻"):
    sections = ["要闻", "心理访谈", "政策信息"]   #咨询栏分三子栏
    if section not in sections:
        section = "要闻"
    items = news.get_china(section)
    t, online = news.last_updated("china_" + section)

    return render_template("teacher_news.html", u=u, sections=sections,active=section, items=items, news_t=t, online=online)

#历史资讯
@app.route("/teacher/news/<section>/all")
@login_required(role="counselor")
def teacher_news_all(u, section):
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

    return render_template("teacher_news_all.html", u=u, sections=sections,active=section, rows=rows, page=page, pages=pages,total=total, news_t=t, online=online)

#资讯搜索
@app.route("/teacher/news/search", methods=["GET"])
@login_required(role="counselor")
def teacher_news_search(u):
   #先搜索本网站内的文章，本地找不到公网搜索
    q = (request.args.get("q") or "").strip()
    if not q:
        return redirect(url_for("teacher_news"))
    hits, found = news.search_china(q)
    #公网搜索链接
    from urllib.parse import quote
    baidu = "https://www.baidu.com/s?wd=" + quote("site:psy.china.com.cn " + q)
    bing = "https://www.bing.com/search?q=" + quote("site:psy.china.com.cn " + q)
    return render_template("teacher_news_search.html", u=u, q=q, hits=hits,found=found, baidu=baidu, bing=bing)

#心理期刊首页
@app.route("/teacher/journal")
@login_required(role="counselor")
def teacher_journal(u):
    items = news.get_journal()
    t, online = news.last_updated("journal")
    return render_template("journal.html", u=u, items=items, news_t=t, online=online)

#历史期刊
@app.route("/teacher/journal/all")
@login_required(role="counselor")
def teacher_journal_all(u):
    page = max(1, request.args.get("page", 1, type=int))
    per = 20
    items = news.FALLBACK_JOURNAL
    total = len(items)
    pages = max(1, (total+per-1)//per)
    page = min(page, pages)
    rows = items[(page-1)*per:page*per]
    return render_template("journal_all.html", u=u, rows=rows, page=page,pages=pages, total=total)

#期刊检索
@app.route("/teacher/journal/search", methods=["GET"])
@login_required(role="counselor")
def teacher_journal_search(u):
    #站内检索期刊
    q = (request.args.get("q") or "").strip()
    if not q:
        return redirect(url_for("teacher_journal"))
    hits, found = news.search_journal(q)
    from urllib.parse import quote
    baidu = "https://www.baidu.com/s?wd="+quote("site:xlykzz.com "+q)  #期刊官网搜索链接
    bing = "https://www.bing.com/search?q="+quote("site:xlykzz.com "+q)
    return render_template("journal_search.html", u=u, q=q, hits=hits,found=found, baidu=baidu, bing=bing)

@app.route("/teacher/article")
@login_required(role="counselor")
def teacher_article(u):
    url = request.args.get("url", "")
    art = news.fetch_article(url) if url.startswith("http") else None
    return render_template("article.html", u=u, art=art, url=url)

#求助页面
@app.route("/help")
@login_required()
def help_page(u):
    return render_template("help.html")



#个人信息模块
#区分角色：学生/教师
PROFILE_FIELDS = {
    "student": ["real_name", "gender", "student_id", "school", "college", "major","class_name", "grade", "enrollment_year", "education_level",
                "student_status", "phone", "avatar"],
    "counselor": ["real_name", "gender", "employee_id", "teacher_title", "department","qualification", "phone", "intro", "avatar"],}

#基本信息
@app.route("/profile", methods=["GET", "POST"])
@login_required()
def profile(u):
    fields = PROFILE_FIELDS.get(u.role, PROFILE_FIELDS["student"])
    if request.method == "POST":
        for f in fields:
            if f in request.form:
                setattr(u, f, request.form.get(f, "").strip())
        #头像
        if request.form.get("avatar"):
            u.avatar = request.form.get("avatar")
            u.avatar_type = "emoji"
            u.avatar_file = ""
        #学号/工号为首次必填
        if u.role == "student" and u.real_name and (u.student_id or u.school):
            u.profile_completed = True
        elif u.role == "counselor" and u.real_name and u.department:
            u.profile_completed = True
        db.session.commit()
        flash("个人信息已保存", "ok")
        return redirect(url_for("profile"))
    return render_template("profile.html", u=u, fields=fields)

#图片头像上传接口
@app.route("/profile/avatar", methods=["POST"])
@login_required()
def avatar_upload(u):
    f = request.files.get("avatar_file")
    if not f or not f.filename:
        flash("请选择要上传的图片", "err")
        return redirect(url_for("profile"))
    ext = (f.filename.rsplit(".", 1)[-1] or "").lower()
    if ext not in ALLOWED_IMG:   #上传格式判断
        flash("仅支持 png/jpg/jpeg/gif/webp 格式的图片", "err")
        return redirect(url_for("profile"))
    #清理旧头像
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


#减压舱模块
@app.route("/relax")
@login_required()
def relax(u):
    return render_template("relax.html")

#减压训练方法
@app.route("/relax/<method>")
@login_required()
def relax_method(u, method):
    methods = {              #四种减压方法
        "grounding": "grounding.html",
        "pmr": "pmr.html",
        "mindful": "mindful.html",
        "breath": None, }
    if method == "breath":
        return redirect(url_for("breath"))
    if method not in methods:
        return redirect(url_for("relax"))
    return render_template(methods[method])


#文章阅读页
@app.route("/reader")
@login_required()
def reader(u):
    url = request.args.get("url", "")
    art = news.fetch_article(url) if url.startswith("http") else None
    return render_template("article.html", u=u, art=art, url=url, back=url_for("learn"))


#irt自适应测评首页
@app.route("/irt")
@login_required()
def irt_home(u):
    bank = engine_irt.load_bank()["scales"]
    scales = []
    for code, sc in bank.items():
        last = IRTTest.query.filter_by(user_id=u.id, scale_code=code).order_by(IRTTest.created_at.desc()).first()   #展示最近一次测评
        scales.append({"code": code, "name": sc["name"], "short": sc["short"],"description": sc["description"], "n_total": len(sc["items"]),
                       "max_items": sc["max_items"], "last": last})
    return render_template("irt_home.html", u=u, scales=scales)

#开启一套irt测评
@app.route("/irt/take/<code>")
@login_required()
def irt_take(u, code):
    if code not in engine_irt.load_bank()["scales"]:
        flash("未知量表", "error")
        return redirect(url_for("irt_home"))
    bank = engine_irt.get_scale(code)
    #初始化测试记录
    rec = IRTTest(user_id=u.id, scale_code=code, n_items=0)
    db.session.add(rec)
    db.session.commit()
    session["irt"] = {"test_id": rec.id, "scale": code, "answered": {}}
    return render_template("irt_take.html", u=u, scale=bank, rec=rec)

#答题交互接口
@app.route("/irt/answer", methods=["POST"])
@login_required()
def irt_answer(u):
    st = session.get("irt")
    if not st or st.get("scale") not in engine_irt.load_bank()["scales"]:
        return jsonify({"ok": False, "error": "session expired"}), 400
    data = request.get_json(force=True) or {}
    item_id = data.get("item_id")
    score = int(data.get("score", -1))
    bank = engine_irt.get_scale(st["scale"])
    answered = st["answered"]
    #初始化，未作答时返回theta=0处信息量最大的首题
    if item_id == "__init__":
        first = engine_irt.next_item(0.0, set(), st["scale"])
        return jsonify({"ok": True, "done": False, "theta": 0.0, "se": 1.0, "n": 0,"next": {"id": first["id"], "stem": first["stem"],
                     "options": first["options"], "dim": first.get("dim", "")}})
    item = next((i for i in bank["items"] if i["id"] == item_id), None)
    if not item or score < 0 or score >= item["n_levels"]:
        return jsonify({"ok": False, "error": "bad answer"}), 400
    #记录作答
    answered[item_id] = score
    st["answered"] = answered
    session["irt"] = st
    #重新估计theta
    responses = [{"item": next(i for i in bank["items"] if i["id"] == k), "score": v} for k, v in answered.items()]
    theta, se = engine_irt.eap_estimate(responses)
    reason = engine_irt.stop_reason(theta, se, len(responses), bank["max_items"])
    #选择下一題
    next_it = None if reason else engine_irt.next_item(theta, set(answered.keys()), st["scale"])
    #当全部答完但未达SE阈值，显示题库已耗尽
    if next_it is None and reason is None:
        reason = "bank_exhausted"
    return jsonify({"ok": True, "done": bool(next_it is None),"stop_reason": reason,"theta": round(theta, 2), "se": round(se, 2), "n": len(responses),
        "next": None if next_it is None else {"id": next_it["id"], "stem": next_it["stem"],"options": next_it["options"], "dim": next_it.get("dim", ""),}
        })

#测评保存
@app.route("/irt/finish/<int:tid>")
@login_required()
def irt_finish(u, tid):
    rec = IRTTest.query.get_or_404(tid)
    if rec.user_id != u.id:
        return redirect(url_for("irt_home"))
    bank = engine_irt.get_scale(rec.scale_code)
    #使用会话中的作答数据收尾
    st = session.get("irt") or {}
    answered = st.get("answered", {}) if st.get("test_id") == tid else {}   #若是会话已经过期，则用rec已存数据
    #若rec已完成（n_items>0）直接展示
    if rec.n_items == 0 and answered:
        responses = [{"item": next(i for i in bank["items"] if i["id"] == k), "score": v} for k, v in answered.items()]
        theta, se = engine_irt.eap_estimate(responses)
        rec.theta = round(theta, 3)
        rec.se = round(se, 3)
        rec.t_score = engine_irt.theta_to_t(theta)
        rec.level, _ = engine_irt.risk_level(theta, rec.scale_code)
        rec.n_items = len(responses)
        rec.responses = json.dumps([{"item_id": r["item"]["id"], "stem": r["item"]["stem"],
                                     "score": r["score"]} for r in responses], ensure_ascii=False)
        dims = engine_irt.dimension_thetas(responses)
        rec.dims = json.dumps(dims, ensure_ascii=False)
        db.session.commit()
        session.pop("irt", None)
    return redirect(url_for("irt_result", tid=rec.id))

#irt测评结果详情页
@app.route("/irt/result/<int:tid>")
@login_required()
def irt_result(u, tid):
    rec = IRTTest.query.get_or_404(tid)
    if rec.user_id != u.id:
        return redirect(url_for("irt_home"))
    bank = engine_irt.get_scale(rec.scale_code)
    responses = json.loads(rec.responses or "[]")
    dims = json.loads(rec.dims or "{}")
    level_cls = {"正常范围": "ok", "无明显焦虑": "ok", "无明显抑郁": "ok",
                 "轻度困扰": "warn", "轻度焦虑": "warn", "轻度抑郁": "warn",
                 "中度症状": "danger", "中度焦虑": "danger", "中度抑郁": "danger",
                 "重度症状": "critical", "重度焦虑": "critical", "重度抑郁": "critical"}.get(rec.level, "ok")
    return render_template("irt_result.html", u=u, rec=rec, scale=bank,responses=responses, dims=dims, level_cls=level_cls)

#irt测评历史
@app.route("/irt/history")
@login_required()
def irt_history(u):
    rows = IRTTest.query.filter_by(user_id=u.id).order_by(IRTTest.created_at.desc()).all()
    return render_template("irt_history.html", u=u, rows=rows)

#我的测评总览页
@app.route("/my_assessments")
@login_required()
def my_assessments(u):
    #合并普通量表和irt测评表的全部历史
    normal = Assessment.query.filter_by(user_id=u.id).order_by(Assessment.created_at.desc()).all()
    irt_rows = IRTTest.query.filter_by(user_id=u.id).order_by(IRTTest.created_at.desc()).all()
    merged = []
    for a in normal:
        merged.append({"kind": "normal","time": a.created_at,"name": engine.SCALES.get(a.scale_code, {}).get("name", a.scale_code),
            "code": a.scale_code,"score_text": f"{a.score} 分","level": a.level or "—","detail": "固定题数量表","url": url_for("history"),})
    for r in irt_rows:
        bank = engine_irt.load_bank()["scales"].get(r.scale_code, {})
        merged.append({"kind": "irt","time": r.created_at,"name": bank.get("name", r.scale_code.upper()) + "（IRT）",
            "code": r.scale_code,"score_text": f"T{r.t_score} · θ{round(r.theta,2):+.2f}","level": r.level or "—",
            "detail": f"自适应 {r.n_items} 题 · SE {round(r.se,2)}","url": url_for("irt_result", tid=r.id),})
    merged.sort(key=lambda x: x["time"], reverse=True)
    return render_template("my_assessments.html", u=u, rows=merged,n_normal=len(normal), n_irt=len(irt_rows))



#RAG心理咨询模块
#知识库对话页面
@app.route("/rag_chat")
@login_required()
def rag_chat_page(u):
    sid = request.args.get("sid", type=int)
    cur = None
    msgs = []
    if sid:
        cur = RAGSession.query.filter_by(id=sid, user_id=u.id).first()
        if cur:
            msgs = RAGMessage.query.filter_by(session_id=cur.id).order_by(RAGMessage.id).all()
    sessions = RAGSession.query.filter_by(user_id=u.id).order_by(RAGSession.last_at.desc()).limit(30).all()

    return render_template("rag_chat.html", u=u, rag_status=rag_counselor.status(),sessions=sessions, cur=cur, msgs=msgs)

#新建RAG对话
@app.route("/api/rag/session/new", methods=["POST"])
@login_required()
def rag_session_new(u):
    s = RAGSession(user_id=u.id, title="新对话")
    db.session.add(s)
    db.session.commit()
    return jsonify({"ok": True, "sid": s.id})

#删除对话
@app.route("/api/rag/session/<int:sid>/delete", methods=["POST"])
@login_required()
def rag_session_delete(u, sid):
    s = RAGSession.query.filter_by(id=sid, user_id=u.id).first()
    if s:
        RAGMessage.query.filter_by(session_id=s.id).delete()
        db.session.delete(s)
        db.session.commit()
    return jsonify({"ok": True})

#RAG问答接口
@app.route("/api/rag/chat", methods=["POST"])
@login_required()
def rag_chat_api(u):
    data = request.get_json(force=True) or {}
    msg = (data.get("message") or "").strip()
    sid = data.get("sid")
    if not msg:
        return jsonify({"ok": False, "error": "empty"}), 400
    #校验模型就绪状态
    if not rag_counselor.status().get("ready"):
        return jsonify({"ok": False, "not_ready": True,"error": "模型仍在加载，请稍等片刻后重试"}), 503
    #获取或创建会话
    s = RAGSession.query.filter_by(id=sid, user_id=u.id).first() if sid else None
    if not s:
        s = RAGSession(user_id=u.id, title=msg[:18] or "新对话")
        db.session.add(s)
        db.session.commit()
    #历史消息
    prior = RAGMessage.query.filter_by(session_id=s.id).order_by(RAGMessage.id.desc()).limit(8).all()
    prior = list(reversed(prior))
    history = [{"role": m.role, "content": m.content} for m in prior if m.content != rag_counselor.PLACEHOLDER_REPLY]
    #保存用户消息
    um = RAGMessage(session_id=s.id, role="user", content=msg)
    db.session.add(um)
    #首条消息用于更新会话标题
    if s.title == "新对话":
        s.title = msg[:18]
    s.last_at = datetime.now()
    db.session.commit()
    try:
        result = rag_counselor.chat(msg, history=history)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    #保存AI消息
    am = RAGMessage(session_id=s.id, role="assistant", content=result["reply"],crisis=result.get("crisis", False),sources="、".join(result.get("sources", [])))
    db.session.add(am)
    db.session.commit()

    return jsonify({"ok": True, "sid": s.id, "title": s.title, **result})

#启动时后台加载本地模型
import threading as _th
def _boot_rag():
    try:
        rag_counselor.init_rag()
    except Exception as _e:
        print(f"[RAG] 后台加载失败: {_e}")
_th.Thread(target=_boot_rag, daemon=True, name="rag-boot").start()


if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(host="127.0.0.1", port=5000, debug=False)





































