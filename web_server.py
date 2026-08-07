"""
中央气象台台风快讯 - 爬虫 + Web 服务
功能：
  1. 定时爬取最新 3 条台风快讯
  2. 网页端实时展示多条台风快讯
  3. 提供 API 接口（全部列表 / 单条索引）供外部工具调用
"""

import os
import re
import json
import time
import threading
from datetime import datetime

import requests
from flask import Flask, jsonify, render_template, request

# ========== 配置 ==========
URL = "https://www.nmc.cn/publish/typhoon/typhoon_new.html"
AJAX_BASE = "https://www.nmc.cn/f/rest/getContent"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DATA_FILE = os.path.join(DATA_DIR, "typhoon_latest.json")
DEFAULT_INTERVAL = 300  # 默认 5 分钟后重试（无下次更新时间时使用）
BULLETIN_COUNT = 3       # 爬取最新 N 条快讯
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/125.0.0.0 Safari/537.36"
}

# ========== 爬虫模块 ==========

def clean_html(text):
    """去除HTML标签和多余空白"""
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def extract_wind_radius(label, text):
    """提取风圈半径（七级/十级/十二级）"""
    pattern = label + r'.*?东北方向(\d+)公里.*?东南方向(\d+)公里.*?西南方向(\d+)公里.*?西北方向(\d+)公里'
    m = re.search(pattern, text, re.DOTALL)
    if m:
        return {"东北": m.group(1), "东南": m.group(2), "西南": m.group(3), "西北": m.group(4)}
    return {}


def parse_bulletin_from_text(text):
    """从清洗后的纯文本中提取单条快讯所有字段"""
    info = {}

    m = re.search(r'(\d{4})年总(\d+)期', text)
    if m:
        info["年份"] = m.group(1)
        info["总期数"] = m.group(2)

    m = re.search(r'中国气象局中央气象台(\d{2}月\d{2}日\d{2}时\d{2}分)', text)
    if m:
        info["发布时间"] = m.group(1)

    m = re.search(r'[\u201c"]([^\u201d\u201c"]+)[\u201d"][，,]\s*([A-Z]+)', text)
    if m:
        info["中文名"] = m.group(1).strip()
        info["英文名"] = m.group(2).strip()

    m = re.search(r'编\s*号[：:]\s*(\d+)\s*号', text)
    if m:
        info["编号"] = m.group(1)

    m = re.search(r'中心位置[：:]\s*(.+?)强度等级', text)
    if m:
        info["中心位置"] = m.group(1).strip()

    m = re.search(r'强度等级[：:]\s*(.+?)最大风力', text)
    if m:
        info["强度等级"] = m.group(1).strip()

    m = re.search(r'最大风力[：:]\s*(.+?)中心气压', text)
    if m:
        info["最大风力"] = m.group(1).strip()

    m = re.search(r'中心气压[：:]\s*(.+?)参考位置', text)
    if m:
        info["中心气压"] = m.group(1).strip()

    m = re.search(r'参考位置[：:]\s*(.+?)风圈半径', text)
    if m:
        info["参考位置"] = m.group(1).strip()

    m = re.search(r'预报结论[：:]\s*(.+?)(?:（下次)', text)
    if m:
        info["预报结论"] = m.group(1).strip()

    m = re.search(r'下次更新时间为(.+?)[）)]', text)
    if m:
        info["下次更新时间"] = m.group(1).strip()

    # 风圈半径
    info["七级风圈"] = extract_wind_radius("七级风圈半径", text)
    info["十级风圈"] = extract_wind_radius("十级风圈半径", text)
    info["十二级风圈"] = extract_wind_radius("十二级风圈半径", text)

    # 历史时间戳列表
    history = re.findall(r'(\d{4}/\d{2}/\d{2} \d{2}:\d{2})', text)
    info["历史快讯时间列表"] = history

    return info


