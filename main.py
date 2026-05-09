import sys
# リアルタイムログ出力設定
print("🚀 プレイボール速報・システム稼働開始...")
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

# 【完全網羅】日本人選手キーワード（1人4パターン × 15名 = 60キーワード）
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

# 排除キーワード（地味な動画・データ動画を徹底排除）
BLACK_KEYWORDS = ["probable", "pitchers", "lineup", "interview", "press", "availability", "roster", "update", "alignment", "summary", "preview", "warmup", "positioning", "against", "at bat", "statcast", "recap", "daily", "full highlights"]

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
    """NPB動画を探索（解析精度を極限まで強化）"""
    candidates = []
    # ルートB: スポーツナビをメインに据える（requestsベースで安定）
    print("🔍 NPB探索中 (スポーツナビ解析)...")
    try:
        url = "https://sports.yahoo.co.jp/video/list/promo/live/baseball/npb"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        res = requests.get(url, headers=headers, timeout=20)
        
        # ID、リンク、タイトルの三位一体抽出
        items = re.findall(r'href="/video/player/(\d+)".*?><h3[^>]*?>(.*?)</h3>', res.text, re.DOTALL)
        unique_items = []
        seen_ids = set()
        for v_id, title in items:
            if v_id not in seen_ids:
                unique_items.append((v_id, title.strip()))
                seen_ids.add(v_id)

        for v_id, title in unique_items:
            if v_id not in history:
                if any(kw in title.lower() for kw in BLACK_KEYWORDS): continue
                print(f"  ✅ NPB候補発見: {title}")
                candidates.append({
                    "title": title, "url": f"https://sports.yahoo.co.jp/video/player/{v_id}", 
                    "id": v_id, "type": "npb", "source": "スポーツナビ", "priority": 1
                })
    except Exception as e: print(f"  ⚠️ ルートB失敗: {e}")
    return candidates

def get_mlb_candidates(history, is_test_mode):
    print("🔍 MLB動画を探索中（日本人選手完全網羅）...")
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
                                # 全員網羅したJPN_KEYWORDSでチェック
                                if any(kw in title.lower() for kw in JPN_KEYWORDS):
                                    candidates.append({"title": title, "url": v_url, "id": v_id, "type": "mlb", "source": "@MLBJapan", "priority": 2})
                    except: continue
        except: continue
    return candidates

def analyze_video_with_ai(video_path, title, source_account, model_name):
    """Botラベルを排除した自然なキャプションを生成"""
    print(f"🧠 AI解析中 (モデル: {model_name})...")
    try:
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING": time.sleep(2); video_file = genai.get_file(video_file.name)
        model = genai.GenerativeModel(model_name)
        
        prompt = f"""
        野球動画({title})を解析し、以下の2つを必ず出力せよ。

        [秒数のみ]
        [本文]

        【ルール】
        ・一段目：【 】付きの鋭い見出し（皮肉や分析を交える）。
        ・二段目：ニュースの核心。
        ・三段目：アナリスト視点の鋭い所感。
        ・四段目：[0:12] のような自然なタイムスタンプ。
        ・「です・ます」禁止。標準語の「だ・である」調を徹底。
        ・ラベル（START:、CAPTION:、秒数: 等）は絶対に出力するな。
        ・ハッシュタグは合計25〜30個。中黒「・」は禁止。
        引用：{source_account} は最後に1回だけ記載。
        """
        response = model.generate_content([prompt, video_file])
        res_text = response.text
        genai.delete_file(video_file.name)

        # ラベル文字（START等）が混入していたら物理的に削除
        clean_text = re.sub(r'(?i)(START|CAPTION|秒数|本文|開始)[:：]\s*', '', res_text).strip()

        lines = [l.strip() for l in clean_text.split('\n') if l.strip()]
        if not lines: return 0, None
        
        # 最初の行に数字が含まれていればそれを秒数に
        first_line_match = re.search(r"(\d+)", lines[0])
        if first_line_match:
            start_sec = int(first_line_match.group(1))
            ai_caption = "\n".join(lines[1:])
        else:
            start_sec = 0
            ai_caption = "\n".join(lines)

        print(f"  ✨ 解析成功: 開始 {start_sec}s")
        return start_sec, ai_caption
    except: return None, None

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats(); history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    cleanup_gemini_storage()
    flash_model = get_available_flash_model()
    
    print(f"⚾️ 探索開始...")
    npb_candidates = get_npb_candidates(history)
    mlb_candidates = get_mlb_candidates(history, is_test_mode)
    candidates = npb_candidates + mlb_candidates
    
    if not candidates: print("😴 新着なし"); return

    total_posted = stats['npb'] + stats['mlb']
    mlb_ratio = stats['mlb'] / total_posted if total_posted > 0 else 0
    print(f"📊 現在のMLB比率: {mlb_ratio*100:.1f}%")

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