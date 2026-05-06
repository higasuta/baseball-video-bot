import sys
# リアルタイムログ出力のためのフラッシュ
print("🚀 Pythonスクリプト起動...")
sys.stdout.flush()

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
    """MLB APIから確実に動画を取得"""
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
    print(f"🧠 AIによる動画解析中...")
    try:
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING": time.sleep(2); video_file = genai.get_file(video_file.name)
        
        # ログで確認された正しいモデル名
        model = genai.GenerativeModel("gemini-flash-latest")
        prompt = f"野球動画({title})を解析し「START:秒」と「CAPTION:内容」を出力せよ。語り口調。引用：{source_account}と記載。"
        response = model.generate_content([prompt, video_file])
        res_text = response.text
        genai.delete_file(video_file.name)
        
        start_match = re.search(r"START:(\d+)", res_text); start_sec = int(start_match.group(1)) if start_match else 0
        caption_match = re.search(r"CAPTION:(.*)", res_text, re.DOTALL); ai_caption = caption_match.group(1).strip() if caption_match else None
        print(f"  ✨ AI解析成功: 開始 {start_sec}s")
        return start_sec, ai_caption
    except Exception as e:
        print(f"  ⚠️ AI解析失敗: {e}")
        return 0, None

def upload_to_pixeldrain(file_path):
    """Pixeldrain API を使用して100%直リンクを取得"""
    print(f"📥 Pixeldrain(API)へアップロード中...")
    try:
        with open(file_path, 'rb') as f:
            # 1. API経由でアップロード
            res = requests.post('https://pixeldrain.com/api/file', files={'file': f}, timeout=60).json()
            if res.get('success'):
                file_id = res.get('id')
                # 2. Instagramが直接ダウンロードできる「生データURL」を生成
                direct_url = f"https://pixeldrain.com/api/file/{file_id}"
                return direct_url
            else:
                print(f"  ❌ Pixeldrain拒絶: {res}")
    except Exception as e:
        print(f"  ❌ Pixeldrain通信失敗: {e}")
    return None

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats(); history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    print(f"⚾️ MLBルートから動画を確保します...")
    video_data = get_mlb_video(history, is_test_mode)

    if video_data:
        print(f"🎯 ターゲット確定: {video_data['title']}")
        temp_input = "temp_video.mp4"
        subprocess.run(['curl', '-L', video_data['url'], '-o', temp_input])
        
        if not os.path.exists(temp_input) or os.path.getsize(temp_input) < 10000:
            print("❌ ダウンロード失敗。"); return

        start_sec, ai_caption = analyze_video_with_ai(temp_input, video_data['title'], video_data['source'])
        if not ai_caption: ai_caption = f"【速報】最高のプレー！\n\n引用：{video_data['source']}\n#プロ野球"
        
        output_file = "output.mp4"
        filter_complex = "scale=1134:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
        # 高品質＆movflags付与でMetaをパスさせる
        subprocess.run(['ffmpeg', '-ss', str(start_sec), '-i', temp_input, '-t', '90', '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-b:v', '4M', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-y', output_file])
        
        # 投稿
        public_url = upload_to_pixeldrain(output_file)
        if public_url:
            print(f"✅ 直リンク確保: {public_url}")
            time.sleep(10) # 浸透待機

            print(f"📸 Instagram送信開始...")
            post_res = requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media", data={'media_type': 'REELS', 'video_url': public_url, 'caption': ai_caption, 'access_token': ACCESS_TOKEN}).json()
            
            if 'id' in post_res:
                creation_id = post_res['id']
                print(f"⏳ 処理待機 (ID: {creation_id})...")
                for i in range(20):
                    time.sleep(30)
                    status_res = requests.get(f"https://graph.facebook.com/v21.0/{creation_id}", params={'fields': 'status_code,status', 'access_token': ACCESS_TOKEN}).json()
                    status = (status_res.get('status_code') or status_res.get('status') or "").upper()
                    print(f"  [{i+1}/20] API Status: {status}")
                    
                    if 'FINISHED' in status:
                        print(f"🚀 公開リクエスト...")
                        requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN})
                        print(f"🏁 投稿完了！")
                        with open(history_file, 'a') as fh: fh.write(video_data['id'] + "\n")
                        stats[video_data['type']] += 1; save_stats(stats); return
                    elif 'ERROR' in status:
                        print(f"❌ 失敗: {status_res}"); return
            else: print(f"❌ コンテナ作成失敗: {post_res}")
    else: print("😴 投稿対象なし。")

if __name__ == "__main__":
    main()
