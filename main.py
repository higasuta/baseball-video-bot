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
BLACK_KEYWORDS = ["probable", "pitchers", "lineup", "interview", "press", "availability", "roster", "update", "投球練習"]

def get_stats():
    if os.path.exists('stats.json'):
        try:
            with open('stats.json', 'r') as f: return json.load(f)
        except: pass
    return {"npb": 7, "mlb": 3}

def save_stats(stats):
    with open('stats.json', 'w') as f: json.dump(stats, f)

def get_npb_video(history):
    """NPBスキャン（Xのアカウントから動画を探す）"""
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
        print(f"🔍 スキャン中: @{user_name}")
        try:
            # playlist-end を 30 に拡大して深く探す
            cmd = ['yt-dlp', '--get-id', '--get-title', '--get-url', '--print', 'upload_date', '--playlist-end', '30', '--match-filter', "duration < 300 & !is_live", '--no-check-certificates', '--user-agent', 'Mozilla/5.0', '--quiet', src]
            process = subprocess.run(cmd, capture_output=True, text=True)
            if process.returncode != 0:
                print(f"  ⚠️ yt-dlpが反応しませんでした。")
                continue
            
            lines = [l for l in process.stdout.split('\n') if l.strip()]
            for i in range(0, len(lines)-3, 4):
                title, video_id, video_url, upload_date = lines[i], lines[i+1], lines[i+2], lines[i+3]
                
                if video_id in history:
                    continue # 既読は静かにスルー
                
                if upload_date < week_ago:
                    print(f"  ⏩ 期間外スキップ ({upload_date}): {title[:20]}...")
                    continue

                print(f"✅ NPB動画をターゲットに決定: {title}")
                return {"title": title, "url": video_url, "id": video_id, "type": "npb", "source_account": f"@{user_name}"}
        except: continue
    return None

def get_mlb_video(history, is_test_mode):
    """MLBスキャン（APIから日本人動画を探す）"""
    print(f"🔍 MLB日本人選手スキャン開始...")
    # 過去3日分まで範囲を広げる
    for day_offset in range(3):
        date_str = (datetime.datetime.now() - datetime.timedelta(days=day_offset)).strftime('%Y-%m-%d')
        url = f"https://statsapi.mlb.com/api/v1/schedule/games/?sportId=1&startDate={date_str}&endDate={date_str}"
        try:
            res = requests.get(url).json()
            for date_data in res.get('dates', []):
                for game in date_data.get('games', []):
                    content = requests.get(f"https://statsapi.mlb.com/api/v1/game/{game['gamePk']}/content").json()
                    highlights = content.get('highlights', {}).get('highlights', {}).get('items', [])
                    for item in highlights:
                        title = item.get('headline', '')
                        video_id = str(item.get('id'))
                        if video_id in history: continue
                        
                        video_url = next((p['url'] for p in item.get('playbacks', []) if p['name'] == 'mp4Avc'), None)
                        if not video_url: continue
                        
                        is_jpn = any(kw in title.lower() for kw in JPN_KEYWORDS)
                        is_boring = any(kw in title.lower() for kw in BLACK_KEYWORDS)
                        
                        if is_boring:
                            print(f"  ⏩ 地味動画スキップ: {title[:20]}...")
                            continue

                        if is_jpn or is_test_mode:
                            print(f"✅ MLB動画をターゲットに決定: {title}")
                            return {"title": title, "url": video_url, "id": video_id, "type": "mlb", "source_account": "@MLBJapan"}
        except: continue
    return None

