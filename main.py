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

JPN_KEYWORDS = ["大谷", "山本", "ダルビッシュ", "鈴木誠也", "吉田正尚", "今永", "松井裕樹", "千賀", "前田健太", "菊池雄星", "ohtani", "yamamoto", "imanaga", "菅野"]
BLACK_KEYWORDS = ["probable", "pitchers", "lineup", "interview", "press", "availability", "roster", "update"]

def get_stats():
    if os.path.exists('stats.json'):
        try:
            with open('stats.json', 'r') as f: return json.load(f)
        except: pass
    return {"npb": 7, "mlb": 3}

def save_stats(stats):
    with open('stats.json', 'w') as f: json.dump(stats, f)

def get_mlb_video(history, is_test_mode):
    print(f"🔍 MLB(API) をスキャン中...")
    for day_offset in range(3):
        date_str = (datetime.datetime.now() - datetime.timedelta(days=day_offset)).strftime('%Y-%m-%d')
        url = f"https://statsapi.mlb.com/api/v1/schedule/games/?sportId=1&startDate={date_str}&endDate={date_str}"
        try:
            res = requests.get(url).json()
            if 'dates' not in res: continue
            for date_data in res['dates']:
                for game in date_data.get('games', []):
                    try:
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
        except: continue
    return None

def analyze_video_with_ai(video_path, title, source_account):
    print(f"🧠 AIによる動画解析中 (Gemini)...")
    try:
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING": time.sleep(2); video_file = genai.get_file(video_file.name)
        
        # 確実に通るモデル名を指定
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = f"野球動画({title})を解析し「START:秒」と「CAPTION:内容」を出力せよ。引用：{source_account}と記載。"
        response = model.generate_content([prompt, video_file])
        res_text = response.text
        genai.delete_file(video_file.name)
        start_match = re.search(r"START:(\d+)", res_text); start_sec = int(start_match.group(1)) if start_match else 0
        caption_match = re.search(r"CAPTION:(.*)", res_text, re.DOTALL); ai_caption = caption_match.group(1).strip() if caption_match else None
        print(f"  ✨ AI解析完了 (開始: {start_sec}s)")
        return start_sec, ai_caption
    except Exception as e:
        print(f"  ⚠️ AI解析スキップ: {e}")
        return 0, None

def upload_to_catbox(file_path):
    """Instagramが直接読み取れる直リンク(files.catbox.moe)を取得"""
    print(f"📥 Catbox(直リンク)へアップロード中...")
    try:
        with open(file_path, 'rb') as f:
            # reqtype: fileupload を明示
            res = requests.post('https://catbox.moe/user/api.php', data={'reqtype': 'fileupload'}, files={'fileToUpload': f}, timeout=60)
            if res.status_code == 200:
                url = res.text.strip()
                if "https" in url: return url
    except Exception as e:
        print(f"  ❌ Catbox失敗: {e}")
    return None

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats(); history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    print(f"⚾️ 探索開始...")
    video_data = get_mlb_video(history, is_test_mode)

    if video_data:
        print(f"🎯 ターゲット確定: {video_data['title']}")
        temp_input = "temp_video.mp4"
        subprocess.run(['curl', '-L', video_data['url'], '-o', temp_input])
        
        if not os.path.exists(temp_input) or os.path.getsize(temp_input) < 10000:
            print("❌ ダウンロード失敗。"); return

        start_sec, ai_caption = analyze_video_with_ai(temp_input, video_data['title'], video_data['source'])
        if not ai_caption: ai_caption = f"【朗報】最高のプレー！\n\n引用：{video_data['source']}\n#プロ野球"
        
        output_file = "output.mp4"
        filter_complex = "scale=1134:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
        # Instagramが絶対に拒絶しないスペックで書き出し
        subprocess.run(['ffmpeg', '-ss', str(start_sec), '-i', temp_input, '-t', '90', '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-b:v', '4M', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', '-y', output_file])
        
        # 投稿（Catboxによる直リンク）
        public_url = upload_to_catbox(output_file)
        if public_url:
            print(f"✅ 直リンク確保: {public_url}")
            time.sleep(10) # 念のため待機

            print(f"📸 Instagram送信開始...")
            post_url = f"https://graph.facebook.com/v21.0/{INSTA_ID}/media"
            params = {'media_type': 'REELS', 'video_url': public_url, 'caption': ai_caption, 'access_token': ACCESS_TOKEN}
            post_res = requests.post(post_url, data=params).json()
            
            if 'id' in post_res:
                creation_id = post_res['id']
                print(f"⏳ ステータス監視 (ID: {creation_id})...")
                for i in range(20):
                    time.sleep(30)
                    status_res = requests.get(f"https://graph.facebook.com/v21.0/{creation_id}", params={'fields': 'status_code,status', 'access_token': ACCESS_TOKEN}).json()
                    status = (status_res.get('status_code') or status_res.get('status') or "PROCESSING").upper()
                    print(f"  [{i+1}/20] API Response: {status}")
                    
                    if 'FINISHED' in status:
                        print(f"🚀 公開実行...")
                        publish_res = requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN}).json()
                        if 'id' in publish_res:
                            print(f"🏁 投稿完了！ 投稿ID: {publish_res['id']}")
                            with open(history_file, 'a') as fh: fh.write(video_data['id'] + "\n")
                            stats[video_data['type']] += 1; save_stats(stats); return
                    elif 'ERROR' in status:
                        print(f"❌ Instagram処理失敗: {status_res}"); return
            else: print(f"❌ コンテナ作成失敗: {post_res}")
    else: print("😴 投稿対象なし。")

if __name__ == "__main__":
    main()
