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
    """RSSフィードから動画候補を取得"""
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

def analyze_video_with_ai(video_path, title):
    """Gemini 1.5 Flashに動画を解析させ、切り抜き秒数とキャプションを決めてもらう"""
    print(f"🧠 AIによる動画解析を開始...")
    try:
        # 動画をGeminiにアップロード
        video_file = genai.upload_file(path=video_path)
        
        # 処理完了を待機
        while video_file.state.name == "PROCESSING":
            time.sleep(2)
            video_file = genai.get_file(video_file.name)

        model = genai.GenerativeModel("gemini-1.5-flash-latest")
        prompt = (
            f"この野球動画（タイトル：{title}）を解析してください。\n\n"
            "1. 動画の中で最も盛り上がっている「見どころ」を60秒〜90秒以内で特定し、その開始秒数を「START:秒」の形式で教えてください。\n"
            "2. 動画の内容に基づき、2ch野球スレまとめ風の熱いキャプションを作成してください。\n\n"
            "出力形式：\n"
            "START:[秒数]\n"
            "CAPTION:[作成したキャプション]"
        )
        
        response = model.generate_content([prompt, video_file])
        res_text = response.text
        
        # 解析結果から秒数とキャプションを抽出
        start_match = re.search(r"START:(\d+)", res_text)
        start_sec = int(start_match.group(1)) if start_match else 0
        
        caption_match = re.search(r"CAPTION:(.*)", res_text, re.DOTALL)
        caption = caption_match.group(1).strip() if caption_match else "【速報】野球まとめ"
        
        # ファイルを削除（クリーンアップ）
        genai.delete_file(video_file.name)
        
        return start_sec, caption
    except Exception as e:
        print(f"AI解析失敗: {e}")
        return 0, None

def process_video_final(input_url, start_sec):
    """動画加工：AIが決めた開始時間から90秒切り抜く"""
    input_file = "input.mp4"
    output_file = "output.mp4"
    print(f"📥 ダウンロード中...")
    subprocess.run(['yt-dlp', '-o', input_file, '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]', input_url])
    
    print(f"✂️ AI推奨の {start_sec}秒目から切り抜き加工中...")
    # -ss [開始秒] -t 90 [期間]
    filter_complex = "scale=1134:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
    subprocess.run([
        'ffmpeg', '-ss', str(start_sec), '-i', input_file, 
        '-t', '90', '-vf', filter_complex, 
        '-r', '30', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'fast', '-crf', '23', '-c:a', 'aac', '-b:a', '128k', '-y', output_file
    ])
    return output_file

# --- 投稿・MLBスキャン等は前回と同じため省略(main内から呼び出し) ---

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats()
    history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    video_data = get_npb_video(history) # ここではMLBも同様のフロー
    # (MLBスキャンロジックが入る)

    if video_data:
        print(f"🎯 ターゲット確定: {video_data['title']}")
        # まずは解析用に生動画をダウンロード
        raw_file = "raw_input.mp4"
        subprocess.run(['yt-dlp', '-o', raw_file, '--match-filter', 'duration < 600', '-f', 'mp4', video_data['url']])
        
        # AIに解析させて秒数とキャプションを決定！
        start_sec, ai_caption = analyze_video_with_ai(raw_file, video_data['title'])
        
        # 決定した秒数でリール加工
        processed_file = process_video_final(video_data['url'], start_sec)
        
        # あとはアップロード
        # (upload_video, post_reelsを呼び出す)
        print(f"🏁 AIが選んだ {start_sec}秒から切り抜いた動画を投稿します。")
        # ... 以降、既存の投稿処理 ...
