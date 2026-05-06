import sys
# 1. 何よりも先にこれを出力させる
print("🚀 Pythonスクリプトが正常に起動しました。初期化を開始します...")
sys.stdout.flush()

import requests
print("📦 requests ライブラリの読み込み完了")
import datetime
import os
import time
import subprocess
import google.generativeai as genai
print("🧠 AIライブラリの読み込み完了")
import json
import re
import xml.etree.ElementTree as ET

# ==========================================
# 設定・環境変数の読み込み
# ==========================================
print("🔑 環境変数をチェック中...")
INSTA_ID = os.getenv('INSTA_BUSINESS_ID')
ACCESS_TOKEN = os.getenv('INSTA_ACCESS_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    print("✅ Gemini APIの設定完了")

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

def get_npb_video(history):
    """スポーツナビから動画を取得（YouTube以外の代替ルート）"""
    url = "https://sports.yahoo.co.jp/video/list/promo/live/baseball/npb"
    print(f"🔍 NPB動画を探索中 (スポナビ): {url}")
    try:
        # タイムアウトを設定して固まらないようにする
        cmd = ['yt-dlp', '--get-id', '--get-title', '--get-url', '--playlist-end', '5', '--no-check-certificates', url]
        output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=40).decode().split('\n')
        for i in range(0, len(output)-2, 3):
            title, v_id, v_url = output[i], output[i+1], output[i+2]
            if v_id and v_id not in history:
                print(f"✅ スポナビで動画を発見: {title}")
                return {"title": title, "url": v_url, "id": v_id, "type": "npb", "source": "スポーツナビ"}
    except: pass
    return None

def get_mlb_video(history, is_test_mode):
    print(f"🔍 MLB(API) をスキャン中...")
    for day_offset in range(3):
        date_str = (datetime.datetime.now() - datetime.timedelta(days=day_offset)).strftime('%Y-%m-%d')
        url = f"https://statsapi.mlb.com/api/v1/schedule/games/?sportId=1&startDate={date_str}&endDate={date_str}"
        try:
            res = requests.get(url, timeout=20).json()
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
    print(f"🧠 AIによる動画解析を開始します...")
    try:
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING": time.sleep(2); video_file = genai.get_file(video_file.name)
        model = genai.GenerativeModel("gemini-1.5-flash-latest")
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

def upload_to_gofile(file_path):
    print(f"📥 GoFileへアップロードを開始...")
    try:
        server_res = requests.get('https://api.gofile.io/servers', timeout=20).json()
        if server_res['status'] == 'ok':
            server = server_res['data']['servers'][0]['name']
            with open(file_path, 'rb') as f:
                up_res = requests.post(f'https://{server}.gofile.io/contents/uploadfile', files={'file': f}, timeout=60).json()
                if up_res['status'] == 'ok':
                    return up_res['data']['downloadPage']
    except Exception as e: print(f"  ❌ GoFile失敗: {e}")
    return None

def main():
    print("⚾️ メインプロセス開始")
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats(); history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    video_data = get_npb_video(history) or get_mlb_video(history, is_test_mode)

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
        print("✂️ 動画加工中...")
        subprocess.run(['ffmpeg', '-ss', str(start_sec), '-i', temp_input, '-t', '90', '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-b:v', '4M', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-y', output_file])
        
        public_url = upload_to_gofile(output_file)
        if public_url:
            print(f"✅ 公開URL確保: {public_url}")
            time.sleep(10)

            print(f"📸 Instagramへリクエスト送信...")
            post_res = requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media", data={'media_type': 'REELS', 'video_url': public_url, 'caption': ai_caption, 'access_token': ACCESS_TOKEN}).json()
            
            if 'id' in post_res:
                creation_id = post_res['id']
                print(f"⏳ 処理待機 (ID: {creation_id})...")
                for i in range(20):
                    time.sleep(30)
                    status_res = requests.get(f"https://graph.facebook.com/v21.0/{creation_id}", params={'fields': 'status_code,status', 'access_token': ACCESS_TOKEN}).json()
                    status = (status_res.get('status_code') or status_res.get('status') or "PROCESSING").upper()
                    print(f"  [{i+1}/20] Status: {status}")
                    if 'FINISHED' in status:
                        print(f"🚀 公開実行！")
                        requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN})
                        print(f"🏁 投稿完了！")
                        with open(history_file, 'a') as fh: fh.write(video_data['id'] + "\n")
                        stats[video_data['type']] += 1; save_stats(stats); return
                    elif 'ERROR' in status:
                        print(f"❌ Instagramエラー: {status_res}"); return
            else: print(f"❌ コンテナ作成失敗: {post_res}")
    else: print("😴 投稿対象なし。")

if __name__ == "__main__":
    main()
