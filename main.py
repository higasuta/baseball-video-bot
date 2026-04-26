import requests
import datetime
import os
import time
import subprocess
import google.generativeai as genai
import json

# ==========================================
# GitHub Secrets から「隠し金庫」の鍵を読み込む
# ==========================================
INSTA_ID = os.getenv('INSTA_BUSINESS_ID')
ACCESS_TOKEN = os.getenv('INSTA_ACCESS_TOKEN')
GEMINI_KEY = os.getenv('GEMINI_API_KEY')

# Geminiの設定
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)

# 判定キーワード
JPN_MLB_KEYWORDS = ["ohtani", "yamamoto", "imanaga", "darvish", "suzuki", "yoshida", "senga", "matsui", "maeda", "kikuchi"]
HOT_KEYWORDS = ["home run", "hr", "grand slam", "history", "record", "historic", "milestone", "walk-off"]

def get_stats():
    if os.path.exists('stats.json'):
        try:
            with open('stats.json', 'r') as f: return json.load(f)
        except: pass
    return {"npb": 7, "mlb": 3}

def save_stats(stats):
    with open('stats.json', 'w') as f: json.dump(stats, f)

def get_npb_video(history, is_test_mode):
    sources = ["https://www.youtube.com/@NPB.official/videos", "https://x.com/npb"]
    duration_limit = 600 if is_test_mode else 180
    for src in sources:
        print(f"🔍 NPBスキャン中: {src}")
        try:
            cmd = ['yt-dlp', '--get-id', '--get-title', '--get-url', '--match-filter', f'duration < {duration_limit}', '--max-downloads', '1', src]
            output = subprocess.check_output(cmd).decode().split('\n')
            if len(output) >= 3:
                video_id = output[1]
                if is_test_mode or video_id not in history:
                    return {"title": output[0], "desc": "NPB公式動画", "url": output[2], "id": video_id, "type": "npb", "is_hot": False}
        except: continue
    return None

