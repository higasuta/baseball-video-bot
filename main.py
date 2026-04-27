import requests
import datetime
import os
import time
import subprocess
import google.generativeai as genai
import json
import re
import xml.etree.ElementTree as ET

# ==========================================
# 設定・環境変数の読み込み
# ==========================================
INSTA_ID = os.getenv('INSTA_BUSINESS_ID')
ACCESS_TOKEN = os.getenv('INSTA_ACCESS_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

JPN_MLB_KEYWORDS = ["ohtani", "yamamoto", "imanaga", "darvish", "suzuki", "yoshida", "senga", "matsui", "maeda", "kikuchi"]

def get_stats():
    if os.path.exists('stats.json'):
        try:
            with open('stats.json', 'r') as f: return json.load(f)
        except: pass
    return {"npb": 7, "mlb": 3}

def save_stats(stats):
    with open('stats.json', 'w') as f: json.dump(stats, f)

def get_npb_video(history):
    feeds = [
        {"name": "NPB公式", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UC7vYid8pCUpIOn85X_2f_ig"},
        {"name": "パ・リーグ公式", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UC0v-pxTo1XamIDE-f__Ad0Q"}
    ]
    for feed in feeds:
        try:
            response = requests.get(feed['url'], timeout=10)
            root = ET.fromstring(response.content)
            ns = {'ns': 'http://www.w3.org/2005/Atom', 'yt': 'http://www.youtube.com/xml/schemas/2015'}
            for entry in root.findall('ns:entry', ns):
                video_id = entry.find('yt:videoId', ns).text
                if video_id not in history:
                    return {"title": entry.find('ns:title', ns).text, "url": f"https://www.youtube.com/watch?v={video_id}", "id": video_id, "type": "npb"}
        except: continue
    return None

def get_mlb_video(history, is_test_mode):
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
                    desc = item.get('description', '')
                    video_id = str(item.get('id'))
                    if video_id in history: continue
                    video_url = next((p['url'] for p in item['playbacks'] if p['name'] == 'mp4Avc'), None)
                    if not video_url: continue
                    is_jpn = any(name in title.lower() or name in desc.lower() for name in JPN_MLB_KEYWORDS)
                    if is_jpn or is_test_mode:
                        return {"title": title, "desc": desc, "url": video_url, "id": video_id, "type": "mlb", "is_hot": False}
        except: continue
    return None

def analyze_video_with_ai(video_path, title):
    """Geminiに動画を解析させる（最新モデルリスト対応版）"""
    if not os.path.exists(video_path): return 0, None
    print(f"🧠 AIによる動画解析中...")
    try:
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING":
            time.sleep(2)
            video_file = genai.get_file(video_file.name)

        # ログに基づいて利用可能なモデル名を修正
        candidate_models = ["gemini-2.0-flash", "gemini-flash-latest", "gemini-1.5-flash"]
        
        res_text = ""
        for model_name in candidate_models:
            try:
                print(f"  👉 モデル {model_name} を試行中...")
                model = genai.GenerativeModel(model_name)
                prompt = (
                    f"この野球動画（タイトル：{title}）を解析してください。\n\n"
                    "1. 最も盛り上がっている見どころの開始秒数を「START:秒」で教えてください（不明なら0）。\n"
                    "2. 2ch野球スレまとめ解説動画のナレーター風に、熱いキャプションを作成してください。\n"
                    "見出し、要約、所感の3段構成。ハッシュタグ25個以上（中黒・は禁止）。\n\n"
                    "出力形式：\nSTART:[秒]\nCAPTION:[内容]"
                )
                response = model.generate_content([prompt, video_file])
                res_text = response.text
                if res_text: break
            except:
                continue

        genai.delete_file(video_file.name)

        if not res_text:
            return 0, None

        start_match = re.search(r"START:(\d+)", res_text)
        start_sec = int(start_match.group(1)) if start_match else 0
        caption_match = re.search(r"CAPTION:(.*)", res_text, re.DOTALL)
        caption = caption_match.group(1).strip() if caption_match else None
        return start_sec, caption
    except Exception as e:
        print(f"⚠️ AI解析失敗: {e}")
        return 0, None

def process_video_final(input_file, start_sec, title):
    if not os.path.exists(input_file): return None
    output_file = "output.mp4"
    is_vertical = "#shorts" in title.lower()
    print(f"✂️ 加工中 (Start: {start_sec}s / Vertical: {is_vertical})...")
    
    if is_vertical:
        filter_complex = "scale=1080:-2,pad=1080:1920:(1080-iw)/2:(1920-ih)/2:color=black,setsar=1"
    else:
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
        mlb_item = get_mlb_video(history, is_test_mode)
        if mlb_item:
            total = stats['npb'] + stats['mlb']
            ratio = stats['mlb'] / total if total > 0 else 0
            if is_test_mode or ratio < 0.35:
                video_data = mlb_item

    if video_data:
        print(f"🎯 ターゲット確定: {video_data['title']}")
        temp_input = "temp_video.mp4"
        
        # YouTubeダウンロード (Android偽装)
        print(f"📥 ダウンロード開始...")
        cmd = [
            'yt-dlp', '-o', temp_input,
            '--no-check-certificates',
            '--extractor-args', 'youtube:player_client=android',
            '--format', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]',
            video_data['url']
        ]
        subprocess.run(cmd)

        if not os.path.exists(temp_input):
            print("❌ ダウンロードに失敗しました。")
            return

        with open(history_file, 'a') as f: f.write(video_data['id'] + "\n")

        # AI解析 (ここでのTypeErrorを回避)
        res = analyze_video_with_ai(temp_input, video_data['title'])
        start_sec, ai_caption = res if res else (0, None)
        
        if not ai_caption: 
            ai_caption = f"【速報】{video_data['title']}\n#プロ野球 #NPB #MLB"
        
        processed_file = process_video_final(temp_input, start_sec, video_data['title'])
        
        if processed_file:
            print(f"☁️ アップロード中...")
            try:
                with open(processed_file, 'rb') as f:
                    res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f})
                    if res.status_code == 200:
                        public_url = res.json()['data']['url'].replace('https://tmpfiles.org/', 'https://tmpfiles.org/dl/')
                        
                        print(f"📸 Instagram投稿中...")
                        base_url = f"https://graph.facebook.com/v21.0/{INSTA_ID}/media"
                        post_res = requests.post(base_url, data={'media_type': 'REELS', 'video_url': public_url, 'caption': ai_caption, 'access_token': ACCESS_TOKEN}).json()
                        
                        if 'id' in post_res:
                            creation_id = post_res['id']
                            for _ in range(30):
                                time.sleep(20)
                                status = requests.get(f"https://graph.facebook.com/v21.0/{creation_id}", params={'fields': 'status_code', 'access_token': ACCESS_TOKEN}).json()
                                if status.get('status_code') == 'FINISHED':
                                    requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN})
                                    print(f"🏁 投稿完了！")
                                    stats[video_data['type']] += 1
                                    save_stats(stats)
                                    break
            except Exception as e:
                print(f"❌ 投稿エラー: {e}")
    else:
        print("😴 投稿対象なし。")

if __name__ == "__main__":
    main()
