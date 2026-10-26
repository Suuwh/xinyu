# 心屿 · AI校园心理健康护航平台

## 一、项目简介

面向高校心理咨询中心的"AI心理陪伴 + 标准化测评 + 匿名树洞 + 危机预警闭环 + 咨询师工作台"一体化Web系统，解决高校"心理咨询师不足、学生有情绪问题不敢开口、危机事件发现滞后"的现实痛点。

核心创新点：**AI对话中的情绪识别与高危信号检测 → 自动生成预警工单 → 咨询师在工作台处理闭环**。

## 二、功能模块

| 角色  | 功能                                                                        |
| --- | ------------------------------------------------------------------------- |
| 学生  | AI倾诉对话（多轮、情绪识别、危机话术）、PHQ-9/GAD-7量表测评与结果解读、匿名树洞（发帖/回应/点赞）、预约咨询、心理科普、测评历史曲线 |
| 咨询师 | 数据看板（PHQ得分分布、7日预警趋势、核心指标）、预警工单处理、预约确认管理                                   |

## 三、技术栈与数据库切换

- 后端：Python 3.13 + Flask 3.x + Flask-SQLAlchemy
- 前端：Jinja2模板 + 原生JS + ECharts（本地引入，离线可用）
- AI引擎：`engine.py` 词典法情绪识别 + 危机词库 + 9套专业量表应答（本地规则引擎，预留大模型API接口）

**数据库：默认 SQLite**

如需切换到 MySQL（生产/答辩展示）：

```bash
pip install pymysql
# Windows PowerShell：
$env:DATABASE_URL="mysql+pymysql://root:你的MySQL密码@127.0.0.1:3306/xinyu?charset=utf8mb4"
python seed.py    # 首次在MySQL建表并写入演示数据
python app.py
```

## 四、快速启动

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 初始化数据库并写入演示数据
python seed.py

# 3. 启动（默认 http://127.0.0.1:5000）
python app.py
```

## 五、演示账号

| 角色  | 账号                             | 密码     |
| --- | ------------------------------ | ------ |
| 学生  | student1 / student2 / student3 | 123456 |
| 咨询师 | counselor                      | 123456 |

## 六、目录结构

```
xinyu/
├── app.py            # Flask主应用与全部路由
├── models.py         # SQLAlchemy数据模型
├── engine.py         # 本地AI引擎：情绪识别/危机检测/量表/RAG应答
├── seed.py           # 演示数据一键生成
├── requirements.txt
├── templates/        # 14个页面模板
└── static/
    ├── css/style.css
    └── js/           # chat.js + echarts.min.js
```

## 七、说明

本项目为教学竞赛演示作品，心理量表结果不构成医疗诊断；危机热线仅为演示数据。
