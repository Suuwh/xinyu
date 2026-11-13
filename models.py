"""数据模型"""

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(16), default="student")   #student/counselor
    real_name = db.Column(db.String(64), default="")
    gender = db.Column(db.String(8), default="")
    grade = db.Column(db.String(32), default="")
    major = db.Column(db.String(64), default="")
    phone = db.Column(db.String(32), default="")
    avatar = db.Column(db.String(16), default="🌻")
    avatar_type = db.Column(db.String(16), default="emoji")   #emoji/upload
    avatar_file = db.Column(db.String(128), default="")       #本地上传头像文件名
    profile_completed = db.Column(db.Boolean, default=False)  #首次登录是否已完成基本信息
    #咨询师资质认证
    qualification_no = db.Column(db.String(64), default="")   # 注册系统编号/证书编号
    qualification_verified = db.Column(db.Boolean, default=False)
    #学籍信息
    student_id = db.Column(db.String(32), default="")
    school = db.Column(db.String(128), default="")
    college = db.Column(db.String(128), default="")
    class_name = db.Column(db.String(64), default="")
    enrollment_year = db.Column(db.String(8), default="")
    education_level = db.Column(db.String(32), default="")
    student_status = db.Column(db.String(32), default="")
    #教职工信息
    employee_id = db.Column(db.String(32), default="")
    teacher_title = db.Column(db.String(64), default="")
    department = db.Column(db.String(128), default="")
    qualification = db.Column(db.String(256), default="")
    intro = db.Column(db.String(512), default="")
    created_at = db.Column(db.DateTime, default=datetime.now)

    def set_password(self, pwd):
        self.password_hash = generate_password_hash(pwd)

    def check_password(self, pwd):
        return check_password_hash(self.password_hash, pwd)


class Counselor(db.Model):
    __tablename__ = "counselors"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    title = db.Column(db.String(64), default="心理咨询师")
    specialty = db.Column(db.String(256), default="")
    bio = db.Column(db.String(512), default="")
    location = db.Column(db.String(128), default="")
    avatar = db.Column(db.String(8), default="🧑‍🏫")
    rating = db.Column(db.Float, default=4.9)
    is_pausing = db.Column(db.Boolean, default=False)   #暂停预约：学生端不再显示该教师、不可预约


#心理量表定义
class Scale(db.Model):
    __tablename__ = "scales"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), unique=True)   #phq9/gad7
    name = db.Column(db.String(64))
    desc = db.Column(db.String(256))
    questions = db.Column(db.Text)  
    options = db.Column(db.Text)     


class Assessment(db.Model):
    __tablename__ = "assessments"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    scale_code = db.Column(db.String(32))
    answers = db.Column(db.Text)                      
    score = db.Column(db.Integer, default=0)
    level = db.Column(db.String(32), default="")
    advice = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.now)


class ChatSession(db.Model):
    __tablename__ = "chat_sessions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    title = db.Column(db.String(128), default="新对话")
    created_at = db.Column(db.DateTime, default=datetime.now)
    last_at = db.Column(db.DateTime, default=datetime.now)


class ChatMessage(db.Model):
    __tablename__ = "chat_messages"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("chat_sessions.id"))
    role = db.Column(db.String(16))      #user/assistant
    content = db.Column(db.Text)
    emotion = db.Column(db.String(32), default="")
    risk = db.Column(db.String(16), default="none")
    created_at = db.Column(db.DateTime, default=datetime.now)


class Alert(db.Model):
    __tablename__ = "alerts"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    source = db.Column(db.String(16), default="chat")    #chat/treehole/assessment
    content = db.Column(db.Text)
    trigger = db.Column(db.String(128), default="")
    level = db.Column(db.String(16), default="high")   #high/medium
    status = db.Column(db.String(16), default="open")   #open/handled
    note = db.Column(db.String(256), default="")
    created_at = db.Column(db.DateTime, default=datetime.now)
    handled_at = db.Column(db.DateTime, nullable=True)


