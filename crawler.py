"""
独立爬虫脚本 —— 供 GitHub Actions 定时调用
输出: data/typhoon_latest.json（包含最新 3 条快讯）
"""

import os
import re
import json
import sys
import time
import traceback
from datetime import datetime, timedelta

import requests

os.environ["TZ"] = "Asia/Shanghai"
try:
    time.tzset()
except AttributeError:
    pass

URL = "https://www.nmc.cn/publish/typhoon/typhoon_new.html"
AJAX_BASE = "https://www.nmc.cn/f/rest/getContent"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/125.0.0.0 Safari/537.36"
}

MAX_RETRIES = 3
RETRY_DELAY_SEC = 10
BULLETIN_COUNT = 3  # 爬取最新 N 条快讯

def clean_html(text):
    """清洗 HTML，同时处理 &nbsp; 实体和 \\xa0 字符"""
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ")
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def extract_wind_radius(label, text):
    """提取风圈半径（七级/十级/十二级）"""
    pattern = label + r'.*?东北方向(\d+)公里.*?东南方向(\d+)公里.*?西南方向(\d+)公里.*?西北方向(\d+)公里'
    m = re.search(pattern, text, re.DOTALL)
    if m:
        return {"东北": m.group(1), "东南": m.group(2), "西南": m.group(3), "西北": m.group(4)}
    return {}

def parse_bulletin_from_text(text):
    """从清洗后的纯文本中提取单条快讯字段"""
    info = {}

    m = re.search(r"(\d{4})年总(\d+)期", text)
    if m:
        info["年份"] = m.group(1)
        info["总期数"] = m.group(2)

    m = re.search(r"中国气象局中央气象台(\d{2}月\d{2}日\d{2}时\d{2}分)", text)
    if m:
        info["发布时间"] = m.group(1)

    m = re.search(r'[\u201c"]([^\u201d\u201c"]+)[\u201d"][，,]\s*([A-Z]+)', text)
    if m:
        info["中文名"] = m.group(1).strip()
        info["英文名"] = m.group(2).strip()

    m = re.search(r"编[\s\xa0]*号[：:][\s\xa0]*(\d+)[\s\xa0]*号", text)
    if m:
        info["编号"] = m.group(1)

    m = re.search(r"中心位置[：:]\s*(.+?)强度等级", text)
    if m:
        info["中心位置"] = m.group(1).strip()

    m = re.search(r"强度等级[：:]\s*(.+?)最大风力", text)
    if m:
        info["强度等级"] = m.group(1).strip()

    m = re.search(r"最大风力[：:]\s*(.+?)中心气压", text)
    if m:
        info["最大风力"] = m.group(1).strip()

    m = re.search(r"中心气压[：:]\s*(.+?)参考位置", text)
    if m:
        info["中心气压"] = m.group(1).strip()

    m = re.search(r"参考位置[：:]\s*(.+?)(?:风圈半径|预报结论)", text)
    if m:
        info["参考位置"] = m.group(1).strip()

    m = re.search(r"预报结论[：:]\s*(.+?)(?:（下次)", text)
    if m:
        info["预报结论"] = m.group(1).strip()

    m = re.search(r"下次更新时间为(.+?)[）)]", text)
    if m:
        info["下次更新时间"] = m.group(1).strip()

    # 风圈半径
    info["七级风圈"] = extract_wind_radius("七级风圈半径", text)
    info["十级风圈"] = extract_wind_radius("十级风圈半径", text)
    info["十二级风圈"] = extract_wind_radius("十二级风圈半径", text)

    # 历史时间戳列表
    history = re.findall(r"(\d{4}/\d{2}/\d{2} \d{2}:\d{2})", text)
    info["历史快讯时间列表"] = history

    return info

def is_bulletin_valid(data):
    """验证单条快讯数据是否完整"""
    if "error" in data:
        return False
    if not data.get("中文名") or not data.get("发布时间") or not data.get("总期数"):
        return False
    return True

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

