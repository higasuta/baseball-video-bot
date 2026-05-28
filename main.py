import sys
# リアルタイムログ出力設定
print("🚀 プレイボール速報・システム最終形態（完全新ルート ＋ 偽動画排除）起動...")
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

# 【完全網羅】日本人選手（15名 × 4パターン = 60キーワード）
JPN_KEYWORDS = [
    "大谷翔平", "大谷", "shohei ohtani", "ohtani", "山本由伸", "山本", "yoshinobu yamamoto", "yamamoto",
    "佐々木朗希", "佐々木", "roki sasaki", "sasaki", "ダルビッシュ有", "ダルビッシュ", "yu darvish", "darvish",
    "松井裕樹", "松井", "yuki matsui", "matsui", "鈴木誠也", "鈴木", "seiya suzuki", "suzuki",
    "今永昇太", "今永", "shota imanaga", "imanaga", "千賀滉大", "千賀", "kodai senga", "senga",
    "菅野智之", "菅野", "tomoyuki sugano", "sugano", "小笠原慎之介", "小笠原", "shinnosuke ogasawara", "ogasawara",
    "岡本和真", "岡本", "kazuma okamoto", "okamoto", "今井達也", "今井", "tatsuya imai", "imai",
    "吉田正尚", "吉田", "masataka yoshida", "yoshida", "菊池雄星", "菊池", "yusei kikuchi", "kikuchi",
    "村上宗隆", "村上", "munetaka murakami", "murakami"
]

BLACK_KEYWORDS = ["probable", "pitchers", "lineup", "interview", "press", "availability", "roster", "update", "alignment", "summary", "preview", "warmup", "positioning", "against", "at bat", "statcast", "recap", "daily", "full highlights", "outing", "talks"]

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
    """環境で本当に使える最新Flashモデル名を自動特定"""
    print("📋 利用可能なAIモデルを探索中...")
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        for target in ["gemini-1.5-flash-latest", "gemini-1.5-flash", "gemini-flash"]:
            for m in available_models:
                if target in m:
                    print(f"  ✅ 採用モデル: {m}")
                    return m
        return available_models[0]
    except Exception as e:
        print(f"  ⚠️ モデル探索失敗: {e}")
        return "models/gemini-1.5-flash"

def get_npb_video(history):
    """【完全新ルート】Microsoft Bing Video RSS ＋ Livedoor 動画をスキャン"""
    candidates = []
    ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    
    # ルート1: Bing Video RSS (Microsoftインフラ経由、ブロックが極めて困難)
    print("🔍 NPBルートA (Bing Video RSS) 探索中...")
    try:
        # プロ野球の最新動画を検索するRSS
        url = "https://www.bing.com/news/search?q=プロ野球+動画+OR+ハイライト&qft=interval%3d%227%22&format=RSS&setlang=ja"
        res = requests.get(url, timeout=15)
        root = ET.fromstring(res.content)
        for item in root.findall('.//item')[:10]:
            title = item.find('title').text
            v_url = item.find('link').text
            v_id = v_url.split('/')[-1] if '/' in v_url else v_url
            if v_id not in history and any(k in title for k in ["安打", "本塁打", "三振", "勝利", "動画"]):
                print(f"  ✅ Bingルートで候補発見: {title[:20]}...")
                candidates.append({"title": title.strip(), "url": v_url, "id": v_id, "type": "npb", "source": "BingNews"})
    except: pass

    # ルート2: Livedoor ニュース (野球ビデオ枠 - 独自CDN)
    print("🔍 NPBルートB (Livedoor動画) 探索中...")
    try:
        url = "https://news.livedoor.com/category/v/baseball/"
        res = requests.get(url, headers={"User-Agent": ua}, timeout=15)
        v_ids = re.findall(r'article/detail/(\d+)/', res.text)
        for v_id in list(dict.fromkeys(v_ids))[:3]:
            if v_id not in history:
                candidates.append({"title": "NPB注目シーン", "url": f"https://news.livedoor.com/article/detail/{v_id}/", "id": v_id, "type": "npb", "source": "Livedoor"})
    except: pass

    return candidates

