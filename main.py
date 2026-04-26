import requests
import datetime
import os
import time
import subprocess
import google.generativeai as genai
import json

# ==========================================
# 【設定済み】各種キーとID
# ==========================================
INSTA_ID = '17841436151352537'
ACCESS_TOKEN = 'EAAN3eJp86t0BRFY4Eu9qiDAFwZCLAAVSP2bgSOmzKEKBZBF1namAjdGXVxlFDV5HAiPS5v2CNCq7L5dlLZCheYmvkBNyEWSsZBLZAk85ZAikHj1GG6hSsnJSY6b4pOUwV50vQOhn87dOastLOL2ZAqcl3RgzpSKWsV3ZB674cRb1XagsmdGlBzyzUnbWPK1lPCyr'
GEMINI_KEY = 'AIzaSyDx6Tly31o6xB_CoLlnVhHpPbvL0EloRY0'

genai.configure(api_key=GEMINI_KEY)

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
    dates_to_check = [
        datetime.datetime.now().strftime('%Y-%m-%d'),
        (datetime.datetime.now() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
    ]
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

def process_video_v4(input_url):
    input_file = "input.mp4"
    output_file = "output.mp4"
    print("🎬 動画の加工を開始...")
    subprocess.run(['curl', '-L', input_url, '-o', input_file])
    # リール用 1080x1920 ズーム加工
    filter_complex = "scale=1080:-2,scale=iw*1.05:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black"
    subprocess.run(['ffmpeg', '-i', input_file, '-vf', filter_complex, '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-c:a', 'aac', '-y', output_file])
    return output_file

def upload_video(file_path):
    """【最新修正】tmpfiles.org を使用して安定した直リンクを取得"""
    print("☁️ 外部サーバー(tmpfiles.org)へアップロード中...")
    try:
        with open(file_path, 'rb') as f:
            res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f})
            if res.status_code == 200:
                data = res.json()
                # Instagramが読み込める直リンク形式に変換
                # https://tmpfiles.org/xxxx -> https://tmpfiles.org/dl/xxxx
                url = data['data']['url'].replace('https://tmpfiles.org/', 'https://tmpfiles.org/dl/')
                print(f"✅ アップロード成功: {url}")
                return url
    except Exception as e:
        print(f"❌ アップロード失敗: {e}")
    return None

def generate_caption(title, desc):
    for model_name in ["gemini-2.0-flash", "gemini-1.5-flash"]:
        try:
            model = genai.GenerativeModel(model_name)
            prompt = f"野球まとめ解説動画の管理人。ニュース「{title}」「{desc}」から最高に熱いインスタ投稿を作れ。掟：1.標準語語り口調 2.見出し【朗報】等 3.全人物#タグ25個 4.URL不要。"
            response = model.generate_content(prompt)
            return response.text.strip()
        except: continue
    return f"【衝撃】プロ野球・MLB最新速報！\n#プロ野球 #MLB"

def post_reels(video_url, caption):
    base_url = f"https://graph.facebook.com/v21.0/{INSTA_ID}/media"
    payload = {'media_type': 'REELS', 'video_url': video_url, 'caption': caption, 'access_token': ACCESS_TOKEN}
    res = requests.post(base_url, data=payload).json()
    if 'id' not in res:
        print(f"❌ Instagramへの登録失敗: {res}")
        return None
    
    creation_id = res['id']
    print(f"⏳ Instagram側の処理を待機中 (ID: {creation_id})...")
    status_url = f"https://graph.facebook.com/v21.0/{creation_id}"
    for _ in range(30):
        time.sleep(20)
        status = requests.get(status_url, params={'fields': 'status_code', 'access_token': ACCESS_TOKEN}).json()
        print(f"   ステータス: {status.get('status_code')}")
        if status.get('status_code') == 'FINISHED':
            break
        elif status.get('status_code') == 'ERROR':
            print(f"❌ Instagram内部エラー: {status}")
            return None
    
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
        processed_file = process_video_v4(video_data['url'])
        
        if os.path.exists(processed_file) and os.path.getsize(processed_file) > 0:
            public_url = upload_video(processed_file)
            if public_url:
                print(f"🔗 Instagram用URL: {public_url}")
                caption = generate_caption(video_data['title'], video_data['desc'])
                result = post_reels(public_url, caption)
                if result and 'id' in result:
                    print(f"🏁 投稿成功！ ID: {result['id']}")
                    if not is_test_mode:
                        with open(history_file, 'a') as f: f.write(video_data['id'] + "\n")
                        stats[video_data['type']] += 1
                        save_stats(stats)
                else: print(f"❌ 最終公開に失敗しました: {result}")
            else: print("❌ アップロードに失敗しました。")
        else: print("❌ 動画の加工に失敗しました。")
    else: print("😴 新着なし")

if __name__ == "__main__":
    main()
