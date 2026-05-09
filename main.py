import sys
# リアルタイムログ出力
print("🚀 プレイボール速報・システム最終形態（日本人メジャーリーガー完全網羅版）起動...")
sys.stdout.flush()

import requests
import datetime
import os
import time
import subprocess
import google.generativeai as genai
import json
import re

# ==========================================
# 設定・環境変数の読み込み
# ==========================================
INSTA_ID = os.getenv('INSTA_BUSINESS_ID')
ACCESS_TOKEN = os.getenv('INSTA_ACCESS_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# 【完全網羅】日本人選手キーワード（1人4パターン × 15名 = 60キーワード）
JPN_KEYWORDS = [
    # ドジャース
    "大谷翔平", "大谷", "shohei ohtani", "ohtani",
    "山本由伸", "山本", "yoshinobu yamamoto", "yamamoto",
    "佐々木朗希", "佐々木", "roki sasaki", "sasaki",
    # パドレス
    "ダルビッシュ有", "ダルビッシュ", "yu darvish", "darvish",
    "松井裕樹", "松井", "yuki matsui", "matsui",
    # カブス
    "鈴木誠也", "鈴木", "seiya suzuki", "suzuki",
    "今永昇太", "今永", "shota imanaga", "imanaga",
    # メッツ
    "千賀滉大", "千賀", "kodai senga", "senga",
    # ロッキーズ
    "菅野智之", "菅野", "tomoyuki sugano", "sugano",
    # ナショナルズ
    "小笠原慎之介", "小笠原", "shinnosuke ogasawara", "ogasawara",
    # ブルージェイズ
    "岡本和真", "岡本", "kazuma okamoto", "okamoto",
    # アストロズ
    "今井達也", "今井", "tatsuya imai", "imai",
    # レッドソックス
    "吉田正尚", "吉田", "masataka yoshida", "yoshida",
    # エンゼルス
    "菊池雄星", "菊池", "yusei kikuchi", "kikuchi",
    # ホワイトソックス
    "村上宗隆", "村上", "munetaka murakami", "murakami"
]

# 排除キーワード
BLACK_KEYWORDS = ["probable", "pitchers", "lineup", "interview", "press", "availability", "roster", "update", "alignment", "summary", "preview", "warmup", "positioning", "against", "at bat", "statcast", "recap", "daily", "full highlights"]

def get_stats():
    if os.path.exists('stats.json'):
        try:
            with open('stats.json', 'r') as f: return json.load(f)
        except: pass
    return {"npb": 75, "mlb": 25}

def save_stats(stats):
    with open('stats.json', 'w') as f:
        json.dump(stats, f)

def cleanup_gemini_storage():
    try:
        for f in genai.list_files():
            genai.delete_file(f.name)
        print("🧹 AIストレージを掃除しました。")
    except: pass

def get_available_flash_model():
    try:
        model_names = [m.name for m in genai.list_models() if 'flash' in m.name]
        priority_models = ["models/gemini-flash-lite-latest", "models/gemini-2.5-flash", "models/gemini-1.5-flash"]
        for pm in priority_models:
            if pm in model_names: return pm
        return model_names[0] if model_names else "models/gemini-1.5-flash"
    except: return "models/gemini-1.5-flash"

def get_npb_candidates(history):
    candidates = []
    # ルートA: パ・リーグTV
    try:
        url = "https://pacificleague.com/video"
        cmd = ['yt-dlp', '--get-id', '--get-title', '--get-url', '--playlist-end', '5', '--no-check-certificates', '--quiet', url]
        output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=40).decode().split('\n')
        for i in range(0, len(output)-2, 3):
            title, v_id, v_url = output[i].strip(), output[i+1].strip(), output[i+2].strip()
            if v_id and v_id not in history:
                candidates.append({"title": title, "url": v_url, "id": v_id, "type": "npb", "source": "パ・リーグTV", "priority": 1})
    except: pass

    # ルートB: スポーツナビ
    try:
        url = "https://sports.yahoo.co.jp/video/list/promo/live/baseball/npb"
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        matches = re.findall(r'href="/video/player/(\d+)"', res.text)
        unique_ids = list(dict.fromkeys(matches))[:5]
        for v_id in unique_ids:
            if v_id not in history:
                v_url = f"https://sports.yahoo.co.jp/video/player/{v_id}"
                v_res = requests.get(v_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                t_match = re.search(r'<title>(.*?)</title>', v_res.text)
                title = t_match.group(1).split('-