def fetch_bulletin_from_ajax(data_id):
    """通过 AJAX 接口获取指定 data-id 的快讯内容并解析"""
    try:
        resp = requests.get(AJAX_BASE, params={"dataId": data_id},
                           headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        text = clean_html(resp.text)
        return parse_bulletin_from_text(text)
    except Exception as e:
        return {"error": str(e), "data_id": data_id}


def fetch_typhoon_data():
    """爬取最新 BULLETIN_COUNT 条台风快讯，返回 {"bulletins": [...], "爬取时间": "..."}"""
    try:
        resp = requests.get(URL, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        html = resp.text
    except Exception as e:
        return {"bulletins": [], "error": f"请求失败: {str(e)}", "爬取时间": datetime.now().isoformat()}

    # 提取所有历史快讯 data-id
    data_ids = re.findall(r'<p class="time[^"]*"\s+data-id=([A-Za-z0-9_]+)>', html)
    if not data_ids:
        return {"bulletins": [], "error": "未找到任何快讯 data-id", "爬取时间": datetime.now().isoformat()}

    # 从主页面解析第一条（最新）快讯
    text = clean_html(html)
    bulletins = []
    bulletins.append(parse_bulletin_from_text(text))

    # 通过 AJAX 获取后续快讯
    for i in range(1, min(BULLETIN_COUNT, len(data_ids))):
        bulletins.append(fetch_bulletin_from_ajax(data_ids[i]))

    return {
        "bulletins": bulletins,
        "爬取时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }


def save_data(data):
    """保存到 JSON 文件"""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_data():
    """从 JSON 文件读取"""
    if not os.path.exists(DATA_FILE):
        return {"bulletins": [], "状态": "尚未爬取", "提示": "等待首次爬取完成"}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_next_update_time(next_str, now=None):
    """
    解析"下次更新时间"如 "9日20时30分" 或 "10日8时30分"，
    返回下一次爬取的目标 datetime（下次更新时间 + 5 分钟）。
    格式不匹配或解析失败返回 None。
    """
    if not next_str:
        return None
    import re as _re
    m = _re.match(r'(\d{1,2})日(\d{1,2})时(\d{1,2})分', next_str.strip())
    if not m:
        return None
    day, hour, minute = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if now is None:
        now = datetime.now()

    # 构建目标时间（同月同日 + 当月推断）
    target = now.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)

    # 如果目标时间已过（同一天但时刻已过，或者天数比今天小=跨月），顺延到下一月
    if target <= now:
        if now.month == 12:
            target = target.replace(year=now.year + 1, month=1)
        else:
            target = target.replace(month=now.month + 1)

    # 加 5 分钟
    from datetime import timedelta
    target += timedelta(minutes=5)
    return target


def scheduled_crawl():
    """定时爬取循环（后台线程）—— 根据最新快讯的下次更新时间动态调度"""
    while True:
        now = datetime.now()
        print(f"[{now.strftime('%H:%M:%S')}] 开始爬取台风快讯...")
        data = fetch_typhoon_data()
        bulletins = data.get("bulletins", [])
        if data.get("error") and not bulletins:
            print(f"  爬取失败: {data['error']}，{DEFAULT_INTERVAL}秒后重试")
            time.sleep(DEFAULT_INTERVAL)
            continue

        save_data(data)
        names = ", ".join([b.get("中文名", "N/A") for b in bulletins[:3] if b.get("中文名")])
        print(f"  爬取成功！{len(bulletins)} 条快讯: {names}")

        # 根据最新快讯的下次更新时间计算下一次爬取时间
        next_update = bulletins[0].get("下次更新时间") if bulletins else None
        next_target = parse_next_update_time(next_update, now) if next_update else None
        if next_target:
            wait = (next_target - datetime.now()).total_seconds()
            if wait <= 0:
                wait = DEFAULT_INTERVAL
            print(f"  下次更新时间: {next_update}, "
                  f"计划下次爬取: {next_target.strftime('%m月%d日 %H:%M')}")
        else:
            wait = DEFAULT_INTERVAL
            print(f"  无法解析下次更新时间，{DEFAULT_INTERVAL}秒后重试")

        time.sleep(wait)


# ========== Flask Web 服务 ==========

app = Flask(__name__)


@app.after_request
def add_cors_headers(response):
    """允许跨域请求（方便外部工具调用）"""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.route("/")
def index():
    """台风快讯展示页面"""
    return render_template("index.html")


@app.route("/api/typhoon", methods=["GET", "POST"])
def api_typhoon():
    """API 接口：返回全部台风快讯 JSON 数据"""
    data = load_data()
    return jsonify(data)


@app.route("/api/typhoon/<int:index>", methods=["GET"])
def api_typhoon_by_index(index):
    """API 接口：按索引返回单条快讯（0=最新, 1=第二新, 2=第三新）"""
    data = load_data()
    bulletins = data.get("bulletins", [])
    if index < 0 or index >= len(bulletins):
        return jsonify({"error": f"索引 {index} 超出范围，共 {len(bulletins)} 条快讯"}), 404
    return jsonify(bulletins[index])


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    """手动触发一次爬取"""
    data = fetch_typhoon_data()
    if not data.get("error") or data.get("bulletins"):
        save_data(data)
    return jsonify(data)


if __name__ == "__main__":
    # 启动时立即爬取一次
    print("=" * 50)
    print("  台风快讯监控系统启动（多快讯模式）")
    print("  API 接口: http://127.0.0.1:5000/api/typhoon")
    print("  单条 API: http://127.0.0.1:5000/api/typhoon/<index>")
    print("  展示页面: http://127.0.0.1:5000")
    print("=" * 50)

    initial_data = fetch_typhoon_data()
    bulletins = initial_data.get("bulletins", [])
    if bulletins:
        save_data(initial_data)
        names = ", ".join([b.get("中文名", "N/A") for b in bulletins[:3] if b.get("中文名")])
        print(f"首次爬取完成: {len(bulletins)} 条快讯 [{names}]")
    else:
        print(f"首次爬取失败: {initial_data.get('error', '未知错误')}")

    # 启动后台定时爬取线程
    t = threading.Thread(target=scheduled_crawl, daemon=True)
    t.start()

    # 启动 Flask
    app.run(host="0.0.0.0", port=5000, debug=False)
