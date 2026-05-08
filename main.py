import sys
# リアルタイムログ出力
print("🚀 プレイボール速報・新章突入（自然なキャプション ＋ 頻度向上モード）...")
sys.stdout.flush()

import requests
import datetime
import os
import time
import subprocess
import google.generativeai as genai
import json
import re

# ==========================================
# 設定・環境変数の読み込み
# ==========================================
INSTA_ID = os.getenv('INSTA_BUSINESS_ID')
ACCESS_TOKEN = os.getenv('INSTA_ACCESS_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

JPN_KEYWORDS = ["大谷", "山本", "ダルビッシュ", "鈴木誠也", "吉田正尚", "今永", "松井裕樹", "千賀", "前田健太", "菊池雄星", "ohtani", "yamamoto", "imanaga", "菅野", "senga", "darvish"]

BLACK_KEYWORDS = [
    "probable", "pitchers", "lineup", "interview", "press", "availability", 
    "roster", "update", "alignment", "summary", "preview", "warmup", 
    "positioning", "against", "at bat", "statcast", "recap", "daily",
    "measuring", "animated", "distance", "deep dive", "analyzing", "data viz",
    "condensed", "breaking down", "bat tracking", "talks", "more", 
    "first pitch", "pre-game", "ceremonial", "wild pitch", "full highlights",
    "outing", "on big game", "post-game", "comments", "reaction"
]

def get_stats():
    if os.path.exists('stats.json'):
        try:
            with open('stats.json', 'r') as f: return json.load(f)
        except: pass
    return {"npb": 75, "mlb": 25}

def save_stats(stats):
    with open('stats.json', 'w') as f:
        json.dump(stats, f)

def cleanup_gemini_storage():
    try:
        for f in genai.list_files():
            genai.delete_file(f.name)
        print("🧹 AIストレージを掃除しました。")
    except: pass

def get_available_flash_model():
    try:
        model_names = [m.name for m in genai.list_models() if 'flash' in m.name]
        priority_models = ["models/gemini-flash-lite-latest", "models/gemini-2.5-flash", "models/gemini-1.5-flash"]
        for pm in priority_models:
            if pm in model_names: return pm
        return model_names[0] if model_names else "models/gemini-1.5-flash"
    except: return "models/gemini-1.5-flash"

def get_npb_candidates(history):
    url = "https://pacificleague.com/video"
    print(f"🔍 NPB動画を探索中 (パ・リーグTV): {url}")
    candidates = []
    try:
        cmd = ['yt-dlp', '--get-id', '--get-title', '--get-url', '--playlist-end', '10', '--no-check-certificates', '--quiet', url]
        output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=60).decode().split('\n')
        for i in range(0, len(output)-2, 3):
            title, v_id, v_url = output[i].strip(), output[i+1].strip(), output[i+2].strip()
            if v_id and v_id not in history:
                if any(kw in title.lower() for kw in BLACK_KEYWORDS): continue
                print(f"  ✅ パ・リーグTVで候補発見: {title}")
                candidates.append({"title": title, "url": v_url, "id": v_id, "type": "npb", "source": "パ・リーグTV", "priority": 1})
    except Exception as e: print(f"  ⚠️ NPBスキャン失敗: {e}")
    return candidates

def get_mlb_candidates(history, is_test_mode):
    print("🔍 MLB動画を探索中 (公式API)...")
    candidates = []
    for day_offset in [0, 1]:
        date_str = (datetime.datetime.now() - datetime.timedelta(days=day_offset)).strftime('%Y-%m-%d')
        url = f"https://statsapi.mlb.com/api/v1/schedule/games/?sportId=1&startDate={date_str}&endDate={date_str}"
        try:
            res = requests.get(url, timeout=15).json()
            if 'dates' not in res: continue
            for date_data in res['dates']:
                for game in date_data.get('games', []):
                    try:
                        content = requests.get(f"https://statsapi.mlb.com/api/v1/game/{game['gamePk']}/content").json()
                        highlights = content.get('highlights', {}).get('highlights', {}).get('items', [])
                        for item in highlights:
                            title = item.get('headline', '')
                            v_id = str(item.get('id'))
                            v_url = next((p['url'] for p in item['playbacks'] if p['name'] == 'mp4Avc'), None)
                            if v_url and v_id not in history:
                                if any(kw in title.lower() for kw in BLACK_KEYWORDS): continue
                                is_jpn = any(kw in title.lower() for kw in JPN_KEYWORDS)
                                if is_jpn: candidates.append({"title": title, "url": v_url, "id": v_id, "type": "mlb", "source": "@MLBJapan", "priority": 2})
                                elif is_test_mode and "home run" in title.lower(): candidates.append({"title": title, "url": v_url, "id": v_id, "type": "mlb", "source": "@MLBJapan", "priority": 3})
                    except: continue
        except: continue
    return candidates

