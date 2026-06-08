import sys
# 1行目からリアルタイムでログを出力
print("🚀 プレイボール速報・システム最終形態（SRT構造修復 ＋ 同期修正）起動...")
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

JPN_KEYWORDS = ["大谷翔平", "大谷", "shohei ohtani", "ohtani", "山本由伸", "山本", "yoshinobu yamamoto", "yamamoto", "佐々木朗希", "佐々木", "roki sasaki", "sasaki", "ダルビッシュ有", "ダルビッシュ", "yu darvish", "darvish", "村上宗隆", "村上", "munetaka murakami", "murakami"]
BLACK_KEYWORDS = ["probable", "pitchers", "lineup", "interview", "press", "availability", "roster", "update", "alignment", "summary", "preview", "warmup", "positioning", "against", "at bat", "statcast", "recap", "daily", "full highlights", "outing", "talks", "roberts", "manager"]

def get_stats():
    if os.path.exists('stats.json'):
        try:
            with open('stats.json', 'r') as f: return json.load(f)
        except: pass
    return {"mlb_count": 0}

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
    """SRTを物理的に解体し、構造を正しく再構築して時間を補正する"""
    # AIの認識ラグ(0.8s) + 動画の切り出し位置
    correction = offset_sec + 0.8

    def shift_timestamp(time_str):
        # 00:00:00,000 形式をパースして計算
        h, m, s_ms = time_str.split(':')
        s, ms = s_ms.split(',')
        total_ms = (int(h)*3600 + int(m)*60 + int(s)) * 1000 + int(ms)
        shifted_ms = max(0, total_ms - int(correction * 1000))
        new_h, rem = divmod(shifted_ms, 3600000)
        new_m, rem = divmod(rem, 60000)
        new_s, new_ms = divmod(rem, 1000)
        return f"{new_h:02}:{new_m:02}:{new_s:02},{new_ms:03}"

    # 構造を破壊せずブロックを抽出する最強の正規表現
    # インデックス番号、時間、テキストを1セットで捕まえる
    pattern = r"(\d+)\s*\n(\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3})\s*\n(.*?)(?=\n\d+\s*\n\d{2}:\d{2}:\d{2},\d{3}|$)"
    matches = re.findall(pattern, srt_text, re.DOTALL)
    
    final_blocks = []
    for i, match in enumerate(matches):
        _, time_line, text_content = match
        text_content = text_content.strip()
        
        # クリーニング（日本語か重要単語が含まれる場合のみ採用）
        if is_japanese(text_content) or any(w in text_content.upper() for w in ["MLB", "HR", "MVP", "OUT"]):
            try:
                times = time_line.split(' --> ')
                start_t = shift_timestamp(times[0].strip())
                end_t = shift_timestamp(times[1].strip())
                
                # 正しいSRT形式で再構築（必ず空行を挟む）
                final_blocks.append(f"{len(final_blocks)+1}\n{start_t} --> {end_t}\n{text_content}")
            except: continue
                
    return "\n\n".join(final_blocks)

def analyze_video_with_ai(video_path, title, source_account, model_name):
    print(f"🧠 AI解析中...")
    try:
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING": time.sleep(2); video_file = genai.get_file(video_file.name)
        model = genai.GenerativeModel(model_name)
        
        sub_prompt = """
        動画の英語実況を完璧に聞き取り、日本語SRT字幕を作成せよ。
        ・開始秒数は 00:00:00,000 から打て。
        ・日本語のみ出力し、必ず [SRT_START] と [SRT_END] で囲め。
        """

        prompt = f"野球動画({title})を解析せよ。[数値1つ(開始秒数)] [本文] {sub_prompt} 【ルール】ラベルや###禁止。ハッシュタグ30個必須。引用：{source_account}"
        
        response = model.generate_content([prompt, video_file])
        res_text = response.text
        genai.delete_file(video_file.name)

        srt_raw = None
        srt_match = re.search(r'\[SRT_START\](.*?)\[SRT_END\]', res_text, re.DOTALL)
        if srt_match:
            srt_raw = srt_match.group(1).strip()
            res_text = res_text.replace(srt_match.group(0), "")

        # 本文クリーンアップ
        clean_text = re.sub(r'(?i)(#+|\*+)?(START|CAPTION|秒数|本文|開始|タイトル|見出し|要約|所感|概要|SRT)(#+|\*+)?[:：]?\s*', '', res_text).strip()
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
        print(f"  ⚠️ AI失敗: {e}"); return 0, None, None

def get_mlb_video(history):
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
                            title = item.get('headline', ''); v_id = str(item.get('id'))
                            v_url = next((p['url'] for p in item['playbacks'] if p['name'] == 'mp4Avc'), None)
                            if v_url and v_id not in history:
                                if any(kw in title.lower() for kw in JPN_KEYWORDS):
                                    if not any(bk in title.lower() for bk in BLACK_KEYWORDS):
                                        candidates.append({"title": title, "url": v_url, "id": v_id, "type": "mlb", "source": "@MLBJapan"})
                    except: continue
        except: continue
    return candidates

def main():
    stats = get_stats(); history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    cleanup_gemini_storage()
    flash_model = get_available_flash_model()
    candidates = get_mlb_video(history)
    if not candidates: return
    
    for video in candidates:
        print(f"🎯 ターゲット確定: {video['title']}")
        temp_input = "temp_video.mp4"
        subprocess.run(['yt-dlp', '-o', temp_input, '--quiet', video['url']])
        if not os.path.exists(temp_input): continue

        start_sec, ai_caption, srt_data = analyze_video_with_ai(temp_input, video['title'], video['source'], flash_model)
        if ai_caption is None: continue

        video_filters = "scale=1134:-2,crop=1080:ih"
        if srt_data:
            with open("subtitles.srt", "w", encoding="utf-8") as sf: sf.write(srt_data)
            # 正しいフィルター順序: 字幕焼き込み ➔ pad(黒帯)
            video_filters += ",subtitles=./subtitles.srt:force_style='Fontname=Noto Sans CJK JP,FontSize=22,PrimaryColour=&H00FFFFFF,BackColour=&H80000000,BorderStyle=4,Outline=0,MarginV=20'"
            print("🎨 字幕構造を修復して焼き込み中...")

        filter_complex = f"{video_filters},pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
        subprocess.run(['ffmpeg', '-ss', str(start_sec), '-i', temp_input, '-t', '90', '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-b:v', '5M', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-y', 'output.mp4'])
        
        try:
            if os.path.exists('output.mp4'):
                with open('output.mp4', 'rb') as f:
                    res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f}, timeout=60).json()
                    if res.get('status') == 'success':
                        public_url = res['data']['url'].replace("tmpfiles.org/", "tmpfiles.org/dl/")
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
