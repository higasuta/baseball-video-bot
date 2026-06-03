import sys
import os
import requests
import datetime
import time
import subprocess
from google import genai
import json
import re

def log(msg):
    print(f"{msg}")
    sys.stdout.flush()

log("🚀 プレイボール速報・システム最終形態（FFmpegパス ＋ フォント同期）起動...")

# ==========================================
# 設定・環境変数
# ==========================================
INSTA_ID = os.getenv('INSTA_BUSINESS_ID')
ACCESS_TOKEN = os.getenv('INSTA_ACCESS_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

# ファイル名は相対パスで統一（FFmpegのパースエラー防止）
TMP_VIDEO = "temp_video.mp4"
TMP_SRT = "subtitles.srt"
OUT_VIDEO = "output.mp4"

client = None
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)

JPN_KEYWORDS = ["大谷翔平", "大谷", "shohei ohtani", "ohtani", "山本由伸", "山本", "yoshinobu yamamoto", "yamamoto", "佐々木朗希", "佐々木", "roki sasaki", "sasaki", "ダルビッシュ有", "ダルビッシュ", "yu darvish", "darvish", "松井裕樹", "松井", "yuki matsui", "matsui", "鈴木誠也", "鈴木", "seiya suzuki", "suzuki", "今永昇太", "今永", "shota imanaga", "imanaga", "千賀滉大", "千賀", "kodai senga", "senga", "菅野智之", "菅野", "tomoyuki sugano", "sugano", "小笠原慎之介", "小笠原", "shinnosuke ogasawara", "ogasawara", "岡本和真", "岡本", "kazuma okamoto", "okamoto", "今井達也", "今井", "tatsuya imai", "imai", "吉田正尚", "吉田", "masataka yoshida", "yoshida", "菊池雄星", "菊池", "yusei kikuchi", "kikuchi", "村上宗隆", "村上", "munetaka murakami", "murakami"]
BLACK_KEYWORDS = ["probable", "pitchers", "lineup", "interview", "press", "roster", "statcast", "talks"]

def get_stats():
    if os.path.exists('stats.json'):
        try:
            with open('stats.json', 'r') as f: return json.load(f)
        except: pass
    return {"npb": 0, "mlb": 0}

def save_stats(stats):
    with open('stats.json', 'w') as f: json.dump(stats, f)

def is_japanese(text):
    return bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', text))

def shift_srt_time(srt_text, offset_sec):
    correction = offset_sec + 0.5 
    def shift_match(match):
        time_str = match.group(1)
        h, m, s_ms = time_str.split(':')
        s, ms = s_ms.split(',')
        total_ms = (int(h)*3600 + int(m)*60 + int(s)) * 1000 + int(ms)
        shifted_ms = max(0, total_ms - int(correction * 1000))
        new_h, rem = divmod(shifted_ms, 3600000)
        new_m, rem = divmod(rem, 60000)
        new_s, new_ms = divmod(rem, 1000)
        return f"{new_h:02}:{new_m:02}:{new_s:02},{new_ms:03}"
    
    shifted_text = re.sub(r'(\d{2}:\d{2}:\d{2},\d{3})', shift_match, srt_text)
    cleaned_lines = []
    for line in shifted_text.splitlines():
        if "-->" in line or line.strip().isdigit():
            cleaned_lines.append(line)
        else:
            line = re.sub(r'^(English|Original|Transcript|Source|原文|英語|日本語)[:：]\s*', '', line, flags=re.IGNORECASE)
            if is_japanese(line): cleaned_lines.append(line)
    return "\n".join(cleaned_lines)

def analyze_video_with_ai(video_path, title, source_account, model_name, is_mlb=False):
    log(f"🧠 AI解析開始...")
    try:
        with open(video_path, 'rb') as f:
            uploaded_file = client.files.upload(file=f, config={'mime_type': 'video/mp4'})
        while uploaded_file.state.name == "PROCESSING":
            time.sleep(2)
            uploaded_file = client.files.get(name=uploaded_file.name)
        
        subtitle_instruction = ""
        if is_mlb:
            subtitle_instruction = "英語実況を日本語SRT字幕にせよ。日本語のみ。絶対同期。[SRT_START]...[SRT_END]で囲め。"

        prompt = f"野球動画({title})を解析せよ。[数値1つ(開始秒数)]と[本文]を出力。{subtitle_instruction} 【ルール】見出し、要約、所感を日本語のみで。"
        response = client.models.generate_content(model=model_name, contents=[uploaded_file, prompt])
        res_text = response.text
        client.files.delete(name=uploaded_file.name)

        srt_data = None
        if is_mlb:
            srt_match = re.search(r'\[SRT_START\](.*?)\[SRT_END\]', res_text, re.DOTALL)
            if srt_match: srt_data = shift_srt_time(srt_match.group(1).strip(), 0)

        clean_text = re.sub(r'(?i)(START|CAPTION|秒数|本文|開始|タイトル|見出し|概要|所感|SRT)[:：]\s*', '', res_text).strip()
        lines = [l.strip() for l in clean_text.split('\n') if l.strip()]
        if not lines: return 0, None, None
        
        start_sec = 0
        match = re.search(r"(\d+)", lines[0])
        if match:
            start_sec = int(match.group(1))
            ai_caption = "\n".join(lines[1:])
        else: ai_caption = "\n".join(lines)
        return start_sec, ai_caption, srt_data
    except Exception as e:
        log(f"  ⚠️ AI解析失敗: {e}"); return 0, None, None

