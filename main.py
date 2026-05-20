import sys
# 1行目からログを出力
print("🚀 プレイボール速報・システム最終形態（AI安定化 ＋ プレー映像厳選モード）起動...")
sys.stdout.flush()

import requests
import datetime
import os
import time
import subprocess
import google.generativeai as genai
import json
import re
import xml.etree.ElementTree as ET

# ==========================================
# 設定・環境変数の読み込み
# ==========================================
INSTA_ID = os.getenv('INSTA_BUSINESS_ID')
ACCESS_TOKEN = os.getenv('INSTA_ACCESS_TOKEN')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# 日本人選手キーワード
JPN_KEYWORDS = ["大谷翔平", "大谷", "shohei ohtani", "ohtani", "山本由伸", "山本", "佐々木朗希", "佐々木", "ダルビッシュ有", "ダルビッシュ", "松井裕樹", "松井", "鈴木誠也", "鈴木", "今永昇太", "今永", "千賀滉大", "千賀", "菅野智之", "菅野", "小笠原慎之介", "小笠原", "岡本和真", "岡本", "今井達也", "今井", "吉田正尚", "吉田", "菊池雄星", "菊池", "村上宗隆", "村上"]

# 【厳選】インタビュー、感想、地味な動画を徹底排除するキーワード
BLACK_KEYWORDS = [
    "probable", "pitchers", "lineup", "interview", "press", "availability", 
    "roster", "update", "alignment", "summary", "preview", "warmup", 
    "positioning", "against", "at bat", "statcast", "recap", "daily",
    "full highlights", "talks", "comments", "reaction", "on", "outing"
]

def get_stats():
    if os.path.exists('stats.json'):
        try:
            with open('stats.json', 'r') as f: return json.load(f)
        except: pass
    return {"npb": 75, "mlb": 25}

def save_stats(stats):
    with open('stats.json', 'w') as f:
        json.dump(stats, f)

def get_stable_model():
    """2.0は制限が厳しすぎるため、安定した1.5-flashを強制選択"""
    return "models/gemini-1.5-flash"

def get_npb_video(history):
    """【新ルート】Googleニュースのビデオ検索RSSからNPB動画を探索"""
    print("🔍 NPB探索 (Google News Video RSS)...")
    # 検索クエリを「プロ野球 動画」に絞ったRSS
    url = "https://news.google.com/rss/search?q=プロ野球+動画+OR+ハイライト&hl=ja&gl=JP&ceid=JP:ja"
    
    try:
        res = requests.get(url, timeout=15)
        root = ET.fromstring(res.content)
        for item in root.findall('.//item')[:15]:
            title = item.find('title').text
            v_url = item.find('link').text
            v_id = item.find('guid').text if item.find('guid') is not None else v_url
            
            if v_id not in history:
                # 記事ではなく「プレーの気配」があるものに限定
                if any(k in title for k in ["安打", "本塁打", "奪三振", "勝利", "タイムリー"]):
                    if not any(k in title.lower() for k in BLACK_KEYWORDS):
                        print(f"  ✅ 新ルートで発見: {title[:30]}")
                        return {"title": title.strip(), "url": v_url, "id": v_id, "type": "npb", "source": "GoogleNewsVideo"}
    except: pass
    return None

def get_mlb_video(history, is_test_mode):
    print("🔍 MLB動画を探索中（日本人15名限定・プレー映像厳選）...")
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
                                # タイトルからインタビュー系を徹底排除
                                if any(kw in title.lower() for kw in BLACK_KEYWORDS): continue
                                # 日本人選手が「プレー」している動画か
                                if any(kw in title.lower() for kw in JPN_KEYWORDS):
                                    print(f"  ✅ プレー動画を発見: {title}")
                                    return {"title": title, "url": v_url, "id": v_id, "type": "mlb", "source": "@MLBJapan"}
                    except: continue
        except: continue
    return None

def analyze_video_with_ai(video_path, title, source_account, model_name):
    print(f"🧠 AIによる動画解析中 (安定版モデル)...")
    try:
        # クォータ掃除
        for f in genai.list_files(): genai.delete_file(f.name)
        
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING": time.sleep(2); video_file = genai.get_file(video_file.name)
        
        model = genai.GenerativeModel(model_name)
        prompt = f"""
        野球動画({title})を解析し、以下を必ず出力せよ。
        1. [秒数のみを1行目に]
        2. [本文を2行目以降に]

        【ルール】
        ・あなたは野球まとめ解説動画の毒舌ナレーターだ。一段目：【 】付きの鋭い見出し。二段目：要約。三段目：皮肉と愛の所感。
        ・[0:05] のような形式のタイムスタンプを1つ自然に入れろ。
        ・標準語「だ・である」調。ですます禁止。ラベル(START:等)は一切書くな。
        ・ハッシュタグ25個。引用：{source_account} を最後に。
        """
        response = model.generate_content([prompt, video_file])
        res_text = response.text
        genai.delete_file(video_file.name)

        # ラベル物理抹殺
        clean_text = re.sub(r'(?i)(START|CAPTION|秒数|本文|開始|タイトル|見出し|概要|所感)[:：]\s*', '', res_text).strip()
        lines = [l.strip() for l in clean_text.split('\n') if l.strip()]
        
        start_sec = 0
        first_line_match = re.search(r"(\d+)", lines[0]) if lines else None
        if first_line_match:
            start_sec = int(first_line_match.group(1))
            ai_caption = "\n".join(lines[1:])
        else: ai_caption = "\n".join(lines)
            
        print(f"  ✨ 解析成功: 開始 {start_sec}s")
        return start_sec, ai_caption
    except Exception as e:
        print(f"  ⚠️ AI解析失敗: {e}")
        return 0, None

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats(); history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    # 安定版モデルを選択
    flash_model = get_stable_model()
    
    print(f"⚾️ 探索開始...")
    video_data = get_npb_video(history) or get_mlb_video(history, is_test_mode)

    if video_data:
        print(f"🎯 ターゲット確定: {video_data['title']}")
        temp_input = "temp_video.mp4"
        
        # ダウンロード
        subprocess.run(['curl', '-L', video_data['url'], '-o', temp_input])
        if not os.path.exists(temp_input) or os.path.getsize(temp_input) < 10000:
            # yt-dlpでの代替
            subprocess.run(['yt-dlp', '-o', temp_input, '--no-check-certificates', '--quiet', video_data['url']])

        if not os.path.exists(temp_input) or os.path.getsize(temp_input) < 10000:
            print("❌ ダウンロード失敗。"); return

        start_sec, ai_caption = analyze_video_with_ai(temp_input, video_data['title'], video_data['source'], flash_model)
        if ai_caption is None:
            # プレーがないと判断された場合は履歴に入れてスルー
            with open(history_file, 'a') as fh: fh.write(video_data['id'] + "\n"); return

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
                        for _ in range(20):
                            time.sleep(30)
                            status_res = requests.get(f"https://graph.facebook.com/v21.0/{creation_id}", params={'fields': 'status_code,status', 'access_token': ACCESS_TOKEN}).json()
                            status = (status_res.get('status_code') or status_res.get('status') or "").upper()
                            if status == 'FINISHED':
                                requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN})
                                print(f"🏁 投稿完了！")
                                with open(history_file, 'a') as fh: fh.write(video_data['id'] + "\n")
                                stats[video_data['type']] += 1; save_stats(stats); return
        except Exception as e: print(f"  ❌ システムエラー: {e}")
    else: print("😴 投稿対象なし。")

if __name__ == "__main__":
    main()
