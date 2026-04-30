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

JPN_KEYWORDS = ["大谷", "山本", "ダルビッシュ", "鈴木誠也", "吉田正尚", "今永", "松井裕樹", "千賀", "前田健太", "菊池雄星", "ohtani", "yamamoto", "imanaga"]
BLACK_KEYWORDS = ["probable", "pitchers", "lineup", "interview", "press", "availability", "roster", "update"]

def get_stats():
    if os.path.exists('stats.json'):
        try:
            with open('stats.json', 'r') as f: return json.load(f)
        except: pass
    return {"npb": 7, "mlb": 3}

def save_stats(stats):
    with open('stats.json', 'w') as f: json.dump(stats, f)

def fetch_raw_x_data(url):
    """Xから動画リストを力技で取得する"""
    # 複数のクライアント設定を試す
    cmd = [
        'yt-dlp', '--get-id', '--get-title', '--get-url', '--print', 'upload_date',
        '--playlist-end', '20',
        '--no-check-certificates',
        '--quiet', '--no-warnings',
        '--extractor-args', 'twitter:api=guest', # ゲストAPIを明示
        url
    ]
    try:
        process = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
        return process.stdout.split('\n')
    except:
        return []

def get_npb_video(history):
    sources = [
        "https://twitter.com/PacificleagueTV",
        "https://twitter.com/sportsnavi_ybB",
        "https://twitter.com/BaseballkingJP",
        "https://twitter.com/FullcountJP",
        "https://twitter.com/ABEMA_baseball"
    ]
    week_ago = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime('%Y%m%d')
    
    for src in sources:
        user_name = src.split('/')[-1]
        print(f"🔍 @{user_name} をスキャン中...")
        output = fetch_raw_x_data(src)
        lines = [l for l in output if l.strip()]
        
        print(f"  👉 取得できた行数: {len(lines)} (4行で動画1件分)")
        
        if len(lines) < 4:
            print(f"  ⚠️ @{user_name} はXのブロックにより中身を読み取れませんでした。")
            continue

        for i in range(0, len(lines)-3, 4):
            title, video_id, video_url, upload_date = lines[i], lines[i+1], lines[i+2], lines[i+3]
            
            if video_id in history:
                continue
            
            if upload_date < week_ago:
                continue

            print(f"✅ 未投稿動画を特定: {title}")
            return {"title": title, "url": video_url, "id": video_id, "type": "npb", "source_account": f"@{user_name}"}
    return None

def get_mlb_video(history, is_test_mode):
    # MLBはAPIなので確実
    print(f"🔍 MLB(API)をスキャン中...")
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
                        video_id = str(item.get('id'))
                        if video_id in history: continue
                        video_url = next((p['url'] for p in item.get('playbacks', []) if p['name'] == 'mp4Avc'), None)
                        if video_url and (any(kw in title.lower() for kw in JPN_KEYWORDS) or is_test_mode):
                            if not any(kw in title.lower() for kw in BLACK_KEYWORDS):
                                print(f"✅ MLB動画を特定: {title}")
                                return {"title": title, "url": video_url, "id": video_id, "type": "mlb", "source_account": "@MLBJapan"}
        except: continue
    return None

# AI解析・加工は前回のロジックを継承（gemini-flash-latestを使用）
def analyze_video_with_ai(video_path, title, source_account):
    if not os.path.exists(video_path): return 0, None
    print(f"🧠 AI解析中...")
    try:
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING": time.sleep(2); video_file = genai.get_file(video_file.name)
        model = genai.GenerativeModel("gemini-flash-latest")
        prompt = (f"野球動画（{title}）を解析せよ。\n1. 見どころ開始秒数を「START:秒」で。\n2. 熱いキャプションを作成。最後に『引用：{source_account}』と記載。\nSTART:[秒]\nCAPTION:[内容]")
        response = model.generate_content([prompt, video_file])
        res_text = response.text
        genai.delete_file(video_file.name)
        start_match = re.search(r"START:(\d+)", res_text); start_sec = int(start_match.group(1)) if start_match else 0
        caption_match = re.search(r"CAPTION:(.*)", res_text, re.DOTALL); caption = caption_match.group(1).strip() if caption_match else None
        return start_sec, caption
    except: return 0, None

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats()
    history_file = "history.txt"
    with open(history_file, 'r') as f: history = f.read().splitlines()

    print(f"⚾️ 探索開始 {'(テストモード)' if is_test_mode else ''}")
    video_data = get_npb_video(history)
    if not video_data:
        video_data = get_mlb_video(history, is_test_mode)

    if video_data:
        print(f"🎯 ターゲット決定: {video_data['title']}")
        temp_input = "temp_video.mp4"
        
        # ダウンロード
        if video_data['type'] == 'npb':
            subprocess.run(['yt-dlp', '-o', temp_input, '--no-check-certificates', video_data['url']])
        else:
            subprocess.run(['curl', '-L', video_data['url'], '-o', temp_input])
        if not os.path.exists(temp_input): return

        # AI解析 & 加工
        start_sec, ai_caption = analyze_video_with_ai(temp_input, video_data['title'], video_data['source_account'])
        if not ai_caption: ai_caption = f"【朗報】最高のプレー！\n\n引用：{video_data['source_account']}\n#プロ野球"
        
        output_file = "output.mp4"
        filter_complex = "scale=1134:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
        subprocess.run(['ffmpeg', '-ss', str(start_sec), '-i', temp_input, '-t', '90', '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'fast', '-crf', '20', '-movflags', '+faststart', '-y', output_file])
        
        try:
            with open(output_file, 'rb') as f:
                up_res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f})
                if up_res.status_code == 200:
                    public_url = up_res.json()['data']['url'].replace('https://tmpfiles.org/', 'https://tmpfiles.org/dl/')
                    print(f"📸 Instagram送信中...")
                    post_res = requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media", data={'media_type': 'REELS', 'video_url': public_url, 'caption': ai_caption, 'access_token': ACCESS_TOKEN}).json()
                    
                    if 'id' in post_res:
                        creation_id = post_res['id']
                        print(f"⏳ 待機中 (ID: {creation_id})...")
                        for i in range(20):
                            time.sleep(30)
                            status_res = requests.get(f"https://graph.facebook.com/v21.0/{creation_id}", params={'fields': 'status_code', 'access_token': ACCESS_TOKEN}).json()
                            status = status_res.get('status_code')
                            print(f"  [{i+1}/20] Status: {status}")
                            
                            if status == 'FINISHED':
                                pub_res = requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN}).json()
                                if 'id' in pub_res:
                                    print(f"🏁 投稿完了！")
                                    # ★成功した時だけ歴史に刻む！
                                    with open(history_file, 'a') as fh: fh.write(video_data['id'] + "\n")
                                    stats[video_data['type']] += 1
                                    save_stats(stats)
                                    return
                            elif status == 'ERROR':
                                print(f"❌ 処理失敗"); return
        except Exception as e: print(f"❌ エラー: {e}")
    else: print("😴 投稿対象なし。")

if __name__ == "__main__":
    main()
