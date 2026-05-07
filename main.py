import sys
# リアルタイムログ出力
print("🚀 プレイボール速報・システム稼働中...")
sys.stdout.flush()

import requests
import datetime
import os
import time
import subprocess
import google.generativeai as genai
import json
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

# ==========================================
# 設定・環境変数の読み込み
# ==========================================
INSTA_ID = os.getenv('INSTA_BUSINESS_ID')
ACCESS_TOKEN = os.getenv('INSTA_ACCESS_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# 日本人選手フィルター
JPN_KEYWORDS = ["大谷", "山本", "ダルビッシュ", "鈴木誠也", "吉田正尚", "今永", "松井裕樹", "千賀", "前田健太", "菊池雄星", "ohtani", "yamamoto", "imanaga", "菅野", "senga", "darvish"]

# 【超厳格】除外キーワード：これらが含まれる動画は候補から即座に外す
BLACK_KEYWORDS = [
    "probable", "pitchers", "lineup", "interview", "press", "availability", 
    "roster", "update", "alignment", "summary", "preview", "warmup", 
    "positioning", "against", "at bat", "statcast", "pre-game", "highlights of the day"
]

def get_stats():
    if os.path.exists('stats.json'):
        try:
            with open('stats.json', 'r') as f: return json.load(f)
        except: pass
    return {"npb": 7, "mlb": 3}

def save_stats(stats):
    with open('stats.json', 'w') as f:
        json.dump(stats, f)

def get_all_candidates(history, is_test_mode):
    """NPB(過去1週間)とMLBから全ての未投稿動画をリストアップする"""
    candidates = []
    
    # 1. NPBスキャン (スポナビRSS)
    print("🔍 NPBスキャン中 (スポナビRSS)...")
    one_week_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)
    rss_url = "https://sports.yahoo.co.jp/video/rss/baseball/npb"
    try:
        res = requests.get(rss_url, timeout=20)
        if res.status_code == 200:
            root = ET.fromstring(res.content)
            for item in root.findall('.//item'):
                title = item.find('title').text
                v_url = item.find('link').text
                pub_date = parsedate_to_datetime(item.find('pubDate').text)
                v_id = item.find('guid').text if item.find('guid') is not None else v_url
                
                if v_id not in history and pub_date > one_week_ago:
                    if not any(kw in title.lower() for kw in BLACK_KEYWORDS):
                        candidates.append({"title": title, "url": v_url, "id": v_id, "type": "npb", "source": "スポーツナビ"})
    except: pass

    # 2. MLBスキャン (API)
    print("🔍 MLBスキャン中 (公式API)...")
    for day_offset in range(3):
        date_str = (datetime.datetime.now() - datetime.timedelta(days=day_offset)).strftime('%Y-%m-%d')
        url = f"https://statsapi.mlb.com/api/v1/schedule/games/?sportId=1&startDate={date_str}&endDate={date_str}"
        try:
            res = requests.get(url).json()
            for date_data in res.get('dates', []):
                for game in date_data.get('games', []):
                    content = requests.get(f"https://statsapi.mlb.com/api/v1/game/{game['gamePk']}/content").json()
                    for item in content.get('highlights', {}).get('highlights', {}).get('items', []):
                        title = item.get('headline', '')
                        v_id = str(item.get('id'))
                        v_url = next((p['url'] for p in item.get('playbacks', []) if p['name'] == 'mp4Avc'), None)
                        
                        if v_url and v_id not in history:
                            if any(kw in title.lower() for kw in BLACK_KEYWORDS): continue
                            if any(kw in title.lower() for kw in JPN_KEYWORDS) or is_test_mode:
                                candidates.append({"title": title, "url": v_url, "id": v_id, "type": "mlb", "source": "@MLBJapan"})
        except: continue
    
    return candidates

