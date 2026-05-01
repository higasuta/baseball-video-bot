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
    """YouTube RSSからNPB動画を取得"""
    feeds = [{"name": "パ・リーグTV", "id": "UC0v-pxTo1XamIDE-f__Ad0Q"}]
    for feed in feeds:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={feed['id']}"
        print(f"🔍 RSSチェック中: {feed['name']}")
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
    """MLB APIから動画を取得（ブロックされない確実なルート）"""
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

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats(); history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    print(f"⚾️ 探索開始...")
    video_data = get_npb_video(history)
    if not video_data:
        video_data = get_mlb_video(history, is_test_mode)

    if video_data:
        print(f"🎯 ターゲット: {video_data['title']}")
        temp_input = "temp_video.mp4"
        
        # ダウンロード（YouTubeならandroid偽装、MLBならcurl）
        if video_data['type'] == 'npb':
            subprocess.run(['yt-dlp', '-o', temp_input, '--extractor-args', 'youtube:player_client=android', video_data['url']])
        else:
            subprocess.run(['curl', '-L', video_data['url'], '-o', temp_input])
        
        if not os.path.exists(temp_input) or os.path.getsize(temp_input) < 5000:
            print("⚠️ NPBダウンロード失敗。MLBへ切り替えます。")
            video_data = get_mlb_video(history, is_test_mode)
            if video_data:
                subprocess.run(['curl', '-L', video_data['url'], '-o', temp_input])
            else: print("😴 候補なし"); return

        # AI解析
        print(f"🧠 AI解析中...")
        ai_caption = None; start_sec = 0
        try:
            video_file = genai.upload_file(path=temp_input)
            while video_file.state.name == "PROCESSING": time.sleep(2); video_file = genai.get_file(video_file.name)
            model = genai.GenerativeModel("gemini-1.5-flash-latest")
            prompt = f"野球動画({video_data['title']})を解析し「START:秒」と「CAPTION:内容」を出力せよ。引用：{video_data['source']}と記載せよ。"
            response = model.generate_content([prompt, video_file])
            res_text = response.text
            genai.delete_file(video_file.name)
            start_match = re.search(r"START:(\d+)", res_text); start_sec = int(start_match.group(1)) if start_match else 0
            caption_match = re.search(r"CAPTION:(.*)", res_text, re.DOTALL); ai_caption = caption_match.group(1).strip() if caption_match else None
        except: print("⚠️ AI解析失敗。デフォルトを使用。")

        if not ai_caption: ai_caption = f"【朗報】最高のプレー！\n\n引用：{video_data['source']}\n#プロ野球"
        
        # 加工（高画質化 2500k）
        output_file = "output.mp4"
        filter_complex = "scale=1134:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
        subprocess.run(['ffmpeg', '-ss', str(start_sec), '-i', temp_input, '-t', '90', '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-b:v', '2500k', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-y', output_file])
        
        # Instagram投稿
        try:
            with open(output_file, 'rb') as f:
                up_res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f})
                if up_res.status_code == 200:
                    public_url = up_res.json()['data']['url'].replace('https://tmpfiles.org/', 'https://tmpfiles.org/dl/')
                    print(f"📥 保存完了。15秒待機...")
                    time.sleep(15)

                    print(f"📸 Instagram送信中...")
                    post_res = requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media", data={'media_type': 'REELS', 'video_url': public_url, 'caption': ai_caption, 'access_token': ACCESS_TOKEN}).json()
                    
                    if 'id' in post_res:
                        creation_id = post_res['id']
                        print(f"⏳ 完了待機 (ID: {creation_id})...")
                        for i in range(20):
                            time.sleep(30)
                            # status_code または status の両方をチェック
                            status_res = requests.get(f"https://graph.facebook.com/v21.0/{creation_id}?fields=status_code,status&access_token={ACCESS_TOKEN}").json()
                            print(f"  [{i+1}/20] API Response: {status_res}")
                            status = status_res.get('status_code') or status_res.get('status')
                            
                            if status == 'FINISHED':
                                print(f"🚀 公開実行...")
                                requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN})
                                with open(history_file, 'a') as fh: fh.write(video_data['id'] + "\n")
                                stats[video_data['type']] += 1; save_stats(stats)
                                print(f"🏁 投稿完了！"); return
                            elif status == 'ERROR':
                                print(f"❌ 処理失敗。"); return
                    else: print(f"❌ コンテナ作成失敗: {post_res}")
        except Exception as e: print(f"❌ エラー: {e}")
    else: print("😴 投稿対象なし。")

if __name__ == "__main__":
    main()
