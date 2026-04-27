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

# 日本人選手フィルター（MLB API用）
JPN_KEYWORDS = ["大谷", "山本", "ダルビッシュ", "鈴木誠也", "吉田正尚", "今永", "松井裕樹", "千賀", "前田健太", "菊池雄星", "ohtani", "yamamoto"]

def get_stats():
    if os.path.exists('stats.json'):
        try:
            with open('stats.json', 'r') as f: return json.load(f)
        except: pass
    return {"npb": 7, "mlb": 3}

def save_stats(stats):
    with open('stats.json', 'w') as f: json.dump(stats, f)

def get_npb_video(history):
    """NPBメディアXアカウントを巡回（twitter.comドメイン使用）"""
    # x.comではなくtwitter.comを使うことでyt-dlpの互換性を確保
    sources = [
        "https://twitter.com/PacificleagueTV",
        "https://twitter.com/sportsnavi_ybB",
        "https://twitter.com/BaseballkingJP",
        "https://twitter.com/FullcountJP",
        "https://twitter.com/DAZN_JPN",
        "https://twitter.com/ABEMA_baseball",
        "https://twitter.com/tvtokyo_sports",
        "https://twitter.com/nikkan_yakyuu",
        "https://twitter.com/jsports_yakyu",
        "https://twitter.com/easysportsJP",
        "https://twitter.com/sptv_yakyu"
    ]
    
    week_ago = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime('%Y%m%d')
    
    for src in sources:
        user_name = src.split('/')[-1]
        print(f"🔍 スキャン中: @{user_name}")
        try:
            cmd = [
                'yt-dlp', 
                '--get-id', '--get-title', '--get-url', '--print', 'upload_date',
                '--playlist-end', '20', 
                '--match-filter', "duration < 240 & !is_live",
                '--no-check-certificates',
                '--quiet',
                src
            ]
            process = subprocess.run(cmd, capture_output=True, text=True)
            if process.returncode != 0: continue

            lines = [l for l in process.stdout.split('\n') if l.strip()]
            for i in range(0, len(lines)-3, 4):
                title, video_id, video_url, upload_date = lines[i], lines[i+1], lines[i+2], lines[i+3]
                
                if video_id not in history and upload_date >= week_ago:
                    print(f"✅ NPB動画発見: {title}")
                    return {"title": title, "url": video_url, "id": video_id, "type": "npb", "source_account": f"@{user_name}"}
        except: continue
    return None