def analyze_video_with_ai(video_path, title, source_account, model_name):
    """人間が書いたような自然なキャプションを生成"""
    print(f"🧠 AIによる動画解析中 (使用モデル: {model_name})...")
    try:
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING": time.sleep(2); video_file = genai.get_file(video_file.name)
        model = genai.GenerativeModel(model_name)
        
        prompt = f"""
        野球動画({title})を解析し、以下の2つを必ず出力せよ。

        1. 動画の開始秒数（数値1つだけ）
        2. インスタのリール用キャプション本文

        【キャプション構成ルール】
        ・一段目：【 】で囲った、見た人を一気に引き込む鋭い見出し（皮肉や分析を交える）。
        ・二段目：ニュースの核心を2行程度で。
        ・三段目：アナリスト視点からの熱い、または皮肉のきいた鋭い所感。
        ・四段目：見どころのタイムスタンプ（例：「0:12 豪快なスイング」「0:18 確信歩き」など自然に）。
        
        【重要：Bot感を消すための禁止事項】
        ・「START:」「CAPTION:」「秒数：」などのラベル文字は絶対に書くな。
        ・ネットスラング（ワロタ、www、ｷﾀ━━）は禁止。
        ・標準語の「だ・である」調を徹底。
        ・引用：{source_account} は最後に1回だけ記載。
        ・ハッシュタグは合計25個程度。
        """
        response = model.generate_content([prompt, video_file])
        res_text = response.text
        genai.delete_file(video_file.name)

        # 最初の数字を開始秒数として抽出
        start_match = re.search(r"(\d+)", res_text)
        start_sec = int(start_match.group(1)) if start_match else 0
        
        # 数値を除いた残りをキャプションとする
        ai_caption = re.sub(r"^\d+\s*", "", res_text).strip()
        
        print(f"  ✨ AI解析成功: 開始 {start_sec}s")
        return start_sec, ai_caption
    except Exception as e:
        print(f"  ⚠️ AI解析失敗: {e}")
        return None, None

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats(); history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    cleanup_gemini_storage()
    flash_model = get_available_flash_model()
    
    print(f"⚾️ 探索開始...")
    npb_candidates = get_npb_video(history)
    mlb_candidates = get_mlb_video(history, is_test_mode)
    candidates = npb_candidates + mlb_candidates
    
    if not candidates: print("😴 新着なし"); return

    total_posted = stats['npb'] + stats['mlb']
    mlb_ratio = stats['mlb'] / total_posted if total_posted > 0 else 0

    candidates.sort(key=lambda x: x['priority'])
    
    for video in candidates[:15]:
        if not is_test_mode and video['type'] == 'mlb' and mlb_ratio > 0.25 and len(npb_candidates) > 0:
            continue

        print(f"🎯 ターゲット確定: {video['title']}")
        temp_input = "temp_video.mp4"
        subprocess.run(['curl', '-L', video['url'], '-o', temp_input])
        if not os.path.exists(temp_input) or os.path.getsize(temp_input) < 10000: continue

        start_sec, ai_caption = analyze_video_with_ai(temp_input, video['title'], video['source'], flash_model)
        if ai_caption is None:
            with open(history_file, 'a') as fh: fh.write(video['id'] + "\n")
            continue

        output_file = "output.mp4"
        filter_complex = "scale=1134:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
        subprocess.run(['ffmpeg', '-ss', str(start_sec), '-i', temp_input, '-t', '90', '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-b:v', '5M', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-y', output_file])
        
        try:
            with open(output_file, 'rb') as f:
                res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f}, timeout=60).json()
                if res.get('status') == 'success':
                    public_url = res['data']['url'].replace("http://", "https://").replace("tmpfiles.org/", "tmpfiles.org/dl/")
                    print(f"✅ 公開準備完了: {public_url}")
                    time.sleep(10)
                    post_res = requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media", data={'media_type': 'REELS', 'video_url': public_url, 'caption': ai_caption, 'access_token': ACCESS_TOKEN}).json()
                    
                    if 'id' in post_res:
                        creation_id = post_res['id']
                        for _ in range(20):
                            time.sleep(30)
                            status_res = requests.get(f"https://graph.facebook.com/v21.0/{creation_id}", params={'fields': 'status_code,status', 'access_token': ACCESS_TOKEN}).json()
                            status = (status_res.get('status_code') or status_res.get('status') or "").upper()
                            if status == 'FINISHED':
                                requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN})
                                print(f"🏁 投稿完了！: {video['title']}")
                                with open(history_file, 'a') as fh: fh.write(video['id'] + "\n")
                                stats[video['type']] += 1; save_stats(stats); return
        except Exception as e: print(f"  ❌ エラー: {e}")
    print("😴 終了。")

if __name__ == "__main__":
    main()