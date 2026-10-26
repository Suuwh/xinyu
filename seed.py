"""心屿 · 初始化演示数据"""
import os
import json
from datetime import datetime, timedelta
from app import app, db
from models import (User, Counselor, Assessment, ChatSession, ChatMessage,
                    TreePost, TreeComment, Appointment, Alert, Resource, MoodDiary)
import engine


def reset():
    with app.app_context():
        db.drop_all(); db.create_all()

        # --- 咨询师 ---
        c = User(username="counselor", role="counselor", real_name="李老师",
                 gender="女", employee_id="T20130518", teacher_title="副教授",
                 department="学生心理健康教育与咨询中心",
                 qualification="国家二级心理咨询师 · 中国心理学会注册心理师",
                 qualification_no="X-22-001", qualification_verified=True,
                 profile_completed=True, avatar_type="emoji",
                 intro="从事高校心理咨询12年，温暖、共情、不评判，累计接待学生2000+人次。",
                 avatar="👩‍🏫")
        c.set_password("123456"); db.session.add(c); db.session.flush()
        db.session.add(Counselor(user_id=c.id, title="国家二级心理咨询师 · 副教授",
            specialty="抑郁焦虑、学业压力、人际关系",
            bio="从事高校心理咨询12年，温暖、共情、不评判，累计接待学生2000+人次。",
            location="大学生活动中心 302 心理辅导室", avatar="👩‍🏫", rating=4.9,
            is_pausing=False));

        c2 = User(username="counselor2", role="counselor", real_name="王老师",
                  gender="男", employee_id="T20080302", teacher_title="教授",
                  department="学生心理健康教育与咨询中心",
                  qualification="临床心理学博士 · 督导师",
                  qualification_no="C-99-015", qualification_verified=True,
                  profile_completed=True, avatar_type="emoji",
                  intro="临床心理学博士，擅长认知行为疗法（CBT），风格理性而温和。",
                  avatar="👨‍🏫")
        c2.set_password("123456"); db.session.add(c2); db.session.flush()
        db.session.add(Counselor(user_id=c2.id, title="心理中心主任 · 教授",
            specialty="情绪障碍、生涯规划、家庭关系",
            bio="临床心理学博士，擅长认知行为疗法（CBT），风格理性而温和。",
            location="大学生活动中心 305 个体咨询室", avatar="👨‍🏫", rating=4.8,
            is_pausing=False));

        # --- 学生 ---
        students = []
        stu_info = [
            ("student1", "王小明", "2024010101", "🌻"),
            ("student2", "刘思雨", "2024010102", "🌙"),
            ("student3", "张浩然", "2024010103", "🐳"),
        ]
        for name, g, sid, av in stu_info:
            u = User(username=name, role="student", real_name=g, grade="2024级",
                     major="软件技术", gender="男" if name != "student2" else "女",
                     student_id=sid, school="某某职业技术学院",
                     college="信息工程学院", class_name="软件2401班",
                     enrollment_year="2024", education_level="专科（高职）",
                     student_status="在校（学籍注册）", avatar=av,
                     profile_completed=True, avatar_type="emoji")
            u.set_password("123456"); db.session.add(u); db.session.flush(); students.append(u)

        # --- 测评历史（15套方向明确量表，贴近学生画像；分数均由引擎真实计分得出）---
        POSITIVE = {"ses", "swls", "cdrisc10", "psss", "apgar"}  # 高分=健康的正向品质量表
        DIRECTIONAL = ["phq9", "gad7", "ses", "ucla", "iad", "pss10", "isi",
                       "swls", "sds", "sas", "cesd", "cdrisc10", "psss", "apgar", "tai"]
        # 整体困扰程度：王小明(轻度应考压力) / 刘思雨(中度) / 张浩然(高危)
        distress = {"王小明": 0.16, "刘思雨": 0.60, "张浩然": 0.85}

        def make_answers(code, frac, uid=0):
            s = engine.SCALES[code]
            opts = s["options"]
            vmax = max(v for _, v in opts)
            vmin = min(v for _, v in opts)
            rev = set(s.get("reverse", []))
            # 确定性逐题扰动，让二值/粗粒度量表的得分更贴近真实分布而非整体塌缩到极值
            jitter = [0.0, 0.12, -0.10, 0.06, -0.14, 0.09, -0.04, 0.13, -0.08, 0.05]
            ans = []
            for i in range(1, len(s["questions"]) + 1):
                f = (1 - frac) if code in POSITIVE else frac
                if i in rev:
                    f = 1 - f
                f += jitter[(i + uid) % len(jitter)]
                f = max(0.0, min(1.0, f))
                raw = vmin + f * (vmax - vmin)
                ans.append(min(opts, key=lambda o: abs(o[1] - raw))[1])
            return ans

        for u in students:
            frac = distress.get(u.real_name, 0.3)
            for j, code in enumerate(DIRECTIONAL):
                ans = make_answers(code, frac, uid=u.id)
                r = engine.assess_scale(code, ans)
                rec = Assessment(user_id=u.id, scale_code=code, answers=json.dumps(ans),
                                 score=r["score"], level=r["level"],
                                 advice=r.get("advice", ""),
                                 created_at=datetime.now() - timedelta(days=1 + j % 6,
                                                                       hours=j * 2 % 9))
                db.session.add(rec)
            # PHQ-9 中重度以上自动生成高危预警工单
            phq = engine.assess_scale("phq9", make_answers("phq9", frac))
            if phq["score"] >= 10:
                db.session.add(Alert(user_id=u.id, source="assessment",
                    content=f"PHQ-9={phq['score']}分（{phq['level']}）", trigger="量表高危:phq9",
                    level="high", created_at=datetime.now() - timedelta(days=2)))

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
            ("感觉撑不下去了", "最近真的好累，做什么都没意思，有时候甚至觉得活着没什么意义，不想活了。", "崩溃 绝望", students[2]),
        ]
        for t, ct, tg, u in posts_data:
            crisis = any(w in ct for w in engine.CRISIS_WORDS)
            p = TreePost(user_id=u.id, nickname="匿名同学", title=t, content=ct, tags=tg,
                         crisis_flag=crisis, likes=5+len(t), created_at=datetime.now()-timedelta(days=2))
            db.session.add(p); db.session.flush()
            db.session.add(TreeComment(post_id=p.id, nickname="匿名同学", content="抱抱你，不是一个人～"))
            if crisis:
                db.session.add(Alert(user_id=u.id, source="treehole", content=ct[:200],
                    trigger="树洞敏感词", level="high",
                    created_at=datetime.now()-timedelta(days=2)))

        # --- 预约 ---
        db.session.add(Appointment(counselor_id=c.id, student_id=students[0].id,
            date=(datetime.now()+timedelta(days=1)).strftime('%Y-%m-%d'),
            time_slot="周二 10:00-11:00", topic="考试焦虑、睡眠差", status="pending"))
        db.session.add(Appointment(counselor_id=c.id, student_id=students[1].id,
            date=(datetime.now()-timedelta(days=1)).strftime('%Y-%m-%d'),
            time_slot="周一 14:00-15:00", topic="情绪低落", status="confirmed"))

        # --- 心情日记（三个演示学生都有测试数据） ---
        seed_moods = {
            students[0]: [(3,"今天阳光不错，晒了被子"),(1,"课有点多"),(-2,"ddl要来了"),(0,"一般"),
                          (-3,"和朋友闹别扭"),(1,"吃了好吃的"),(3,"完成了作业，轻松")],
            students[1]: [(3,"和室友一起去了操场散步"),(-1,"上午有点烦，下午好了"),(2,"社团活动很开心"),
                          (-2,"想家了，打了个电话"),(4,"今天被夸了，高兴")],
            students[2]: [(-3,"考研压力好大，哭了很久"),(1,"朋友陪我聊了会天"),(-1,"复习状态一般"),
                          (2,"跑步出了一身汗，轻松多了"),(0,"平平淡淡的一天"),(3,"模考进步了，加油！")],
        }
        for stu, moods in seed_moods.items():
            for i,(m,n) in enumerate(moods):
                db.session.add(MoodDiary(user_id=stu.id, mood=m, note=n,
                    created_at=datetime.now()-timedelta(days=len(moods)-i)))

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
            ("考试周自救：压力大到学不进去怎么办？", "一份可立刻执行的减压清单。",
             "当压力大到大脑空白，先别逼自己“高效”，而是先降低生理唤醒：\n\n"
             "1. 做3轮4-7-8呼吸，让心率降下来；\n"
             "2. 把任务拆到“5分钟能开始”的颗粒度，启动比完成更重要；\n"
             "3. 用番茄钟25+5，休息时离开座位走动；\n"
             "4. 保证睡眠，熬夜换来的效率往往是负的；\n"
             "5. 允许自己“不完美地完成”，完成大于完美。",
             "心屿心理中心 李老师", "学校心理咨询中心公众号"),
            ("如何走出失恋的情绪低谷？", "给正在经历关系结束的你。",
             "失恋后的痛苦是真实的“丧失反应”，会经历否认、愤怒、讨价还价、低落、接纳几个阶段，这很正常。\n\n"
             "建议：允许自己难过但设定时限；暂时减少翻看对方动态；规律吃饭睡觉运动；把感受写下来或找人说；不要在情绪最低点做重大决定。\n\n"
             "如果持续两周以上严重失眠、无法正常生活，请寻求咨询。",
             "心屿心理中心 王老师", "学校心理咨询中心公众号"),
            ("社恐、内向、回避社交，到底有什么区别？", "厘清概念，停止给自己乱贴标签。",
             "内向是一种性格偏好，独处能充电；社交焦虑是对社交评价的过度恐惧，伴随心慌、回避；回避型则更多与依恋模式有关。\n\n"
             "内向不需要被“治疗”。但如果社交恐惧已经让你逃课、回避必要场合，可以通过认知调整和逐级暴露练习改善，咨询师能帮你。",
             "心屿心理中心 李老师", "学校心理咨询中心公众号"),
        ]
        for t, s, ct, a, src in articles:
            db.session.add(Resource(title=t, kind="article", summary=s, content=ct,
                author=a, source=src, created_at=datetime.now()-timedelta(days=1)))

        videos = [
            ("TED演讲：摆脱完美主义的三个步骤", "心理学研究者讲解如何与不完美共处。",
             "这是一段约13分钟的TED演讲，讲者结合自身经历与研究数据，分享了如何用“自我慈悲”代替“自我批评”。\n\n"
             "适合：总是苛责自己、害怕犯错、容易拖延的同学。\n"
             "观看建议：泡杯茶，安静地看，看完写下一个对自己温柔的句子。",
             "TED / B站官方中字", "TED.com",
             "https://www.ted.com/search?q=%E5%AE%8C%E7%BE%8E%E4%B8%BB%E4%B9%89"),
            ("正念呼吸引导（10分钟）", "跟着音频，做一次回到当下的呼吸练习。",
             "这是一段10分钟的正念引导音频，适合在焦虑、走神、睡前使用。\n\n"
             "用法：找一个不被打扰的地方，戴上耳机，跟着声音把注意力轻轻放在呼吸上。走神是正常的，发现走神再温柔地拉回来即可。",
             "Headspace 官方", "B站精选合集",
             "https://search.bilibili.com/all?keyword=%E6%AD%A3%E5%BF%B5%E5%91%BC%E5%90%B8%E5%BC%95%E5%AF%BC10%E5%88%86%E9%92%9F"),
            ("纪录片《我们的青春》片段", "看同龄人如何与焦虑共处。",
             "这部纪录片记录了几位中国大学生的真实一年：考研、失恋、迷茫、成长。\n\n"
             "你会发现，原来大家都在跌跌撞撞中长大。",
             "哔哩哔哩纪录片", "B站",
             "https://search.bilibili.com/all?keyword=%E7%BA%AA%E5%BD%95%E7%89%87%E6%88%91%E4%BB%AC%E7%9A%84%E9%9D%92%E6%98%A5"),
            ("渐进式肌肉放松引导（15分钟）", "从头到脚逐组放松，缓解躯体紧绷。",
             "跟着引导，依次紧绷再松开全身肌肉群。适合长期肩颈僵硬、睡前身体放松不下来的同学。\n\n"
             "建议：平躺、闭眼，效果最佳。",
             "北京大学学生心理健康教育与咨询中心", "B站官方账号",
             "https://search.bilibili.com/all?keyword=%E6%B8%90%E8%BF%9B%E5%BC%8F%E8%82%8C%E8%82%89%E6%94%BE%E6%9D%BE%E5%BC%95%E5%AF%BC"),
            ("TED-Ed：压力如何影响你的身体", "用动画讲清压力反应的生理机制。",
             "这段约5分钟的科普动画解释了短期压力如何调动身体、长期压力又如何影响免疫与睡眠（TED-Ed官方课程，Sharon Horesh Bergquist）。\n\n"
             "看完你会更理解：减压不是矫情，是对身体负责。",
             "TED-Ed", "TED.com / B站中字",
             "https://www.ted.com/talks/sharon_horesh_bergquist_how_stress_affects_your_body"),
            ("正念冥想入门：给初学者的10分钟", "零基础也能跟着做的正念练习。",
             "正念不是“什么都不想”，而是温柔地把走神的注意力一次次带回当下。\n\n"
             "适合：脑子停不下来、睡前反刍、注意力涣散的同学。",
             "Now冥想 官方", "B站精选合集",
             "https://search.bilibili.com/all?keyword=%E6%AD%A3%E5%BF%B5%E5%86%A5%E6%83%B3%E5%85%A5%E9%97%A8%E5%88%9D%E5%AD%A6%E8%80%8510%E5%88%86%E9%92%9F"),
            ("身体扫描引导（15分钟）", "从头到脚的深度放松，适合睡前。",
             "平躺闭眼，跟随引导把注意力从头顶慢慢移到脚底，觉察而不评判。\n\n"
             "长期练习有助于降低身体唤醒、改善入睡困难。",
             "壹心理 官方", "B站精选合集",
             "https://search.bilibili.com/all?keyword=%E8%BA%AB%E4%BD%93%E6%89%AB%E6%8F%8F%E6%AD%A3%E5%BF%B515%E5%88%86%E9%92%9F"),
            ("TED演讲：如何应对压力而不被压垮", "重新认识压力与身心的关系。",
             "健康心理学家凯利·麦格尼格尔结合研究指出：压力本身未必有害，“相信压力有害”的信念与身体反应同样关键（TED官方演讲）。\n\n"
             "约15分钟，提供了把压力反应重新理解为“赋能”的视角。",
             "TED / B站官方中字", "TED.com",
             "https://www.ted.com/talks/kelly_mcgonigal_how_to_make_stress_your_friend"),
            ("情绪急救：被拒绝后如何自愈", "心理学教授讲解情绪伤口的处理。",
             "盖伊·温奇用生动案例讲解被拒绝、孤独、反刍等常见心理伤口，以及像处理身体伤口一样处理情绪的方法（TED官方演讲）。\n\n"
             "约17分钟，实用且有共鸣。",
             "TED / B站官方中字", "TED.com",
             "https://www.ted.com/talks/guy_winch_why_we_all_need_to_practice_emotional_first_aid"),
        ]
        for t, s, ct, a, src, url in videos:
            db.session.add(Resource(title=t, kind="video", summary=s, content=ct,
                author=a, source=src, url=url, created_at=datetime.now()-timedelta(days=2)))

        books = [
            ("《被讨厌的勇气》", "阿德勒心理学的入门经典，对话体，好读。",
             "这本书用“青年与哲人对话”的形式，讲清了一个核心观点：人的烦恼都来自人际关系，而你随时可以改变——只要你有“被讨厌的勇气”。\n\n"
             "适合：在意别人评价、讨好型人格、总是不开心的同学。\n"
             "作者：岸见一郎 / 古贺史健。",
             "心屿心理中心 推荐", "机械工业出版社", "covers/bei-taoyan-de-yongqi.jpg"),
            ("《也许你该找个人聊聊》", "一位心理咨询师自己也去做咨询的真实故事。",
             "作者洛莉是一位心理治疗师，她自己也在咨询室里崩溃、哭泣、被治愈。\n\n"
             "读这本书，你会发现：咨询师也是普通人，心理咨询既神秘又普通，它就是两个真实的人，在一个安全的房间里，认真聊聊你的人生。",
             "心屿心理中心 推荐", "果麦文化 / 上海文化出版社", "covers/yexu-ni-gai-zhaogerenliaoliao.jpg"),
            ("《心流》", "为什么专注做一件事会让人忘记烦恼？",
             "米哈里·契克森米哈赖提出“心流”概念：当挑战与技能匹配、目标清晰、反馈即时，人会进入一种全然投入的状态，时间感消失，幸福感升起。\n\n"
             "对大学生的启发：与其刷短视频获得短暂快感，不如给自己设置一个小而清晰的任务，进入专注。",
             "心屿心理中心 推荐", "中信出版社", "covers/xinliu.jpg"),
            ("《蛤蟆先生去看心理医生》", "用童话讲透10次心理咨询的全过程。",
             "抑郁的蛤蟆先生走进咨询室，在与苍鹭咨询师的10次对话中，逐渐理解童年、情绪与自我。\n\n"
             "这本书把专业的TA沟通分析理论讲得像故事一样好读，是心理咨询入门首选。",
             "心屿心理中心 推荐", "天津人民出版社", "covers/hama-xiansheng.jpg"),
            ("《自控力》", "斯坦福大学最受欢迎的心理学课程。",
             "凯利·麦格尼格尔结合神经科学与实验，解释为什么我们会失控，以及如何不靠“硬扛”提升自控。\n\n"
             "适合：拖延、熬夜、管不住手机的同学。",
             "心屿心理中心 推荐", "文化发展出版社", "covers/zikongli.jpg"),
            ("《当下的力量》", "教你停止对过去和未来的反刍，回到当下。",
             "埃克哈特·托利指出，大部分痛苦来自大脑对过去的懊悔和对未来的焦虑，而解脱之道是把意识锚定在“此刻”。\n\n"
             "适合：容易内耗、睡前脑子停不下来的同学。",
             "心屿心理中心 推荐", "中信出版社", "covers/dangxia-de-liliang.jpg"),
            ("《非暴力沟通》", "学会好好说话，也学会听见自己和他人的需要。",
             "马歇尔·卢森堡提出“观察—感受—需要—请求”四步法，帮助我们在冲突中表达而不指责、倾听而不防备。\n\n"
             "适合：宿舍矛盾、亲密关系、家庭沟通中容易吵架或压抑的同学。",
             "心屿心理中心 推荐", "华夏出版社", "covers/fei-baoli-goutong.jpg"),
            ("《自卑与超越》", "阿德勒谈自卑如何成为成长的动力。",
             "阿德勒认为，人人都有不同程度的自卑，关键在于如何把自卑感转化为“追求优越”的行动，而非陷入退缩。\n\n"
             "适合：总是否定自己、害怕尝试的同学。",
             "心屿心理中心 推荐", "民主与建设出版社", "covers/zibei-yu-chaoyue.jpg"),
            ("《睡眠革命》", "用R90方法科学改善睡眠。",
             "尼克·利特尔黑尔斯以90分钟睡眠周期为核心，给出固定起床时间、睡眠环境、日间补觉等可执行方案。\n\n"
             "适合：熬夜、入睡困难、作息混乱的大学生。",
             "心屿心理中心 推荐", "北京联合出版公司", "covers/shuimian-geming.jpg"),
        ]
        for t, s, ct, a, src, cover in books:
            db.session.add(Resource(title=t, kind="book", summary=s, content=ct,
                author=a, source=src, cover=cover, created_at=datetime.now()-timedelta(days=3)))

        db.session.commit()
        print("✅ 演示数据已写入。账号：student1/2/3、counselor，密码 123456")


if __name__ == "__main__":
    reset()

