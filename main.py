import sys
# リアルタイムログ出力
print("🚀 プレイボール速報・システム稼働中...")
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
from email.utils import parsedate_to_datetime

# ==========================================
# 設定・環境変数の読み込み
# ==========================================
INSTA_ID = os.getenv('INSTA_BUSINESS_ID')
ACCESS_TOKEN = os.getenv('INSTA_ACCESS_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# 日本人選手フィルター
JPN_KEYWORDS = ["大谷", "山本", "ダルビッシュ", "鈴木誠也", "吉田正尚", "今永", "松井裕樹", "千賀", "前田健太", "菊池雄星", "ohtani", "yamamoto", "imanaga", "菅野"]

# 【厳格化】除外キーワード：プレー以外の動画を徹底排除
BLACK_KEYWORDS = [
    "probable", "pitchers", "lineup", "interview", "press", "availability", 
    "roster", "update", "alignment", "summary", "preview", "warmup", 
    "positioning", "highlights of the day", "pre-game"
]

def get_stats():
    if os.path.exists('stats.json'):
        try:
            with open('stats.json', 'r') as f: return json.load(f)
        except: pass
    return {"npb": 7, "mlb": 3}

def save_stats(stats):
    with open('stats.json', 'w') as f:
        json.dump(stats, f)

def get_npb_video(history):
    """スポナビRSSから過去1週間のNPB名シーンを探索"""
    rss_url = "https://sports.yahoo.co.jp/video/rss/baseball/npb"
    print(f"🔍 NPBスキャン中 (スポナビRSS・過去1週間対象): {rss_url}")
    
    # 1週間前の境界線
    one_week_ago = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)
    
    try:
        res = requests.get(rss_url, timeout=20)
        if res.status_code != 200: return None
        root = ET.fromstring(res.content)
        
        for item in root.findall('.//item'):
            title = item.find('title').text
            v_url = item.find('link').text
            pub_date_str = item.find('pubDate').text
            v_id = item.find('guid').text if item.find('guid') is not None else v_url
            
            # 日付解析
            pub_date = parsedate_to_datetime(pub_date_str)
            
            # 判定ロジック
            if v_id not in history and pub_date > one_week_ago:
                if any(kw in title.lower() for kw in BLACK_KEYWORDS):
                    continue
                
                print(f"✅ スポナビで動画を発見 ({pub_date.strftime('%Y-%m-%d')}): {title}")
                return {"title": title, "url": v_url, "id": v_id, "type": "npb", "source": "スポーツナビ"}
    except Exception as e:
        print(f"⚠️ スポナビRSS取得失敗: {e}")
    return None

def get_mlb_video(history, is_test_mode):
    """MLB APIから名シーンを探索"""
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
                                # プレー以外の動画を排除
                                if any(kw in title.lower() for kw in BLACK_KEYWORDS): continue
                                if any(kw in title.lower() for kw in JPN_KEYWORDS) or is_test_mode:
                                    print(f"✅ MLB動画を発見: {title}")
                                    return {"title": title, "url": video_url, "id": v_id, "type": "mlb", "source": "@MLBJapan"}
                    except: continue
        except: continue
    return None

