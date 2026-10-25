import sys
import requests
import datetime
import os
import time
import subprocess
from google import genai # 最新SDK
import json
import re

# 1行目からリアルタイムでログを出力
print("🚀 プレイボール速報・MLB自動翻訳システム（2026.08 最終復旧版）起動...")
sys.stdout.flush()

# ==========================================
# 設定・環境変数の読み込み
# ==========================================
INSTA_ID = os.getenv('INSTA_BUSINESS_ID')
ACCESS_TOKEN = os.getenv('INSTA_ACCESS_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

client = None
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)

JPN_KEYWORDS = ["大谷翔平", "大谷", "shohei ohtani", "ohtani", "山本由伸", "山本", "yoshinobu yamamoto", "yamamoto", "佐々木朗希", "佐々木", "roki sasaki", "sasaki", "ダルビッシュ有", "ダルビッシュ", "yu darvish", "darvish", "村上宗隆", "村上", "munetaka murakami", "murakami", "鈴木誠也", "seiya suzuki", "今永昇太", "shota imanaga", "吉田正尚", "masataka yoshida"]
BLACK_KEYWORDS = ["probable", "pitchers", "lineup", "interview", "press", "availability", "roster", "update", "alignment", "summary", "preview", "warmup", "positioning", "against", "at bat", "statcast", "recap", "daily", "full highlights", "outing", "talks", "roberts", "manager"]

def get_stats():
    if os.path.exists('stats.json'):
        try:
            with open('stats.json', 'r') as f: return json.load(f)
        except: pass
    return {"mlb_count": 0}

def save_stats(stats):
    with open('stats.json', 'w') as f: json.dump(stats, f)

def is_japanese(text):
    return bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', text))

def shift_srt_time(srt_text, offset_sec):
    """SRT構造を修復し時間を物理補正"""
    correction = offset_sec + 0.8
    def shift_timestamp(time_str):
        h, m, s_ms = time_str.split(':')
        s, ms = s_ms.split(',')
        total_ms = (int(h)*3600 + int(m)*60 + int(s)) * 1000 + int(ms)
        shifted_ms = max(0, total_ms - int(correction * 1000))
        new_h, rem = divmod(shifted_ms, 3600000)
        new_m, rem = divmod(rem, 60000)
        new_s, new_ms = divmod(rem, 1000)
        return f"{new_h:02}:{new_m:02}:{new_s:02},{new_ms:03}"

    pattern = r"(\d+)\s*\n(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3})\s*\n(.*?)(?=\n\d+\s*\n\d{2}:\d{2}:\d{2},\d{3}|$)"
    matches = re.findall(pattern, srt_text, re.DOTALL)
    final_blocks = []
    for i, match in enumerate(matches):
        _, time_line, text_content = match
        text_content = text_content.strip()
        if is_japanese(text_content) or any(w in text_content.upper() for w in ["MLB", "HR", "MVP", "OUT"]):
            try:
                times = time_line.split(' --> ')
                start_t = shift_timestamp(times[0].strip())
                end_t = shift_timestamp(times[1].strip())
                final_blocks.append(f"{len(final_blocks)+1}\n{start_t} --> {end_t}\n{text_content}")
            except: continue
    return "\n\n".join(final_blocks)

