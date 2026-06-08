import sys
import requests
import datetime
import os
import time
import subprocess
from google import genai
import json
import re
import logging

# リアルタイムでログを出力
print("🚀 プレイボール速報・MLB自動翻訳投稿システム（特化型）起動...")
sys.stdout.flush()

# ==========================================
# ロギング設定
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# ==========================================
# 設定・環境変数の読み込み
# ==========================================
INSTA_ID = os.getenv('INSTA_BUSINESS_ID')
ACCESS_TOKEN = os.getenv('INSTA_ACCESS_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

client = None
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)

def auth_headers():
    return {'Authorization': f'Bearer {ACCESS_TOKEN}'}

# 日本人選手キーワード
JPN_KEYWORDS = ["大谷翔平", "大谷", "shohei ohtani", "ohtani", "山本由伸", "山本", "yoshinobu yamamoto", "yamamoto", "佐々木朗希", "佐々木", "roki sasaki", "sasaki", "ダルビッシュ有", "ダルビッシュ", "yu darvish", "darvish", "村上宗隆", "村上", "munetaka murakami", "murakami"]

# 排除ワード（インタビュー、監督の喋り、スタッツ解析を徹底排除）
BLACK_KEYWORDS = [
    "probable", "pitchers", "lineup", "interview", "press", "availability", 
    "roster", "update", "alignment", "summary", "preview", "warmup", 
    "positioning", "statcast", "recap", "talks", "roberts", "manager", "pregame", "postgame"
]

def get_stats():
    if os.path.exists('stats.json'):
        try:
            with open('stats.json', 'r') as f: return json.load(f)
        except Exception as e: logger.warning(f"stats.json読み込み失敗: {e}")
    return {"mlb_count": 0}

def save_stats(stats):
    try:
        with open('stats.json', 'w') as f: json.dump(stats, f)
    except Exception as e: logger.warning(f"stats.json保存失敗: {e}")

def cleanup_gemini_storage():
    try:
        for f in client.files.list(): client.files.delete(name=f.name)
        logger.info("🧹 AIストレージの掃除完了。")
    except Exception as e: logger.warning(f"Geminiストレージ掃除失敗: {e}")

def get_available_flash_model():
    try:
        models = [m.name for m in client.models.list()]
        priority = ["models/gemini-2.0-flash-exp", "models/gemini-1.5-flash", "models/gemini-flash-lite-latest"]
        for pm in priority:
            if pm in models: return pm
        return models[0]
    except Exception as e:
        logger.error(f"モデル取得失敗: {e}")
        return "gemini-1.5-flash"

def is_japanese(text):
    return bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', text))

def shift_srt_time(srt_text, offset_sec, apply_human_correction=True):
    """SRT構造を維持しつつ時間を補正（0.5s先行）"""
    correction = offset_sec + (0.5 if apply_human_correction else 0)
    def shift_timestamp(time_str):
        h, m, s_ms = time_str.split(':')
        s, ms = s_ms.split(',')
        total_ms = (int(h)*3600 + int(m)*60 + int(s)) * 1000 + int(ms)
        shifted_ms = max(0, total_ms - int(correction * 1000))
        new_h, rem = divmod(shifted_ms, 3600000)
        new_m, rem = divmod(rem, 60000)
        new_s, new_ms = divmod(rem, 1000)
        return f"{new_h:02}:{new_m:02}:{new_s:02},{new_ms:03}"

    blocks = re.split(r'\n(?=\d+\n\d{2}:\d{2}:\d{2})', srt_text.strip())
    final_blocks = []
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3: continue
        time_line = next((l for l in lines if "-->" in l), None)
        if not time_line: continue
        text_content = " ".join(lines[lines.index(time_line)+1:])
        if is_japanese(text_content) or any(w in text_content.upper() for w in ["MLB", "HR", "MVP", "OUT"]):
            try:
                times = time_line.split(' --> ')
                start_t, end_t = shift_timestamp(times[0].strip()), shift_timestamp(times[1].strip())
                final_blocks.append(f"{len(final_blocks)+1}\n{start_t} --> {end_t}\n{text_content.strip()}")
            except: continue
    return "\n\n".join(final_blocks)

def analyze_video_with_ai(video_path, title, source_account, model_name):
    logger.info(f"🧠 AI解析中（MLB翻訳モード）...")
    try:
        with open(video_path, 'rb') as f:
            uploaded_file = client.files.upload(file=f, config={'mime_type': 'video/mp4'})
        while uploaded_file.state.name == "PROCESSING":
            time.sleep(2)
            uploaded_file = client.files.get(name=uploaded_file.name)
        
        prompt = f"""
        野球動画({title})を解析し、以下を出力せよ。
        [数値1つ(開始秒数)]
        [本文]
        また、英語実況を完璧に聞き取り、日本語SRTにせよ。日本語のみ出力。絶対同期。[SRT_START]...[SRT_END]で囲め。

        【ルール】
        ・本文：ラベル(見出し:等)やMarkdown(###等)は一切禁止。ハッシュタグ30個必須。引用：{source_account}
        """
        
        response = client.models.generate_content(model=model_name, contents=[uploaded_file, prompt])
        res_text = response.text
        client.files.delete(name=uploaded_file.name)

        srt_data = None
        srt_match = re.search(r'\[SRT_START\](.*?)\[SRT_END\]', res_text, re.DOTALL)
        if srt_match:
            srt_raw = srt_match.group(1).strip()
            srt_data = shift_srt_time(srt_raw, 0, apply_human_correction=False)
            res_text = res_text.replace(srt_match.group(0), "")

        clean_text = re.sub(r'(?i)(#+|\*+)?(START|CAPTION|秒数|本文|開始|タイトル|見出し|要約|所感|概要|SRT)(#+|\*+)?[:：]?\s*', '', res_text).strip()
        lines = [l.strip() for l in clean_text.split('\n') if l.strip()]
        if not lines: return 0, None, None
        
        start_sec = 0
        match = re.search(r"(\d+)", lines[0])
        if match:
            start_sec = int(match.group(1))
            ai_caption = "\n".join(lines[1:])
            if srt_data: srt_data = shift_srt_time(srt_data, start_sec, apply_human_correction=True)
        else: ai_caption = "\n".join(lines)
        return start_sec, ai_caption, srt_data
    except Exception as e:
        logger.error(f"AI解析失敗: {e}"); return 0, None, None

