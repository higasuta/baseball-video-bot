import sys
# 1行目からリアルタイムでログを出力
print("🚀 プレイボール速報・システム最終形態（キャプション完全クリーン化）起動...")
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

JPN_KEYWORDS = ["大谷翔平", "大谷", "shohei ohtani", "ohtani", "山本由伸", "山本", "yoshinobu yamamoto", "yamamoto", "佐々木朗希", "佐々木", "roki sasaki", "sasaki", "ダルビッシュ有", "ダルビッシュ", "yu darvish", "darvish", "松井裕樹", "松井", "yuki matsui", "matsui", "鈴木誠也", "鈴木", "seiya suzuki", "suzuki", "今永昇太", "今永", "shota imanaga", "imanaga", "千賀滉大", "千賀", "kodai senga", "senga", "菅野智之", "菅野", "tomoyuki sugano", "sugano", "小笠原慎之介", "小笠原", "shinnosuke ogasawara", "ogasawara", "岡本和真", "岡本", "kazuma okamoto", "okamoto", "今井達也", "今井", "tatsuya imai", "imai", "吉田正尚", "吉田", "masataka yoshida", "yoshida", "菊池雄星", "菊池", "yusei kikuchi", "kikuchi", "村上宗隆", "村上", "munetaka murakami", "murakami"]
BLACK_KEYWORDS = ["probable", "pitchers", "lineup", "interview", "press", "availability", "roster", "update", "alignment", "summary", "preview", "warmup", "positioning", "against", "at bat", "statcast", "recap", "daily", "full highlights", "outing", "talks"]

def get_stats():
    if os.path.exists('stats.json'):
        try:
            with open('stats.json', 'r') as f: return json.load(f)
        except: pass
    return {"npb": 75, "mlb": 25}

def save_stats(stats):
    with open('stats.json', 'w') as f: json.dump(stats, f)

def cleanup_gemini_storage():
    try:
        for f in genai.list_files(): genai.delete_file(f.name)
        print("🧹 AIストレージの掃除完了。")
    except: pass

def get_available_flash_model():
    try:
        model_names = [m.name for m in genai.list_models() if 'flash' in m.name]
        priority_models = ["models/gemini-1.5-flash", "models/gemini-flash-lite-latest"]
        for pm in priority_models:
            if pm in model_names: return pm
        return model_names[0] if model_names else "models/gemini-1.5-flash"
    except: return "models/gemini-1.5-flash"

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
            line = re.sub(r'^(English|Original|原文|英語|日本語)[:：]\s*', '', line, flags=re.IGNORECASE)
            if is_japanese(line): cleaned_lines.append(line)
    return "\n".join(cleaned_lines)

def analyze_video_with_ai(video_path, title, source_account, model_name, is_mlb=False):
    print(f"🧠 AIによる動画解析中...")
    try:
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING": time.sleep(2); video_file = genai.get_file(video_file.name)
        model = genai.GenerativeModel(model_name)
        
        subtitle_prompt = ""
        if is_mlb:
            subtitle_prompt = "また、英語実況を完璧に聞き取り日本語SRT字幕を作成せよ。日本語のみ出力。絶対同期。[SRT_START]...[SRT_END]で囲め。"

        prompt = f"野球動画({title})を解析し、以下を出力せよ。[数値1つ(開始秒数)] [本文] {subtitle_prompt} 【ルール】見出し、要約、所感。START: 等のラベル禁止。引用：{source_account} を最後に。"
        response = model.generate_content([prompt, video_file])
        res_text = response.text
        genai.delete_file(video_file.name)

        # 1. 字幕データ(SRT)の抽出と削除（本文に残さない）
        srt_data = None
        if is_mlb:
            srt_match = re.search(r'\[SRT_START\](.*?)\[SRT_END\]', res_text, re.DOTALL)
            if srt_match:
                srt_data = srt_match.group(1).strip()
                # 本文からSRTブロックを物理的に削除
                res_text = res_text.replace(srt_match.group(0), "")

        # 2. 本文から不要なラベル・Markdownを物理抹殺
        # 見出し、要約、所感、**見出し**、START: などをすべて消去
        clean_text = re.sub(r'(?i)(\*\*|#)?(START|CAPTION|秒数|本文|開始|タイトル|見出し|要約|所感|概要|SRT)(\*\*|#)?[:：]\s*', '', res_text).strip()
        
        lines = [l.strip() for l in clean_text.split('\n') if l.strip()]
        if not lines: return 0, None, None
        
        start_sec = 0
        match = re.search(r"(\d+)", lines[0])
        if match:
            start_sec = int(match.group(1))
            ai_caption = "\n".join(lines[1:])
            if srt_data: srt_data = shift_srt_time(srt_data, start_sec)
        else:
            ai_caption = "\n".join(lines)
            
        return start_sec, ai_caption, srt_data
    except Exception as e:
        print(f"  ⚠️ AI解析失敗: {e}"); return 0, None, None

