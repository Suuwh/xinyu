"""心屿 · 初始化演示数据"""
import os
from datetime import datetime, timedelta
from app import app, db
from models import (User, Counselor, Assessment, ChatSession, ChatMessage,
                    TreePost, TreeComment, Appointment, Alert, Resource, MoodDiary)
import engine


def reset():
    with app.app_context():
        db.drop_all(); db.create_all()

        # --- 咨询师 ---
        c = User(username="counselor", role="counselor", real_name="李老师")
        c.set_password("123456"); db.session.add(c); db.session.flush()
        db.session.add(Counselor(user_id=c.id, title="国家二级心理咨询师 · 副教授",
            specialty="抑郁焦虑、学业压力、人际关系",
            bio="从事高校心理咨询12年，温暖、共情、不评判，累计接待学生2000+人次。",
            location="大学生活动中心 302 心理辅导室", avatar="👩‍🏫", rating=4.9));

        c2 = User(username="counselor2", role="counselor", real_name="王老师")
        c2.set_password("123456"); db.session.add(c2); db.session.flush()
        db.session.add(Counselor(user_id=c2.id, title="心理中心主任 · 教授",
            specialty="情绪障碍、生涯规划、家庭关系",
            bio="临床心理学博士，擅长认知行为疗法（CBT），风格理性而温和。",
            location="大学生活动中心 305 个体咨询室", avatar="👨‍🏫", rating=4.8));

        # --- 学生 ---
        students = []
        for name, g in [("student1", "王同学"), ("student2", "刘同学"), ("student3", "张同学")]:
            u = User(username=name, role="student", real_name=g, grade="大二", major="软件工程")
            u.set_password("123456"); db.session.add(u); db.session.flush(); students.append(u)

        # --- 测评历史 ---
        phq_scores = [2, 18, 22]
        for u, sc in zip(students, phq_scores):
            a = Assessment(user_id=u.id, scale_code="phq9", answers="[]",
                           score=sc,
                           level=next((n for lo,hi,n in engine.SCALES['phq9']['levels'] if lo<=sc<=hi),''),
                           advice="", created_at=datetime.now()-timedelta(days=2))
            db.session.add(a)
            if sc >= 10:
                db.session.add(Alert(user_id=u.id, source="assessment",
                    content=f"PHQ-9={sc}分（{a.level}）", trigger="量表高危",
                    level="high", created_at=datetime.now()-timedelta(days=2)))

        # --- 聊天记录 ---
        s = ChatSession(user_id=students[0].id, title="关于期末焦虑")
        db.session.add(s); db.session.flush()
        db.session.add(ChatMessage(session_id=s.id, role="user", content="最近期末周压力大，睡不着", emotion="焦虑", risk="none"))
        db.session.add(ChatMessage(session_id=s.id, role="assistant", content="考试周压力大很正常…先做一个25分钟番茄钟试试。", emotion="焦虑", risk="none"))

        # 高危对话触发预警
        s2 = ChatSession(user_id=students[1].id, title="很难受")
        db.session.add(s2); db.session.flush()
        db.session.add(ChatMessage(session_id=s2.id, role="user", content="我不想活了，想自杀", emotion="绝望", risk="high"))
        db.session.add(Alert(user_id=students[1].id, source="chat",
            content="我不想活了，想自杀", trigger="自杀", level="high"))

        # --- 树洞 ---
        posts_data = [
            ("大三了，依旧不知道自己想干什么", "开学一个月了，看着身边人都有方向，我却每天躺平，越躺越焦虑。有没有和我一样的同学？", "焦虑 未来 迷茫", students[2]),
            ("考研复习到崩溃的瞬间", "今天做英语阅读错了一半，坐在图书馆突然就哭了。我是不是不适合考研？", "考研 压力", students[0]),
            ("想家的夜晚", "在外地上大学，每次妈妈打电话都想哭。但又不敢说，怕他们担心。", "想家 孤独", students[2]),
            ("和室友闹僵了", "因为一点小事和室友冷战一周了，每天回宿舍都像上刑。", "室友 人际", students[1]),
            ("其实我也挺优秀的", "今天被老师夸了！原来认真做一件事是真的会被看见的，分享给大家。", "正能量", students[0]),
        ]
        for t, ct, tg, u in posts_data:
            crisis = any(w in ct for w in engine.CRISIS_WORDS)
            p = TreePost(user_id=u.id, nickname="匿名同学", title=t, content=ct, tags=tg,
                         crisis_flag=crisis, likes=5+len(t), created_at=datetime.now()-timedelta(days=2))
            db.session.add(p); db.session.flush()
            db.session.add(TreeComment(post_id=p.id, nickname="匿名同学", content="抱抱你，不是一个人～"))

        # --- 预约 ---
        db.session.add(Appointment(counselor_id=c.id, student_id=students[0].id,
            date=(datetime.now()+timedelta(days=1)).strftime('%Y-%m-%d'),
            time_slot="周二 10:00-11:00", topic="考试焦虑、睡眠差", status="pending"))
        db.session.add(Appointment(counselor_id=c.id, student_id=students[1].id,
            date=(datetime.now()-timedelta(days=1)).strftime('%Y-%m-%d'),
            time_slot="周一 14:00-15:00", topic="情绪低落", status="confirmed"))

        # --- 心情日记 ---
        moods = [(3,"今天阳光不错，晒了被子"),(1,"课有点多"),(-2,"ddl要来了"),(0,"一般"),
                 (-3,"和朋友闹别扭"),(1,"吃了好吃的"),(3,"完成了作业，轻松")]
        for i,(m,n) in enumerate(moods):
            db.session.add(MoodDiary(user_id=students[0].id, mood=m, note=n,
                created_at=datetime.now()-timedelta(days=7-i)))

        # --- 心理成长内容 ---
        articles = [
            ("为什么你总是“越努力越焦虑”？", "这是一篇给完美主义者的温柔提醒。",
             "很多同学把“焦虑”当成敌人，但焦虑其实是身体在提醒你“这件事很重要”。\n\n"
             "心理学中有一个“倒U型曲线”：适度焦虑能让人表现更好，完全不焦虑反而容易拖延。问题在于，当焦虑超过某个临界点，大脑就会把“任务”当成“威胁”，出现大脑空白、逃避、刷手机等反应。\n\n"
             "三个可操作的小方法：\n"
             "1. 把“我必须做完”换成“我先做5分钟”——启动焦虑会大幅下降；\n"
             "2. 给任务写下来——写在纸上的担忧会从脑子里移出去，负担感减轻；\n"
             "3. 区分“能控制”和“不能控制”——只在能控制的那一小部分上用力。\n\n"
             "焦虑不需要被消灭，它只需要被理解。",
             "心屿心理中心 李老师", "学校心理咨询中心公众号"),
            ("睡眠不足，真的会让情绪变糟", "睡眠与情绪的科学关系。",
             "为什么熬夜之后第二天特别容易烦躁、想哭？\n\n"
             "加州大学伯克利分校的研究发现：缺眠会让大脑杏仁核（负责恐惧、愤怒）的反应增强约60%，而负责理性调控的前额叶活动下降。这意味着——你不是“想太多”，是真的“硬件”被影响了。\n\n"
             "给大学生的睡眠建议：\n"
             "· 固定起床时间比固定入睡时间更重要；\n"
             "· 睡前1小时把手机放到够不到的地方；\n"
             "· 卧室只用来睡觉，不要在床上学习；\n"
             "· 躺下20分钟睡不着就起身，做会儿单调的事再回去。",
             "心屿心理中心 李老师", "参考文献：Walker, 2017《Why We Sleep》"),
            ("和室友处不好，是我的问题吗？", "一篇关于宿舍关系的文章。",
             "宿舍矛盾几乎是每个大学生都会遇到的话题。\n\n"
             "需要先明确：宿舍冲突大多不是“谁对谁错”，而是生活习惯、边界、沟通方式的差异。\n\n"
             "可以试试：\n"
             "1. 用“我感到…”代替“你总是…”，例如“我昨晚被吵醒了，今天很困”，而不是“你怎么总是熬夜！”；\n"
             "2. 把最不能妥协的1-2条底线说清楚，其他小事放一放；\n"
             "3. 不必强求“成为朋友”，室友可以只是“住在一起的人”。\n\n"
             "如果冲突已严重影响生活，辅导员和咨询师都可以协助你。",
             "心屿心理中心 王老师", "学校心理咨询中心公众号"),
        ]
        for t, s, ct, a, src in articles:
            db.session.add(Resource(title=t, kind="article", summary=s, content=ct,
                author=a, source=src, created_at=datetime.now()-timedelta(days=1)))

        videos = [
            ("TED演讲：摆脱完美主义的三个步骤", "心理学研究者讲解如何与不完美共处。",
             "这是一段约13分钟的TED演讲，讲者结合自身经历与研究数据，分享了如何用“自我慈悲”代替“自我批评”。\n\n"
             "适合：总是苛责自己、害怕犯错、容易拖延的同学。\n"
             "观看建议：泡杯茶，安静地看，看完写下一个对自己温柔的句子。",
             "TED / B站官方中字", "TED.com"),
            ("正念呼吸引导（10分钟）", "跟着音频，做一次回到当下的呼吸练习。",
             "这是一段10分钟的正念引导音频，适合在焦虑、走神、睡前使用。\n\n"
             "用法：找一个不被打扰的地方，戴上耳机，跟着声音把注意力轻轻放在呼吸上。走神是正常的，发现走神再温柔地拉回来即可。",
             "Headspace 官方", "B站精选合集"),
            ("纪录片《我们的青春》片段", "看同龄人如何与焦虑共处。",
             "这部纪录片记录了几位中国大学生的真实一年：考研、失恋、迷茫、成长。\n\n"
             "你会发现，原来大家都在跌跌撞撞中长大。",
             "哔哩哔哩纪录片", "B站"),
        ]
        for t, s, ct, a, src in videos:
            db.session.add(Resource(title=t, kind="video", summary=s, content=ct,
                author=a, source=src, created_at=datetime.now()-timedelta(days=2)))

        books = [
            ("《被讨厌的勇气》", "阿德勒心理学的入门经典，对话体，好读。",
             "这本书用“青年与哲人对话”的形式，讲清了一个核心观点：人的烦恼都来自人际关系，而你随时可以改变——只要你有“被讨厌的勇气”。\n\n"
             "适合：在意别人评价、讨好型人格、总是不开心的同学。\n"
             "作者：岸见一郎 / 古贺史健。",
             "心屿心理中心 推荐", "机械工业出版社"),
            ("《也许你该找个人聊聊》", "一位心理咨询师自己也去做咨询的真实故事。",
             "作者洛莉是一位心理治疗师，她自己也在咨询室里崩溃、哭泣、被治愈。\n\n"
             "读这本书，你会发现：咨询师也是普通人，心理咨询既神秘又普通，它就是两个真实的人，在一个安全的房间里，认真聊聊你的人生。",
             "心屿心理中心 推荐", "果麦文化 / 上海文化出版社"),
            ("《心流》", "为什么专注做一件事会让人忘记烦恼？",
             "米哈里·契克森米哈赖提出“心流”概念：当挑战与技能匹配、目标清晰、反馈即时，人会进入一种全然投入的状态，时间感消失，幸福感升起。\n\n"
             "对大学生的启发：与其刷短视频获得短暂快感，不如给自己设置一个小而清晰的任务，进入专注。",
             "心屿心理中心 推荐", "中信出版社"),
        ]
        for t, s, ct, a, src in books:
            db.session.add(Resource(title=t, kind="book", summary=s, content=ct,
                author=a, source=src, created_at=datetime.now()-timedelta(days=3)))

        db.session.commit()
        print("✅ 演示数据已写入。账号：student1/2/3、counselor，密码 123456")


if __name__ == "__main__":
    reset()
