"""本地离线RAG心理咨询模块"""

from __future__ import annotations
import os
os.environ.setdefault("HF_HOME", os.path.join(os.path.dirname(os.path.abspath(__file__)), "hf_cache"))
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
import re
import json
import pickle
import threading
from pathlib import Path
import numpy as np

BASE_DIR = Path(__file__).parent
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
VEC_CACHE = BASE_DIR / "chroma_db"
VEC_CACHE.mkdir(exist_ok=True)
MODEL_PATH = BASE_DIR / "models" / "qwen2.5-1.5b-instruct-q4_k_m.gguf"
BGE_DIR = BASE_DIR / "models" / "bge-m3"      #本地BGE-M3

#高危关键词
CRISIS_KEYWORDS = ["自杀", "轻生", "不想活", "不想活了", "不想继续", "活不下去", "活够了","割腕", "割脉", "自残", "自伤", "结束生命", 
                   "结束自己", "了结自己","跳楼", "跳下去", "服毒", "上吊", "吞药","伤害别人", "伤害他人", "想杀人", "想报复", "同归于尽",
                    "我走了", "永别", "遗书", "告别信",]

#提示词模板
SYSTEM_PROMPT = """你是"心隅"校园心理中心的陪伴式AI，正通过文字与一位遇到困扰的大学生对话。边界与风格：
你是共情的倾听者，不是医生：不做疾病诊断、不推荐药物；语气温暖真诚、像耐心的学长学姐，不说教、不评判（不说"你就是想太多""你要坚强""别人比你更惨"）。
先共情他的情绪，再依据【知识库参考】给建议。当他问"怎么办、步骤、方法、建议"时，用编号1. 2. 3. 给出2-4个具体步骤，每步写清"怎么做"（可直接照做的动作或话术），不要只给一句笼统的话。
知识库里没有直接答案时，就陪伴倾听、正常化他的感受，并建议预约学校心理咨询师面谈。
出现自伤、自杀、伤人念头时，立刻严肃表达关心、告诉他"你不是一个人"，并强烈建议立即拨打24h心理热线400-161-9995或前往心理咨询中心/医院急诊。
篇幅150-320字：需要给步骤就用编号，否则分2-3段，不要长篇大论，也不要只有一句。
【知识库参考】（仅作依据，不引用编号、不堆砌段落）{context}"""

#知识库加载与分块
def _load_chunks():
    chunks = []
    for md in sorted(KNOWLEDGE_DIR.glob("*.md")):
        topic = md.stem.split("_", 1)[-1] if "_" in md.stem else md.stem
        text = md.read_text(encoding="utf-8")
        sections = re.split(r"\n## ", text)
        for sec in sections:
            sec = sec.strip()
            if len(sec) < 40:
                continue
            chunks.append({"text": sec, "source": md.name, "topic": topic})

    return chunks


#单例
_lock = threading.Lock()
_bundle = {"embed": None, "llm": None, "emb_matrix": None,
           "chunks": None, "ready": False, "error": None}


def init_rag(verbose=True):
    with _lock:
        if _bundle["ready"]:
            return True
        try:
            from sentence_transformers import SentenceTransformer
            from llama_cpp import Llama

            if verbose:
                print("[RAG] 加载 BGE-M3 embedding ...")
            bge_source = str(BGE_DIR) if BGE_DIR.exists() else "BAAI/bge-m3"
            embed = SentenceTransformer(bge_source, device="cpu")

            chunks = _load_chunks()
            cache_file = VEC_CACHE / "kb_embeddings.pkl"

            if cache_file.exists():
                if verbose:
                    print("[RAG] 命中向量缓存 ...")
                with open(cache_file, "rb") as f:
                    cache = pickle.load(f)
                emb_matrix = cache["embeddings"]
                #校验chunk数量一致
                if len(cache["chunks"]) != len(chunks):
                    if verbose:
                        print("[RAG] 知识库已变化，重新编码 ...")
                    emb_matrix = embed.encode([c["text"] for c in chunks],
                                             normalize_embeddings=True).astype(np.float32)
                    with open(cache_file, "wb") as f:
                        pickle.dump({"chunks": chunks, "embeddings": emb_matrix}, f)
            else:
                if verbose:
                    print(f"[RAG] 首次编码 {len(chunks)} 个知识块 ...")
                emb_matrix = embed.encode([c["text"] for c in chunks],
                                         normalize_embeddings=True).astype(np.float32)
                with open(cache_file, "wb") as f:
                    pickle.dump({"chunks": chunks, "embeddings": emb_matrix}, f)

            if verbose:
                print("[RAG] 加载 Qwen2.5-1.5B GGUF (CPU) ...")
            llm = Llama(
                model_path=str(MODEL_PATH),
                n_ctx=1024,
                n_threads=4,
                n_gpu_layers=0,
                verbose=False,
            )

            _bundle.update(embed=embed, llm=llm, emb_matrix=emb_matrix,
                           chunks=chunks, ready=True, error=None)
            if verbose:
                print(f"[RAG] 就绪，知识库 {len(chunks)} 块")
            return True
        except Exception as e:
            import traceback
            _bundle["error"] = f"{e}\n{traceback.format_exc()[-500:]}"
            if verbose:
                print(f"[RAG] 初始化失败: {e}")
            return False


#高危检测
def detect_crisis(message: str) -> bool:
    for kw in CRISIS_KEYWORDS:
        if kw in message:
            return True
        
    return False


