"""
BERT文本情绪识别与心理危机筛查模块
对学生输入文本做两路并行推理：
1、情绪多分类：XLM-RoBERTa情绪模型输出11类概率，结合自定义心理情绪权重与关键词规则，归并为平静、喜悦、焦虑、低落、愤怒、恐惧、压力过载七类；
2、危机风险分类：PsyGUARD细粒度模型输出11类，归并为高危、关注、正常，并用关键词规则二次校验、兜底。
全程本地CPU推理，只做风险筛查，不做心理诊断。
"""

from __future__ import annotations
import os
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional, Union

import torch
from torch import nn
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    BertConfig,
    BertTokenizer,
    BertModel,
    BertPreTrainedModel,
)
from transformers.modeling_outputs import SequenceClassifierOutput

BASE_DIR = Path(__file__).parent
RULES_PATH = BASE_DIR / "data" / "emotion_rules.json"
HOTLINE = "400-161-9995"


#PsyGUARD分类头，与训练时结构保持一致
class _CrisisHead(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.dense = nn.Linear(config.hidden_size, config.hidden_size)
        self.dropout = nn.Dropout(config.hidden_dropout_prob)
        self.out_proj = nn.Linear(config.hidden_size, config.num_labels)

    def forward(self, features):
        x = features[:, 0, :]
        x = self.dropout(x)
        x = self.dense(x)
        x = torch.tanh(x)
        x = self.dropout(x)
        x = self.out_proj(x)
        return x


class _CrisisModel(BertPreTrainedModel):
    def __init__(self, config):
        super().__init__(config)
        self.num_labels = config.num_labels
        self.roberta = BertModel(config)
        self.classifier = _CrisisHead(config)
        self.post_init()

    def forward(self, input_ids=None, attention_mask=None, token_type_ids=None, **kwargs):
        outputs = self.roberta(
            input_ids,
            attention_mask=attention_mask,
            token_type_ids=token_type_ids,
        )

        return SequenceClassifierOutput(logits=self.classifier(outputs[0]))


_bundle = {
    "emotion_model": None,
    "emotion_tok": None,
    "crisis_model": None,
    "crisis_tok": None,
    "rules": None,
    "ready": False,
    "error": None,
}
_lock = threading.Lock()


def init_emotion_screen(verbose: bool = True) -> bool:
    with _lock:
        if _bundle["ready"]:
            return True
        try:
            rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))

            #情绪模型
            emo_dir = str(BASE_DIR / rules["emotion_model"]["path"])
            emo_tok = AutoTokenizer.from_pretrained(emo_dir)
            #FP16加载，压缩CPU内存占用，避免与RAG多模型共存时提交内存耗尽触发原生崩溃
            emo_model = AutoModelForSequenceClassification.from_pretrained(
                emo_dir, dtype=torch.float16
            )
            emo_model.eval()

            #危机模型
            cri_dir = str(BASE_DIR / rules["crisis_model"]["path"])
            cri_cfg = BertConfig.from_pretrained(
                cri_dir,
                num_labels=11,
                problem_type="multi_label_classification",
            )
            cri_tok = BertTokenizer.from_pretrained(cri_dir)
            bin_path = str(Path(cri_dir) / "pytorch_model.bin")
            #危机模型为自定义结构，先实例化再转FP16，并把权重张量转半精度后载入
            _ckpt = torch.load(bin_path, map_location="cpu")
            _ckpt = {k: v.half() for k, v in _ckpt.items()}
            cri_model = _CrisisModel(cri_cfg).half()
            cri_model.load_state_dict(_ckpt, strict=False)
            cri_model.eval()

            _bundle.update(
                emotion_model=emo_model,
                emotion_tok=emo_tok,
                crisis_model=cri_model,
                crisis_tok=cri_tok,
                rules=rules,
                ready=True,
                error=None,
            )
            if verbose:
                print("[情绪筛查] 模型加载完成")
            return True
        except Exception as e:
            import traceback
            _bundle["error"] = f"{e}\n{traceback.format_exc()[-400:]}"
            if verbose:
                print(f"[情绪筛查] 初始化失败: {e}")
            return False


def _count_hits(text: str, keywords) -> int:
    return sum(1 for kw in keywords if kw and kw in text)


def _has_negation(text: str, negations) -> bool:
    return any(ng in text for ng in negations)


def _count_hits_skip_negated(text: str, keywords, neg_chars) -> int:
    """统计正向词命中，剔除被否定前缀(不/没/无)紧邻修饰的情况，如"不开心"。"""
    hits = 0
    for kw in keywords:
        if not kw:
            continue
        start = 0
        while True:
            pos = text.find(kw, start)
            if pos < 0:
                break
            prev = text[pos - 1] if pos > 0 else ""
            if prev not in neg_chars:
                hits += 1
            start = pos + len(kw)
    return hits


