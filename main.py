import sys
import requests
import datetime
import os
import time
import subprocess
import google.generativeai as genai
import json
import re
import logging

# 1行目からリアルタイムでログを出力
print("🚀 プレイボール速報・システム最終形態（プロ仕様・同期補正済）起動...")
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

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# ✅ 修正：ACCESS_TOKENをヘッダー経由で統一
def auth_headers():
    return {'Authorization': f'Bearer {ACCESS_TOKEN}'}

JPN_KEYWORDS = ["大谷翔平", "大谷", "shohei ohtani", "ohtani", "山本由伸", "山本", "yoshinobu yamamoto", "yamamoto", "佐々木朗希", "佐々木", "roki sasaki", "sasaki", "ダルビッシュ有", "ダルビッシュ", "yu darvish", "darvish", "村上宗隆", "村上", "munetaka murakami", "murakami"]
BLACK_KEYWORDS = ["probable", "pitchers", "lineup", "interview", "press", "availability", "roster", "update", "alignment", "summary", "preview", "warmup", "positioning", "against", "at bat", "statcast", "recap", "daily", "full highlights", "outing", "talks"]

def get_stats():
    if os.path.exists('stats.json'):
        try:
            with open('stats.json', 'r') as f: return json.load(f)
        except Exception as e:
            logger.warning(f"stats.json読み込み失敗: {e}")
    return {"npb": 75, "mlb": 25}

def save_stats(stats):
    try:
        with open('stats.json', 'w') as f: json.dump(stats, f)
    except Exception as e:
        logger.warning(f"stats.json保存失敗: {e}")

def cleanup_gemini_storage():
    try:
        for f in genai.list_files(): genai.delete_file(f.name)
        logger.info("🧹 AIストレージの掃除完了。")
    except Exception as e:
        logger.warning(f"Geminiストレージ掃除失敗: {e}")

def get_available_flash_model():
    try:
        model_names = [m.name for m in genai.list_models() if 'flash' in m.name]
        priority_models = ["models/gemini-1.5-flash", "models/gemini-flash-lite-latest"]
        for pm in priority_models:
            if pm in model_names: return pm
        return model_names[0] if model_names else "models/gemini-1.5-flash"
    except Exception as e:
        logger.warning(f"モデル取得失敗、デフォルト使用: {e}")
        return "models/gemini-1.5-flash"

def is_japanese(text):
    return bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', text))

def shift_srt_time(srt_text, offset_sec, apply_human_correction=True):
    """SRT構造を維持しつつ時間を物理補正。apply_human_correctionで0.5秒の先行補正を制御"""
    # AIの認識遅延を補正する0.5秒。二重適用を防ぐためフラグ制に
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

def analyze_video_with_ai(video_path, title, source_account, model_name, is_mlb=False):
    logger.info(f"🧠 AI解析中 (MLB:{is_mlb})...")
    try:
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING":
            time.sleep(2)
            video_file = genai.get_file(video_file.name)
        model = genai.GenerativeModel(model_name)
        sub_prompt = "また、英語実況を日本語SRTにせよ。日本語のみ出力。絶対同期。[SRT_START]...[SRT_END]で囲め。" if is_mlb else ""
        prompt = f"野球動画({title})を解析せよ。[数値1つ(開始秒数)] [本文] {sub_prompt} 【ルール】ラベルや###禁止。ハッシュタグ30個必須。引用：{source_account}"
        
        response = model.generate_content([prompt, video_file])
        res_text = response.text
        genai.delete_file(video_file.name)

        srt_data = None
        if is_mlb:
            srt_match = re.search(r'\[SRT_START\](.*?)\[SRT_END\]', res_text, re.DOTALL)
            if srt_match:
                # ✅ 1回目は構造修復とクリーニングのみ（時間補正は行わない）
                srt_data = shift_srt_time(srt_match.group(1).strip(), 0, apply_human_correction=False)
                res_text = res_text.replace(srt_match.group(0), "")

        clean_text = re.sub(r'(?i)(#+|\*+)?(START|CAPTION|秒数|本文|開始|タイトル|見出し|要約|所感|概要|SRT)(#+|\*+)?[:：]?\s*', '', res_text).strip()
        lines = [l.strip() for l in clean_text.split('\n') if l.strip()]
        if not lines: return 0, None, None
        
        start_sec = 0
        match = re.search(r"(\d+)", lines[0])
        if match:
            start_sec = int(match.group(1))
            ai_caption = "\n".join(lines[1:])
            # ✅ ここで「動画切り出し秒数 ＋ 人間用0.5秒」を一括補正する
            if srt_data: srt_data = shift_srt_time(srt_data, start_sec, apply_human_correction=True)
        else: ai_caption = "\n".join(lines)
        return start_sec, ai_caption, srt_data
    except Exception as e:
        logger.error(f"AI解析失敗: {e}"); return 0, None, None

