import sys
# 1行目からリアルタイムでログを出力
print("🚀 プレイボール速報・システム最終形態（物理同期 ＋ 多重アップローダー）起動...")
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
# 設定・環境変数の読み込み
# ==========================================
INSTA_ID = os.getenv('INSTA_BUSINESS_ID')
ACCESS_TOKEN = os.getenv('INSTA_ACCESS_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

client = None
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)

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

def shift_srt_time(srt_text, offset_sec):
    def shift_match(match):
        time_str = match.group(1)
        h, m, s_ms = time_str.split(':')
        s, ms = s_ms.split(',')
        total_ms = (int(h)*3600 + int(m)*60 + int(s)) * 1000 + int(ms)
        shifted_ms = max(0, total_ms - int(offset_sec * 1000))
        new_h = shifted_ms // 3600000
        new_m = (shifted_ms % 3600000) // 60000
        new_s = (shifted_ms % 60000) // 1000
        new_ms = shifted_ms % 1000
        return f"{new_h:02}:{new_m:02}:{new_s:02},{new_ms:03}"
    return re.sub(r'(\d{2}:\d{2}:\d{2},\d{3})', shift_match, srt_text)

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
            【重要：シンクロ率のルール】
            1. お前が抽出した[開始秒数]の時点を、SRTの 00:00:00,000 (起点) として計算しろ。
            2. 実況の声と字幕のタイミングを0.1秒単位で完璧に一致させろ。
            [SRT_START]
            1
            00:00:00,500 --> 00:00:03,000
            実況：放ったー！場外ホームランだ！
            [SRT_END]
            """

        prompt = f"""
        野球動画({title})を解析し、以下を出力せよ。
        [数値1つ(開始秒数)]
        [本文]
        {subtitle_instruction}
        【ルール】
        ・本文：【 】付きの見出し。要約。所感（だ・である調）。日本語のみ。
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

def upload_video_link(filepath):
    """【多重アップローダー】Catbox優先、tmpfilesをフォールバックに"""
    # 1. Catbox (非常に安定)
    try:
        print("🌐 Catboxへアップロード中...")
        with open(filepath, 'rb') as f:
            res = requests.post("https://catbox.moe/user/api.php", data={'reqtype': 'fileupload'}, files={'fileToUpload': f}, timeout=60)
            if res.status_code == 200 and "https://" in res.text:
                return res.text.strip()
    except Exception as e: print(f"  ⚠️ Catbox失敗: {e}")

    # 2. tmpfiles.org (予備)
    try:
        print("🌐 tmpfiles.orgへアップロード中...")
        with open(filepath, 'rb') as f:
            res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f}, timeout=60).json()
            if res.get('status') == 'success':
                return res['data']['url'].replace("tmpfiles.org/", "tmpfiles.org/dl/")
            else: print(f"  ⚠️ tmpfiles応答エラー: {res}")
    except Exception as e: print(f"  ⚠️ tmpfiles失敗: {e}")
    return None

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
            subtitle_style = "Fontname=Noto Sans CJK JP Bold,FontSize=13,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H60000000,BorderStyle=4,Outline=1,Shadow=0,MarginV=40"
            filter_complex += f",subtitles=subtitles.srt:force_style='{subtitle_style}'"
            print("🎨 字幕を焼き込み中...")

        subprocess.run(['ffmpeg', '-ss', str(start_sec), '-i', temp_input, '-t', '90', '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-b:v', '5M', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-y', output_file])
        
        # --- アップロード処理を強化 ---
        public_url = upload_video_link(output_file)
        if public_url:
            try:
                print(f"✅ 公開URL確保: {public_url}")
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
                else: print(f"  ❌ Instagramコンテナ作成失敗: {post_res}")
            except Exception as e: print(f"  ❌ 投稿プロセスエラー: {e}")
        else:
            print("  ❌ 動画のアップロードに失敗しました。次の候補へ移ります。")
            
    print("😴 終了。")

if __name__ == "__main__":
    main()
