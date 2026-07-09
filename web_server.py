"""
中央气象台台风快讯 - 爬虫 + Web 服务
功能：
  1. 每小时自动爬取 https://www.nmc.cn/publish/typhoon/typhoon_new.html
  2. 网页端实时展示台风快讯
  3. 提供 API 接口供外部工具调用
"""

import os
import re
import json
import time
import threading
from datetime import datetime

import requests
from flask import Flask, jsonify, render_template

# ========== 配置 ==========
URL = "https://www.nmc.cn/publish/typhoon/typhoon_new.html"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DATA_FILE = os.path.join(DATA_DIR, "typhoon_latest.json")
INTERVAL_SECONDS = 3600  # 每小时爬一次
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


def fetch_typhoon_data():
    """爬取台风快讯，返回结构化 dict"""
    try:
        resp = requests.get(URL, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
        html = resp.text
    except Exception as e:
        return {"error": f"请求失败: {str(e)}", "time": datetime.now().isoformat()}

    # 先去除 HTML 标签，获得纯文本
    text = clean_html(html)

    info = {}

    # --- 期号与发布时间 ---
    m = re.search(r'(\d{4})年总(\d+)期', text)
    if m:
        info["年份"] = m.group(1)
        info["总期数"] = m.group(2)

    m = re.search(r'中国气象局中央气象台(\d{2}月\d{2}日\d{2}时\d{2}分)', text)
    if m:
        info["发布时间"] = m.group(1)

    # --- 名称（兼容中文引号" "和英文引号"）---
    m = re.search(r'[\u201c"]([^\u201d\u201c"]+)[\u201d"][，,]\s*([A-Z]+)', text)
    if m:
        info["中文名"] = m.group(1).strip()
        info["英文名"] = m.group(2).strip()

    # --- 编号 ---
    m = re.search(r'编\s*号[：:]\s*(\d+)\s*号', text)
    if m:
        info["编号"] = m.group(1)

    # --- 中心位置 ---
    m = re.search(r'中心位置[：:]\s*(.+?)强度等级', text)
    if m:
        info["中心位置"] = m.group(1).strip()

    # --- 强度等级 ---
    m = re.search(r'强度等级[：:]\s*(.+?)最大风力', text)
    if m:
        info["强度等级"] = m.group(1).strip()

    # --- 最大风力 ---
    m = re.search(r'最大风力[：:]\s*(.+?)中心气压', text)
    if m:
        info["最大风力"] = m.group(1).strip()

    # --- 中心气压 ---
    m = re.search(r'中心气压[：:]\s*(.+?)参考位置', text)
    if m:
        info["中心气压"] = m.group(1).strip()

    # --- 参考位置 ---
    m = re.search(r'参考位置[：:]\s*(.+?)风圈半径', text)
    if m:
        info["参考位置"] = m.group(1).strip()

    # --- 风圈半径 ---
    def extract_wind_radius(label, text):
        pattern = label + r'.*?东北方向(\d+)公里.*?东南方向(\d+)公里.*?西南方向(\d+)公里.*?西北方向(\d+)公里'
        m = re.search(pattern, text, re.DOTALL)
        if m:
            return {"东北": m.group(1), "东南": m.group(2), "西南": m.group(3), "西北": m.group(4)}
        return {}

    info["七级风圈"] = extract_wind_radius("七级风圈半径", text)
    info["十级风圈"] = extract_wind_radius("十级风圈半径", text)
    info["十二级风圈"] = extract_wind_radius("十二级风圈半径", text)

    # --- 预报结论 ---
    m = re.search(r'预报结论[：:]\s*(.+?)(?:（下次)', text)
    if m:
        info["预报结论"] = m.group(1).strip()

    # --- 下次更新时间 ---
    m = re.search(r'下次更新时间为(.+?)[）)]', text)
    if m:
        info["下次更新时间"] = m.group(1).strip()

    # --- 历史快讯链接（从原始 HTML 中提取时间戳）---
    history = re.findall(r'(\d{4}/\d{2}/\d{2} \d{2}:\d{2})', clean_html(html))
    info["历史快讯时间列表"] = history

    # --- 爬取时间戳 ---
    info["爬取时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return info


def save_data(data):
    """保存到 JSON 文件"""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_data():
    """从 JSON 文件读取"""
    if not os.path.exists(DATA_FILE):
        return {"状态": "尚未爬取", "提示": "等待首次爬取完成"}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def scheduled_crawl():
    """定时爬取循环（后台线程）"""
    while True:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始爬取台风快讯...")
        data = fetch_typhoon_data()
        if "error" in data:
            print(f"  爬取失败: {data['error']}")
        else:
            save_data(data)
            print(f"  爬取成功！台风: {data.get('中文名', 'N/A')}, "
                  f"强度: {data.get('强度等级', 'N/A')}")
        time.sleep(INTERVAL_SECONDS)


# ========== Flask Web 服务 ==========

app = Flask(__name__)


@app.route("/")
def index():
    """台风快讯展示页面"""
    return render_template("index.html")


@app.route("/api/typhoon", methods=["GET", "POST"])
def api_typhoon():
    """API 接口：返回台风快讯 JSON 数据"""
    data = load_data()
    return jsonify(data)


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    """手动触发一次爬取"""
    data = fetch_typhoon_data()
    if "error" not in data:
        save_data(data)
    return jsonify(data)


if __name__ == "__main__":
    # 启动时立即爬取一次
    print("=" * 50)
    print("  台风快讯监控系统启动")
    print("  API 接口: http://127.0.0.1:5000/api/typhoon")
    print("  展示页面: http://127.0.0.1:5000")
    print("=" * 50)

    initial_data = fetch_typhoon_data()
    if "error" not in initial_data:
        save_data(initial_data)
        print(f"首次爬取完成: {initial_data.get('中文名', 'N/A')} "
              f"({initial_data.get('强度等级', 'N/A')})")
    else:
        print(f"首次爬取失败: {initial_data['error']}")

    # 启动后台定时爬取线程
    t = threading.Thread(target=scheduled_crawl, daemon=True)
    t.start()

    # 启动 Flask
    app.run(host="0.0.0.0", port=5000, debug=False)