def analyze_video_with_ai(video_path, title, source_account):
    """Gemini 2.0 Flashによる解析"""
    if not os.path.exists(video_path): return 0, None
    print(f"🧠 AI解析中 (Gemini)...")
    try:
        probe = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', video_path])
        total_duration = float(probe)
        
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING": time.sleep(2); video_file = genai.get_file(video_file.name)

        model = genai.GenerativeModel("gemini-2.0-flash")
        prompt = (f"野球動画（{title}）を解析せよ。\n"
                  "1. 見どころの開始秒数を「START:秒」で。\n"
                  "2. 野球2chまとめ解説動画風の語り口調で熱いキャプションを作成せよ。\n"
                  f"3. 最後に必ず『引用：{source_account}』と記載せよ。\n"
                  "START:[秒]\nCAPTION:[内容]")
        response = model.generate_content([prompt, video_file])
        res_text = response.text
        genai.delete_file(video_file.name)
        
        start_match = re.search(r"START:(\d+)", res_text)
        start_sec = int(start_match.group(1)) if start_match else 0
        if total_duration - start_sec < 5: start_sec = 0
        
        caption_match = re.search(r"CAPTION:(.*)", res_text, re.DOTALL)
        caption = caption_match.group(1).strip() if caption_match else None
        print(f"  ✨ AI解析完了 (開始: {start_sec}s)")
        return start_sec, caption
    except Exception as e:
        print(f"  ⚠️ AI解析失敗: {e}")
        return 0, None

def process_video_final(input_file, start_sec):
    output_file = "output.mp4"
    print(f"✂️ 加工中...")
    filter_complex = "scale=1134:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
    subprocess.run(['ffmpeg', '-ss', str(start_sec), '-i', input_file, '-t', '90', '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'fast', '-crf', '23', '-movflags', '+faststart', '-y', output_file])
    return output_file

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats()
    history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    print(f"⚾️ 探索開始 {'(テストモード)' if is_test_mode else ''}")
    video_data = get_npb_video(history)
    
    if not video_data:
        # NPBがなければMLB（比率制限またはテストモード）
        total = stats['npb'] + stats['mlb']
        ratio = stats['mlb'] / total if total > 0 else 0
        if is_test_mode or ratio < 0.40: # 少しMLB比率の上限を緩和
            video_data = get_mlb_video(history, is_test_mode)

    if video_data:
        temp_input = "temp_video.mp4"
        with open(history_file, 'a') as f: f.write(video_data['id'] + "\n")
        
        print(f"📥 ダウンロード開始: {video_data['url']}")
        if video_data['type'] == 'npb':
            subprocess.run(['yt-dlp', '-o', temp_input, '--no-check-certificates', video_data['url']])
        else:
            subprocess.run(['curl', '-L', video_data['url'], '-o', temp_input])

        if not os.path.exists(temp_input) or os.path.getsize(temp_input) < 1000:
            print("❌ ダウンロード失敗またはファイルが空です。")
            return

        start_sec, ai_caption = analyze_video_with_ai(temp_input, video_data['title'], video_data['source_account'])
        if not ai_caption: ai_caption = f"【速報】{video_data['title']}\n\n引用：{video_data['source_account']}\n#プロ野球"
        
        processed_file = process_video_final(temp_input, start_sec)
        
        try:
            with open(processed_file, 'rb') as f:
                up_res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f})
                if up_res.status_code == 200:
                    public_url = up_res.json()['data']['url'].replace('https://tmpfiles.org/', 'https://tmpfiles.org/dl/')
                    print(f"📸 Instagram送信開始...")
                    post_url = f"https://graph.facebook.com/v21.0/{INSTA_ID}/media"
                    post_res = requests.post(post_url, data={'media_type': 'REELS', 'video_url': public_url, 'caption': ai_caption, 'access_token': ACCESS_TOKEN}).json()
                    
                    if 'id' in post_res:
                        creation_id = post_res['id']
                        print(f"⏳ 処理待機 (ID: {creation_id})...")
                        for i in range(30):
                            time.sleep(30)
                            status_res = requests.get(f"https://graph.facebook.com/v21.0/{creation_id}", params={'fields': 'status_code,failure_reason', 'access_token': ACCESS_TOKEN}).json()
                            status = status_res.get('status_code')
                            print(f"  [{i+1}/30] ステータス: {status}")
                            if status == 'FINISHED':
                                print(f"🚀 公開実行...")
                                requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN})
                                print(f"🏁 投稿完了！")
                                stats[video_data['type']] += 1
                                save_stats(stats)
                                return
                            elif status == 'ERROR':
                                print(f"❌ Instagramエラー: {status_res.get('failure_reason')}")
                                return
                    else: print(f"❌ コンテナ作成失敗: {post_res}")
        except Exception as e: print(f"❌ エラー: {e}")
    else:
        print("😴 条件に合う未投稿の動画は見つかりませんでした。")

if __name__ == "__main__":
    main()