def get_mlb_video(history):
    """MLB公式APIからのみ探索"""
    candidates = []
    for day_offset in [0, 1]:
        date_str = (datetime.datetime.now() - datetime.timedelta(days=day_offset)).strftime('%Y-%m-%d')
        url = f"https://statsapi.mlb.com/api/v1/schedule/games/?sportId=1&startDate={date_str}&endDate={date_str}"
        try:
            res = requests.get(url, timeout=15).json()
            for date_data in res.get('dates', []):
                for game in date_data.get('games', []):
                    try:
                        content = requests.get(f"https://statsapi.mlb.com/api/v1/game/{game['gamePk']}/content").json()
                        for item in content.get('highlights', {}).get('highlights', {}).get('items', []):
                            title = item.get('headline', ''); v_id = str(item.get('id'))
                            if v_id not in history and any(kw in title.lower() for kw in JPN_KEYWORDS):
                                if any(bk in title.lower() for bk in BLACK_KEYWORDS): continue
                                v_url = next((p['url'] for p in item['playbacks'] if p['name'] == 'mp4Avc'), None)
                                if v_url: candidates.append({"title": title, "url": v_url, "id": v_id, "type": "mlb", "source": "@MLBJapan"})
                    except: continue
        except Exception as e: logger.error(f"MLB取得失敗: {e}")
    return candidates

def main():
    stats = get_stats(); history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    if client: cleanup_gemini_storage()
    flash_model = get_available_flash_model()
    
    # ✅ MLBのみ探索
    candidates = get_mlb_video(history)
    if not candidates:
        logger.info("😴 MLB新着なし。")
        return
    
    for video in candidates:
        logger.info(f"🎯 確定: {video['title']}")
        temp_input = "temp_video.mp4"
        result = subprocess.run(['yt-dlp', '-o', temp_input, '--quiet', video['url']], capture_output=True, text=True)
        if result.returncode != 0 or not os.path.exists(temp_input):
            logger.error(f"yt-dlp失敗: {result.stderr.strip()}"); continue

        start_sec, ai_caption, srt_data = analyze_video_with_ai(temp_input, video['title'], video['source'], flash_model)
        if ai_caption is None: continue

        # 動画加工：字幕焼き込み対応
        video_filters = "scale=1134:-2,crop=1080:ih"
        if srt_data:
            with open("subtitles.srt", "w", encoding="utf-8") as sf: sf.write(srt_data)
            video_filters += ",subtitles=./subtitles.srt:force_style='Fontname=Noto Sans CJK JP,FontSize=22,PrimaryColour=&H00FFFFFF,BackColour=&H80000000,BorderStyle=4,Outline=0,MarginV=20'"
            logger.info("🎨 字幕焼き込み適用")

        filter_complex = f"{video_filters},pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
        ffmpeg_res = subprocess.run(['ffmpeg', '-ss', str(start_sec), '-i', temp_input, '-t', '90', '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-b:v', '5M', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-y', 'output.mp4'], capture_output=True, text=True)
        if ffmpeg_res.returncode != 0:
            logger.error(f"ffmpeg失敗"); continue
        
        try:
            with open('output.mp4', 'rb') as f:
                res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f}, timeout=60).json()
                if res.get('status') == 'success':
                    public_url = res['data']['url'].replace("tmpfiles.org/", "tmpfiles.org/dl/")
                    post_res = requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media", headers=auth_headers(), data={'media_type': 'REELS', 'video_url': public_url, 'caption': ai_caption}).json()
                    if 'id' in post_res:
                        creation_id = post_res['id']
                        for attempt in range(20):
                            time.sleep(30)
                            status_res = requests.get(f"https://graph.facebook.com/v21.0/{creation_id}", headers=auth_headers(), params={'fields': 'status_code'}).json()
                            status = (status_res.get('status_code') or "").upper()
                            logger.info(f"  ステータス確認 ({attempt+1}/20): {status}")
                            if status == 'FINISHED':
                                requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", headers=auth_headers(), data={'creation_id': creation_id})
                                logger.info("🏁 投稿完了！")
                                with open(history_file, 'a') as fh: fh.write(video['id'] + "\n")
                                stats['mlb_count'] += 1; save_stats(stats); return
        except Exception as e: logger.error(f"システムエラー: {e}")
    logger.info("😴 終了。")

if __name__ == "__main__":
    main()
