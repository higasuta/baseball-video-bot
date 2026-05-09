import sys
# リアルタイムログ出力
print("🚀 プレイボール速報・新章（Nitter回避 ＋ 日本人15名網羅モード）起動...")
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

BLACK_KEYWORDS = ["probable", "pitchers", "lineup", "interview", "press", "availability", "roster", "update", "alignment", "summary", "preview", "warmup", "positioning", "at bat", "statcast", "recap", "daily", "full highlights"]

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
        print("🧹 AIストレージの掃除完了。")
    except: pass

def get_available_flash_model():
    try:
        model_names = [m.name for m in genai.list_models() if 'flash' in m.name]
        priority_models = ["models/gemini-flash-lite-latest", "models/gemini-2.5-flash", "models/gemini-1.5-flash"]
        for pm in priority_models:
            if pm in model_names: return pm
        return model_names[0]
    except: return "models/gemini-1.5-flash"

def get_npb_video(history):
    """Nitter（Xのミラー）経由でパ・リーグTV等の動画をスキャン"""
    # Xを直接見るとブロックされるため、検閲の緩いミラーサイトを使用
    nitter_instances = ["https://nitter.net", "https://nitter.it", "https://nitter.moe"]
    target_accounts = ["PacificleagueTV", "sportsnavi_ybB"]
    
    candidates = []
    for instance in nitter_instances:
        for account in target_accounts:
            url = f"{instance}/{account}"
            print(f"🔍 NPB探索中 (Nitter経由: @{account})...")
            try:
                # Nitter経由で最新ツイートの動画ID、タイトル、URLを取得
                cmd = ['yt-dlp', '--get-id', '--get-title', '--get-url', '--playlist-end', '5', '--no-check-certificates', '--quiet', url]
                output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=40).decode().split('\n')
                for i in range(0, len(output)-2, 3):
                    title, v_id, v_url = output[i].strip(), output[i+1].strip(), output[i+2].strip()
                    if v_id and v_id not in history:
                        if any(kw in title.lower() for kw in BLACK_KEYWORDS): continue
                        print(f"  ✅ Nitterルートで発見: {title}")
                        return {"title": title, "url": v_url, "id": v_id, "type": "npb", "source": f"@{account}", "priority": 1}
            except: continue
    return None

def get_mlb_video(history, is_test_mode):
    print("🔍 MLB動画を探索中（日本人15名4パターン検索）...")
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
                                # 日本人15名の誰かに合致するか
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
        野球動画({title})を解析し、以下の形式で出力せよ。

        [開始秒数(数値のみ)]
        [本文]

        【ルール】
        ・あなたは野球の「2chまとめ解説動画」の、少し皮肉っぽいが愛のあるナレーターだ。
        ・一段目：【 】付きの鋭い見出し。
        ・二段目：ニュースの核心を短く。
        ・三段目：アナリスト視点での深い、あるいは皮肉のきいた解説。
        ・四段目：[0:05] 〇〇の瞬間、のようにタイムスタンプを自然に。
        ・「だ・である」調を徹底。ですます、START、CAPTIONなどのラベルは禁止。
        ・ハッシュタグは25〜30個。中黒「・」は禁止。
        引用：{source_account}
        """
        response = model.generate_content([prompt, video_file])
        res_text = response.text
        genai.delete_file(video_file.name)

        # ラベル文字（START等）を物理的に一掃する正規表現
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

    cleanup_gemini_storage()
    flash_model = get_available_flash_model()
    
    print(f"⚾️ 探索開始...")
    video_data = get_npb_video(history)
    
    # NPBが見つからなければMLB
    if not video_data:
        mlb_list = get_mlb_video(history, is_test_mode)
        if mlb_list:
            total_posted = stats['npb'] + stats['mlb']
            mlb_ratio = stats['mlb'] / total_posted if total_posted > 0 else 0
            # 比率が25%を超えていたらMLBはスキップ
            if not is_test_mode and mlb_ratio > 0.25:
                print(f"🛑 MLB比率制限 ({mlb_ratio*100:.1f}%) のため待機。")
            else:
                video_data = mlb_list[0]

    if video_data:
        print(f"🎯 ターゲット確定: {video_data['title']}")
        temp_input = "temp_video.mp4"
        # Nitter経由のURLはcurlで直接落とせる
        subprocess.run(['curl', '-L', video_data['url'], '-o', temp_input])
        
        if not os.path.exists(temp_input) or os.path.getsize(temp_input) < 10000:
            print("❌ ダウンロード失敗。"); return

        start_sec, ai_caption = analyze_video_with_ai(temp_input, video_data['title'], video_data['source'], flash_model)
        if ai_caption is None:
            with open(history_file, 'a') as fh: fh.write(video_data['id'] + "\n"); return

        output_file = "output.mp4"
        filter_complex = "scale=1134:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
        subprocess.run(['ffmpeg', '-ss', str(start_sec), '-i', temp_input, '-t', '90', '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-b:v', '5M', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-y', output_file])
        
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
                            if status == 'FINISHED':
                                requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN})
                                print(f"🏁 投稿完了！")
                                with open(history_file, 'a') as fh: fh.write(video_data['id'] + "\n")
                                stats[video_data['type']] += 1; save_stats(stats); return
        except Exception as e: print(f"  ❌ エラー: {e}")
    else: print("😴 投稿対象なし。")

if __name__ == "__main__":
    main()