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

def get_npb_candidates(history):
    """YouTube RSSから動画候補を複数取得する"""
    feeds = [
        {"name": "パ・リーグTV", "id": "UC0v-pxTo1XamIDE-f__Ad0Q"},
        {"name": "NPB公式", "id": "UC7vYid8pCUpIOn85X_2f_ig"}
    ]
    candidates = []
    for feed in feeds:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={feed['id']}"
        print(f"🔍 YouTube RSSスキャン中: {feed['name']}")
        try:
            res = requests.get(url, timeout=20)
            root = ET.fromstring(res.content)
            ns = {'ns': 'http://www.w3.org/2005/Atom', 'yt': 'http://www.youtube.com/xml/schemas/2015'}
            for entry in root.findall('ns:entry', ns):
                v_id = entry.find('yt:videoId', ns).text
                title = entry.find('ns:title', ns).text
                if v_id not in history:
                    candidates.append({"title": title, "url": f"https://www.youtube.com/watch?v={v_id}", "id": v_id, "type": "npb", "source": f"YouTube {feed['name']}"})
        except: continue
    return candidates

def get_mlb_candidates(history, is_test_mode):
    """MLB APIから動画候補を取得"""
    print(f"🔍 MLB APIスキャン中...")
    candidates = []
    for day_offset in range(2):
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
                        if v_id not in history and video_url:
                            if any(kw in title.lower() for kw in JPN_KEYWORDS) or is_test_mode:
                                if not any(kw in title.lower() for kw in BLACK_KEYWORDS):
                                    candidates.append({"title": title, "url": video_url, "id": v_id, "type": "mlb", "source": "@MLBJapan"})
        except: continue
    return candidates

def download_video(url, output_path, is_youtube):
    """動画をダウンロード。YouTubeの場合は強力な回避策を使用"""
    if is_youtube:
        # YouTubeのブロックを回避するための最新の戦略（web_creatorクライアント）
        cmd = [
            'yt-dlp', '-o', output_path,
            '--extractor-args', 'youtube:player_client=web_creator,android',
            '--no-check-certificates', url
        ]
    else:
        cmd = ['curl', '-L', url, '-o', output_path]
    
    try:
        subprocess.run(cmd, timeout=120)
        return os.path.exists(output_path) and os.path.getsize(output_path) > 10000
    except:
        return False

def analyze_video_with_ai(video_path, title, source_account):
    print(f"🧠 AIによる動画解析中 (Gemini)...")
    try:
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING": time.sleep(2); video_file = genai.get_file(video_file.name)
        model = genai.GenerativeModel("gemini-flash-latest")
        prompt = (f"野球動画（{title}）を解析せよ。\n1. 見どころ開始秒数を「START:秒」で。\n2. 熱いキャプションを作成。最後に『引用：{source_account}』と記載。\nSTART:[秒]\nCAPTION:[内容]")
        response = model.generate_content([prompt, video_file])
        res_text = response.text
        genai.delete_file(video_file.name)
        start_match = re.search(r"START:(\d+)", res_text); start_sec = int(start_match.group(1)) if start_match else 0
        caption_match = re.search(r"CAPTION:(.*)", res_text, re.DOTALL); caption = caption_match.group(1).strip() if caption_match else None
        return start_sec, caption
    except: return 0, None

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats()
    history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    print(f"⚾️ 探索開始 {'(テストモード)' if is_test_mode else ''}")
    
    # NPBとMLBの候補をすべて集める
    candidates = get_npb_candidates(history)
    total = stats['npb'] + stats['mlb']
    ratio = stats['mlb'] / total if total > 0 else 0
    if is_test_mode or ratio < 0.40:
        candidates += get_mlb_candidates(history, is_test_mode)

    if not candidates:
        print("😴 全ソースにおいて新しい動画が見つかりませんでした。"); return

    # ダウンロードに成功するまで候補を試す
    target = None
    temp_input = "temp_video.mp4"
    for candidate in candidates:
        print(f"📥 試行中: {candidate['title']}")
        if download_video(candidate['url'], temp_input, candidate['type'] == 'npb'):
            target = candidate
            break
        print(f"  ❌ ダウンロード失敗、次の候補へ...")

    if not target:
        print("❌ 候補はありましたが、全てのダウンロードに失敗しました。"); return

    # AI解析 & FFmpeg加工
    start_sec, ai_caption = analyze_video_with_ai(temp_input, target['title'], target['source'])
    if not ai_caption: ai_caption = f"【朗報】最高のプレー！\n\n引用：{target['source']}\n#野球 #プロ野球"
    
    output_file = "output.mp4"
    filter_complex = "scale=1134:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
    subprocess.run(['ffmpeg', '-ss', str(start_sec), '-i', temp_input, '-t', '90', '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'fast', '-crf', '18', '-movflags', '+faststart', '-y', output_file])

    # Instagram投稿
    try:
        with open(output_file, 'rb') as f:
            up_res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f})
            if up_res.status_code == 200:
                public_url = up_res.json()['data']['url'].replace('https://tmpfiles.org/', 'https://tmpfiles.org/dl/')
                print(f"📥 クラウド保存完了。検証のため20秒待機...")
                time.sleep(20)

                # 検証：Instagramがアクセスする前に、自らURLが生きているか確認
                check = requests.head(public_url)
                if check.status_code != 200:
                    print("❌ クラウド上のファイルが読み取れません。中断します。"); return

                print(f"📸 Instagram送信開始...")
                post_res = requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media", data={'media_type': 'REELS', 'video_url': public_url, 'caption': ai_caption, 'access_token': ACCESS_TOKEN}).json()
                
                if 'id' in post_res:
                    creation_id = post_res['id']
                    for i in range(30):
                        time.sleep(30)
                        status_res = requests.get(f"https://graph.facebook.com/v21.0/{creation_id}", params={'fields': 'status_code', 'access_token': ACCESS_TOKEN}).json()
                        status = status_res.get('status_code')
                        print(f"  [{i+1}/30] ステータス: {status}")
                        if status == 'FINISHED':
                            print(f"🚀 公開実行...")
                            requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN})
                            print(f"🏁 投稿完了！")
                            with open(history_file, 'a') as fh: fh.write(target['id'] + "\n")
                            stats[target['type']] += 1
                            save_stats(stats); return
                        elif status == 'ERROR':
                            print(f"❌ 処理失敗: {status_res}"); return
                else: print(f"❌ コンテナ作成失敗: {post_res}")
    except Exception as e: print(f"❌ エラー: {e}")

if __name__ == "__main__":
    main()