def analyze_video_with_ai(video_path, title, source_account):
    print(f"🧠 AIによる動画解析中 (Gemini)...")
    try:
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING": time.sleep(2); video_file = genai.get_file(video_file.name)
        
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        # 【重要】試合シーンかどうかの確認を指示に追加
        prompt = f"""
        野球動画（タイトル：{title}）を解析し、以下の形式で出力せよ。
        
        【重要条件】
        もしこの動画が「試合中のプレー（投球、打撃、守備、走塁）」を含まない事務的な映像（スタメン表、練習、会見など）である場合は、
        理由を問わず CAPTION:SKIP とだけ出力せよ。

        1. 最も盛り上がっている場面の開始秒数を「START:秒」で教えろ。
        2. インスタのリール動画用のキャプションを「CAPTION:内容」で作成せよ。

        【キャプション構成ルール】
        ・一段目：【 】で囲った、見た人を一気に引き込む鋭い見出し。皮肉や驚き、分析を交えた2chまとめ風タイトル。
        ・二段目：ニュースの核心を2〜3行で要約。
        ・三段目：アナリスト視点からの皮肉のきいた鋭い所感。
        ・ネットスラング（ワロタ、www等）は一切禁止。標準語の「だ・である」調を徹底せよ。

        【ハッシュタグ】
        ・登場人物名、チーム名を個別にタグ化（中黒「・」は削除）。
        ・合計25〜29個付与。
        引用：{source_account}を最後に記載。
        """
        
        response = model.generate_content([prompt, video_file])
        res_text = response.text
        genai.delete_file(video_file.name)
        
        if "SKIP" in res_text:
            print("  🛑 AI判定: 試合シーンではないためスキップします。")
            return None, None

        start_match = re.search(r"START:(\d+)", res_text); start_sec = int(start_match.group(1)) if start_match else 0
        caption_match = re.search(r"CAPTION:(.*)", res_text, re.DOTALL); ai_caption = caption_match.group(1).strip() if caption_match else None
        print(f"  ✨ AI解析成功: 開始 {start_sec}s")
        return start_sec, ai_caption
    except Exception as e:
        print(f"  ⚠️ AI解析失敗: {e}")
        return 0, None

def upload_to_tmpfiles(file_path):
    print(f"📥 外部サーバーへアップロード中...")
    try:
        with open(file_path, 'rb') as f:
            res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f}, timeout=60).json()
            if res.get('status') == 'success':
                original_url = res['data']['url']
                return original_url.replace("http://", "https://").replace("tmpfiles.org/", "tmpfiles.org/dl/")
    except: pass
    return None

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats(); history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    print(f"⚾️ スキャン開始...")
    video_data = get_npb_video(history)
    if not video_data:
        total = stats['npb'] + stats['mlb']
        ratio = stats['mlb'] / total if total > 0 else 0
        if is_test_mode or ratio < 0.40:
            video_data = get_mlb_video(history, is_test_mode)

    if video_data:
        print(f"🎯 ターゲット確定: {video_data['title']}")
        temp_input = "temp_video.mp4"
        subprocess.run(['yt-dlp', '-o', temp_input, '--no-check-certificates', video_data['url']])
        
        if not os.path.exists(temp_input) or os.path.getsize(temp_input) < 10000:
            print("❌ ダウンロード失敗。"); return

        # AI解析
        start_sec, ai_caption = analyze_video_with_ai(temp_input, video_data['title'], video_data['source'])
        
        # AIがSKIP判定をした、または解析不能な場合
        if ai_caption == "SKIP" or ai_caption is None:
            # 履歴に追加して次回以降同じものを狙わないようにする
            with open(history_file, 'a') as fh: fh.write(video_data['id'] + "\n")
            print("😴 次の動画を探します...")
            return

        output_file = "output.mp4"
        filter_complex = "scale=1134:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
        subprocess.run(['ffmpeg', '-ss', str(start_sec), '-i', temp_input, '-t', '90', '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-b:v', '5M', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-y', output_file])
        
        public_url = upload_to_tmpfiles(output_file)
        if public_url:
            print(f"✅ 直リンク確保: {public_url}")
            time.sleep(10)
            print(f"📸 Instagram送信開始...")
            post_res = requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media", data={'media_type': 'REELS', 'video_url': public_url, 'caption': ai_caption, 'access_token': ACCESS_TOKEN}).json()
            if 'id' in post_res:
                creation_id = post_res['id']
                print(f"⏳ 処理待機 (ID: {creation_id})...")
                for i in range(20):
                    time.sleep(30)
                    status_res = requests.get(f"https://graph.facebook.com/v21.0/{creation_id}", params={'fields': 'status_code,status', 'access_token': ACCESS_TOKEN}).json()
                    status = (status_res.get('status_code') or status_res.get('status') or "PROCESSING").upper()
                    print(f"  [{i+1}/20] API Status: {status}")
                    if status == 'FINISHED':
                        requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN})
                        print(f"🏁 投稿完了！")
                        with open(history_file, 'a') as fh: fh.write(video_data['id'] + "\n")
                        stats[video_data['type']] += 1
                        save_stats(stats); return
    else: print("😴 投稿対象なし。")

if __name__ == "__main__":
    main()