def analyze_video_with_ai(video_path, title, source_account):
    """Geminiによる解析"""
    print(f"🧠 AIによる動画解析中 (Gemini)...")
    try:
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING": time.sleep(2); video_file = genai.get_file(video_file.name)
        
        # 【修正】モデル名を latest に変更して404を回避
        model = genai.GenerativeModel("gemini-1.5-flash-latest")
        
        prompt = f"""
        野球動画（タイトル：{title}）を解析し、以下の形式で出力せよ。
        
        【重要】
        もし動画が実際のプレー（投球、打撃、守備、走塁）を含まない場合、CAPTION:SKIP と出力せよ。

        START:[秒]
        CAPTION:[内容]

        【キャプション構成】
        ・一段目：【 】で囲った鋭い2ch風の見出し。皮肉や驚き、分析を交えろ。
        ・二段目：ニュース要約（2〜3行）。
        ・三段目：アナリスト視点からの皮肉のきいた鋭い所感。
        ・ネットスラング（ワロタ、www等）は厳禁。標準語の「だ・である」調を徹底。
        ・タグ25〜29個（中黒削除）。最後に 引用：{source_account} を記載。
        """
        
        response = model.generate_content([prompt, video_file])
        res_text = response.text
        genai.delete_file(video_file.name)
        
        if "SKIP" in res_text: return None, "SKIP"

        start_match = re.search(r"START:(\d+)", res_text); start_sec = int(start_match.group(1)) if start_match else 0
        caption_match = re.search(r"CAPTION:(.*)", res_text, re.DOTALL); ai_caption = caption_match.group(1).strip() if caption_match else None
        return start_sec, ai_caption
    except Exception as e:
        print(f"  ⚠️ AIエラー: {e}")
        return None, None

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats(); history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    print(f"⚾️ 探索開始...")
    candidates = get_all_candidates(history, is_test_mode)
    
    if not candidates:
        print("😴 新しい動画が見つかりませんでした。"); return

    # 比率チェック
    total_posted = stats['npb'] + stats['mlb']
    mlb_ratio = stats['mlb'] / total_posted if total_posted > 0 else 0

    # 良い動画が見つかるまでループ
    for video in candidates:
        # MLB比率制限（テストモード以外）
        if not is_test_mode and video['type'] == 'mlb' and mlb_ratio > 0.4:
            continue

        print(f"🎯 候補チェック: {video['title']}")
        temp_input = "temp_video.mp4"
        subprocess.run(['yt-dlp', '-o', temp_input, '--no-check-certificates', video['url']])
        
        if not os.path.exists(temp_input) or os.path.getsize(temp_input) < 10000:
            continue

        start_sec, ai_caption = analyze_video_with_ai(temp_input, video['title'], video['source'])
        
        if ai_caption == "SKIP" or ai_caption is None:
            print("  ⏩ スキップして次へ...")
            with open(history_file, 'a') as fh: fh.write(video['id'] + "\n")
            continue

        # ここまで来れば合格、加工と投稿へ
        output_file = "output.mp4"
        filter_complex = "scale=1134:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
        subprocess.run(['ffmpeg', '-ss', str(start_sec), '-i', temp_input, '-t', '90', '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-b:v', '5M', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-y', output_file])
        
        public_url = None
        try:
            res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': open(output_file, 'rb')}, timeout=60).json()
            if res.get('status') == 'success':
                public_url = res['data']['url'].replace("http://", "https://").replace("tmpfiles.org/", "tmpfiles.org/dl/")
        except: pass

        if public_url:
            print(f"✅ 公開準備完了: {public_url}")
            time.sleep(10)
            post_res = requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media", data={'media_type': 'REELS', 'video_url': public_url, 'caption': ai_caption, 'access_token': ACCESS_TOKEN}).json()
            
            if 'id' in post_res:
                creation_id = post_res['id']
                for i in range(20):
                    time.sleep(30)
                    status_res = requests.get(f"https://graph.facebook.com/v21.0/{creation_id}", params={'fields': 'status_code,status', 'access_token': ACCESS_TOKEN}).json()
                    status = (status_res.get('status_code') or status_res.get('status') or "").upper()
                    if status == 'FINISHED':
                        requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN})
                        print(f"🏁 投稿完了！: {video['title']}")
                        with open(history_file, 'a') as fh: fh.write(video['id'] + "\n")
                        stats[video['type']] += 1
                        save_stats(stats); return # 1件投稿したら終了
    
    print("😴 全ての候補が条件を満たしませんでした。")

if __name__ == "__main__":
    main()
