import sys
# リアルタイムログ出力設定
print("🚀 プレイボール速報・新章（Livedoor/スポブル奪還 ＋ 執念のリトライ）起動...")
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

# 【完全網羅】日本人選手（15名）
JPN_KEYWORDS = ["大谷翔平", "大谷", "shohei ohtani", "ohtani", "山本由伸", "山本", "yoshinobu yamamoto", "yamamoto", "佐々木朗希", "佐々木", "roki sasaki", "sasaki", "ダルビッシュ有", "ダルビッシュ", "yu darvish", "darvish", "松井裕樹", "松井", "yuki matsui", "matsui", "鈴木誠也", "鈴木", "seiya suzuki", "suzuki", "今永昇太", "今永", "shota imanaga", "imanaga", "千賀滉大", "千賀", "kodai senga", "senga", "菅野智之", "菅野", "tomoyuki sugano", "sugano", "小笠原慎之介", "小笠原", "shinnosuke ogasawara", "ogasawara", "岡本和真", "岡本", "kazuma okamoto", "okamoto", "今井達也", "今井", "tatsuya imai", "imai", "吉田正尚", "吉田", "masataka yoshida", "yoshida", "菊池雄星", "菊池", "yusei kikuchi", "kikuchi", "村上宗隆", "村上", "munetaka murakami", "murakami"]

BLACK_KEYWORDS = ["probable", "pitchers", "lineup", "interview", "press", "availability", "roster", "update", "alignment", "summary", "preview", "warmup", "positioning", "at bat", "statcast", "recap", "daily", "full highlights", "outing", "talks"]

def get_stats():
    if os.path.exists('stats.json'):
        try:
            with open('stats.json', 'r') as f: return json.load(f)
        except: pass
    return {"npb": 75, "mlb": 25}

def save_stats(stats):
    with open('stats.json', 'w') as f:
        json.dump(stats, f)

def find_working_model():
    """Gemini 1.5 Flash 系統を最優先で安定稼働させる"""
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        for target in ["gemini-1.5-flash", "gemini-1.5-flash-latest", "gemini-flash"]:
            for m in available_models:
                if target in m: return m
        return available_models[0]
    except: return "models/gemini-1.5-flash"

def get_npb_candidates(history):
    """【新ルート】Livedoor ＆ スポーツブルから動画を執念深くスキャン"""
    candidates = []
    ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    headers = {"User-Agent": ua}

    # ルート1: Livedoor ニュース (野球ビデオ枠)
    print("🔍 NPBルートA (Livedoorニュース) 探索中...")
    try:
        url = "https://news.livedoor.com/category/v/baseball/"
        res = requests.get(url, headers=headers, timeout=15)
        # 記事詳細URLから動画IDを特定
        v_ids = re.findall(r'article/detail/(\d+)/', res.text)
        for v_id in list(dict.fromkeys(v_ids))[:5]:
            if v_id not in history:
                v_url = f"https://news.livedoor.com/article/detail/{v_id}/"
                candidates.append({"title": "NPB名シーン", "url": v_url, "id": v_id, "type": "npb", "source": "Livedoor"})
    except: pass

    # ルート2: スポーツブル (独自配信プレイヤー)
    print("🔍 NPBルートB (スポーツブル) 探索中...")
    try:
        url = "https://sportsbull.jp/category/baseball/"
        res = requests.get(url, headers=headers, timeout=15)
        # SPORTS BULLの動画ページIDを抽出
        v_ids = re.findall(r'https://sportsbull.jp/p/(\d+)/', res.text)
        for v_id in list(dict.fromkeys(v_ids))[:5]:
            if v_id not in history:
                candidates.append({"title": "NPB注目プレー", "url": f"https://sportsbull.jp/p/{v_id}/", "id": v_id, "type": "npb", "source": "SportsBull"})
    except: pass

    return candidates

def get_mlb_candidates(history, is_test_mode):
    print("🔍 MLB動画を探索中（日本人15名限定）...")
    candidates = []
    for day_offset in range(3):
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
                                    candidates.append({"title": title, "url": v_url, "id": v_id, "type": "mlb", "source": "@MLBJapan"})
                    except: continue
        except: continue
    return candidates

