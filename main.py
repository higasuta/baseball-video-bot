import sys
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

# ==========================================
# 設定・環境変数の読み込み
# ==========================================
INSTA_ID = os.getenv('INSTA_BUSINESS_ID')
ACCESS_TOKEN = os.getenv('INSTA_ACCESS_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

JPN_KEYWORDS = ["大谷", "山本", "ダルビッシュ", "鈴木誠也", "吉田正尚", "今永", "松井裕樹", "千賀", "前田健太", "菊池雄星", "ohtani", "yamamoto", "imanaga", "菅野", "senga", "darvish"]
BLACK_KEYWORDS = ["probable", "pitchers", "lineup", "interview", "press", "availability", "roster", "update", "alignment", "summary", "preview", "warmup", "positioning", "against", "at bat", "statcast", "recap", "daily"]

def get_stats():
    if os.path.exists('stats.json'):
        try:
            with open('stats.json', 'r') as f: return json.load(f)
        except: pass
    return {"npb": 7, "mlb": 3}

def save_stats(stats):
    with open('stats.json', 'w') as f:
        json.dump(stats, f)

def cleanup_gemini_storage():
    print("🧹 AIストレージの掃除中...")
    try:
        for f in genai.list_files():
            genai.delete_file(f.name)
        print("  ✅ 完了")
    except: pass

def get_all_candidates(history, is_test_mode):
    candidates = []
    
    # 1. NPBスキャン (スポナビRSS) - 全件チェック
    print("🔍 NPB(スポナビ)を全件スキャン中...")
    rss_url = "https://sports.yahoo.co.jp/video/rss/baseball/npb"
    try:
        res = requests.get(rss_url, timeout=15)
        if res.status_code == 200:
            root = ET.fromstring(res.content)
            items = root.findall('.//item')
            print(f"  👉 RSS内に合計 {len(items)}件 の動画を確認。")
            for item in items:
                title = item.find('title').text
                v_url = item.find('link').text
                v_id = item.find('guid').text if item.find('guid') is not None else v_url
                
                if v_id in history:
                    continue # 投稿済みはスキップ
                
                if any(kw in title.lower() for kw in BLACK_KEYWORDS):
                    continue # 地味動画はスキップ
                
                candidates.append({"title": title, "url": v_url, "id": v_id, "type": "npb", "source": "スポーツナビ"})
                print(f"  ✅ NPB候補: {title[:30]}...")
    except: pass

    # 2. MLBスキャン (API) - 過去3日間
    print("🔍 MLB(公式API)を3日分スキャン中...")
    for day_offset in [0, 1, 2]:
        date_str = (datetime.datetime.now() - datetime.timedelta(days=day_offset)).strftime('%Y-%m-%d')
        url = f"https://statsapi.mlb.com/api/v1/schedule/games/?sportId=1&startDate={date_str}&endDate={date_str}"
        try:
            res = requests.get(url, timeout=15).json()
            for date_data in res.get('dates', []):
                for game in date_data.get('games', []):
                    content = requests.get(f"https://statsapi.mlb.com/api/v1/game/{game['gamePk']}/content").json()
                    highlights = content.get('highlights', {}).get('highlights', {}).get('items', [])
                    for item in highlights:
                        title = item.get('headline', '')
                        v_id = str(item.get('id'))
                        v_url = next((p['url'] for p in item.get('playbacks', []) if p['name'] == 'mp4Avc'), None)
                        
                        if v_url and v_id not in history:
                            if any(kw in title.lower() for kw in BLACK_KEYWORDS): continue
                            
                            # 日本人選手優先
                            is_jpn = any(kw in title.lower() for kw in JPN_KEYWORDS)
                            # テストモードなら「Home Run」という言葉があれば日本人以外でも候補に入れる
                            is_exciting = "home run" in title.lower()
                            
                            if is_jpn or (is_test_mode and is_exciting):
                                candidates.append({"title": title, "url": v_url, "id": v_id, "type": "mlb", "source": "@MLBJapan"})
                                print(f"  ✅ MLB候補: {title[:30]}...")
        except: continue
    
    return candidates

def analyze_video_with_ai(video_path, title, source_account):
    print(f"🧠 AIによる動画解析中 (Gemini)...")
    try:
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING": time.sleep(2); video_file = genai.get_file(video_file.name)
        
        # あなたの環境で動作するモデル名に固定
        model = genai.GenerativeModel("gemini-1.5-flash-latest")
        prompt = f"""
        野球動画({title})を解析し、以下の形式で出力せよ。
        試合中のプレー（投球、打撃、守備、走塁）がない地味な動画は CAPTION:SKIP と出力せよ。
        START:[秒]
        CAPTION:[内容]
        構成：【 】付きの鋭い見出し。要約。鋭い所感。
        ネットスラング禁止。だ・である調。タグ25個以上。引用：{source_account}
        """
        response = model.generate_content([prompt, video_file])
        res_text = response.text
        genai.delete_file(video_file.name)
        
        if "SKIP" in res_text: return None, "SKIP"
        start_match = re.search(r"START:(\d+)", res_text)
        start_sec = int(start_match.group(1)) if start_match else 0
        caption_match = re.search(r"CAPTION:(.*)", res_text, re.DOTALL)
        ai_caption = caption_match.group(1).strip() if caption_match else None
        print(f"  ✨ AI解析成功: 開始 {start_sec}s")
        return start_sec, ai_caption
    except Exception as e:
        print(f"  ⚠️ AIエラー: {e}")
        return None, None

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats(); history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    cleanup_gemini_storage()
    print(f"⚾️ 探索開始...")
    candidates = get_all_candidates(history, is_test_mode)
    
    if not candidates:
        print("😴 履歴にない新しい動画が見つかりませんでした。history.txt を一度空にすることを検討してください。")
        return

    for video in candidates[:5]:
        print(f"🎯 ターゲット試行: {video['title']}")
        temp_input = "temp_video.mp4"
        subprocess.run(['curl', '-L', video['url'], '-o', temp_input])
        
        if not os.path.exists(temp_input) or os.path.getsize(temp_input) < 10000: continue

        start_sec, ai_caption = analyze_video_with_ai(temp_input, video['title'], video['source'])
        
        if ai_caption == "SKIP" or ai_caption is None:
            # AIがボツにした動画も履歴に保存して次回スルー
            with open(history_file, 'a') as fh: fh.write(video['id'] + "\n")
            continue

        output_file = "output.mp4"
        filter_complex = "scale=1134:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
        subprocess.run(['ffmpeg', '-ss', str(start_sec), '-i', temp_input, '-t', '90', '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-b:v', '5000k', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-y', output_file])
        
        try:
            with open(output_file, 'rb') as f:
                res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f}, timeout=60).json()
                if res.get('status') == 'success':
                    public_url = res['data']['url'].replace("http://", "https://").replace("tmpfiles.org/", "tmpfiles.org/dl/")
                    print(f"✅ 公開準備完了")
                    time.sleep(10)
                    post_res = requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media", data={'media_type': 'REELS', 'video_url': public_url, 'caption': ai_caption, 'access_token': ACCESS_TOKEN}).json()
                    
                    if 'id' in post_res:
                        creation_id = post_res['id']
                        for _ in range(20):
                            time.sleep(30)
                            status_res = requests.get(f"https://graph.facebook.com/v21.0/{creation_id}", params={'fields': 'status_code,status', 'access_token': ACCESS_TOKEN}).json()
                            status = (status_res.get('status_code') or status_res.get('status') or "").upper()
                            print(f"  ステータス: {status}")
                            if status == 'FINISHED':
                                requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN})
                                print(f"🏁 投稿完了！: {video['title']}")
                                with open(history_file, 'a') as fh: fh.write(video['id'] + "\n")
                                stats[video['type']] += 1
                                save_stats(stats); return
        except Exception as e: print(f"  ❌ エラー: {e}")
    
    print("😴 終了。")

if __name__ == "__main__":
    main()
