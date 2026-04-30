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

def fetch_from_nitter(source_url, history, check_keywords=False):
    """Nitter経由で動画をスキャンする共通ロジック"""
    user_handle = source_url.split('/')[-1]
    print(f"🔍 nitter.net で @{user_handle} をスキャン中...")
    
    # yt-dlpにNitter経由で最新動画を取得させる
    cmd = [
        'yt-dlp', '--get-id', '--get-title', '--get-url', '--print', 'upload_date',
        '--playlist-end', '10', 
        '--match-filter', "duration < 300 & !is_live",
        '--no-check-certificates',
        '--quiet', '--no-warnings',
        source_url
    ]
    
    try:
        process = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if process.returncode != 0:
            print(f"  ⚠️ Nitter経由でも取得できませんでした。")
            return None

        lines = [l for l in process.stdout.split('\n') if l.strip()]
        print(f"  👉 取得候補数: {len(lines)//4}件")

        for i in range(0, len(lines)-3, 4):
            title, video_id, video_url, upload_date = lines[i], lines[i+1], lines[i+2], lines[i+3]
            
            if video_id in history: continue
            
            if check_keywords:
                if not any(kw in title.lower() for kw in JPN_KEYWORDS): continue
            
            if any(kw in title.lower() for kw in BLACK_KEYWORDS): continue

            print(f"✅ ターゲット特定: {title}")
            return {
                "title": title, "url": video_url, "id": video_id, 
                "source_account": f"@{user_handle}"
            }
    except:
        return None
    return None

def get_npb_video(history):
    # すべて nitter.net 経由に書き換え
    nitter_sources = [
        "https://nitter.net/PacificleagueTV",
        "https://nitter.net/sportsnavi_ybB",
        "https://nitter.net/BaseballkingJP",
        "https://nitter.net/FullcountJP",
        "https://nitter.net/DAZN_JPN",
        "https://nitter.net/ABEMA_baseball",
        "https://nitter.net/tvtokyo_sports",
        "https://nitter.net/nikkan_yakyuu",
        "https://nitter.net/jsports_yakyu",
        "https://nitter.net/easysportsJP",
        "https://nitter.net/sptv_yakyu"
    ]
    for src in nitter_sources:
        res = fetch_from_nitter(src, history)
        if res:
            res['type'] = 'npb'
            return res
    return None

def get_mlb_video(history, is_test_mode):
    # MLBも nitter.net 経由でテスト
    src = "https://nitter.net/MLBJapan"
    res = fetch_from_nitter(src, history, check_keywords=(not is_test_mode))
    if res:
        res['type'] = 'mlb'
        return res
    return None

def analyze_video_with_ai(video_path, title, source_account):
    print(f"🧠 AIによる動画解析中 (Gemini)...")
    try:
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING": time.sleep(2); video_file = genai.get_file(video_file.name)
        model = genai.GenerativeModel("gemini-1.5-flash-latest")
        prompt = (f"野球動画（タイトル：{title}）を解析せよ。\n1. 見どころ開始秒数を「START:秒」で。\n2. 熱いキャプションを作成。最後に『引用：{source_account}』と記載。\nSTART:[秒]\nCAPTION:[内容]")
        response = model.generate_content([prompt, video_file])
        res_text = response.text
        genai.delete_file(video_file.name)
        start_match = re.search(r"START:(\d+)", res_text); start_sec = int(start_match.group(1)) if start_match else 0
        caption_match = re.search(r"CAPTION:(.*)", res_text, re.DOTALL); caption = caption_match.group(1).strip() if caption_match else None
        print(f"  ✨ 解析成功: {start_sec}s")
        return start_sec, caption
    except: return 0, None

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats(); history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    print(f"⚾️ 探索開始 {'(Nitterテストモード)' if is_test_mode else ''}")
    
    # 1. NPBスキャン (Nitter経由)
    video_data = get_npb_video(history)
    
    # 2. なければMLBスキャン (Nitter経由)
    if not video_data:
        video_data = get_mlb_video(history, is_test_mode)

    if video_data:
        temp_input = "temp_video.mp4"
        print(f"📥 ダウンロード開始: {video_data['url']}")
        subprocess.run(['curl', '-L', video_data['url'], '-o', temp_input])
        
        if not os.path.exists(temp_input) or os.path.getsize(temp_input) < 1000:
            print("❌ 動画ファイルの取得に失敗しました。"); return

        # 解析・加工
        start_sec, ai_caption = analyze_video_with_ai(temp_input, video_data['title'], video_data['source_account'])
        if not ai_caption: ai_caption = f"【朗報】最高のプレー！\n\n引用：{video_data['source_account']}\n#プロ野球"
        
        output_file = "output.mp4"
        filter_complex = "scale=1134:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
        subprocess.run(['ffmpeg', '-ss', str(start_sec), '-i', temp_input, '-t', '90', '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-b:v', '3M', '-pix_fmt', 'yuv420p', '-preset', 'fast', '-crf', '18', '-movflags', '+faststart', '-y', output_file])
        
        try:
            with open(output_file, 'rb') as f:
                up_res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f})
                if up_res.status_code == 200:
                    public_url = up_res.json()['data']['url'].replace('https://tmpfiles.org/', 'https://tmpfiles.org/dl/')
                    print(f"📥 クラウド保存完了。安定のため15秒待機...")
                    time.sleep(15)

                    print(f"📸 Instagramへ動画を送信中...")
                    post_res = requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media", data={'media_type': 'REELS', 'video_url': public_url, 'caption': ai_caption, 'access_token': ACCESS_TOKEN}).json()
                    
                    if 'id' in post_res:
                        creation_id = post_res['id']
                        print(f"⏳ 処理待機 (ID: {creation_id})...")
                        for i in range(30):
                            time.sleep(30)
                            status_res = requests.get(f"https://graph.facebook.com/v21.0/{creation_id}", params={'fields': 'status_code', 'access_token': ACCESS_TOKEN}).json()
                            status = status_res.get('status_code')
                            print(f"  [{i+1}/30] API Status: {status}")
                            
                            if status == 'FINISHED':
                                print(f"🚀 公開実行...")
                                pub_res = requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN}).json()
                                if 'id' in pub_res:
                                    print(f"🏁 投稿完了！")
                                    with open(history_file, 'a') as fh: fh.write(video_data['id'] + "\n")
                                    stats[video_data['type']] += 1
                                    save_stats(stats); return
                            elif status == 'ERROR':
                                print(f"❌ Instagramエラー: {status_res}"); return
                    else: print(f"❌ コンテナ作成失敗: {post_res}")
        except Exception as e: print(f"❌ システムエラー: {e}")
    else:
        print("😴 Nitter経由でも新しい動画は見つかりませんでした（またはブロック中です）。")

if __name__ == "__main__":
    main()
