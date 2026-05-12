import sys
# リアルタイムログ出力
print("🚀 プレイボール速報・最終システム（Xログイン突破 ＋ 日本人15名網羅版）起動...")
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

# 【完全網羅】日本人選手キーワード（15名 × 4パターン = 60個）
JPN_KEYWORDS = [
    "大谷翔平", "大谷", "shohei ohtani", "ohtani",
    "山本由伸", "山本", "yoshinobu yamamoto", "yamamoto",
    "佐々木朗希", "佐々木", "roki sasaki", "sasaki",
    "ダルビッシュ有", "ダルビッシュ", "yu darvish", "darvish",
    "松井裕樹", "松井", "yuki matsui", "matsui",
    "鈴木誠也", "鈴木", "seiya suzuki", "suzuki",
    "今永昇太", "今永", "shota imanaga", "imanaga",
    "千賀滉大", "千賀", "kodai senga", "senga",
    "菅野智之", "菅野", "tomoyuki sugano", "sugano",
    "小笠原慎之介", "小笠原", "shinnosuke ogasawara", "ogasawara",
    "岡本和真", "岡本", "kazuma okamoto", "okamoto",
    "今井達也", "今井", "tatsuya imai", "imai",
    "吉田正尚", "吉田", "masataka yoshida", "yoshida",
    "菊池雄星", "菊池", "yusei kikuchi", "kikuchi",
    "村上宗隆", "村上", "munetaka murakami", "murakami"
]

BLACK_KEYWORDS = ["probable", "pitchers", "lineup", "interview", "press", "availability", "roster", "update", "alignment", "summary", "preview", "warmup", "positioning", "against", "at bat", "statcast", "recap", "daily", "full highlights", "outing", "talks", "comments"]

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
        for f in genai.list_files(): genai.delete_file(f.name)
        print("🧹 AIストレージの掃除完了。")
    except: pass

def get_available_flash_model():
    try:
        model_names = [m.name for m in genai.list_models() if 'flash' in m.name]
        priority_models = ["models/gemini-2.0-flash", "models/gemini-flash-lite-latest", "models/gemini-1.5-flash"]
        for pm in priority_models:
            if pm in model_names: return pm
        return model_names[0] if model_names else "models/gemini-1.5-flash"
    except: return "models/gemini-1.5-flash"

def get_npb_video(history):
    """【ログイン突破】Xの公式アカウントから動画を探索"""
    targets = [
        "https://x.com/PacificleagueTV",
        "https://x.com/BaseballkingJP",
        "https://x.com/DAZN_JPN"
    ]
    candidates = []
    
    for url in targets:
        print(f"🔍 Xスキャン中 (@{url.split('/')[-1]})...")
        try:
            # クッキーを使用してアクセス
            cmd = ['yt-dlp', '--get-id', '--get-title', '--get-url', '--playlist-end', '5', '--no-check-certificates', '--quiet']
            if os.path.exists('x_cookies.txt'):
                cmd += ['--cookies', 'x_cookies.txt']
            cmd.append(url)
            
            output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=40).decode().split('\n')
            for i in range(0, len(output)-2, 3):
                title, v_id, v_url = output[i].strip(), output[i+1].strip(), output[i+2].strip()
                if v_id and v_id not in history:
                    if any(kw in title.lower() for kw in BLACK_KEYWORDS): continue
                    candidates.append({"title": title, "url": v_url, "id": v_id, "type": "npb", "source": url.split('/')[-1], "priority": 1})
        except: continue
    return candidates

def get_mlb_video(history, is_test_mode):
    print("🔍 MLB動画を探索中（日本人15名網羅）...")
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
                                if any(kw in title.lower() for kw in JPN_KEYWORDS):
                                    candidates.append({"title": title, "url": v_url, "id": v_id, "type": "mlb", "source": "@MLBJapan", "priority": 2})
                    except: continue
        except: continue
    return candidates