def _emotion_forward(text: str):
    rules = _bundle["rules"]
    em = rules["emotion_model"]
    tok = _bundle["emotion_tok"]
    model = _bundle["emotion_model"]
    inputs = tok(
        text,
        return_tensors="pt",
        truncation=True,
        max_length=em.get("max_length", 256),
    )
    with torch.no_grad():
        logits = model(**inputs).logits
    return torch.sigmoid(logits)[0].tolist()


def _crisis_forward(text: str):
    rules = _bundle["rules"]
    cm = rules["crisis_model"]
    tok = _bundle["crisis_tok"]
    model = _bundle["crisis_model"]
    inputs = tok(
        text,
        return_tensors="pt",
        truncation=True,
        max_length=cm.get("max_length", 512),
    )
    with torch.no_grad():
        logits = model(**inputs).logits
    return torch.sigmoid(logits)[0].tolist()


def _build_emotions(raw_prob, text: str, rules: dict):
    #把11类情绪概率归并为7类，并叠加心理关键词权重
    labels = rules["emotion_model"]["raw_labels"]
    idx = {name: i for i, name in enumerate(labels)}
    kws = rules["keywords"]
    th = rules["thresholds"]

    def p(name):
        return raw_prob[idx[name]]

    p_anger = max(p("anger"), p("disgust") * 0.7)
    p_fear = p("fear")
    p_frust = p("frustration")
    p_sad = p("sadness")
    #平静只保留中性，正向情绪(喜悦/爱/感激)单独归喜悦
    p_neutral = p("neutral")
    p_joy = max(p("joy"), p("love"), p("gratitude"))

    anxiety_hits = _count_hits(text, kws["anxiety"])
    overload_hits = _count_hits(text, kws["overload"])
    anger_hits = _count_hits(text, kws["anger"])
    sadness_hits = _count_hits(text, kws["sadness"])
    #喜悦命中需剔除"不/没/无"否定前缀，如"不开心"
    joy_hits = _count_hits_skip_negated(text, kws["joy"], kws["joy_negation"])

    scores = {name: 0.0 for name in rules["emotion_targets"]}

    #恐惧与焦虑：紧张、担忧等焦虑语境下，fear概率主要归焦虑
    if anxiety_hits:
        scores["恐惧"] += p_fear * (1.0 - th["fear_to_anxiety"])
        scores["焦虑"] += p_fear * th["fear_to_anxiety"]
    else:
        scores["恐惧"] += p_fear

    #挫败烦躁在焦虑与压力过载间分配
    if overload_hits and anxiety_hits:
        scores["焦虑"] += p_frust * 0.5
        scores["压力过载"] += p_frust * 0.5
    elif overload_hits:
        scores["压力过载"] += p_frust * 0.8
        scores["焦虑"] += p_frust * 0.2
    elif anxiety_hits:
        scores["焦虑"] += p_frust
    else:
        scores["焦虑"] += p_frust * 0.6
        scores["压力过载"] += p_frust * 0.4

    #关键词加权
    if anxiety_hits:
        scores["焦虑"] += th["anxiety_keyword_boost"]
        scores["焦虑"] += th["keyword_min_boost"] * (anxiety_hits - 1)
    if overload_hits:
        scores["压力过载"] += th["overload_keyword_boost"]
        scores["压力过载"] += th["keyword_min_boost"] * (overload_hits - 1)
    if anger_hits:
        scores["愤怒"] += p_anger + th["anger_keyword_boost"]
        scores["愤怒"] += th["keyword_min_boost"] * (anger_hits - 1)
    else:
        scores["愤怒"] += p_anger

    #低落：模型悲伤概率 + 低落关键词加权
    scores["低落"] += p_sad
    if sadness_hits:
        scores["低落"] += th["sadness_keyword_boost"]
        scores["低落"] += th["keyword_min_boost"] * (sadness_hits - 1)

    #喜悦：模型正向概率 + 喜悦关键词加权；
    #若已明确命中低落词(如"开心不起来")，压低模型正向概率且不加喜悦加权，让低落占优
    joy_damp = th["joy_neg_damp"] if sadness_hits else 1.0
    scores["喜悦"] += p_joy * joy_damp
    if joy_hits and not sadness_hits:
        scores["喜悦"] += th["joy_keyword_boost"]
        scores["喜悦"] += th["keyword_min_boost"] * (joy_hits - 1)

    #平静：出现负性情绪或喜悦信号时压低，两类及以上强压低
    neg_hits = anxiety_hits + overload_hits + anger_hits + sadness_hits
    damp = 1.0
    if neg_hits >= 2:
        damp = th["neutral_damp_strong"]
    elif neg_hits >= 1 or joy_hits:
        damp = th["neutral_damp"]
    scores["平静"] = p_neutral * damp

    #封顶
    for k in scores:
        scores[k] = min(1.0, scores[k])

    #归一化为占比
    total = sum(scores.values()) or 1.0
    ordered = rules["emotion_targets"]
    return [
        {"label": name, "score": round(scores[name] / total, 3)}
        for name in ordered
    ]


