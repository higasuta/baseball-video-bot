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

# 【超厳格】除外キーワード：プレー以外の動画を即座に外す
BLACK_KEYWORDS = [
    "probable", "pitchers", "lineup", "interview", "press", "availability", 
    "roster", "update", "alignment", "summary", "preview", "warmup", 
    "positioning", "against", "at bat", "statcast", "pre-game", "breaking down",
    "recap", "daily", "highlights of the day"
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

def cleanup_gemini_storage():
    """Geminiのストレージ(20GB制限)を空にする"""
    print("🧹 AIストレージの掃除を開始...")
    try:
        for f in genai.list_files():
            genai.delete_file(f.name)
        print("  ✅ 掃除完了。")
    except:
        print("  ⚠️ 掃除に失敗（または空でした）。")

def get_all_candidates(history, is_test_mode):
    """精鋭動画だけをリストアップする（最大15件）"""
    candidates = []
    
    # 1. NPBスキャン
    print("🔍 NPBスキャン中...")
    rss_url = "https://sports.yahoo.co.jp/video/rss/baseball/npb"
    try:
        res = requests.get(rss_url, timeout=15)
        if res.status_code == 200:
            root = ET.fromstring(res.content)
            for item in root.findall('.//item')[:10]:
                title = item.find('title').text
                v_url = item.find('link').text
                v_id = item.find('guid').text if item.find('guid') is not None else v_url
                if v_id not in history and not any(kw in title.lower() for kw in BLACK_KEYWORDS):
                    candidates.append({"title": title, "url": v_url, "id": v_id, "type": "npb", "source": "スポーツナビ"})
    except: pass

    # 2. MLBスキャン
    print("🔍 MLBスキャン中...")
    for day_offset in [0, 1]:
        date_str = (datetime.datetime.now() - datetime.timedelta(days=day_offset)).strftime('%Y-%m-%d')
        url = f"https://statsapi.mlb.com/api/v1/schedule/games/?sportId=1&startDate={date_str}&endDate={date_str}"
        try:
            res = requests.get(url, timeout=15).json()
            for date_data in res.get('dates', []):
                for game in date_data.get('games', []):
                    content = requests.get(f"https://statsapi.mlb.com/api/v1/game/{game['gamePk']}/content").json()
                    highlights = content.get('highlights', {}).get('highlights', {}).get('items', [])
                    for item in highlights[:5]:
                        title = item.get('headline', '')
                        v_id = str(item.get('id'))
                        v_url = next((p['url'] for p in item.get('playbacks', []) if p['name'] == 'mp4Avc'), None)
                        if v_url and v_id not in history:
                            if any(kw in title.lower() for kw in BLACK_KEYWORDS): continue
                            if any(kw in title.lower() for kw in JPN_KEYWORDS):
                                candidates.append({"title": title, "url": v_url, "id": v_id, "type": "mlb", "source": "@MLBJapan"})
        except: continue
    return candidates[:15]

def analyze_video_with_ai(video_path, title, source_account):
    print(f"🧠 AI解析中...")
    try:
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING": time.sleep(2); video_file = genai.get_file(video_file.name)
        
        # モデル名は 404が出ないことが確認できているものを使用
        model = genai.GenerativeModel("gemini-1.5-flash-latest")
        prompt = f"""
        野球動画({title})を解析し、以下の形式で出力せよ。
        プレー（投球、打撃、守備、走塁）がない場合は CAPTION:SKIP と出力せよ。
        START:[秒]
        CAPTION:[内容]
        構成：【 】付きの鋭い見出し。2〜3行の要約。鋭い所感。
        ネットスラング禁止。だ・である調。タグ25個以上。引用：{source_account}
        """
        response = model.generate_content([prompt, video_file])
        res_text = response.text
        genai.delete_file(video_file.name)
        
        if "SKIP" in res_text: return None, "SKIP"
        start_match = re.search(r"START:(\d+)", res_text)
        start_sec = int(start_match.group(1)) if start_match else 0
        caption_match = re.search(r"CAPTION:(.*)", res_text, re.DOTALL)
        return start_sec, caption_match.group(1).strip() if caption_match else None
    except Exception as e:
        print(f"  ⚠️ AIエラー: {e}")
        return None, None

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats(); history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    # AIストレージを掃除
    cleanup_gemini_storage()

    print(f"⚾️ 探索開始...")
    candidates = get_all_candidates(history, is_test_mode)
    
    if not candidates:
        print("😴 良い動画が見つかりませんでした。"); return

    total_posted = stats['npb'] + stats['mlb']
    mlb_ratio = stats['mlb'] / total_posted if total_posted > 0 else 0

    # 精鋭の5本を順に試す
    for video in candidates[:5]:
        if not is_test_mode and video['type'] == 'mlb' and mlb_ratio > 0.4:
            continue

        print(f"🎯 ターゲット試行: {video['title']}")
        temp_input = "temp_video.mp4"
        subprocess.run(['curl', '-L', video['url'], '-o', temp_input])
        
        if not os.path.exists(temp_input) or os.path.getsize(temp_input) < 10000:
            continue

        start_sec, ai_caption = analyze_video_with_ai(temp_input, video['title'], video['source'])
        
        if ai_caption == "SKIP" or ai_caption is None:
            # SKIPされたものも履歴に入れて次回弾く
            with open(history_file, 'a') as fh: fh.write(video['id'] + "\n")
            continue

        output_file = "output.mp4"
        filter_complex = "scale=1134:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
        subprocess.run(['ffmpeg', '-ss', str(start_sec), '-i', temp_input, '-t', '90', '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-b:v', '5M', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-y', output_file])
        
        try:
            with open(output_file, 'rb') as f:
                res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f}, timeout=60).json()
                if res.get('status') == 'success':
                    public_url = res['data']['url'].replace("http://", "https://").replace("tmpfiles.org/", "tmpfiles.org/dl/")
                    print(f"✅ 公開準備完了")
                    time.sleep(10)
                    post_res = requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media", data={'media_type': 'REELS', 'video_url': public_url, 'caption': ai_caption, 'access_token': ACCESS_TOKEN}).json()
                    
                    if 'id' in post_res:
                        creation_id = post_res['id']
                        for _ in range(20):
                            time.sleep(30)
                            status_res = requests.get(f"https://graph.facebook.com/v21.0/{creation_id}", params={'fields': 'status_code,status', 'access_token': ACCESS_TOKEN}).json()
                            status = (status_res.get('status_code') or status_res.get('status') or "").upper()
                            if status == 'FINISHED':
                                requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN})
                                print(f"🏁 投稿完了！: {video['title']}")
                                # 【修正】video_data → video に変更してエラー回避
                                with open(history_file, 'a') as fh: fh.write(video['id'] + "\n")
                                stats[video['type']] += 1
                                save_stats(stats); return # 成功したら終了
        except: pass
    
    print("😴 本日のスキャンを終了しました。")

if __name__ == "__main__":
    main()
