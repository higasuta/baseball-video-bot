import sys
# 1行目からリアルタイムでログを出力
print("🚀 プレイボール速報・診断モード起動（全タイトルをチェックします）...")
sys.stdout.flush()

import requests
import datetime
import os
import time
import subprocess
from google import genai
import json
import re

# ==========================================
# 設定・環境変数
# ==========================================
INSTA_ID = os.getenv('INSTA_BUSINESS_ID')
ACCESS_TOKEN = os.getenv('INSTA_ACCESS_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

client = None
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)

# 判定を確実にするため小文字で定義
JPN_KEYWORDS = ["大谷翔平", "大谷", "shohei ohtani", "ohtani", "山本由伸", "山本", "yoshinobu yamamoto", "yamamoto", "佐々木朗希", "佐々木", "roki sasaki", "sasaki", "ダルビッシュ有", "ダルビッシュ", "yu darvish", "darvish", "松井裕樹", "松井", "yuki matsui", "matsui", "鈴木誠也", "鈴木", "seiya suzuki", "suzuki", "今永昇太", "今永", "shota imanaga", "imanaga", "千賀滉大", "千賀", "kodai senga", "senga", "菅野智之", "菅野", "tomoyuki sugano", "sugano", "小笠原慎之介", "小笠原", "shinnosuke ogasawara", "ogasawara", "岡本和真", "岡本", "kazuma okamoto", "okamoto", "今井達也", "今井", "tatsuya imai", "imai", "吉田正尚", "吉田", "masataka yoshida", "yoshida", "菊池雄星", "菊池", "yusei kikuchi", "kikuchi", "村上宗隆", "村上", "munetaka murakami", "murakami"]

# フィルタリングを少し緩める（検証のため）
BLACK_KEYWORDS = ["probable", "pitchers", "lineup", "interview", "press", "roster", "alignment", "statcast", "talks"]

def get_stats():
    if os.path.exists('stats.json'):
        try:
            with open('stats.json', 'r') as f: return json.load(f)
        except: pass
    return {"npb": 0, "mlb": 0}

def save_stats(stats):
    with open('stats.json', 'w') as f: json.dump(stats, f)

def get_npb_video(history):
    print("🔍 NPB探索 (NHK公式)...")
    url = "https://www3.nhk.or.jp/sports/json/pro-baseball/index.json"
    candidates = []
    try:
        res = requests.get(url, timeout=15)
        data = res.json()
        clips = data.get('clips', [])
        print(f"  [診断] NHK APIに現在存在する動画: {len(clips)}件")
        
        for clip in clips:
            title = clip.get('title', '')
            v_id = str(clip.get('id'))
            # 診断ログ
            # print(f"    - タイトル確認: {title}") 
            
            if v_id not in history:
                if any(kw in title.lower() for kw in BLACK_KEYWORDS):
                    continue
                v_url = clip.get('video_url') or f"https://www3.nhk.or.jp/sports/special/baseball/npb/videos/{v_id}"
                candidates.append({"title": title, "url": v_url, "id": v_id, "type": "npb", "source": "NHKスポーツ"})
        return candidates
    except Exception as e:
        print(f"  ⚠️ NHK APIエラー: {e}")
        return []

def get_mlb_video(history):
    print("🔍 MLB探索 (公式API)...")
    candidates = []
    # 直近3日分に広げて診断
    for day_offset in [0, 1, 2]:
        date_str = (datetime.datetime.now() - datetime.timedelta(days=day_offset)).strftime('%Y-%m-%d')
        url = f"https://statsapi.mlb.com/api/v1/schedule/games/?sportId=1&startDate={date_str}&endDate={date_str}"
        try:
            res = requests.get(url, timeout=15).json()
            games = [g for d in res.get('dates', []) for g in d.get('games', [])]
            for game in games:
                content_url = f"https://statsapi.mlb.com/api/v1/game/{game['gamePk']}/content"
                c_res = requests.get(content_url, timeout=10).json()
                items = c_res.get('highlights', {}).get('highlights', {}).get('items', [])
                
                for item in items:
                    title = item.get('headline', '')
                    v_id = str(item.get('id'))
                    
                    # 全タイトルを一度表示して、キーワードが合っているか確認する
                    if any(kw in title.lower() for kw in JPN_KEYWORDS):
                        if any(kw in title.lower() for kw in BLACK_KEYWORDS): continue
                        v_url = next((p['url'] for p in item.get('playbacks', []) if p['name'] == 'mp4Avc'), None)
                        if v_url and v_id not in history:
                            print(f"  ✅ 適合動画を発見: {title}")
                            candidates.append({"title": title, "url": v_url, "id": v_id, "type": "mlb", "source": "@MLBJapan"})
        except: continue
    return candidates

def main():
    history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    # 1. NPB探索
    npb_list = get_npb_video(history)
    # 2. MLB探索
    mlb_list = get_mlb_video(history)
    
    candidates = npb_list + mlb_list
    print(f"📊 最終結果: 投稿候補={len(candidates)}件")

    if not candidates:
        print("😴 適合する動画が1件もありませんでした。")
        print("💡 ヒント: APIには動画があっても、タイトルに日本人選手名が含まれていない可能性があります。")
        return

    # あとは通常の投稿処理（省略せずに実行）
    video = candidates[0]
    print(f"🎯 実行ターゲット: {video['title']}")
    # ... (以下、FFmpeg加工・AI解析・投稿処理が続く)