def analyze_video_with_ai(video_path, title, source_account):
    """最新SDKを使用し、503/429エラーに対するリトライを実装"""
    print(f"🧠 AI解析開始...")
    model_name = "gemini-1.5-flash" # 2026年8月現在、最も安定しているモデル
    
    for attempt in range(3):
        try:
            with open(video_path, 'rb') as f:
                uploaded_file = client.files.upload(file=f, config={'mime_type': 'video/mp4'})
            
            while uploaded_file.state.name == "PROCESSING":
                time.sleep(2)
                uploaded_file = client.files.get(name=uploaded_file.name)
            
            sub_prompt = "動画の英語実況を完璧に聞き取り、日本語SRTを作成せよ。日本語のみ。絶対同期。[SRT_START]...[SRT_END]で囲め。"
            prompt = f"野球動画({title})を解析せよ。[数値1つ(開始秒数)] [本文] {sub_prompt} 【ルール】ラベルや###禁止。ハッシュタグ30個。引用：{source_account}"
            
            response = client.models.generate_content(model=model_name, contents=[uploaded_file, prompt])
            res_text = response.text
            client.files.delete(name=uploaded_file.name)

            srt_raw = None
            srt_match = re.search(r'\[SRT_START\](.*?)\[SRT_END\]', res_text, re.DOTALL)
            if srt_match:
                srt_raw = srt_match.group(1).strip()
                res_text = res_text.replace(srt_match.group(0), "")

            clean_text = re.sub(r'(?im)^(\*\*|#|###)?\s*(START|CAPTION|秒数|本文|開始|タイトル|見出し|要約|所感|概要|SRT)\s*[:：]?\s*', '', res_text).strip()
            lines = [l.strip() for l in clean_text.split('\n') if l.strip()]
            if not lines: return 0, None, None
            
            start_sec = 0
            match = re.search(r"(\d+)", lines[0])
            if match:
                start_sec = int(match.group(1))
                ai_caption = "\n".join(lines[1:])
                srt_data = shift_srt_time(srt_raw, start_sec) if srt_raw else None
            else:
                ai_caption = "\n".join(lines)
                srt_data = shift_srt_time(srt_raw, 0) if srt_raw else None
                
            return start_sec, ai_caption, srt_data

        except Exception as e:
            if ("503" in str(e) or "429" in str(e)) and attempt < 2:
                print(f"  ⚠️ AI混雑中。10秒後に再試行します({attempt+1}/3)...")
                time.sleep(10)
                continue
            print(f"  ❌ AI失敗詳細: {e}")
            return 0, None, None

def get_mlb_video(history):
    candidates = []
    for day_offset in range(14):
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
                            if v_id not in history and any(kw in title.lower() for kw in JPN_KEYWORDS):
                                if not any(bk in title.lower() for bk in BLACK_KEYWORDS):
                                    v_url = next((p['url'] for p in item['playbacks'] if p['name'] == 'mp4Avc'), None)
                                    if v_url: candidates.append({"title": title, "url": v_url, "id": v_id, "type": "mlb", "source": "@MLBJapan"})
                    except: continue
        except: continue
    return candidates

def main():
    if not client:
        print("❌ GEMINI_API_KEY が設定されていません。")
        return

    stats = get_stats(); history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    # AIストレージ清掃
    try:
        for f in client.files.list(): client.files.delete(name=f.name)
    except: pass

    candidates = get_mlb_video(history)
    print(f"📊 ターゲット候補: {len(candidates)}件")
    if not candidates: return
    
    for video in candidates:
        print(f"🎯 ターゲット確定: {video['title']}")
        temp_input = "temp_video.mp4"
        # 前回の残骸を削除
        if os.path.exists(temp_input): os.remove(temp_input)
        
        subprocess.run(['yt-dlp', '-o', temp_input, '--quiet', video['url']])
        if not os.path.exists(temp_input):
            print("  ❌ ダウンロード失敗。次へ移ります。")
            continue

        start_sec, ai_caption, srt_data = analyze_video_with_ai(temp_input, video['title'], video['source'])
        if ai_caption is None:
            print("  ⚠️ 解析不能。スキップします。")
            continue

        output_file = "output.mp4"
        video_filters = "scale=1134:-2,crop=1080:ih"
        if srt_data:
            with open("subtitles.srt", "w", encoding="utf-8") as sf: sf.write(srt_data)
            video_filters += ",subtitles=./subtitles.srt:force_style='Fontname=Noto Sans CJK JP,FontSize=22,PrimaryColour=&H00FFFFFF,BackColour=&H80000000,BorderStyle=4,Outline=0,MarginV=20'"
            print("🎨 字幕焼き込み適用")

        filter_complex = f"{video_filters},pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
        subprocess.run(['ffmpeg', '-ss', str(start_sec), '-i', temp_input, '-t', '90', '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-b:v', '5M', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-y', output_file])
        
        try:
            if os.path.exists(output_file):
                with open(output_file, 'rb') as f:
                    res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f}, timeout=60).json()
                    if res.get('status') == 'success':
                        public_url = res['data']['url'].replace("tmpfiles.org/", "tmpfiles.org/dl/")
                        # Instagram投稿
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
                                    stats['mlb_count'] = stats.get('mlb_count', 0) + 1; save_stats(stats); return
        except Exception as e: print(f"  ❌ システムエラー: {e}")
    print("😴 終了。")

if __name__ == "__main__":
    main()