def _build_crisis(raw_prob, text: str, rules: dict):
    cm = rules["crisis_model"]
    labels = cm["raw_labels"]
    th = rules["thresholds"]
    kws = rules["keywords"]

    high_idx = cm["high_risk_index"]
    watch_idx = cm["watch_index"]

    high_probs = [(labels[i], raw_prob[i]) for i in high_idx]
    high_probs.sort(key=lambda x: -x[1])
    watch_prob = max(raw_prob[i] for i in watch_idx)
    top_label, top_prob = high_probs[0]

    #关键词二次校验
    negated = _has_negation(text, kws["negation"])
    kw_self = _count_hits(text, kws["crisis_self"])
    kw_others = _count_hits(text, kws["crisis_others"])
    kw_explore = _count_hits(text, kws["crisis_explore"])
    keyword_hit = (kw_self + kw_others + kw_explore) > 0

    keyword_forced = False
    if keyword_hit and not negated:
        #探索类归为关注，直接自伤/伤人归为高危
        if kw_self or kw_others:
            keyword_forced = True
        elif kw_explore and top_prob < th["crisis_prob_watch"]:
            keyword_forced = False

    #风险等级
    if keyword_forced and (kw_self or kw_others):
        level = "high"
    elif top_prob >= th["crisis_prob_high"]:
        level = "high"
    elif watch_prob >= th["crisis_prob_watch"] or kw_explore:
        level = "watch"
    elif top_prob >= th["crisis_prob_watch"]:
        level = "watch"
    else:
        level = "safe"

    #命中的细粒度标签
    hit_labels = [
        labels[i]
        for i in (high_idx + watch_idx)
        if raw_prob[i] >= th["crisis_prob_watch"]
    ]
    if not hit_labels and level != "safe":
        hit_labels = [top_label]
    if kw_others and not hit_labels:
        hit_labels = ["他人攻击倾向"]

    #风险分数0-1
    model_score = max(top_prob, watch_prob)
    if level == "high":
        risk_score = max(th["risk_score_high"], min(1.0, 0.55 + model_score * 0.4))
    elif level == "watch":
        risk_score = max(th["risk_score_watch"], min(0.6, 0.25 + model_score * 0.4))
    else:
        risk_score = min(th["risk_score_watch"], model_score * 0.5)

    return {
        "level": level,
        "risk_score": round(risk_score, 3),
        "labels": hit_labels,
        "keyword_forced": keyword_forced,
        "keyword_hit": keyword_hit,
    }


_LEVEL_CN = {"high": "高危", "watch": "关注", "safe": "正常"}


def screen(text: str) -> dict:
    """对单条文本做情绪与危机筛查，返回结构化结果。"""
    text = (text or "").strip()
    if not _bundle["ready"]:
        return {
            "ready": False,
            "risk_level": "safe",
            "risk_level_cn": "正常",
            "risk_score": 0.0,
            "emotions": [],
            "dominant_emotion": "",
            "crisis_labels": [],
            "crisis": False,
            "by_keyword": False,
        }
    if not text:
        return {
            "ready": True,
            "risk_level": "safe",
            "risk_level_cn": "正常",
            "risk_score": 0.0,
            "emotions": [],
            "dominant_emotion": "",
            "crisis_labels": [],
            "crisis": False,
            "by_keyword": False,
        }

    rules = _bundle["rules"]

    #两路并行推理
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_emo = pool.submit(_emotion_forward, text)
        fut_cri = pool.submit(_crisis_forward, text)
        emo_prob = fut_emo.result()
        cri_prob = fut_cri.result()

    emotions = _build_emotions(emo_prob, text, rules)
    crisis = _build_crisis(cri_prob, text, rules)

    dominant = max(emotions, key=lambda e: e["score"])["label"] if emotions else ""

    return {
        "ready": True,
        "risk_level": crisis["level"],
        "risk_level_cn": _LEVEL_CN[crisis["level"]],
        "risk_score": crisis["risk_score"],
        "emotions": emotions,
        "dominant_emotion": dominant,
        "crisis_labels": crisis["labels"],
        "crisis": crisis["level"] == "high",
        "by_keyword": crisis["keyword_forced"],
        "hotline": HOTLINE,
    }


def status() -> dict:
    return {
        "ready": _bundle["ready"],
        "error": _bundle["error"],
    }













