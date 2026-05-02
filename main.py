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

def get_npb_video(history):
    """確実なYouTube RSS経由で動画を探索"""
    feeds = [{"name": "パ・リーグTV", "id": "UC0v-pxTo1XamIDE-f__Ad0Q"}]
    for feed in feeds:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={feed['id']}"
        try:
            res = requests.get(url, timeout=20)
            root = ET.fromstring(res.content)
            ns = {'ns': 'http://www.w3.org/2005/Atom', 'yt': 'http://www.youtube.com/xml/schemas/2015'}
            for entry in root.findall('ns:entry', ns):
                v_id = entry.find('yt:videoId', ns).text
                title = entry.find('ns:title', ns).text
                if v_id not in history:
                    return {"title": title, "url": f"https://www.youtube.com/watch?v={v_id}", "id": v_id, "type": "npb", "source": f"YouTube {feed['name']}"}
        except: continue
    return None

def get_mlb_video(history, is_test_mode):
    """MLB APIから日本人動画を探索（ブロックされない確実なルート）"""
    print(f"🔍 MLB APIをスキャン中...")
    for day_offset in range(3):
        date_str = (datetime.datetime.now() - datetime.timedelta(days=day_offset)).strftime('%Y-%m-%d')
        url = f"https://statsapi.mlb.com/api/v1/schedule/games/?sportId=1&startDate={date_str}&endDate={date_str}"
        try:
            res = requests.get(url).json()
            for date_data in res.get('dates', []):
                for game in date_data.get('games', []):
                    content = requests.get(f"https://statsapi.mlb.com/api/v1/game/{game['gamePk']}/content").json()
                    items = content.get('highlights', {}).get('highlights', {}).get('items', [])
                    for item in items:
                        title = item.get('headline', '')
                        v_id = str(item.get('id'))
                        video_url = next((p['url'] for p in item.get('playbacks', []) if p['name'] == 'mp4Avc'), None)
                        if video_url and v_id not in history:
                            if any(kw in title.lower() for kw in JPN_KEYWORDS) or is_test_mode:
                                if not any(kw in title.lower() for kw in BLACK_KEYWORDS):
                                    return {"title": title, "url": video_url, "id": v_id, "type": "mlb", "source": "@MLBJapan"}
        except: continue
    return None

def analyze_video_with_ai(video_path, title, source_account):
    print(f"🧠 AIによる動画解析中 (Gemini)...")
    try:
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING": time.sleep(2); video_file = genai.get_file(video_file.name)
        
        # あなたの環境で確実に動作するモデル名
        for m_name in ["gemini-1.5-flash", "gemini-1.5-flash-latest"]:
            try:
                model = genai.GenerativeModel(m_name)
                prompt = f"野球動画({title})を解析し、最も熱いシーンの開始秒数を「START:秒」の形式で教えろ。また、YouTubeの2ch解説動画風のキャプションを「CAPTION:内容」で作成せよ。引用：{source_account}と記載せよ。"
                response = model.generate_content([prompt, video_file])
                res_text = response.text
                genai.delete_file(video_file.name)
                start_match = re.search(r"START:(\d+)", res_text); start_sec = int(start_match.group(1)) if start_match else 0
                caption_match = re.search(r"CAPTION:(.*)", res_text, re.DOTALL); caption = caption_match.group(1).strip() if caption_match else None
                print(f"  ✨ 解析成功: {start_sec}s")
                return start_sec, caption
            except: continue
        return 0, None
    except: return 0, None

def upload_to_catbox(file_path):
    """Catbox.moe へアップロード（transfer.shよりも安定）"""
    print(f"📥 Catboxへアップロード中...")
    try:
        with open(file_path, 'rb') as f:
            res = requests.post('https://catbox.moe/user/api.php', data={'reqtype': 'fileupload'}, files={'fileToUpload': f}, timeout=120)
            if res.status_code == 200:
                url = res.text.strip()
                return url
    except Exception as e:
        print(f"❌ アップロード失敗: {e}")
    return None

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats(); history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    print(f"⚾️ 探索開始...")
    video_data = get_npb_video(history) or get_mlb_video(history, is_test_mode)

    if video_data:
        print(f"🎯 ターゲット: {video_data['title']}")
        temp_input = "temp_video.mp4"
        
        # YouTubeはブロックが酷いので、ダメなら即MLBへ
        if video_data['type'] == 'npb':
            res = subprocess.run(['yt-dlp', '-o', temp_input, '--extractor-args', 'youtube:player_client=android', video_data['url']])
            if res.returncode != 0:
                print("⚠️ YouTube遮断。MLBにフォールバックします。")
                video_data = get_mlb_video(history, is_test_mode)
                if not video_data: print("😴 候補なし"); return
                subprocess.run(['curl', '-L', video_data['url'], '-o', temp_input])
        else:
            subprocess.run(['curl', '-L', video_data['url'], '-o', temp_input])
        
        if not os.path.exists(temp_input) or os.path.getsize(temp_input) < 10000: return

        # AI & 加工
        start_sec, ai_caption = analyze_video_with_ai(temp_input, video_data['title'], video_data['source'])
        if not ai_caption: ai_caption = f"【速報】最高のプレー！\n\n引用：{video_data['source']}\n#野球"
        
        output_file = "output.mp4"
        filter_complex = "scale=1134:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
        subprocess.run(['ffmpeg', '-ss', str(start_sec), '-i', temp_input, '-t', '90', '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-b:v', '3000k', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-y', output_file])
        
        # 投稿
        public_url = upload_to_catbox(output_file)
        if public_url:
            print(f"✅ 公開URL: {public_url}")
            time.sleep(15) # 安定待機
            
            print(f"📸 Instagram送信中...")
            post_url = f"https://graph.facebook.com/v21.0/{INSTA_ID}/media"
            post_res = requests.post(post_url, data={'media_type': 'REELS', 'video_url': public_url, 'caption': ai_caption, 'access_token': ACCESS_TOKEN}).json()
            
            if 'id' in post_res:
                creation_id = post_res['id']
                print(f"⏳ 完了待機 (ID: {creation_id})...")
                for i in range(20):
                    time.sleep(30)
                    status_res = requests.get(f"https://graph.facebook.com/v21.0/{creation_id}", params={'fields': 'status_code,status', 'access_token': ACCESS_TOKEN}).json()
                    status = status_res.get('status_code') or status_res.get('status')
                    print(f"  [{i+1}/20] Status: {status}")
                    
                    if status == 'FINISHED':
                        print(f"🚀 公開実行...")
                        requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN})
                        print(f"🏁 投稿完了！")
                        with open(history_file, 'a') as fh: fh.write(video_data['id'] + "\n")
                        stats[video_data['type']] += 1; save_stats(stats); return
                    elif status == 'ERROR' or 'Error' in str(status):
                        print(f"❌ Instagramエラー: {status_res}"); return
            else: print(f"❌ コンテナ作成失敗: {post_res}")
    else: print("😴 投稿対象なし。")

if __name__ == "__main__":
    main()
