import requests
import datetime
import os
import time
import subprocess
import google.generativeai as genai
import json
import re

# ==========================================
# GitHub Secrets から鍵を安全に読み込む
# ==========================================
INSTA_ID = os.getenv('INSTA_BUSINESS_ID')
ACCESS_TOKEN = os.getenv('INSTA_ACCESS_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

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

def get_npb_video(history):
    """NPB公式スキャン（ブラウザ偽装強化版）"""
    sources = [
        "https://www.youtube.com/@NPB.official/videos",
        "https://www.youtube.com/@PacificLeagueSpecial/videos", 
        "https://x.com/npb"
    ]
    for src in sources:
        print(f"🔍 NPBスキャン中: {src}")
        try:
            # yt-dlpにブラウザのふりをさせる引数を追加
            cmd = [
                'yt-dlp', 
                '--get-id', '--get-title', '--get-url', 
                '--match-filter', 'duration < 180', 
                '--playlist-end', '5', 
                '--no-check-certificates',
                '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                src
            ]
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT).decode().split('\n')
            
            for i in range(0, len(output)-2, 3):
                title = output[i]
                video_id = output[i+1]
                video_url = output[i+2]
                if video_id and video_id not in history:
                    print(f"✅ 新着NPB動画発見: {title}")
                    return {"title": title, "desc": "NPB公式最新動画", "url": video_url, "id": video_id, "type": "npb", "is_hot": False}
        except Exception as e:
            print(f"⚠️ {src} の取得に失敗しました。次を試します。")
            continue
    return None

def get_mlb_video(history, is_test_mode):
    """MLBスキャン"""
    print(f"🔍 MLB日本人選手スキャン開始...")
    dates = [datetime.datetime.now().strftime('%Y-%m-%d'), (datetime.datetime.now() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')]
    for date_str in dates:
        url = f"https://statsapi.mlb.com/api/v1/schedule/games/?sportId=1&startDate={date_str}&endDate={date_str}"
        try:
            response = requests.get(url).json()
            if 'dates' not in response or not response['dates']: continue
            for game in response['dates'][0]['games']:
                content_url = f"https://statsapi.mlb.com/api/v1/game/{game['gamePk']}/content"
                content_data = requests.get(content_url).json()
                if 'highlights' not in content_data or 'highlights' not in content_data['highlights']: continue
                
                for item in content_data['highlights']['highlights']['items']:
                    title = item.get('headline', '')
                    desc = item.get('description', '')
                    video_id = str(item.get('id'))
                    if video_id in history: continue

                    video_url = next((p['url'] for p in item['playbacks'] if p['name'] == 'mp4Avc'), None)
                    if not video_url: continue

                    is_jpn = any(name in title.lower() or name in desc.lower() for name in JPN_MLB_KEYWORDS)
                    if is_jpn or is_test_mode:
                        is_hot = any(kw in title.lower() or kw in desc.lower() for kw in HOT_KEYWORDS)
                        return {"title": title, "desc": desc, "url": video_url, "id": video_id, "type": "mlb", "is_hot": is_hot}
        except Exception as e:
            print(f"⚠️ MLB APIエラー: {e}")
            continue
    return None

def process_video_v5(input_url):
    input_file = "input.mp4"
    output_file = "output.mp4"
    print(f"📥 動画ダウンロード開始...")
    subprocess.run(['curl', '-L', input_url, '-o', input_file])
    print(f"✂️ 動画加工中 (FFmpeg)...")
    filter_complex = "scale=1134:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
    subprocess.run(['ffmpeg', '-i', input_file, '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'fast', '-crf', '23', '-c:a', 'aac', '-b:a', '128k', '-y', output_file])
    return output_file

def upload_video(file_path):
    print(f"☁️ サーバーへアップロード中...")
    try:
        with open(file_path, 'rb') as f:
            res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f})
            if res.status_code == 200:
                url = res.json()['data']['url']
                return url.replace('http://', 'https://').replace('https://tmpfiles.org/', 'https://tmpfiles.org/dl/')
    except: return None

def generate_caption(title, desc):
    print(f"🤖 AI執筆中...")
    if not GEMINI_API_KEY: return None
    try:
        model = genai.GenerativeModel("gemini-flash-latest")
        prompt = f"あなたはプロ野球MLBまとめ動画の管理人です。ニュース：『{title}』 / 『{desc}』。一段目【朗報等】見出し、二段目要約、三段目熱い所感、の構成で。標準語語り口調。全人物#タグ、タグ25個以上。文章のみ出力。"
        response = model.generate_content(prompt)
        return response.text.strip().replace("・", "")
    except Exception as e:
        print(f"AIエラー: {e}")
        return None

def post_reels(video_url, caption):
    print(f"📸 Instagram投稿リクエスト中...")
    base_url = f"https://graph.facebook.com/v21.0/{INSTA_ID}/media"
    res = requests.post(base_url, data={'media_type': 'REELS', 'video_url': video_url, 'caption': caption, 'access_token': ACCESS_TOKEN}).json()
    if 'id' not in res: 
        print(f"❌ エラー: {res}")
        return None
    creation_id = res['id']
    print(f"⏳ 処理待ち中 (ID: {creation_id})...")
    for _ in range(40):
        time.sleep(20)
        status = requests.get(f"https://graph.facebook.com/v21.0/{creation_id}", params={'fields': 'status_code', 'access_token': ACCESS_TOKEN}).json()
        if status.get('status_code') == 'FINISHED': break
        elif status.get('status_code') == 'ERROR': return None
    return requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN}).json()

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats()
    history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    print(f"⚾️ 探索開始 {'(テストモード)' if is_test_mode else ''}")
    
    video_data = get_npb_video(history)
    
    if not video_data:
        mlb_item = get_mlb_video(history, is_test_mode)
        if mlb_item:
            total = stats['npb'] + stats['mlb']
            ratio = stats['mlb'] / total if total > 0 else 0
            print(f"📊 現在のMLB比率: {ratio*100:.1f}%")
            if is_test_mode or mlb_item['is_hot'] or ratio < 0.35:
                video_data = mlb_item
            else:
                print(f"🛑 MLB投稿制限中 (NPB待ち)")

    if video_data:
        print(f"🎯 ターゲット確定: {video_data['title']}")
        with open(history_file, 'a') as f: f.write(video_data['id'] + "\n")
        processed_file = process_video_v5(video_data['url'])
        public_url = upload_video(processed_file)
        if public_url:
            caption = generate_caption(video_data['title'], video_data['desc'])
            if not caption: caption = f"【速報】{video_data['title']}\n#プロ野球 #MLB"
            result = post_reels(public_url, caption)
            if result and 'id' in result:
                print(f"🏁 投稿成功！ ID: {result['id']}")
                stats[video_data['type']] += 1
                save_stats(stats)
            else: print(f"❌ 公開失敗")
    else:
        print("😴 投稿対象なし。")

if __name__ == "__main__":
    main()