def get_npb_video(history):
    url = "https://www3.nhk.or.jp/sports/json/pro-baseball/index.json"
    candidates = []
    try:
        res = requests.get(url, timeout=15)
        res.raise_for_status()
        data = res.json()
        for clip in data.get('clips', []):
            v_id = str(clip.get('id'))
            if v_id not in history:
                candidates.append({"title": clip.get('title',''), "url": clip.get('video_url') or f"https://www3.nhk.or.jp/sports/special/baseball/npb/videos/{v_id}", "id": v_id, "type": "npb", "source": "NHKスポーツ"})
    except Exception as e: logger.error(f"NPB動画取得失敗: {e}")
    return candidates

def get_mlb_video(history, is_test_mode):
    candidates = []
    for day_offset in [0, 1]:
        date_str = (datetime.datetime.now() - datetime.timedelta(days=day_offset)).strftime('%Y-%m-%d')
        url = f"https://statsapi.mlb.com/api/v1/schedule/games/?sportId=1&startDate={date_str}&endDate={date_str}"
        try:
            res = requests.get(url, timeout=15)
            data = res.json()
            for date_data in data.get('dates', []):
                for game in date_data.get('games', []):
                    try:
                        content = requests.get(f"https://statsapi.mlb.com/api/v1/game/{game['gamePk']}/content").json()
                        for item in content.get('highlights', {}).get('highlights', {}).get('items', []):
                            title = item.get('headline', ''); v_id = str(item.get('id'))
                            v_url = next((p['url'] for p in item['playbacks'] if p['name'] == 'mp4Avc'), None)
                            if v_url and v_id not in history and any(kw in title.lower() for kw in JPN_KEYWORDS):
                                candidates.append({"title": title, "url": v_url, "id": v_id, "type": "mlb", "source": "@MLBJapan"})
                    except: continue
        except Exception as e: logger.error(f"MLB取得失敗: {e}")
    return candidates

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats(); history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    cleanup_gemini_storage()
    flash_model = get_available_flash_model()
    candidates = get_npb_video(history) + get_mlb_video(history, is_test_mode)
    if not candidates:
        logger.info("😴 候補なし。")
        return
    candidates.sort(key=lambda x: 1 if x['type'] == 'npb' else 2)
    
    for video in candidates:
        logger.info(f"🎯 確定: {video['title']}")
        temp_input = "temp_video.mp4"
        
        # ✅ 修正：yt-dlpのreturncode確認
        result = subprocess.run(['yt-dlp', '-o', temp_input, '--quiet', video['url']], capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"yt-dlp失敗: {result.stderr.strip()}"); continue

        start_sec, ai_caption, srt_data = analyze_video_with_ai(temp_input, video['title'], video['source'], flash_model, is_mlb=(video['type'] == 'mlb'))
        if ai_caption is None: continue

        video_filters = "scale=1134:-2,crop=1080:ih"
        if video['type'] == 'mlb' and srt_data:
            with open("subtitles.srt", "w", encoding="utf-8") as sf: sf.write(srt_data)
            video_filters += ",subtitles=./subtitles.srt:force_style='Fontname=Noto Sans CJK JP,FontSize=22,PrimaryColour=&H00FFFFFF,BackColour=&H80000000,BorderStyle=4,Outline=0,MarginV=20'"
            logger.info("🎨 字幕焼き込み適用")

        filter_complex = f"{video_filters},pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"

        # ✅ 修正：ffmpegのreturncode確認
        ffmpeg_res = subprocess.run(['ffmpeg', '-ss', str(start_sec), '-i', temp_input, '-t', '90', '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-b:v', '5M', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-y', 'output.mp4'], capture_output=True, text=True)
        if ffmpeg_res.returncode != 0:
            logger.error(f"ffmpeg失敗: {ffmpeg_res.stderr[-500:]}"); continue
        
        try:
            with open('output.mp4', 'rb') as f:
                res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f}, timeout=60).json()
                if res.get('status') == 'success':
                    public_url = res['data']['url'].replace("tmpfiles.org/", "tmpfiles.org/dl/")
                    # ✅ 修正：ヘッダー経由でリクエスト
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
                                stats[video['type']] += 1; save_stats(stats); return
                            elif status == 'ERROR':
                                logger.error(f"Instagram処理エラー: {status_res}"); break
        except Exception as e: logger.error(f"システムエラー: {e}")
    logger.info("😴 終了。")

if __name__ == "__main__":
    main()