def fetch_typhoon_data(retry=0):
    """抓取最新 3 条台风快讯，失败时自动重试"""
    try:
        resp = requests.get(URL, headers=HEADERS, timeout=30)
        resp.encoding = "utf-8"
        html = resp.text
    except Exception as e:
        if retry < MAX_RETRIES - 1:
            print(f"[RETRY {retry + 1}/{MAX_RETRIES}] 请求异常: {e}，{RETRY_DELAY_SEC}s 后重试...")
            time.sleep(RETRY_DELAY_SEC)
            return fetch_typhoon_data(retry + 1)
        return {"bulletins": [], "error": str(e), "爬取时间": datetime.now().isoformat()}

    # 提取所有历史快讯 data-id
    data_ids = re.findall(r'<p class="time[^"]*"\s+data-id=([A-Za-z0-9_]+)>', html)
    if not data_ids:
        if retry < MAX_RETRIES - 1:
            print(f"[RETRY {retry + 1}/{MAX_RETRIES}] 未找到 data-id，{RETRY_DELAY_SEC}s 后重试...")
            time.sleep(RETRY_DELAY_SEC)
            return fetch_typhoon_data(retry + 1)
        return {"bulletins": [], "error": "未找到任何快讯 data-id", "爬取时间": datetime.now().isoformat()}

    # 从主页面解析第一条（最新）快讯
    text = clean_html(html)
    bulletins = []
    first = parse_bulletin_from_text(text)
    bulletins.append(first)

    # 通过 AJAX 获取第 2、3 条快讯
    for i in range(1, min(BULLETIN_COUNT, len(data_ids))):
        b = fetch_bulletin_from_ajax(data_ids[i])
        bulletins.append(b)

    # 检查最新一条是否完整，不完整则重试
    if not is_bulletin_valid(bulletins[0]) and retry < MAX_RETRIES - 1:
        missing = []
        if not bulletins[0].get("中文名"):
            missing.append("中文名")
        if not bulletins[0].get("发布时间"):
            missing.append("发布时间")
        if not bulletins[0].get("总期数"):
            missing.append("总期数")
        print(f"[RETRY {retry + 1}/{MAX_RETRIES}] 数据不完整（中文名={bulletins[0].get('中文名')}, "
              f"发布时间={bulletins[0].get('发布时间')}），{RETRY_DELAY_SEC}s 后重试...")
        time.sleep(RETRY_DELAY_SEC)
        return fetch_typhoon_data(retry + 1)

    if not is_bulletin_valid(bulletins[0]) and retry >= MAX_RETRIES - 1:
        bulletins[0]["error"] = f"重试{MAX_RETRIES}次后数据仍不完整"
        bulletins[0]["_retries"] = retry + 1

    result = {
        "bulletins": bulletins,
        "爬取时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    return result

def parse_next_update_time(next_str, now=None):
    """解析"下次更新时间"如 "9日20时30分"，返回目标时间+5分钟。
       若解析失败或目标时间在2天以前，返回 None（立即爬取）。
       若目标在当月已过去（如今天是13日目标11日），也返回 None。"""
    if not next_str:
        return None
    m = re.match(r'(\d{1,2})日(\d{1,2})时(\d{1,2})分', next_str.strip())
    if not m:
        return None
    day, hour, minute = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if now is None:
        now = datetime.now()

    target = now.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)

    if target < now - timedelta(days=2):
        return None

    if target <= now:
        return None

    target += timedelta(minutes=5)
    return target

if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(script_dir, "data")
    out_path = os.path.join(data_dir, "typhoon_latest.json")

    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            old_data = json.load(f)
        old_bulletins = old_data.get("bulletins", [])
        # 使用最新快讯的"下次更新时间"做跳过判断
        if old_bulletins and old_bulletins[0].get("下次更新时间"):
            next_target = parse_next_update_time(old_bulletins[0]["下次更新时间"])
            if next_target and datetime.now() < next_target:
                print(f"SKIP: 下次更新时间+5分钟为 {next_target.strftime('%m月%d日 %H:%M')}，"
                      f"当前时间 {datetime.now().strftime('%m月%d日 %H:%M')}，尚未到达，跳过本次爬取")
                sys.exit(0)

    os.makedirs(data_dir, exist_ok=True)

    data = fetch_typhoon_data()
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    if data.get("error") and not data.get("bulletins"):
        print(f"FAIL: {data['error']}", file=sys.stderr)
        sys.exit(1)
    else:
        bulletins = data.get("bulletins", [])
        if bulletins:
            b0 = bulletins[0]
            names = ", ".join([b.get("中文名", "?") for b in bulletins[:3] if b.get("中文名")])
            print(f"OK: 共 {len(bulletins)} 条快讯 [{names}] → {out_path}")
        else:
            print(f"FAIL: 无快讯数据 → {out_path}", file=sys.stderr)
            sys.exit(1)
