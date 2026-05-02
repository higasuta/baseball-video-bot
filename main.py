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
    """YouTube RSSから動画を取得（ discovery はRSSが最も確実 ）"""
    feeds = [
        {"name": "パ・リーグTV", "id": "UC0v-pxTo1XamIDE-f__Ad0Q"},
        {"name": "NPB公式", "id": "UC7vYid8pCUpIOn85X_2f_ig"}
    ]
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
                    print(f"✅ 新着発見: {title}")
                    return {"title": title, "url": f"https://www.youtube.com/watch?v={v_id}", "id": v_id, "type": "npb", "source": f"YouTube {feed['name']}"}
        except: continue
    return None

def get_mlb_video(history, is_test_mode):
    """MLB APIから取得"""
    print(f"🔍 MLB APIスキャン中...")
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
                        v_id = str(item.get('id'))
                        video_url = next((p['url'] for p in item.get('playbacks', []) if p['name'] == 'mp4Avc'), None)
                        if video_url and v_id not in history:
                            if any(kw in title.lower() for kw in JPN_KEYWORDS) or is_test_mode:
                                if not any(kw in title.lower() for kw in BLACK_KEYWORDS):
                                    return {"title": title, "url": video_url, "id": v_id, "type": "mlb", "source": "@MLBJapan"}
        except: continue
    return None

def download_with_retry(video_data, output_path):
    """YouTubeブロックを回避するために中継API(Invidious)を使用"""
    if video_data['type'] == 'mlb':
        # MLBは直リンクなのでcurlでOK
        subprocess.run(['curl', '-L', video_data['url'], '-o', output_path])
        return os.path.exists(output_path) and os.path.getsize(output_path) > 5000

    # NPB(YouTube)の場合：中継サーバー（Invidious）経由でダウンロード
    video_id = video_data['id']
    instances = ["https://yewtu.be", "https://invidious.snopyta.org", "https://vid.puffyan.us"]
    for ins in instances:
        print(f"📥 中継サーバー試行中: {ins}")
        try:
            # 動画ストリームURLをAPIから取得
            api_url = f"{ins}/api/v1/videos/{video_id}"
            video_info = requests.get(api_url, timeout=20).json()
            # 最高画質のURLを探す
            formats = video_info.get('formatStreams', [])
            if not formats: continue
            
            stream_url = formats[0]['url']
            subprocess.run(['curl', '-L', stream_url, '-o', output_path], timeout=60)
            if os.path.exists(output_path) and os.path.getsize(output_path) > 10000:
                return True
        except: continue
    
    # 最終手段：通常のyt-dlp
    print("📥 最終手段(yt-dlp)を試行...")
    subprocess.run(['yt-dlp', '-o', output_path, '--extractor-args', 'youtube:player_client=android', video_data['url']])
    return os.path.exists(output_path) and os.path.getsize(output_path) > 10000

def analyze_video_with_ai(video_path, title, source_account):
    print(f"🧠 AI解析中...")
    try:
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING": time.sleep(2); video_file = genai.get_file(video_file.name)
        
        # あなたの環境で動作するモデル名のリスト
        for m_name in ["gemini-2.0-flash", "gemini-flash-latest"]:
            try:
                model = genai.GenerativeModel(m_name)
                prompt = f"野球動画({title})を解析し「START:秒」と「CAPTION:内容」を出力せよ。引用：{source_account}と記載せよ。"
                response = model.generate_content([prompt, video_file])
                res_text = response.text
                genai.delete_file(video_file.name)
                start_match = re.search(r"START:(\d+)", res_text); start_sec = int(start_match.group(1)) if start_match else 0
                caption_match = re.search(r"CAPTION:(.*)", res_text, re.DOTALL); ai_caption = caption_match.group(1).strip() if caption_match else None
                if ai_caption: 
                    print(f"  ✨ AI解析成功: 開始 {start_sec}s")
                    return start_sec, ai_caption
            except: continue
        return 0, None
    except: return 0, None

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats(); history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    print(f"⚾️ 探索開始...")
    video_data = get_npb_video(history) or get_mlb_video(history, is_test_mode)

    if video_data:
        print(f"🎯 ターゲット決定: {video_data['title']}")
        temp_input = "temp_video.mp4"
        
        if not download_with_retry(video_data, temp_input):
            print("❌ ダウンロード全ルート失敗。"); return

        start_sec, ai_caption = analyze_video_with_ai(temp_input, video_data['title'], video_data['source'])
        if not ai_caption: ai_caption = f"【速報】最高のプレー！\n\n引用：{video_data['source']}\n#プロ野球"
        
        output_file = "output.mp4"
        filter_complex = "scale=1134:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
        # ビットレートを 3000k に固定（Instagramの拒絶防止）
        subprocess.run(['ffmpeg', '-ss', str(start_sec), '-i', temp_input, '-t', '90', '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-b:v', '3000k', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-y', output_file])
        
        try:
            print(f"📥 クラウドへアップロード中...")
            with open(output_file, 'rb') as f:
                # Catbox.moeを使用
                up_res = requests.post('https://catbox.moe/user/api.php', data={'reqtype': 'fileupload'}, files={'fileToUpload': f}, timeout=120)
                if up_res.status_code == 200:
                    public_url = up_res.text.strip()
                    print(f"✅ 公開URL: {public_url}")
                    time.sleep(15) 

                    print(f"📸 Instagram送信開始...")
                    post_url = f"https://graph.facebook.com/v21.0/{INSTA_ID}/media"
                    post_res = requests.post(post_url, data={'media_type': 'REELS', 'video_url': public_url, 'caption': ai_caption, 'access_token': ACCESS_TOKEN}).json()
                    
                    if 'id' in post_res:
                        creation_id = post_res['id']
                        print(f"⏳ 待機 (ID: {creation_id})...")
                        for i in range(20):
                            time.sleep(30)
                            # fieldsから不備のある failure_reason を除去し、APIの挙動を安定化
                            status_res = requests.get(f"https://graph.facebook.com/v21.0/{creation_id}", params={'fields': 'status_code,status', 'access_token': ACCESS_TOKEN}).json()
                            status = (status_res.get('status_code') or status_res.get('status') or "").upper()
                            print(f"  [{i+1}/20] API Response: {status_res}")
                            
                            if 'FINISHED' in status:
                                print(f"🚀 公開実行...")
                                pub_res = requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN}).json()
                                if 'id' in pub_res:
                                    print(f"🏁 投稿完了！ 投稿ID: {pub_res['id']}")
                                    with open(history_file, 'a') as fh: fh.write(video_data['id'] + "\n")
                                    stats[video_data['type']] += 1; save_stats(stats); return
                                else: print(f"❌ 公開失敗: {pub_res}"); return
                            elif 'ERROR' in status:
                                print(f"❌ 処理失敗: {status_res}"); return
                    else: print(f"❌ コンテナ作成失敗: {post_res}")
        except Exception as e: print(f"❌ システムエラー: {e}")
    else: print("😴 投稿対象なし。")

if __name__ == "__main__":
    main()
