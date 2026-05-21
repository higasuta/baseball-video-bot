import sys
# リアルタイムログ出力設定
print("🚀 プレイボール速報・システム最終形態 起動...")
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

# 【完全網羅】日本人15名（4パターン検索）
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

def find_working_ai_model():
    """環境で本当に使えるモデル名を自動取得"""
    print("📋 利用可能なAIモデルを確認中...")
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        for target in ["gemini-1.5-flash-latest", "gemini-1.5-flash", "gemini-flash", "flash"]:
            for m in available_models:
                if target in m:
                    print(f"  ✅ 採用モデル: {m}")
                    return m
        return available_models[0]
    except: return "models/gemini-1.5-flash"

def get_npb_video(history):
    """【執念】ブロックを回避する4つのNPBルート"""
    ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    
    # ルート1: NHK JSON
    print("🔍 NPBルートA (NHK公式) 探索中...")
    try:
        res = requests.get("https://www3.nhk.or.jp/sports/json/pro-baseball/index.json", timeout=15)
        for clip in res.json().get('clips', []):
            v_id = str(clip['id'])
            if v_id not in history:
                url = clip.get('video_url') or f"https://www3.nhk.or.jp/sports/special/baseball/npb/videos/{v_id}"
                return {"title": clip['title'], "url": url, "id": v_id, "type": "npb", "source": "NHKスポーツ"}
    except: pass

    # ルート2: 日刊スポーツ RSS (新聞社系)
    print("🔍 NPBルートB (日刊スポーツ) 探索中...")
    try:
        rss = requests.get("https://www.nikkansports.com/baseball/news/index.xml", timeout=10)
        root = ET.fromstring(rss.content)
        for item in root.findall('.//item')[:10]:
            title = item.find('title').text
            if "動画" in title or "安打" in title or "HR" in title:
                v_url = item.find('link').text
                v_id = v_url.split('/')[-1]
                if v_id not in history:
                    return {"title": title, "url": v_url, "id": v_id, "type": "npb", "source": "日刊スポーツ"}
    except: pass

    # ルート3: THE ANSWER (独自配信)
    print("🔍 NPBルートC (THE ANSWER) 探索中...")
    try:
        res = requests.get("https://the-ans.jp/category/baseball/", headers={"User-Agent": ua}, timeout=10)
        matches = re.findall(r'href="(https://the-ans\.jp/news/(\d+)/)"[^>]*?>(.*?)</a>', res.text)
        for v_url, v_id, title in matches:
            if v_id not in history:
                return {"title": title.strip(), "url": v_url, "id": v_id, "type": "npb", "source": "TheAnswer"}
    except: pass

    return None

def get_mlb_video(history, is_test_mode):
    """MLB日本人15名（ヒットや本塁打を優先）"""
    print("🔍 MLB動画を探索中（日本人15名）...")
    candidates = []
    for day_offset in range(2):
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
                                if any(kw in title.lower() for kw in JPN_KEYWORDS):
                                    priority = 2
                                    # 本塁打やヒットなら最優先
                                    if any(k in title.lower() for k in ["home run", "homer", "rbi", "single", "double", "triple"]):
                                        priority = 1
                                    candidates.append({"title": title, "url": v_url, "id": v_id, "type": "mlb", "source": "@MLBJapan", "priority": priority})
                    except: continue
        except: continue
    
    if candidates:
        candidates.sort(key=lambda x: x['priority'])
        return candidates[0]
    return None

def analyze_video_with_ai(video_path, title, source_account, model_name):
    """AIによる動画解析（進捗をログに表示）"""
    print(f"🧠 AIによる動画解析中（動画サイズが大きいと数分かかります）...")
    try:
        # クォータ掃除
        for f in genai.list_files(): genai.delete_file(f.name)
        
        video_file = genai.upload_file(path=video_path)
        
        # 進捗を視覚化
        print("  ⏳ AIが動画をスキャン中", end="")
        while video_file.state.name == "PROCESSING":
            print(".", end="")
            sys.stdout.flush()
            time.sleep(5)
            video_file = genai.get_file(video_file.name)
        print("\n  ✅ スキャン完了。キャプション執筆中...")

        model = genai.GenerativeModel(model_name)
        prompt = f"""
        野球動画({title})を解析し、以下を出力せよ。
        1. 開始秒数(数値1つのみ)
        2. インスタのリール用キャプション本文
        【ルール】
        ・一段目：【 】付きの鋭い見出し。皮肉と分析を交えろ。ですます、STARTラベルなどは禁止。
        ・自然なタイムスタンプ、ハッシュタグ25個、引用：{source_account} を入れろ。
        """
        response = model.generate_content([prompt, video_file])
        res_text = response.text
        genai.delete_file(video_file.name)

        # ラベル物理抹殺
        clean_text = re.sub(r'(?i)(START|CAPTION|秒数|本文|開始|タイトル|見出し|概要|所感|解説)[:：]\s*', '', res_text).strip()
        lines = [l.strip() for l in clean_text.split('\n') if l.strip()]
        start_sec = int(re.search(r"(\d+)", lines[0]).group(1)) if lines else 0
        ai_caption = "\n".join(lines[1:]) if len(lines) > 1 else clean_text
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

    flash_model = find_working_ai_model()
    print(f"⚾️ 探索開始...")
    video_data = get_npb_video(history) or get_mlb_video(history, is_test_mode)

    if video_data:
        print(f"🎯 ターゲット確定: {video_data['title']}")
        temp_input = "temp_video.mp4"
        subprocess.run(['curl', '-L', video_data['url'], '-o', temp_input])
        
        if not os.path.exists(temp_input) or os.path.getsize(temp_input) < 10000:
            subprocess.run(['yt-dlp', '-o', temp_input, '--no-check-certificates', '--quiet', video_data['url']])

        if not os.path.exists(temp_input) or os.path.getsize(temp_input) < 10000: return

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
                                print(f"🏁 投稿完了！"); with open(history_file, 'a') as fh: fh.write(video_data['id'] + "\n")
                                stats[video_data['type']] += 1; save_stats(stats); return
        except Exception as e: print(f"  ❌ エラー: {e}")
    else: print("😴 投稿対象なし。")

if __name__ == "__main__":
    main()
