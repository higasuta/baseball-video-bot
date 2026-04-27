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

# 日本人選手フィルター
JPN_KEYWORDS = ["大谷", "山本", "ダルビッシュ", "鈴木誠也", "吉田正尚", "今永", "松井裕樹", "千賀", "前田健太", "菊池雄星", "ohtani", "yamamoto"]

def get_stats():
    if os.path.exists('stats.json'):
        try:
            with open('stats.json', 'r') as f: return json.load(f)
        except: pass
    return {"npb": 7, "mlb": 3}

def save_stats(stats):
    with open('stats.json', 'w') as f: json.dump(stats, f)

def fetch_x_video(url_list, history, check_keywords=False):
    """XのURLリストから動画を探す"""
    week_ago = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime('%Y%m%d')
    
    for src in url_list:
        user_name = src.split('/')[-1]
        print(f"🔍 スキャン中: @{user_name}")
        try:
            cmd = [
                'yt-dlp', 
                '--get-id', '--get-title', '--get-url', '--print', 'upload_date',
                '--playlist-end', '40', 
                '--match-filter', "duration < 240 & !is_live",
                '--no-check-certificates',
                '--quiet', '--no-warnings',
                src
            ]
            process = subprocess.run(cmd, capture_output=True, text=True)
            output = process.stdout.split('\n')
            
            if process.returncode != 0:
                print(f"  ⚠️ yt-dlpエラー: {process.stderr[:100]}")
                continue

            lines = [l for l in output if l.strip()]
            print(f"  👉 {len(lines) // 4}件の動画候補を取得しました")

            for i in range(0, len(lines)-3, 4):
                title = lines[i]
                video_id = lines[i+1]
                video_url = lines[i+2]
                upload_date = lines[i+3]
                
                if not video_id or video_id in history:
                    continue
                
                if upload_date < week_ago:
                    continue

                if check_keywords and not any(kw in title.lower() for kw in JPN_KEYWORDS):
                    continue
                
                print(f"✅ ターゲット発見！ ({upload_date}): {title}")
                return {
                    "title": title, "url": video_url, "id": video_id, "source_account": f"@{user_name}"
                }
        except Exception as e:
            print(f"  ❌ エラー: {e}")
            continue
    return None

def get_npb_video(history):
    sources = [
        "https://x.com/PacificleagueTV",
        "https://x.com/sportsnavi_ybB",
        "https://x.com/BaseballkingJP",
        "https://x.com/FullcountJP",
        "https://x.com/DAZN_JPN",
        "https://x.com/ABEMA_baseball",
        "https://x.com/tvtokyo_sports",
        "https://x.com/nikkan_yakyuu",
        "https://x.com/jsports_yakyu",
        "https://x.com/easysportsJP",
        "https://x.com/sptv_yakyu"
    ]
    data = fetch_x_video(sources, history)
    if data: data['type'] = 'npb'
    return data

def get_mlb_video(history):
    sources = ["https://x.com/MLBJapan"]
    data = fetch_x_video(sources, history, check_keywords=True)
    if data: data['type'] = 'mlb'
    return data

def analyze_video_with_ai(video_path, title, source_account):
    if not os.path.exists(video_path): return 0, None
    print(f"🧠 AIによる動画解析中...")
    try:
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING":
            time.sleep(2)
            video_file = genai.get_file(video_file.name)

        candidate_models = ["gemini-2.0-flash", "gemini-flash-latest"]
        res_text = ""
        for model_name in candidate_models:
            try:
                print(f"  👉 モデル {model_name} を試行中...")
                model = genai.GenerativeModel(model_name)
                prompt = (
                    f"この野球動画（タイトル：{title}）を解析してください。\n\n"
                    "1. 最も盛り上がっている場面の開始秒数を「START:秒」で教えてください。\n"
                    "2. 2ch野球スレまとめ風の語り口調で熱いキャプションを作成してください。\n"
                    f"3. 最後に必ず『引用：{source_account}』と記載してください。\n\n"
                    "START:[秒]\nCAPTION:[内容]"
                )
                response = model.generate_content([prompt, video_file])
                res_text = response.text
                if res_text: break
            except: continue

        genai.delete_file(video_file.name)
        if not res_text: return 0, None

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
    
    video_data = get_npb_video(history)
    if not video_data:
        total = stats['npb'] + stats['mlb']
        ratio = stats['mlb'] / total if total > 0 else 0
        if is_test_mode or ratio < 0.35:
            video_data = get_mlb_video(history)

    if video_data:
        print(f"🎯 決定: {video_data['title']}")
        temp_input = "temp_video.mp4"
        
        print(f"📥 ダウンロード開始...")
        subprocess.run(['yt-dlp', '-o', temp_input, '--no-check-certificates', video_data['url']])

        if not os.path.exists(temp_input):
            print("❌ ダウンロード失敗。")
            return

        with open(history_file, 'a') as f: f.write(video_data['id'] + "\n")

        res = analyze_video_with_ai(temp_input, video_data['title'], video_data['source_account'])
        start_sec, ai_caption = res if res else (0, None)
        if not ai_caption: ai_caption = f"【速報】{video_data['title']}\n\n引用：{video_data['source_account']}\n#プロ野球"
        
        processed_file = process_video_final(temp_input, start_sec)
        
        print(f"☁️ サーバーアップロード中...")
        try:
            with open(processed_file, 'rb') as f:
                up_res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f})
                if up_res.status_code == 200:
                    public_url = up_res.json()['data']['url'].replace('https://tmpfiles.org/', 'https://tmpfiles.org/dl/')
                    
                    print(f"📸 Instagram投稿中...")
                    base_url = f"https://graph.facebook.com/v21.0/{INSTA_ID}/media"
                    post_data = {'media_type': 'REELS', 'video_url': public_url, 'caption': ai_caption, 'access_token': ACCESS_TOKEN}
                    post_res = requests.post(base_url, data=post_data).json()
                    
                    if 'id' in post_res:
                        creation_id = post_res['id']
                        for _ in range(30):
                            time.sleep(20)
                            status_url = f"https://graph.facebook.com/v21.0/{creation_id}"
                            status = requests.get(status_url, params={'fields': 'status_code', 'access_token': ACCESS_TOKEN}).json()
                            if status.get('status_code') == 'FINISHED':
                                requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN})
                                print(f"🏁 投稿完了！")
                                stats[video_data['type']] += 1
                                save_stats(stats)
                                break
                    else:
                        print(f"❌ Instagram投稿失敗: {post_res}")
                else:
                    print(f"❌ クラウドアップロード失敗: {up_res.status_code}")
        except Exception as e:
            print(f"❌ プロセスエラー: {e}")
    else:
        print("😴 条件に合う未投稿の動画は見つかりませんでした。")

if __name__ == "__main__":
    main()