class TreePost(db.Model):
    __tablename__ = "tree_posts"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    nickname = db.Column(db.String(64), default="匿名同学")
    title = db.Column(db.String(128))
    content = db.Column(db.Text)
    tags = db.Column(db.String(128), default="")
    likes = db.Column(db.Integer, default=0)
    media_kind = db.Column(db.String(16), default="")   #image/audio/video
    media_url = db.Column(db.String(256), default="")   
    crisis_flag = db.Column(db.Boolean, default=False)
    hidden = db.Column(db.Boolean, default=False, server_default="0")    #学生端仅自己可见
    created_at = db.Column(db.DateTime, default=datetime.now)


class TreeComment(db.Model):
    __tablename__ = "tree_comments"
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("tree_posts.id"))
    nickname = db.Column(db.String(64), default="匿名同学")
    content = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)

class Appointment(db.Model):
    __tablename__ = "appointments"
    id = db.Column(db.Integer, primary_key=True)
    counselor_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    date = db.Column(db.String(16))
    time_slot = db.Column(db.String(32))
    topic = db.Column(db.String(256), default="")
    status = db.Column(db.String(16), default="pending")  #pending/confirmed/done/cancelled
    created_at = db.Column(db.DateTime, default=datetime.now)


class Resource(db.Model):
    __tablename__ = "resources"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(128))
    category = db.Column(db.String(32), default="科普")
    summary = db.Column(db.String(256), default="")
    content = db.Column(db.Text, default="")
    author = db.Column(db.String(64), default="心隅心理中心")
    source = db.Column(db.String(128), default="")
    url = db.Column(db.String(256), default="")    #视频/书籍的外部观看或检索链接
    cover = db.Column(db.String(256), default="")     #书籍封面图片
    kind = db.Column(db.String(16), default="article")  #article/video/book
    created_at = db.Column(db.DateTime, default=datetime.now)

#学生心情记录
class MoodDiary(db.Model):
    __tablename__ = "mood_diary"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    mood = db.Column(db.Integer, default=0)        #-5 ~ +5
    note = db.Column(db.String(256), default="")
    created_at = db.Column(db.DateTime, default=datetime.now)


#IRT自适应测评记录
class IRTTest(db.Model):
    __tablename__ = "irt_tests"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    scale_code = db.Column(db.String(16))           #scl90/sas/sds
    theta = db.Column(db.Float, default=0.0)       #最终潜变量估计
    se = db.Column(db.Float, default=1.0)         #测量标准误
    t_score = db.Column(db.Integer, default=50)    #T分
    level = db.Column(db.String(32), default="")   #风险等级
    n_items = db.Column(db.Integer, default=0)      #实际作答题数
    responses = db.Column(db.Text, default="")      
    dims = db.Column(db.Text, default="")         
    created_at = db.Column(db.DateTime, default=datetime.now)

#本地RAG咨询会话
class RAGSession(db.Model):
    __tablename__ = "rag_sessions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    title = db.Column(db.String(128), default="新对话")
    created_at = db.Column(db.DateTime, default=datetime.now)
    last_at = db.Column(db.DateTime, default=datetime.now)


#本地RAG咨询消息
class RAGMessage(db.Model):
    __tablename__ = "rag_messages"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("rag_sessions.id"))
    role = db.Column(db.String(16))                 #user/assistant
    content = db.Column(db.Text)
    crisis = db.Column(db.Boolean, default=False)   #是否高危回复
    sources = db.Column(db.String(256), default="")   #引用知识库
    emotion = db.Column(db.Text, default="")        #本条用户消息的情绪占比json
    created_at = db.Column(db.DateTime, default=datetime.now)


#文本情绪筛查记录（脱敏存储）
class EmotionScreenLog(db.Model):
    __tablename__ = "emotion_screen_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    session_id = db.Column(db.Integer, nullable=True)
    masked_text = db.Column(db.String(128), default="")   #脱敏后的文本片段
    risk_level = db.Column(db.String(16), default="safe")  #high/watch/safe
    risk_score = db.Column(db.Float, default=0.0)
    dominant_emotion = db.Column(db.String(16), default="")
    emotions = db.Column(db.Text, default="")             #六类情绪占比json
    crisis_labels = db.Column(db.String(128), default="")
    by_keyword = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)





    