def get_mlb_video(history, is_test_mode):
    """MLB日本人選手15名のプレー映像を探索"""
    print("🔍 MLB動画を探索中（日本人15名限定）...")
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
                            title = item.get('headline', '')
                            v_id = str(item.get('id'))
                            v_url = next((p['url'] for p in item['playbacks'] if p['name'] == 'mp4Avc'), None)
                            if v_url and v_id not in history:
                                if any(kw in title.lower() for kw in JPN_KEYWORDS):
                                    return {"title": title, "url": v_url, "id": v_id, "type": "mlb", "source": "@MLBJapan"}
                    except: continue
        except: continue
    return None

def analyze_video_with_ai(video_path, title, source_account, model_name):
    """ラベルを物理的に抹殺したキャプションを生成"""
    print(f"🧠 AIによる動画解析中 (モデル: {model_name})...")
    try:
        # 古いファイルを削除
        for f in genai.list_files(): genai.delete_file(f.name)
        
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING": time.sleep(2); video_file = genai.get_file(video_file.name)
        
        model = genai.GenerativeModel(model_name)
        prompt = f"""
        野球動画({title})を解析し、以下を必ず出力せよ。
        1. [秒数のみを1行目に]
        2. [本文を2行目以降に]
        【ルール】鋭い2ch風の見出し。ニュース要約と鋭い所感。
        [0:05] 〇〇の瞬間、のように自然なタイムスタンプ。標準語「だ・である」調。
        ラベル(START:等)は絶対書くな。ハッシュタグ25個。引用：{source_account}
        """
        response = model.generate_content([prompt, video_file])
        res_text = response.text
        genai.delete_file(video_file.name)

        # 【物理抹殺】ラベル文字を徹底消去
        clean_text = re.sub(r'(?i)(START|CAPTION|秒数|本文|開始|タイトル|見出し|概要|所感|解説|所見|結論|タイムスタンプ)[:：]\s*', '', res_text).strip()
        lines = [l.strip() for l in clean_text.split('\n') if l.strip()]
        
        start_sec = 0
        first_line_match = re.search(r"(\d+)", lines[0]) if lines else None
        if first_line_match:
            start_sec = int(first_line_match.group(1))
            ai_caption = "\n".join(lines[1:])
        else:
            ai_caption = "\n".join(lines)
        return start_sec, ai_caption
    except Exception as e:
        print(f"  ⚠️ AI解析失敗: {e}")
        return 0, None

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats(); history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    # 有効なモデルを特定
    flash_model = find_working_ai_model()
    
    print(f"⚾️ 探索開始...")
    npb_candidates = get_npb_video(history)
    video_data = npb_candidates[0] if npb_candidates else get_mlb_video(history, is_test_mode)

    if video_data:
        print(f"🎯 ターゲット確定: {video_data['title']}")
        temp_input = "temp_video.mp4"
        
        # 二段構えダウンロード
        subprocess.run(['curl', '-L', video_data['url'], '-o', temp_input])
        if not os.path.exists(temp_input) or os.path.getsize(temp_input) < 10000:
            subprocess.run(['yt-dlp', '-o', temp_input, '--no-check-certificates', '--quiet', video_data['url']])

        # 【0.1秒鑑定】HTML記事の誤爆を物理的に排除
        if os.path.exists(temp_input):
            with open(temp_input, 'rb') as f:
                header = f.read(100).decode(errors='ignore')
                if "<html" in header.lower() or "<!doctype" in header.lower() or os.path.getsize(temp_input) < 1000000:
                    print("❌ ダウンロード失敗: 動画ではなくHTML記事でした。ボツにします。")
                    # 同じ記事を二度と狙わないよう履歴に入れる
                    with open(history_file, 'a') as fh: fh.write(video_data['id'] + "\n")
                    return

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
                        print(f"⏳ 完了待機...")
                        for i in range(20):
                            time.sleep(30)
                            status_res = requests.get(f"https://graph.facebook.com/v21.0/{creation_id}", params={'fields': 'status_code,status', 'access_token': ACCESS_TOKEN}).json()
                            status = (status_res.get('status_code') or status_res.get('status') or "").upper()
                            print(f"  API Response: {status}")
                            if status == 'FINISHED':
                                requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN})
                                print(f"🏁 投稿完了！")
                                with open(history_file, 'a') as fh: fh.write(video_data['id'] + "\n")
                                stats[video_data['type']] += 1; save_stats(stats); return
        except Exception as e: print(f"  ❌ システムエラー: {e}")
    else: print("😴 投稿対象なし。")

if __name__ == "__main__":
    main()
