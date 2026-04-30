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
    """YouTubeのRSSフィードから動画を取得（ブロックされない確実な方法）"""
    feeds = [
        {"name": "パ・リーグTV", "id": "UC0v-pxTo1XamIDE-f__Ad0Q"},
        {"name": "NPB公式", "id": "UC7vYid8pCUpIOn85X_2f_ig"}
    ]
    for feed in feeds:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={feed['id']}"
        print(f"🔍 YouTube RSSスキャン中: {feed['name']}")
        try:
            res = requests.get(url, timeout=20)
            root = ET.fromstring(res.content)
            ns = {'ns': 'http://www.w3.org/2005/Atom', 'yt': 'http://www.youtube.com/xml/schemas/2015'}
            for entry in root.findall('ns:entry', ns):
                video_id = entry.find('yt:videoId', ns).text
                title = entry.find('ns:title', ns).text
                if video_id not in history:
                    print(f"✅ 動画発見: {title}")
                    return {"title": title, "url": f"https://www.youtube.com/watch?v={video_id}", "id": video_id, "type": "npb", "source_account": f"YouTube {feed['name']}"}
        except: continue
    return None

def get_mlb_video(history, is_test_mode):
    """MLB APIから日本人動画を取得（非常に確実）"""
    print(f"🔍 MLB(API) をスキャン中...")
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
                        video_id = str(item.get('id'))
                        video_url = next((p['url'] for p in item.get('playbacks', []) if p['name'] == 'mp4Avc'), None)
                        if video_url and video_id not in history:
                            if any(kw in title.lower() for kw in JPN_KEYWORDS) or is_test_mode:
                                if not any(kw in title.lower() for kw in BLACK_KEYWORDS):
                                    print(f"✅ MLB動画発見: {title}")
                                    return {"title": title, "url": video_url, "id": video_id, "type": "mlb", "source_account": "@MLBJapan"}
        except: continue
    return None

def analyze_video_with_ai(video_path, title, source_account):
    if not os.path.exists(video_path): return 0, None
    print(f"🧠 AIによる動画解析中 (Gemini 1.5 Flash)...")
    try:
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING": time.sleep(2); video_file = genai.get_file(video_file.name)
        
        # 以前成功したモデル名を使用
        model = genai.GenerativeModel("gemini-1.5-flash-latest")
        prompt = (f"野球動画（タイトル：{title}）を解析せよ。\n"
                  "1. 最高潮の場面の開始秒数を「START:秒」で。\n"
                  "2. 野球2chまとめ解説動画風の語り口調でキャプションを作成。\n"
                  f"3. 最後に必ず『引用：{source_account}』と記載。\n"
                  "START:[秒]\nCAPTION:[内容]")
        response = model.generate_content([prompt, video_file])
        res_text = response.text
        genai.delete_file(video_file.name)
        start_match = re.search(r"START:(\d+)", res_text); start_sec = int(start_match.group(1)) if start_match else 0
        caption_match = re.search(r"CAPTION:(.*)", res_text, re.DOTALL); caption = caption_match.group(1).strip() if caption_match else None
        print(f"  ✨ AI解析成功: 開始 {start_sec}s")
        return start_sec, caption
    except Exception as e:
        print(f"  ⚠️ AI解析スキップ: {e}")
        return 0, None

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats(); history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    print(f"⚾️ 探索開始 {'(テストモード)' if is_test_mode else ''}")
    video_data = get_npb_video(history)
    if not video_data:
        total = stats['npb'] + stats['mlb']
        ratio = stats['mlb'] / total if total > 0 else 0
        if is_test_mode or ratio < 0.40: video_data = get_mlb_video(history, is_test_mode)

    if video_data:
        print(f"🎯 決定: {video_data['title']}")
        temp_input = "temp_video.mp4"
        
        if video_data['type'] == 'npb':
            # YouTubeブロック回避（android_embeddedクライアント）
            subprocess.run(['yt-dlp', '-o', temp_input, '--extractor-args', 'youtube:player_client=android_embedded', video_data['url']])
        else:
            subprocess.run(['curl', '-L', video_data['url'], '-o', temp_input])
        
        if not os.path.exists(temp_input) or os.path.getsize(temp_input) < 1000:
            print("❌ ダウンロード失敗。"); return

        start_sec, ai_caption = analyze_video_with_ai(temp_input, video_data['title'], video_data['source_account'])
        if not ai_caption: ai_caption = f"【速報】今日の好プレー！\n\n引用：{video_data['source_account']}\n#野球 #プロ野球"
        
        output_file = "output.mp4"
        filter_complex = "scale=1134:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
        subprocess.run(['ffmpeg', '-ss', str(start_sec), '-i', temp_input, '-t', '90', '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'fast', '-crf', '18', '-movflags', '+faststart', '-y', output_file])
        
        try:
            with open(output_file, 'rb') as f:
                up_res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f})
                if up_res.status_code == 200:
                    public_url = up_res.json()['data']['url'].replace('https://tmpfiles.org/', 'https://tmpfiles.org/dl/')
                    print(f"📥 クラウド保存完了。安定のため15秒待機...")
                    time.sleep(15)

                    print(f"📸 Instagram送信開始...")
                    post_res = requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media", data={'media_type': 'REELS', 'video_url': public_url, 'caption': ai_caption, 'access_token': ACCESS_TOKEN}).json()
                    
                    if 'id' in post_res:
                        creation_id = post_res['id']
                        print(f"⏳ 処理待機 (ID: {creation_id})...")
                        for i in range(30):
                            time.sleep(30)
                            # fieldsから不備のあるfailure_reasonを除去
                            status_res = requests.get(f"https://graph.facebook.com/v21.0/{creation_id}", params={'fields': 'status_code', 'access_token': ACCESS_TOKEN}).json()
                            status = status_res.get('status_code')
                            print(f"  [{i+1}/30] API Status: {status}")
                            
                            if status == 'FINISHED':
                                print(f"🚀 公開リクエスト...")
                                pub_res = requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN}).json()
                                if 'id' in pub_res:
                                    print(f"🏁 投稿完了！ ID: {pub_res['id']}")
                                    with open(history_file, 'a') as fh: fh.write(video_data['id'] + "\n")
                                    stats[video_data['type']] += 1
                                    save_stats(stats); return
                                else:
                                    print(f"❌ 公開失敗: {pub_res}"); return
                            elif status == 'ERROR':
                                print(f"❌ 処理エラー: {status_res}"); return
                    else: print(f"❌ コンテナ作成失敗: {post_res}")
        except Exception as e: print(f"❌ システムエラー: {e}")
    else: print("😴 投稿対象なし。")

if __name__ == "__main__":
    main()
