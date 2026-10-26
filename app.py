"""心屿 · AI校园心理健康护航平台 — 应用主入口"""
import json
import os
from datetime import datetime, timedelta
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for,
                   session, jsonify, flash)

from models import db, User, Counselor, Assessment, ChatSession, ChatMessage, \
    Alert, TreePost, TreeComment, Appointment, Resource, MoodDiary
import engine

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
# 数据库：默认 SQLite 开箱即用；如需 MySQL，设置环境变量 DATABASE_URL 即可，例如：
# DATABASE_URL=mysql+pymysql://root:你的密码@127.0.0.1:3306/xinyu?charset=utf8mb4
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "xinyu.db"))
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = "xinyu-secret-demo-key"
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
            if role and u.role != role:
                flash("该页面需要相应权限", "warn")
                return redirect(url_for("index"))
            return f(u, *args, **kwargs)
        return wrapper
    return decor


@app.context_processor
def inject_globals():
    return {"now": datetime.now()}


# ---------------- 认证 ----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        real_name = request.form.get("real_name", "").strip()
        if not username or not password:
            flash("用户名和密码不能为空", "err")
        elif User.query.filter_by(username=username).first():
            flash("用户名已存在", "err")
        else:
            u = User(username=username, role="student", real_name=real_name,
                     gender=request.form.get("gender", ""),
                     grade=request.form.get("grade", ""),
                     major=request.form.get("major", ""))
            u.set_password(password)
            db.session.add(u)
            db.session.commit()
            session["uid"] = u.id
            flash("注册成功，欢迎加入心屿", "ok")
            return redirect(url_for("index"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = User.query.filter_by(username=request.form.get("username", "")).first()
        if u and u.check_password(request.form.get("password", "")):
            session["uid"] = u.id
            return redirect(request.args.get("next") or url_for("index"))
        flash("用户名或密码错误", "err")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------- 首页（按角色分流） ----------------
@app.route("/")
@login_required()
def index(u):
    if u.role == "counselor":
        return redirect(url_for("teacher_home"))
    latest = Assessment.query.filter_by(user_id=u.id).order_by(Assessment.created_at.desc()).first()
    open_alerts = Alert.query.filter_by(user_id=u.id, status="open").count()
    return render_template("index.html", u=u, latest=latest, open_alerts=open_alerts)


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


@app.route("/assessment/<code>", methods=["GET", "POST"])
@login_required()
def assessment_run(u, code):
    if code not in engine.SCALES:
        return redirect(url_for("assessments"))
    scale = engine.SCALES[code]
    if request.method == "POST":
        answers = request.form.getlist("q")
        r = engine.assess_scale(code, answers)
        a = Assessment(user_id=u.id, scale_code=code, answers=json.dumps(answers),
                       score=r["score"], level=r["level"], advice=r["advice"])
        db.session.add(a)
        if r["level"] in ("重度抑郁", "中重度抑郁", "重度焦虑", "重度失眠", "高度孤独感", "高压力", "困扰严重"):
            db.session.add(Alert(user_id=u.id, source="assessment",
                                content=f"{scale['name']}={r['score']}分（{r['level']}）",
                                trigger="量表高危", level="high"))
        db.session.commit()
        return render_template("result.html", u=u, scale=scale, r=r)
    return render_template("scale.html", u=u, code=code, scale=scale)


@app.route("/history")
@login_required()
def history(u):
    rows = Assessment.query.filter_by(user_id=u.id).order_by(Assessment.created_at.desc()).all()
    return render_template("history.html", u=u, rows=rows)


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
    rows = MoodDiary.query.filter_by(user_id=u.id).order_by(MoodDiary.created_at.desc()).limit(60).all()
    return render_template("mood.html", u=u, rows=rows)


@app.route("/api/mood")
@login_required()
def mood_api(u):
    rows = MoodDiary.query.filter_by(user_id=u.id).order_by(MoodDiary.created_at).all()
    labels = [r.created_at.strftime("%m-%d") for r in rows]
    vals = [r.mood for r in rows]
    # 结合量表
    sc = Assessment.query.filter_by(user_id=u.id, scale_code="phq9").order_by(Assessment.created_at).all()
    return jsonify({"labels": labels, "vals": vals,
                    "phq_labels": [a.created_at.strftime("%m-%d") for a in sc],
                    "phq_vals": [a.score for a in sc]})


# ---------------- 树洞 ----------------
SENSITIVE = ["自杀", "轻生", "自残"]


@app.route("/treehole", methods=["GET", "POST"])
@login_required()
def treehole(u):
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        tags = request.form.get("tags", "").strip()
        if not title or not content:
            flash("标题和内容不能为空", "err")
        else:
            crisis = any(w in content for w in SENSITIVE)
            p = TreePost(user_id=u.id, nickname="匿名同学", title=title,
                         content=content, tags=tags, crisis_flag=crisis)
            db.session.add(p)
            if crisis:
                db.session.add(Alert(user_id=u.id, source="treehole", content=content[:200],
                                    trigger="树洞敏感词", level="high"))
            db.session.commit()
            flash("已发布，谢谢你愿意说出来", "ok")
        return redirect(url_for("treehole"))
    posts = TreePost.query.order_by(TreePost.likes.desc()).all()
    return render_template("treehole.html", u=u, posts=posts)


@app.route("/treehole/<int:pid>", methods=["GET", "POST"])
@login_required()
def treehole_detail(u, pid):
    p = db.session.get(TreePost, pid)
    if not p:
        return redirect(url_for("treehole"))
    if request.method == "POST":
        c = TreeComment(post_id=pid, nickname="匿名同学",
                        content=request.form.get("content", "").strip())
        db.session.add(c)
        db.session.commit()
        return redirect(url_for("treehole_detail", pid=pid))
    comments = TreeComment.query.filter_by(post_id=pid).order_by(TreeComment.id).all()
    return render_template("detail.html", u=u, p=p, comments=comments)


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
    counselors = User.query.filter_by(role="counselor").all()
    infos = {c.id: Counselor.query.filter_by(user_id=c.id).first() for c in counselors}
    if request.method == "POST":
        cid = request.form.get("counselor_id", type=int)
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
    names = {c.id: c.real_name or c.username for c in User.query.filter(User.role == "counselor").all()}
    return render_template("my_booking.html", u=u, rows=rows, names=names)


# ---------------- 心理成长（科普/视频/书单） ----------------
@app.route("/learn")
@app.route("/learn/<tab>")
@login_required()
def learn(u, tab="article"):
    rows = Resource.query.filter_by(kind=tab).order_by(Resource.created_at.desc()).all()
    return render_template("learn.html", u=u, rows=rows, tab=tab)


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
    return render_template("teacher_home.html", u=u)


@app.route("/dash")
@login_required(role="counselor")
def dash(u):
    return render_template("dash.html", u=u)


@app.route("/api/dash/overview")
@login_required(role="counselor")
def dash_overview(u):
    total = User.query.filter_by(role="student").count()
    open_alerts = Alert.query.filter_by(status="open").count()
    recent = Assessment.query.order_by(Assessment.created_at.desc()).limit(20).all()
    # 近30天有测评的学生数
    thirty = datetime.now() - timedelta(days=30)
    active = Assessment.query.filter(Assessment.created_at >= thirty).with_entities(
        Assessment.user_id).distinct().count()
    # 各量表得分分布（仅最近一次）
    latest_by_scale = {}
    for a in Assessment.query.order_by(Assessment.created_at.desc()).all():
        latest_by_scale.setdefault(a.scale_code, []).append(a.score)
    days, acounts = [], []
    for i in range(6, -1, -1):
        d = (datetime.now() - timedelta(days=i)).date()
        days.append(d.strftime("%m-%d"))
        acounts.append(Alert.query.filter(db.func.date(Alert.created_at) == d).count())
    return jsonify({
        "total": total, "open": open_alerts, "active": active,
        "days": days, "acounts": acounts,
        "latest": [{"scale": a.scale_code, "score": a.score, "level": a.level,
                    "user": (db.session.get(User, a.user_id).real_name or '')} for a in recent],
        "by_scale": latest_by_scale,
    })


@app.route("/alerts")
@login_required(role="counselor")
def alerts(u):
    rows = Alert.query.order_by(Alert.status == "open", Alert.created_at.desc()).all()
    users = {x.id: x.real_name or x.username for x in User.query.all()}
    return render_template("alerts.html", u=u, rows=rows, users=users)


@app.route("/alerts/<int:aid>/handle", methods=["POST"])
@login_required(role="counselor")
def alert_handle(u, aid):
    a = db.session.get(Alert, aid)
    if a:
        a.status = "handled"
        a.note = request.form.get("note", "")
        a.handled_at = datetime.now()
        db.session.commit()
    return redirect(url_for("alerts"))


@app.route("/manage_booking")
@login_required(role="counselor")
def manage_booking(u):
    rows = Appointment.query.filter_by(counselor_id=u.id).order_by(Appointment.created_at.desc()).all()
    users = {x.id: x for x in User.query.all()}
    return render_template("manage_booking.html", u=u, rows=rows, users=users)


@app.route("/manage_booking/<int:aid>/<action>")
@login_required(role="counselor")
def manage_booking_action(u, aid, action):
    a = db.session.get(Appointment, aid)
    if a and a.counselor_id == u.id and action in ("confirmed", "done", "cancelled"):
        a.status = action
        db.session.commit()
    return redirect(url_for("manage_booking"))


# ---------------- 启动 ----------------
def init_db():
    db.create_all()


if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(host="127.0.0.1", port=5000, debug=False)