# --- get_npb_video, get_mlb_video は変更なし ---
def get_npb_video(history):
    url = "https://www3.nhk.or.jp/sports/json/pro-baseball/index.json"
    candidates = []
    try:
        res = requests.get(url, timeout=15); data = res.json(); clips = data.get('clips', [])
        found = 0
        for clip in clips:
            v_id = str(clip.get('id')); title = clip.get('title', '')
            v_url = clip.get('video_url') or f"https://www3.nhk.or.jp/sports/special/baseball/npb/videos/{v_id}"
            if v_id not in history:
                if any(kw in title.lower() for kw in BLACK_KEYWORDS): continue
                candidates.append({"title": title, "url": v_url, "id": v_id, "type": "npb", "source": "NHKスポーツ"})
                found += 1
            if found >= 5: break
        return candidates
    except: return []

def get_mlb_video(history, is_test_mode):
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
                            title = item.get('headline', ''); v_id = str(item.get('id'))
                            v_url = next((p['url'] for p in item['playbacks'] if p['name'] == 'mp4Avc'), None)
                            if v_url and v_id not in history:
                                if any(kw in title.lower() for kw in JPN_KEYWORDS):
                                    candidates.append({"title": title, "url": v_url, "id": v_id, "type": "mlb", "source": "@MLBJapan"})
                    except: continue
        except: continue
    return candidates

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats(); history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    cleanup_gemini_storage()
    flash_model = get_available_flash_model()
    
    candidates = get_npb_video(history) + get_mlb_video(history, is_test_mode)
    if not candidates: return
    candidates.sort(key=lambda x: 1 if x['type'] == 'npb' else 2)
    
    for video in candidates:
        print(f"🎯 ターゲット確定: {video['title']}")
        temp_input = "temp_video.mp4"
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        subprocess.run(['yt-dlp', '-o', temp_input, '--user-agent', ua, '--quiet', video['url']])
        if not os.path.exists(temp_input): continue

        start_sec, ai_caption, srt_data = analyze_video_with_ai(temp_input, video['title'], video['source'], flash_model, is_mlb=(video['type'] == 'mlb'))
        if ai_caption is None: continue

        output_file = "output.mp4"
        filter_complex = "scale=1134:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
        
        if video['type'] == 'mlb' and srt_data:
            with open("subtitles.srt", "w", encoding="utf-8") as sf: sf.write(srt_data)
            filter_complex += ",subtitles=subtitles.srt:force_style='Fontname=Noto Sans CJK JP,FontSize=13,MarginV=45'"
            print("🎨 字幕焼き込み適用")

        subprocess.run(['ffmpeg', '-ss', str(start_sec), '-i', temp_input, '-t', '90', '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-b:v', '5M', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-y', output_file])
        
        try:
            with open(output_file, 'rb') as f:
                res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f}, timeout=60).json()
                if res.get('status') == 'success':
                    public_url = res['data']['url'].replace("tmpfiles.org/", "tmpfiles.org/dl/")
                    time.sleep(10)
                    post_res = requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media", data={'media_type': 'REELS', 'video_url': public_url, 'caption': ai_caption, 'access_token': ACCESS_TOKEN}).json()
                    if 'id' in post_res:
                        creation_id = post_res['id']
                        for _ in range(20):
                            time.sleep(30)
                            status_res = requests.get(f"https://graph.facebook.com/v21.0/{creation_id}", params={'fields': 'status_code', 'access_token': ACCESS_TOKEN}).json()
                            if (status_res.get('status_code') or "").upper() == 'FINISHED':
                                requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN})
                                print(f"🏁 投稿完了！")
                                with open(history_file, 'a') as fh: fh.write(video['id'] + "\n")
                                stats[video['type']] += 1; save_stats(stats); return
        except Exception as e: print(f"  ❌ システムエラー: {e}")
    print("😴 終了。")

if __name__ == "__main__":
    main()