def main():
    history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    stats = get_stats()
    if client:
        try:
            for f in client.files.list(): client.files.delete(name=f.name)
        except: pass

    try:
        models = [m.name for m in client.models.list()]
        model_name = next((p for p in ["models/gemini-2.0-flash-exp", "models/gemini-1.5-flash"] if p in models), models[0])
    except: model_name = "models/gemini-1.5-flash"

    candidates = []
    log("🔍 NPB探索...")
    try:
        res = requests.get("https://www3.nhk.or.jp/sports/json/pro-baseball/index.json", timeout=15).json()
        for clip in res.get('clips', []):
            v_id = str(clip.get('id'))
            if v_id not in history:
                candidates.append({"title": clip.get('title', ''), "url": clip.get('video_url') or f"https://www3.nhk.or.jp/sports/special/baseball/npb/videos/{v_id}", "id": v_id, "type": "npb", "source": "NHKスポーツ"})
    except: pass

    log("🔍 MLB探索...")
    for day in [0, 1]:
        date_str = (datetime.datetime.now() - datetime.timedelta(days=day)).strftime('%Y-%m-%d')
        try:
            res = requests.get(f"https://statsapi.mlb.com/api/v1/schedule/games/?sportId=1&startDate={date_str}&endDate={date_str}", timeout=15).json()
            for date_data in res.get('dates', []):
                for game in date_data.get('games', []):
                    c_res = requests.get(f"https://statsapi.mlb.com/api/v1/game/{game['gamePk']}/content", timeout=10).json()
                    for item in c_res.get('highlights', {}).get('highlights', {}).get('items', []):
                        title = item.get('headline', ''); v_id = str(item.get('id'))
                        if v_id not in history and any(kw in title.lower() for kw in JPN_KEYWORDS):
                            v_url = next((p['url'] for p in item['playbacks'] if p['name'] == 'mp4Avc'), None)
                            if v_url: candidates.append({"title": title, "url": v_url, "id": v_id, "type": "mlb", "source": "@MLBJapan"})
        except: continue

    log(f"📊 候補: {len(candidates)}件")
    for video in candidates:
        log(f"🎯 ターゲット: {video['title']}")
        for f in [TMP_VIDEO, TMP_SRT, OUT_VIDEO]:
            if os.path.exists(f): os.remove(f)

        subprocess.run(['yt-dlp', '-o', TMP_VIDEO, '--quiet', video['url']])
        if not os.path.exists(TMP_VIDEO): continue

        start_sec, ai_caption, srt_data = analyze_video_with_ai(TMP_VIDEO, video['title'], video['source'], model_name, is_mlb=(video['type'] == 'mlb'))
        
        if ai_caption:
            filter_complex = "scale=1134:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
            
            # MLBかつ有効な字幕データがある場合のみ焼き込み
            if video['type'] == 'mlb' and srt_data and len(srt_data) > 10:
                with open(TMP_SRT, "w", encoding="utf-8") as sf:
                    sf.write(srt_data)
                # Linuxで最も安全な指定方法 (相対パス、フォント名修正)
                filter_complex += f",subtitles={TMP_SRT}:force_style='Fontname=Noto Sans CJK JP,FontSize=13,MarginV=45'"
                log("🎨 字幕焼き込みを適用")

            # FFmpeg実行
            res = subprocess.run(['ffmpeg', '-ss', str(start_sec), '-i', TMP_VIDEO, '-t', '90', '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-b:v', '5M', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-y', OUT_VIDEO], capture_output=True, text=True)
            
            if not os.path.exists(OUT_VIDEO):
                log(f"  ❌ FFmpeg出力失敗: {res.stderr}")
                continue

            try:
                with open(OUT_VIDEO, 'rb') as f:
                    resp = requests.post("https://catbox.moe/user/api.php", data={'reqtype': 'fileupload'}, files={'fileToUpload': f}, timeout=60)
                    public_url = resp.text.strip() if resp.status_code == 200 else None
                
                if public_url and "https://" in public_url:
                    log(f"✅ 公開URL: {public_url}")
                    post_res = requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media", data={'media_type': 'REELS', 'video_url': public_url, 'caption': ai_caption, 'access_token': ACCESS_TOKEN}).json()
                    if 'id' in post_res:
                        creation_id = post_res['id']
                        for _ in range(20):
                            time.sleep(30)
                            status = requests.get(f"https://graph.facebook.com/v21.0/{creation_id}", params={'fields': 'status_code', 'access_token': ACCESS_TOKEN}).json().get('status_code', '').upper()
                            if status == 'FINISHED':
                                requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN})
                                log("🏁 投稿完了！")
                                with open(history_file, 'a') as fh: fh.write(video['id'] + "\n")
                                stats[video['type']] += 1; save_stats(stats); return
            except Exception as e: log(f"❌ エラー: {e}")
    log("😴 終了。")

if __name__ == "__main__":
    main()
