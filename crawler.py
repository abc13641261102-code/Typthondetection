"""
独立爬虫脚本 —— 供 GitHub Actions 定时调用
输出: data/typhoon_latest.json
"""

import os
import re
import json
import sys
from datetime import datetime

import requests

URL = "https://www.nmc.cn/publish/typhoon/typhoon_new.html"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/125.0.0.0 Safari/537.36"
}


def clean_html(text):
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_typhoon_data():
    try:
        resp = requests.get(URL, headers=HEADERS, timeout=30)
        resp.encoding = "utf-8"
        html = resp.text
    except Exception as e:
        return {"error": str(e), "time": datetime.now().isoformat()}

    text = clean_html(html)
    info = {}

    # 期号
    m = re.search(r"(\d{4})年总(\d+)期", text)
    if m:
        info["年份"] = m.group(1)
        info["总期数"] = m.group(2)

    # 发布时间
    m = re.search(r"中国气象局中央气象台(\d{2}月\d{2}日\d{2}时\d{2}分)", text)
    if m:
        info["发布时间"] = m.group(1)

    # 名称（兼容中英文引号）
    m = re.search(r'[\u201c"]([^\u201d\u201c"]+)[\u201d"][，,]\s*([A-Z]+)', text)
    if m:
        info["中文名"] = m.group(1).strip()
        info["英文名"] = m.group(2).strip()

    # 编号
    m = re.search(r"编\s*号[：:]\s*(\d+)\s*号", text)
    if m:
        info["编号"] = m.group(1)

    # 中心位置
    m = re.search(r"中心位置[：:]\s*(.+?)强度等级", text)
    if m:
        info["中心位置"] = m.group(1).strip()

    # 强度等级
    m = re.search(r"强度等级[：:]\s*(.+?)最大风力", text)
    if m:
        info["强度等级"] = m.group(1).strip()

    # 最大风力
    m = re.search(r"最大风力[：:]\s*(.+?)中心气压", text)
    if m:
        info["最大风力"] = m.group(1).strip()

    # 中心气压
    m = re.search(r"中心气压[：:]\s*(.+?)参考位置", text)
    if m:
        info["中心气压"] = m.group(1).strip()

    # 参考位置
    m = re.search(r"参考位置[：:]\s*(.+?)风圈半径", text)
    if m:
        info["参考位置"] = m.group(1).strip()

    # 风圈半径
    def extract_wind_radius(label, text):
        pattern = label + r".*?东北方向(\d+)公里.*?东南方向(\d+)公里.*?西南方向(\d+)公里.*?西北方向(\d+)公里"
        m = re.search(pattern, text, re.DOTALL)
        if m:
            return {"东北": m.group(1), "东南": m.group(2), "西南": m.group(3), "西北": m.group(4)}
        return {}

    info["七级风圈"] = extract_wind_radius("七级风圈半径", text)
    info["十级风圈"] = extract_wind_radius("十级风圈半径", text)
    info["十二级风圈"] = extract_wind_radius("十二级风圈半径", text)

    # 预报结论
    m = re.search(r"预报结论[：:]\s*(.+?)(?:（下次)", text)
    if m:
        info["预报结论"] = m.group(1).strip()

    # 下次更新时间
    m = re.search(r"下次更新时间为(.+?)[）)]", text)
    if m:
        info["下次更新时间"] = m.group(1).strip()

    # 历史快讯
    history = re.findall(r"(\d{4}/\d{2}/\d{2} \d{2}:\d{2})", text)
    info["历史快讯时间列表"] = history

    info["爬取时间"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return info


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(script_dir, "data")
    os.makedirs(data_dir, exist_ok=True)

    data = fetch_typhoon_data()
    out_path = os.path.join(data_dir, "typhoon_latest.json")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    if "error" in data:
        print(f"FAIL: {data['error']}", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"OK: {data.get('中文名','?')} ({data.get('强度等级','?')}) "
              f"→ {out_path}")