#检索
def retrieve(query: str, k: int = 3):
    if not _bundle["ready"]:
        return []
    qv = _bundle["embed"].encode([query], normalize_embeddings=True).astype(np.float32)
    #余弦相似度
    sims = (_bundle["emb_matrix"] @ qv[0]).tolist()
    #top-k索引
    ranked = sorted(range(len(sims)), key=lambda i: sims[i], reverse=True)[:k]
    return [dict(_bundle["chunks"][i], score=round(sims[i], 3)) for i in ranked]

N_CTX = 1024
MAX_OUT = 460
def est_tokens(s: str) -> int:
    if not s:
        return 0
    t = 0
    for ch in s:
        o = ord(ch)
        if (0x4E00 <= o <= 0x9FFF) or (0x3000 <= o <= 0x30FF) or (0xFF00 <= o <= 0xFFEF):
            t += 1
        elif ch.isspace():
            t += 0.3
        else:
            t += 0.36
    return int(t) + 1

PLACEHOLDER_REPLY = "本地 AI 模型尚未加载完成，请稍后再试。"


#生成回答
def chat(user_message: str, history: list | None = None) -> dict:
    if not _bundle["ready"]:
        return {"reply": PLACEHOLDER_REPLY, "ready": False,
                "crisis": False, "sources": [], "topic": ""}

    #1）高危拦截
    if detect_crisis(user_message):
        return {
            "reply": ("我看到你说了这样的话，心里一下子揪紧了——谢谢你愿意把这些说出来。""你现在一定非常非常难受，但请你一定一定先告诉自己：这不是你的错，你也不是一个人。\n\n"
                    "如果你现在有伤害自己的念头或计划，请立刻做一件事：拨打 **24 小时心理危机热线 400-161-9995**，""那边有专业的人 24 小时陪着你；或者马上去最近医院的急诊。"
                    "你也可以马上约学校心理咨询中心的面谈，我们会一直在这里接住你。"),"crisis": True,"sources": ["05_危机干预.md"],"topic": "危机干预",}

    #2）RAG检索
    hits = retrieve(user_message, k=4)

    #3) 预算组装
    in_budget = N_CTX - MAX_OUT - 30
    q = user_message
    while est_tokens(q) > 150 and len(q) > 4:
        q = q[:int(len(q) * 0.9)]
    used = est_tokens(q)
    hist = []
    h_budget = 95
    h_used = 0
    for h in reversed(history or []):
        if h.get("role") not in ("user", "assistant"):
            continue
        c = (h.get("content") or "").strip()
        if not c or c == PLACEHOLDER_REPLY:
            continue
        c = c[:130]
        ct = est_tokens(c)
        if h_used + ct > h_budget:
            continue
        hist.insert(0, {"role": h["role"], "content": c})
        h_used += ct
    used += h_used
    #system固定模板占用
    fixed_sys = SYSTEM_PROMPT.replace("{context}", "")
    used += est_tokens(fixed_sys)
    #检索上下文：逐块加入直到预算满
    ctx_budget = in_budget - used
    parts = []
    c_used = 0
    for i, h in enumerate(hits):
        piece = f"[参考{i+1}·{h.get('topic','')}]\n{h['text']}"
        pt = est_tokens(piece)
        if c_used + pt > ctx_budget:
            remain = ctx_budget - c_used
            if remain > 45:
                piece = piece[:int(remain * 1.5)]
                parts.append(piece)
            break
        parts.append(piece)
        c_used += pt
    context = "\n\n---\n\n".join(parts)
    if not context.strip():
        context = "（知识库中暂无直接相关内容，请以陪伴倾听为主。）"

    #组装messages
    sys_prompt = SYSTEM_PROMPT.format(context=context)
    messages = [{"role": "system", "content": sys_prompt}]
    messages.extend(hist)
    messages.append({"role": "user", "content": q})

    # 4) LLM生成
    llm = _bundle["llm"]
    resp = llm.create_chat_completion(
        messages=messages,
        temperature=0.7,
        top_p=0.9,
        max_tokens=460,
        repeat_penalty=1.1,
    )
    choice = resp["choices"][0]
    reply = choice["message"]["content"].strip()
    finish = choice.get("finish_reason", "")

    # 5) 若因长度被截断，自动续写一次
    if finish == "length":
        cont_msgs = [
            {"role": "system", "content": "你是心理陪伴助手。请直接接着下面这段回复的末尾继续把话说完，不要重复已有内容，不要寒暄，用中文，控制在150字以内自然收尾。"},
            {"role": "assistant", "content": reply},{"role": "user", "content": "请继续。"},]
        try:
            r2 = llm.create_chat_completion(messages=cont_msgs, temperature=0.6, top_p=0.9,max_tokens=220, repeat_penalty=1.1,)
            extra = r2["choices"][0]["message"]["content"].strip()
            #去掉续写可能重复的开头
            if extra and not extra.startswith(reply[-12:]):
                reply = reply.rstrip() + extra
        except Exception:
            pass

    return {"reply": reply,"crisis": False,"sources": list({h.get("source", "") for h in hits if h.get("source")}),
        "topic": hits[0].get("topic", "") if hits else "",}


def status():
    return {"ready": _bundle["ready"],"error": _bundle["error"],"model_path_exists": MODEL_PATH.exists(),
        "model_size_mb": round(MODEL_PATH.stat().st_size / 1024 / 1024, 1) if MODEL_PATH.exists() else 0,
        "kb_chunks": len(_bundle["chunks"]) if _bundle["chunks"] else 0,}