def get_mlb_video(history, is_test_mode):
    dates_to_check = [datetime.datetime.now().strftime('%Y-%m-%d'), (datetime.datetime.now() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')]
    for date_str in dates_to_check:
        print(f"🔍 MLBスキャン中 ({date_str})...")
        url = f"https://statsapi.mlb.com/api/v1/schedule/games/?sportId=1&startDate={date_str}&endDate={date_str}"
        try:
            response = requests.get(url).json()
            if 'dates' not in response or not response['dates']: continue
            for game in response['dates'][0]['games']:
                content_url = f"https://statsapi.mlb.com/api/v1/game/{game['gamePk']}/content"
                content_data = requests.get(content_url).json()
                if 'highlights' not in content_data['highlights']: continue
                items = content_data['highlights']['highlights']['items']
                for item in items:
                    title = item.get('headline', '')
                    desc = item.get('description', '')
                    video_url = next((p['url'] for p in item['playbacks'] if p['name'] == 'mp4Avc'), None)
                    if not video_url: continue
                    is_jpn = any(name in title.lower() or name in desc.lower() for name in JPN_MLB_KEYWORDS)
                    if is_jpn or (is_test_mode and item['id'] not in history):
                        is_hot = any(kw in title.lower() or kw in desc.lower() for kw in HOT_KEYWORDS)
                        return {"title": title, "desc": desc, "url": video_url, "id": item['id'], "type": "mlb", "is_hot": is_hot}
        except: continue
    return None

def process_video_v5(input_url):
    input_file = "input.mp4"
    output_file = "output.mp4"
    print("🎬 動画の加工中...")
    subprocess.run(['curl', '-L', input_url, '-o', input_file])
    filter_complex = "scale=1134:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
    subprocess.run(['ffmpeg', '-i', input_file, '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'fast', '-crf', '23', '-c:a', 'aac', '-b:a', '128k', '-y', output_file])
    return output_file

def upload_video(file_path):
    print("☁️ アップロード中...")
    try:
        with open(file_path, 'rb') as f:
            res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f})
            if res.status_code == 200:
                return res.json()['data']['url'].replace('http://', 'https://').replace('https://tmpfiles.org/', 'https://tmpfiles.org/dl/')
    except: return None

def generate_caption(title, desc):
    """【YouTubeまとめ風】お使いのキーで確実なモデル名を使用"""
    try:
        model = genai.GenerativeModel("gemini-flash-latest")
        prompt = f"""
        あなたはプロ野球・MLB専門のYouTubeまとめ解説動画の管理人です。
        ニュース：『{title}』 / 『{desc}』
        
        以下の【構成】を厳守し、標準語の語り口調（〜だ、〜である）で出力せよ。
        
        【構成】
        1. 一段目：【朗報】や【驚愕】等から始まる、20-30文字のインパクトある見出し。
        2. 二段目：ニュースの核心を2-3行で簡潔にまとめたもの。
        3. 三段目：データやファンの反応を交えた、あなたの熱い所感。
        
        【ルール】
        ・「概要：」「見出し：」などのラベル名は一切書かない。
        ・敬語は禁止。落ち着いた書き言葉にすること。
        ・登場人物・チーム名をすべて個別に#タグ化せよ。中黒「・」は絶対に使わず詰めろ（例：#ダルビッシュ有）。
        ・合計25個以上の大量のハッシュタグを並べろ。
        
        文章のみ出力してください。
        """
        response = model.generate_content(prompt)
        return response.text.strip().replace("・", "")
    except Exception as e:
        print(f"AIエラー: {e}")
        return None

def post_reels(video_url, caption):
    base_url = f"https://graph.facebook.com/v21.0/{INSTA_ID}/media"
    payload = {'media_type': 'REELS', 'video_url': video_url, 'caption': caption, 'access_token': ACCESS_TOKEN}
    res = requests.post(base_url, data=payload).json()
    if 'id' not in res:
        print(f"❌ Instagramへの登録失敗: {res}")
        return None
    
    creation_id = res['id']
    print(f"⏳ 処理完了を待機中 (ID: {creation_id})...")
    status_url = f"https://graph.facebook.com/v21.0/{creation_id}"
    for _ in range(40):
        time.sleep(20)
        status = requests.get(status_url, params={'fields': 'status_code', 'access_token': ACCESS_TOKEN}).json()
        print(f"   ステータス: {status.get('status_code')}")
        if status.get('status_code') == 'FINISHED': break
        elif status.get('status_code') == 'ERROR': return None
    
    publish_url = f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish"
    return requests.post(publish_url, data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN}).json()

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats()
    history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    print(f"⚾️ 探索開始 {'(テストモード)' if is_test_mode else ''}")
    video_data = get_npb_video(history, is_test_mode) or get_mlb_video(history, is_test_mode)

    if video_data:
        print(f"🚀 ターゲット決定: {video_data['title']}")
        processed_file = process_video_v5(video_data['url'])
        
        if os.path.exists(processed_file) and os.path.getsize(processed_file) > 0:
            public_url = upload_video(processed_file)
            if public_url:
                print(f"🔗 Instagram用URL: {public_url}")
                caption = generate_caption(video_data['title'], video_data['desc'])
                if not caption:
                    caption = f"【速報】{video_data['title']}\n#プロ野球 #MLB"
                
                result = post_reels(public_url, caption)
                if result and 'id' in result:
                    print(f"🏁 投稿成功！ ID: {result['id']}")
                    if not is_test_mode:
                        with open(history_file, 'a') as f: f.write(video_data['id'] + "\n")
                        stats[video_data['type']] += 1
                        save_stats(stats)
            else: print("❌ アップロード失敗")
        else: print("❌ 加工失敗")
    else: print("😴 新着なし")

if __name__ == "__main__":
    main()
