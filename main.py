import sys
print("🚀 プレイボール速報・システム最終形態（言語検知クリーナー ＋ 物理同期）起動...")
sys.stdout.flush()

import requests
import datetime
import os
import time
import subprocess
from google import genai
import json
import re

# ==========================================
# 設定・環境変数
# ==========================================
INSTA_ID = os.getenv('INSTA_BUSINESS_ID')
ACCESS_TOKEN = os.getenv('INSTA_ACCESS_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

client = None
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)

JPN_KEYWORDS = ["大谷翔平", "大谷", "shohei ohtani", "ohtani", "山本由伸", "山本", "yoshinobu yamamoto", "yamamoto", "佐々木朗希", "佐々木", "roki sasaki", "sasaki", "ダルビッシュ有", "ダルビッシュ", "yu darvish", "darvish", "村上宗隆", "村上", "munetaka murakami", "murakami"]
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
        for f in client.files.list(): client.files.delete(name=f.name)
        print("🧹 AIストレージの掃除完了。")
    except: pass

def get_available_flash_model():
    try:
        models = [m.name for m in client.models.list()]
        priority = ["models/gemini-2.0-flash-exp", "models/gemini-1.5-flash", "models/gemini-flash-lite-latest"]
        for p in priority:
            if p in models: return p
        return models[0]
    except: return "models/gemini-1.5-flash"

def is_japanese(text):
    """文字列に日本語（ひらがな、カタカナ、漢字）が含まれているか判定"""
    return bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', text))

def shift_srt_time(srt_text, offset_sec):
    """SRTの時間を補正し、かつ『日本語を含まない原文行』のみを物理排除する"""
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
        # 時間行、インデックス行はそのまま保持
        if "-->" in line or line.strip().isdigit():
            cleaned_lines.append(line)
        else:
            # 1. AIが付加しがちな「英語：」「日本語：」などのラベルを削除
            line = re.sub(r'^(English|Original|Transcript|Source|原文|英語|日本語)[:：]\s*', '', line, flags=re.IGNORECASE)
            # 2. 日本語が含まれている行のみを保持（これでMLBなどの英単語入り日本語は残る）
            if is_japanese(line):
                cleaned_lines.append(line)
            # 3. 日本語がない行（＝純粋な英語原文）は、ここで無視される
    
    return "\n".join(cleaned_lines)

def analyze_video_with_ai(video_path, title, source_account, model_name, is_mlb=False):
    print(f"🧠 AIによる動画解析中...")
    try:
        with open(video_path, 'rb') as f:
            uploaded_file = client.files.upload(file=f, config={'mime_type': 'video/mp4'})
        while uploaded_file.state.name == "PROCESSING": time.sleep(2); uploaded_file = client.files.get(name=uploaded_file.name)
        
        subtitle_instruction = ""
        if is_mlb:
            subtitle_instruction = """
            また、動画の英語実況を完璧に聞き取り、日本語訳字幕データ(SRT)を作成せよ。
            【厳守ルール】
            1. 出力は「日本語」を主体とせよ。MLB, HR, MVPなどの野球用語を除き、英語の原文文を併記することは禁止する。
            2. タイムスタンプは、動画ファイルの冒頭からの絶対時間で、実況の喋り出しに0.1秒単位で合わせろ。
            [SRT_START]
            1
            00:00:10,200 --> 00:00:13,000
            実況：これは大きい！MLB記録に並ぶHRだ！
            [SRT_END]
            """

        prompt = f"""
        野球動画({title})を解析し、以下を出力せよ。
        [数値1つ(開始秒数)]
        [本文]
        {subtitle_instruction}
        【本文ルール】
        ・【 】付きの見出し、要約、所感（だ・である調）。日本語のみ。
        ・ハッシュタグは合計25〜30個。
        """
        
        response = client.models.generate_content(model=model_name, contents=[uploaded_file, prompt])
        res_text = response.text
        client.files.delete(name=uploaded_file.name)

        srt_data = None
        if is_mlb:
            srt_match = re.search(r'\[SRT_START\](.*?)\[SRT_END\]', res_text, re.DOTALL)
            if srt_match:
                srt_data = srt_match.group(1).strip()
                res_text = res_text.replace(srt_match.group(0), "")

        clean_text = re.sub(r'(?i)(START|CAPTION|秒数|本文|開始|タイトル|見出し|概要|所感|SRT)[:：]\s*', '', res_text).strip()
        lines = [l.strip() for l in clean_text.split('\n') if l.strip()]
        if not lines: return 0, None, None
        
        start_sec = 0
        first_line_match = re.search(r"(\d+)", lines[0])
        if first_line_match:
            start_sec = int(first_line_match.group(1))
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
        for clip in clips:
            v_id = str(clip.get('id')); title = clip.get('title', '')
            v_url = clip.get('video_url') or f"https://www3.nhk.or.jp/sports/special/baseball/npb/videos/{v_id}"
            if v_id not in history:
                if any(kw in title.lower() for kw in BLACK_KEYWORDS): continue
                candidates.append({"title": title, "url": v_url, "id": v_id, "type": "npb", "source": "NHKスポーツ"})
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

    if client: cleanup_gemini_storage()
    model_name = get_available_flash_model()
    
    candidates = get_npb_video(history) + get_mlb_video(history, is_test_mode)
    if not candidates: return
    candidates.sort(key=lambda x: 1 if x['type'] == 'npb' else 2)
    
    for video in candidates:
        print(f"🎯 ターゲット確定: {video['title']}")
        temp_input = "temp_video.mp4"
        subprocess.run(['yt-dlp', '-o', temp_input, '--quiet', video['url']])
        if not os.path.exists(temp_input): continue

        start_sec, ai_caption, srt_data = analyze_video_with_ai(temp_input, video['title'], video['source'], model_name, is_mlb=(video['type'] == 'mlb'))
        if ai_caption is None: continue

        output_file = "output.mp4"
        filter_complex = "scale=1134:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
        
        if video['type'] == 'mlb' and srt_data:
            with open("subtitles.srt", "w", encoding="utf-8") as sf: sf.write(srt_data)
            subtitle_style = "Fontname=Noto Sans CJK JP Bold,FontSize=13,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H60000000,BorderStyle=4,Outline=1,Shadow=0,MarginV=45"
            filter_complex += f",subtitles=subtitles.srt:force_style='{subtitle_style}'"
            print("🎨 字幕を焼き込み中（言語検知クリーナー適用済み）...")

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