def analyze_video_with_ai(video_path, title, source_account, model_name):
    print(f"🧠 AIによる動画解析中...")
    try:
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING": time.sleep(2); video_file = genai.get_file(video_file.name)
        model = genai.GenerativeModel(model_name)
        
        prompt = f"""
        野球動画({title})を解析し、以下を出力せよ。
        [開始秒数(数値のみ)を1行目]
        [本文を2行目以降]

        【ルール】
        ・あなたは野球まとめ動画の少し皮肉っぽいが愛のあるナレーターだ。
        ・一段目：【 】付きの鋭い見出し。二段目：要約。三段目：アナリスト視点の鋭い所感。
        ・四段目：[0:05] 〇〇の瞬間、のようにタイムスタンプを自然に添えろ。
        ・「です・ます」禁止。標準語の「だ・である」調を徹底せよ。
        ・START: や CAPTION: などのラベル、ネットスラングは禁止。
        ・ハッシュタグは合計25〜30個（中黒禁止）。引用：{source_account} を最後に。
        """
        response = model.generate_content([prompt, video_file])
        res_text = response.text
        genai.delete_file(video_file.name)

        # ラベル(START:等)を物理的に削り取る
        clean_text = re.sub(r'(?i)(START|CAPTION|秒数|本文|開始|タイトル|見出し|概要|所感)[:：]\s*', '', res_text).strip()
        
        lines = [l.strip() for l in clean_text.split('\n') if l.strip()]
        start_sec = 0
        first_line_match = re.search(r"(\d+)", lines[0]) if lines else None
        if first_line_match:
            start_sec = int(first_line_match.group(1))
            ai_caption = "\n".join(lines[1:])
        else:
            ai_caption = "\n".join(lines)
            
        return start_sec, ai_caption
    except: return None, None

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats(); history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    cleanup_gemini_storage(); flash_model = get_available_flash_model()
    
    print(f"⚾️ 探索開始...")
    npb_list = get_npb_video(history)
    mlb_list = get_mlb_video(history, is_test_mode)
    candidates = npb_list + mlb_list
    
    if not candidates: print("😴 新着なし"); return

    total_posted = stats['npb'] + stats['mlb']
    mlb_ratio = stats['mlb'] / total_posted if total_posted > 0 else 0
    print(f"📊 MLB比率: {mlb_ratio*100:.1f}%")

    candidates.sort(key=lambda x: x.get('priority', 2))
    
    for video in candidates:
        if not is_test_mode and video['type'] == 'mlb' and mlb_ratio > 0.25 and len(npb_list) > 0:
            continue

        print(f"🎯 ターゲット確定: {video['title']}")
        temp_input = "temp_video.mp4"
        
        # ログインクッキーを使用したダウンロード
        cmd = ['yt-dlp', '-o', temp_input, '--no-check-certificates', '--quiet']
        if os.path.exists('x_cookies.txt') and video['type'] == 'npb':
            cmd += ['--cookies', 'x_cookies.txt']
        cmd.append(video['url'])
        
        if video['type'] == 'mlb':
            subprocess.run(['curl', '-L', video['url'], '-o', temp_input])
        else:
            subprocess.run(cmd)
        
        if not os.path.exists(temp_input) or os.path.getsize(temp_input) < 10000:
            continue

        start_sec, ai_caption = analyze_video_with_ai(temp_input, video['title'], video['source'], flash_model)
        if ai_caption is None:
            with open(history_file, 'a') as fh: fh.write(video['id'] + "\n"); continue

        output_file = "output.mp4"
        filter_complex = "scale=1134:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
        subprocess.run(['ffmpeg', '-ss', str(start_sec), '-i', temp_input, '-t', '90', '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-b:v', '5M', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-y', output_file])
        
        try:
            with open(output_file, 'rb') as f:
                res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f}, timeout=60).json()
                if res.get('status') == 'success':
                    public_url = res['data']['url'].replace("http://", "https://").replace("tmpfiles.org/", "tmpfiles.org/dl/")
                    print(f"✅ 公開URL確保")
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
                                print(f"🏁 投稿完了！")
                                with open(history_file, 'a') as fh: fh.write(video['id'] + "\n")
                                stats[video['type']] += 1; save_stats(stats); return
        except Exception as e: print(f"  ❌ エラー: {e}")
    print("😴 終了。")

if __name__ == "__main__":
    main()
