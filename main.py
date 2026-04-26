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

JPN_MLB_KEYWORDS = ["Ohtani", "Yamamoto", "Imanaga", "Darvish", "Suzuki", "Yoshida", "Senga", "Matsui", "Maeda", "Kikuchi"]
HOT_KEYWORDS = ["Home Run", "HR", "Grand Slam", "History", "Record", "Historic", "Milestone", "Walk-off"]

def get_stats():
    if os.path.exists('stats.json'):
        try:
            with open('stats.json', 'r') as f: return json.load(f)
        except: pass
    return {"npb": 7, "mlb": 3}

def save_stats(stats):
    with open('stats.json', 'w') as f: json.dump(stats, f)

def get_npb_video(history):
    """【最優先】NPB公式をスキャン"""
    sources = ["https://www.youtube.com/@NPB.official/videos", "https://x.com/npb"]
    for src in sources:
        print(f"🔍 NPBスキャン中: {src}")
        try:
            cmd = ['yt-dlp', '--get-id', '--get-title', '--get-url', '--match-filter', 'duration < 180', '--max-downloads', '1', src]
            output = subprocess.check_output(cmd).decode().split('\n')
            if len(output) >= 3:
                video_id = output[1]
                if video_id not in history:
                    return {"title": output[0], "desc": "NPB公式最新動画", "url": output[2], "id": video_id, "type": "npb", "is_hot": False}
        except: continue
    return None

def get_mlb_video(history):
    """【二番手】MLB日本人選手をスキャン"""
    print("🔍 MLB日本人選手スキャン中...")
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    url = f"https://statsapi.mlb.com/api/v1/schedule/games/?sportId=1&startDate={today}&endDate={today}"
    try:
        response = requests.get(url).json()
        if 'dates' not in response or not response['dates']: return None
        for game in response['dates'][0]['games']:
            game_pk = game['gamePk']
            content_url = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/content"
            content_data = requests.get(content_url).json()
            if 'highlights' not in content_data['highlights'] or 'highlights' not in content_data['highlights']['highlights']: continue
            for item in content_data['highlights']['highlights']['items']:
                title = item.get('headline', '')
                desc = item.get('description', '')
                if any(name in title for name in JPN_MLB_KEYWORDS):
                    video_url = next((p['url'] for p in item['playbacks'] if p['name'] == 'mp4Avc'), None)
                    if video_url and item['id'] not in history:
                        is_hot = any(kw in title or kw in desc for kw in HOT_KEYWORDS)
                        return {"title": title, "desc": desc, "url": video_url, "id": item['id'], "type": "mlb", "is_hot": is_hot}
    except: return None
    return None

def process_video_v4(input_url):
    """【修正版】105%ズーム ＆ 縦長加工（サイズエラー回避）"""
    input_file = "input.mp4"
    output_file = "output.mp4"
    print("🎬 動画のダウンロードと加工を開始します...")
    subprocess.run(['curl', '-L', input_url, '-o', input_file])
    
    # 修正されたFFmpegフィルタ:
    # 1. 横幅を1080にリサイズ (scale=1080:-2)
    # 2. 105%にズーム (scale=iw*1.05:-2)
    # 3. 1080x1920の枠に入れ、中央の1080px分を切り取る (crop=1080:ih)
    # 4. 上下に黒帯を付けて1920pxの高さにする (pad=1080:1920)
    filter_complex = "scale=1080:-2,scale=iw*1.05:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black"
    
    subprocess.run(['ffmpeg', '-i', input_file, '-vf', filter_complex, '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-c:a', 'aac', '-y', output_file])
    return output_file

def upload_to_catbox(file_path):
    print("☁️ 加工済み動画を一時サーバーへアップロード中...")
    with open(file_path, 'rb') as f:
        res = requests.post('https://catbox.moe/user/api.php', data={'reqtype': 'fileupload'}, files={'fileToUpload': f})
    return res.text

def generate_caption(title, desc):
    model = genai.GenerativeModel("gemini-1.5-flash")
    prompt = f"あなたはYouTubeの野球まとめ解説動画の管理人です。「{title}」「{desc}」から最高に熱いインスタ投稿を作れ。掟：1.標準語語り口調 2.見出し【朗報】等 3.全人物#タグ25個 4.URL不要。文章のみ。"
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except: return f"【衝撃】プロ野球・MLB最新速報！\n#プロ野球 #MLB"

def post_reels(video_url, caption):
    base_url = f"https://graph.facebook.com/v21.0/{INSTA_ID}/media"
    res = requests.post(base_url, data={'media_type': 'REELS', 'video_url': video_url, 'caption': caption, 'access_token': ACCESS_TOKEN}).json()
    if 'id' not in res:
        print(f"❌ 投稿予約失敗: {res}")
        return None
    creation_id = res['id']
    print(f"⏳ Instagram側の処理を待機中 (ID: {creation_id})...")
    time.sleep(60) 
    publish_url = f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish"
    return requests.post(publish_url, data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN}).json()

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats()
    history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    print(f"⚾️ 探索開始：NPB -> MLB {'(テストモード)' if is_test_mode else ''}")
    video_data = get_npb_video(history)
    
    if not video_data:
        mlb_item = get_mlb_video(history)
        if mlb_item:
            total = stats['npb'] + stats['mlb']
            ratio = stats['mlb'] / total if total > 0 else 0
            if is_test_mode or mlb_item['is_hot'] or ratio < 0.3:
                if is_test_mode: print("🛠 テストモード：比率を無視します")
                video_data = mlb_item
            else:
                print(f"📊 比率調整：MLB(通常)は30%を超えているためNPBを待ちます (現在: {ratio:.2f})")

    if video_data:
        print(f"🚀 投稿対象: {video_data['title']}")
        processed_file = process_video_v4(video_data['url'])
        
        if os.path.exists(processed_file) and os.path.getsize(processed_file) > 0:
            public_url = upload_to_catbox(processed_file)
            print(f"🔗 公開URL: {public_url}")
            caption = generate_caption(video_data['title'], video_data['desc'])
            result = post_reels(public_url, caption)
            if result and 'id' in result:
                print(f"🏁 投稿成功！ ID: {result['id']}")
                with open(history_file, 'a') as f: f.write(video_data['id'] + "\n")
                stats[video_data['type']] += 1
                save_stats(stats)
            else: print(f"❌ 最終公開に失敗しました: {result}")
        else: print("❌ 動画の加工に失敗したため、投稿を中止しました。")
    else: print("😴 新着なし")

if __name__ == "__main__":
    main()