def analyze_video_with_ai(video_path, title, source_account, model_name):
    print(f"🧠 AIによる動画解析中...")
    try:
        # クォータ（容量）制限対策
        for f in genai.list_files(): genai.delete_file(f.name)
        
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING": time.sleep(3); video_file = genai.get_file(video_file.name)
        
        model = genai.GenerativeModel(model_name)
        prompt = f"""
        野球動画({title})を解析し、以下を出力せよ。
        1. [数値のみを1行目]
        2. [本文を2行目以降に]

        【ルール】
        ・あなたは野球まとめ動画の少し皮肉っぽいが愛のある解説者だ。
        ・一段目：【 】付きの鋭い見出し。二段目：要約。三段目：アナリスト視点の鋭い所感。
        ・[0:05] 〇〇の瞬間、のようにタイムスタンプを自然に組み込め。
        ・START, CAPTION, 見出し, 概要 などのラベル文字は絶対に書くな。
        ・ハッシュタグ25個。引用：{source_account}
        """
        response = model.generate_content([prompt, video_file])
        res_text = response.text
        genai.delete_file(video_file.name)

        # 【物理抹殺】不純なラベル文字を正規表現で徹底消去
        clean_text = re.sub(r'(?i)(START|CAPTION|秒数|本文|開始|タイトル|見出し|概要|所感|解説|所見|タイムスタンプ)[:：]\s*', '', res_text).strip()
        lines = [l.strip() for l in clean_text.split('\n') if l.strip()]
        
        start_sec = 0
        first_line_match = re.search(r"(\d+)", lines[0]) if lines else None
        if first_line_match:
            start_sec = int(first_line_match.group(1))
            ai_caption = "\n".join(lines[1:])
        else:
            ai_caption = "\n".join(lines)
            
        print(f"  ✨ AI解析成功: 開始 {start_sec}s")
        return start_sec, ai_caption
    except: return None, None

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats(); history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    flash_model = find_working_model()
    
    print(f"⚾️ 探索開始...")
    npb_candidates = get_npb_candidates(history)
    mlb_candidates = get_mlb_candidates(history, is_test_mode)
    # NPBを最優先にしたリトライ用リストを作成
    all_targets = npb_candidates + mlb_candidates
    
    if not all_targets: print("😴 新着なし"); return

    total_posted = stats['npb'] + stats['mlb']
    mlb_ratio = stats['mlb'] / total_posted if total_posted > 0 else 0
    print(f"📊 MLB比率: {mlb_ratio*100:.1f}%")

    # 【不屈のリトライループ】ダウンロードに成功するまでリストを上から順に試す
    for video in all_targets:
        # MLB比率制限: NPB候補がある限りMLBはスキップ
        if not is_test_mode and video['type'] == 'mlb' and mlb_ratio > 0.25 and len(npb_candidates) > 0:
            continue

        print(f"🎯 ターゲット試行: {video['title']} ({video['source']})")
        temp_input = "temp_video.mp4"
        # yt-dlp と curl の二段構えで絶対に落とす
        subprocess.run(['curl', '-L', video['url'], '-o', temp_input])
        if not os.path.exists(temp_input) or os.path.getsize(temp_input) < 10000:
            subprocess.run(['yt-dlp', '-o', temp_input, '--no-check-certificates', '--quiet', video['url']])

        if not os.path.exists(temp_input) or os.path.getsize(temp_input) < 10000:
            print("  ❌ ダウンロード失敗。次の候補を試します。"); continue

        start_sec, ai_caption = analyze_video_with_ai(temp_input, video['title'], video['source'], flash_model)
        if ai_caption is None:
            # プレーがないと判断されたものはIDを残して次へ
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
                        print(f"⏳ ステータス監視中...")
                        for i in range(20):
                            time.sleep(30)
                            status_res = requests.get(f"https://graph.facebook.com/v21.0/{creation_id}", params={'fields': 'status_code,status', 'access_token': ACCESS_TOKEN}).json()
                            status = (status_res.get('status_code') or status_res.get('status') or "").upper()
                            print(f"  API Response: {status}")
                            if status == 'FINISHED':
                                requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN})
                                print(f"🏁 投稿完了！")
                                with open(history_file, 'a') as fh: fh.write(video['id'] + "\n")
                                stats[video['type']] += 1; save_stats(stats); return
        except Exception as e: print(f"  ❌ エラー: {e}")
    print("😴 全ての候補を試しましたが投稿できませんでした。")

if __name__ == "__main__":
    main()
