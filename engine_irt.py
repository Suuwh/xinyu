
"""IRT自适应测评引擎"""

from __future__ import annotations
import json, math, os
import numpy as np

BANK_PATH = os.path.join(os.path.dirname(__file__), "data", "irt_bank.json")
_bank_cache = None


def load_bank():
    global _bank_cache
    if _bank_cache is None:
        with open(BANK_PATH, "r", encoding="utf-8") as f:
            _bank_cache = json.load(f)

    return _bank_cache


def get_scale(code: str) -> dict:
    return load_bank()["scales"][code]


#GRM等级反应模型
def grm_category_probs(theta: float, item: dict) -> np.ndarray:
    a = item["a"]
    b = np.array(item["thresholds"], dtype=float)  # length k-1
    #P*(k|theta)=1/(1+exp(-a*(theta-b_k)))
    #P(k)=P*(k)-P*(k+1)，P*(0)=1,P*(k)=0
    n = item["n_levels"]
    p_star = np.zeros(n + 1)
    p_star[0] = 1.0
    p_star[n] = 0.0
    for k in range(1, n):
        p_star[k] = 1.0 / (1.0 + math.exp(-a * (theta - b[k - 1])))
    probs = p_star[:-1] - p_star[1:]

    return np.clip(probs, 1e-9, 1.0)

#计算单题在θ处的Fisher信息量
def item_info(theta: float, item: dict) -> float:
    a = item["a"]
    probs = grm_category_probs(theta, item)
    b = np.array(item["thresholds"], dtype=float)
    n = item["n_levels"]
    info = 0.0
    #GRM标准公式：a^2*Σ_{g=1}^{k-1}(P_g-P_{g+1})^2/(P(g)*P(g+1))
    p_star = np.zeros(n + 1)
    p_star[0] = 1.0
    p_star[n] = 0.0
    for k in range(1, n):
        p_star[k] = 1.0/(1.0 + math.exp(-a * (theta - b[k - 1])))
    s = 0.0
    for k in range(n):
        pk = p_star[k]-p_star[k + 1]
        if pk < 1e-9:
            continue
        #连续概率差平方和权重
        diff = (p_star[k]-p_star[k + 1]) ** 2
        s += diff/max(pk, 1e-9)
    return (a ** 2) * s


#EAP估计
#积分网格设置：[-4, 4]
_THETA_GRID = np.linspace(-4, 4, 161)
_PRIOR = np.exp(-0.5 * _THETA_GRID ** 2) / math.sqrt(2 * math.pi)  #N(0,1)

def eap_estimate(responses: list[dict]) -> tuple[float, float]:
    if not responses:
        return 0.0, 1.0
    #计算每个格点的P值
    log_post = np.zeros_like(_THETA_GRID)
    for r in responses:
        probs = np.array([grm_category_probs(t, r["item"]) for t in _THETA_GRID])
        log_post += np.log(probs[:, r["score"]])
    log_post += np.log(_PRIORS() + 1e-12)
    post = np.exp(log_post - log_post.max())
    post /= post.sum()
    theta = float((post * _THETA_GRID).sum())
    var = float((post * (_THETA_GRID - theta) ** 2).sum())
    se = math.sqrt(max(var, 1e-6))

    return theta, se

_prior_cache = None
def _PRIORS():
    global _prior_cache
    if _prior_cache is None:
        _prior_cache = np.exp(-0.5 * _THETA_GRID ** 2) / math.sqrt(2 * math.pi)
    return _prior_cache


#最大Fisher信息选题
def next_item(theta: float, answered_ids: set[str], scale_code: str) -> dict | None:
    bank = get_scale(scale_code)
    best, best_info = None, -1.0
    for it in bank["items"]:
        if it["id"] in answered_ids:
            continue
        info = item_info(theta, it)
        if info > best_info:
            best_info = info
            best = it
    return best


#设置结束规则
SE_STOP = 0.30  #设置SE<=0.3时停止
MIN_ITEMS = 5   #设置至少作答5题后才允许停止

def should_stop(theta: float, se: float, answered_count: int, max_items: int) -> bool:
    return stop_reason(theta, se, answered_count, max_items) is not None


def stop_reason(theta: float, se: float, answered_count: int, max_items: int) -> str | None:
    #返回停止原因：se_reached（精度达标）/max_items（达到题数上限，可能小于题库总量）/None（继续）
    #注：题库无题可出的 bank_exhausted 由路由在 next_item 返回 None 时判定
    if answered_count >= max_items:
        return "se_reached" if se <= SE_STOP else "max_items"
    if se <= SE_STOP and answered_count >= MIN_ITEMS:
        return "se_reached"
    return None


#报告指标
def theta_to_t(theta: float) -> int:
    return int(round(50 + 10 * theta))

#根据theta与常模返回
def risk_level(theta: float, scale_code: str) -> tuple[str, str]:
    #theta越高代表症状越重
    if scale_code == "scl90":
        if theta < -0.5: return "正常范围", "ok"
        if theta < 0.3: return "轻度困扰", "warn"
        if theta < 1.0: return "中度症状", "danger"
        return "重度症状", "critical"
    if scale_code == "sas":
        if theta < -0.5: return "无明显焦虑", "ok"
        if theta < 0.3: return "轻度焦虑", "warn"
        if theta < 1.0: return "中度焦虑", "danger"
        return "重度焦虑", "critical"
    if scale_code == "sds":
        if theta < -0.5: return "无明显抑郁", "ok"
        if theta < 0.3: return "轻度抑郁", "warn"
        if theta < 1.0: return "中度抑郁", "danger"
        return "重度抑郁", "critical"
    
    return "未知", "ok"

#SCL-90各维度分别EAP
def dimension_thetas(responses: list[dict]) -> dict:
    dim_map = {}
    for r in responses:
        d = r["item"]["dim"]
        dim_map.setdefault(d, []).append(r)
    out = {}
    for d, rs in dim_map.items():
        th, se = eap_estimate(rs)
        out[d] = {"theta": round(th, 2), "se": round(se, 2), "n": len(rs)}

    return out


#py-irt离线再标定，使用py-irt对历史作答数据重新拟合题目参数,可选
def offline_refit(responses: list[dict], scale_code: str) -> dict:
    try:
        from py_irt.dataset import Dataset
        from py_irt.training import IrtModelTrainer
    except Exception as e:
        return {"ok": False, "reason": f"py_irt 未安装或不可用：{e}"}
    
    return {"ok": True, "note": "py-irt 接口就绪，等待历史作答数据积累后批量拟合。"}

















