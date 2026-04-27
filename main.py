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
    """RSSフィードから新着動画を取得"""
    feeds = [
        {"name": "NPB公式", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UC7vYid8pCUpIOn85X_2f_ig"},
        {"name": "パ・リーグ公式", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UC0v-pxTo1XamIDE-f__Ad0Q"}
    ]
    for feed in feeds:
        print(f"🔍 NPBスキャン中 (RSS): {feed['name']}")
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
    """MLB日本人ハイライトをAPIから取得"""
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
                        is_hot = any(kw in title.lower() or kw in desc.lower() for kw in HOT_KEYWORDS)
                        return {"title": title, "desc": desc, "url": video_url, "id": video_id, "type": "mlb", "is_hot": is_hot}
        except: continue
    return None

def analyze_video_with_ai(video_path, title):
    """Gemini 1.5 Flashに動画を解析させ、切り抜き開始位置とキャプションを決定"""
    print(f"🧠 AIによる動画解析中 (Gemini 1.5 Flash)...")
    try:
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING":
            time.sleep(2)
            video_file = genai.get_file(video_file.name)

        model = genai.GenerativeModel("gemini-1.5-flash-latest")
        prompt = (
            f"この野球動画（タイトル：{title}）を解析してください。\n\n"
            "1. 最も盛り上がっている見どころの開始秒数を「START:秒」で教えてください（不明なら0）。\n"
            "2. 2ch野球スレまとめ解説動画のナレーター風に、熱いキャプションを作成してください。\n"
            "見出し、要約、所感の3段構成。ハッシュタグ25個以上（中黒・は禁止）。\n\n"
            "出力形式：\nSTART:[秒]\nCAPTION:[内容]"
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

def process_video_v6(input_url, start_sec):
    """動画加工：AI指定の開始位置から90秒切り抜き＆縦長化"""
    input_file = "input.mp4"
    output_file = "output.mp4"
    print(f"📥 動画ダウンロード中...")
    subprocess.run(['yt-dlp', '-o', input_file, '-f', 'mp4', input_url])
    
    print(f"✂️ AI推奨の {start_sec}秒から90秒間を切り抜き加工...")
    filter_complex = "scale=1134:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
    subprocess.run([
        'ffmpeg', '-ss', str(start_sec), '-i', input_file, 
        '-t', '90', '-vf', filter_complex, 
        '-r', '30', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'fast', '-crf', '23', '-c:a', 'aac', '-b:a', '128k', '-y', output_file
    ])
    return output_file

def upload_video(file_path):
    print(f"☁️ クラウドへ一時保存中...")
    try:
        with open(file_path, 'rb') as f:
            res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f})
            if res.status_code == 200:
                url = res.json()['data']['url']
                return url.replace('http://', 'https://').replace('https://tmpfiles.org/', 'https://tmpfiles.org/dl/')
    except: return None

def post_reels(video_url, caption):
    print(f"📸 Instagram投稿中...")
    base_url = f"https://graph.facebook.com/v21.0/{INSTA_ID}/media"
    res = requests.post(base_url, data={'media_type': 'REELS', 'video_url': video_url, 'caption': caption, 'access_token': ACCESS_TOKEN}).json()
    if 'id' not in res: return None
    creation_id = res['id']
    print(f"⏳ 処理待ち中...")
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
            if is_test_mode or mlb_item['is_hot'] or ratio < 0.35:
                video_data = mlb_item
            else:
                print(f"🛑 MLB投稿制限中 (NPB待ち)")

    if video_data:
        print(f"🎯 ターゲット確定: {video_data['title']}")
        with open(history_file, 'a') as f: f.write(video_data['id'] + "\n")
        
        # まず解析用に生ファイルをダウンロード
        raw_file = "raw_input.mp4"
        subprocess.run(['yt-dlp', '-o', raw_file, '-f', 'mp4', video_data['url']])
        
        # AI解析
        start_sec, ai_caption = analyze_video_with_ai(raw_file, video_data['title'])
        if not ai_caption: ai_caption = f"【速報】{video_data['title']}\n#プロ野球 #MLB"
        
        # 加工
        processed_file = process_video_v6(video_data['url'], start_sec)
        public_url = upload_video(processed_file)
        
        if public_url:
            result = post_reels(public_url, ai_caption)
            if result and 'id' in result:
                print(f"🏁 投稿成功！")
                stats[video_data['type']] += 1
                save_stats(stats)
            else: print(f"❌ 公開失敗")
    else:
        print("😴 投稿対象なし。")

if __name__ == "__main__":
    main()