def get_mlb_video(history, is_test_mode):
    """MLB日本人限定ハイライト（APIから直接取得するため100%成功する）"""
    print(f"🔍 MLB日本人選手スキャン開始 (API経由)...")
    dates = [datetime.datetime.now().strftime('%Y-%m-%d'), (datetime.datetime.now() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')]
    for date_str in dates:
        url = f"https://statsapi.mlb.com/api/v1/schedule/games/?sportId=1&startDate={date_str}&endDate={date_str}"
        try:
            response = requests.get(url).json()
            if 'dates' not in response or not response['dates']: continue
            for game in response['dates'][0]['games']:
                content_url = f"https://statsapi.mlb.com/api/v1/game/{game['gamePk']}/content"
                content_data = requests.get(content_url).json()
                if 'highlights' not in content_data['highlights']: continue
                for item in content_data['highlights']['highlights']['items']:
                    title = item.get('headline', '')
                    video_id = str(item.get('id'))
                    if video_id in history: continue
                    
                    # 動画URLの抽出
                    video_url = next((p['url'] for p in item['playbacks'] if p['name'] == 'mp4Avc'), None)
                    if not video_url: continue

                    # 日本人選手キーワードで厳格にフィルタリング
                    if any(kw in title.lower() for kw in JPN_KEYWORDS) or is_test_mode:
                        print(f"✅ MLB動画発見: {title}")
                        return {"title": title, "url": video_url, "id": video_id, "type": "mlb", "source_account": "@MLBJapan"}
        except: continue
    return None

def analyze_video_with_ai(video_path, title, source_account):
    if not os.path.exists(video_path): return 0, None
    print(f"🧠 AIによる動画解析中...")
    try:
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING":
            time.sleep(2)
            video_file = genai.get_file(video_file.name)

        model = genai.GenerativeModel("gemini-2.0-flash")
        prompt = (
            f"この野球動画（タイトル：{title}）を解析してください。\n\n"
            "1. 最も盛り上がっている場面の開始秒数を「START:秒」で教えてください。\n"
            "2. YouTubeの野球2chまとめ解説動画の管理人風に、熱い語り口調でキャプションを作成してください。\n"
            f"3. 最後に必ず『引用：{source_account}』と記載してください。\n\n"
            "START:[秒]\nCAPTION:[内容]"
        )
        response = model.generate_content([prompt, video_file])
        res_text = response.text
        genai.delete_file(video_file.name)

        start_match = re.search(r"START:(\d+)", res_text)
        start_sec = int(start_match.group(1)) if start_match else 0
        caption_match = re.search(r"CAPTION:(.*)", res_text, re.DOTALL)
        caption = caption_match.group(1).strip() if caption_match else None
        return start_sec, caption
    except Exception as e:
        print(f"⚠️ AI解析失敗: {e}")
        return 0, None

def process_video_final(input_file, start_sec):
    output_file = "output.mp4"
    print(f"✂️ 加工中 (Start: {start_sec}s)...")
    filter_complex = "scale=1134:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
    subprocess.run([
        'ffmpeg', '-ss', str(start_sec), '-i', input_file, 
        '-t', '90', '-vf', filter_complex, 
        '-r', '30', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'fast', '-crf', '23', '-c:a', 'aac', '-b:a', '128k', '-y', output_file
    ])
    return output_file

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats()
    history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    print(f"⚾️ 探索開始 {'(テストモード)' if is_test_mode else ''}")
    
    # 1. NPB探索
    video_data = get_npb_video(history)
    
    # 2. NPBがない、またはMLB制限以下ならMLB
    if not video_data:
        total = stats['npb'] + stats['mlb']
        ratio = stats['mlb'] / total if total > 0 else 0
        if is_test_mode or ratio < 0.35:
            video_data = get_mlb_video(history, is_test_mode)

    if video_data:
        print(f"🎯 決定: {video_data['title']}")
        temp_input = "temp_video.mp4"
        
        # ダウンロード
        print(f"📥 ダウンロード開始...")
        if video_data['type'] == 'npb':
            subprocess.run(['yt-dlp', '-o', temp_input, '--no-check-certificates', video_data['url']])
        else:
            subprocess.run(['curl', '-L', video_data['url'], '-o', temp_input])

        if not os.path.exists(temp_input):
            print("❌ ダウンロード失敗。")
            return

        with open(history_file, 'a') as f: f.write(video_data['id'] + "\n")

        # AI解析
        res = analyze_video_with_ai(temp_input, video_data['title'], video_data['source_account'])
        start_sec, ai_caption = res if res else (0, None)
        if not ai_caption: ai_caption = f"【速報】{video_data['title']}\n\n引用：{video_data['source_account']}\n#プロ野球"
        
        # 加工・投稿
        processed_file = process_video_final(temp_input, start_sec)
        if processed_file:
            print(f"☁️ クラウドへ送出中...")
            try:
                with open(processed_file, 'rb') as f:
                    up_res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f})
                    if up_res.status_code == 200:
                        public_url = up_res.json()['data']['url'].replace('https://tmpfiles.org/', 'https://tmpfiles.org/dl/')
                        print(f"📸 Instagram投稿リクエスト中...")
                        base_url = f"https://graph.facebook.com/v21.0/{INSTA_ID}/media"
                        post_res = requests.post(base_url, data={'media_type': 'REELS', 'video_url': public_url, 'caption': ai_caption, 'access_token': ACCESS_TOKEN}).json()
                        
                        if 'id' in post_res:
                            creation_id = post_res['id']
                            for _ in range(30):
                                time.sleep(20)
                                status = requests.get(f"https://graph.facebook.com/v21.0/{creation_id}", params={'fields': 'status_code', 'access_token': ACCESS_TOKEN}).json()
                                if status.get('status_code') == 'FINISHED':
                                    requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN})
                                    print(f"🏁 投稿成功！")
                                    stats[video_data['type']] += 1
                                    save_stats(stats)
                                    break
            except Exception as e: print(f"❌ エラー: {e}")
    else:
        print("😴 条件に合う未投稿動画は見つかりませんでした。")

if __name__ == "__main__":
    main()
