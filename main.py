import sys
# リアルタイムログ出力設定
print("🚀 プレイボール速報・システム稼働（NPB広域奪還 ＋ AI解析リトライモード）...")
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

# 【完全網羅】日本人選手（15名 × 4パターン = 60個）
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

BLACK_KEYWORDS = ["probable", "pitchers", "lineup", "interview", "press", "availability", "roster", "update", "alignment", "summary", "preview", "warmup", "positioning", "against", "at bat", "statcast", "recap", "daily", "full highlights", "outing", "talks", "comments"]

def get_stats():
    if os.path.exists('stats.json'):
        try:
            with open('stats.json', 'r') as f: return json.load(f)
        except: pass
    return {"npb": 75, "mlb": 25}

def save_stats(stats):
    with open('stats.json', 'w') as f:
        json.dump(stats, f)

def cleanup_gemini_storage():
    try:
        for f in genai.list_files(): genai.delete_file(f.name)
        print("🧹 AIストレージの掃除完了。")
    except: pass

def get_npb_video(history):
    """Googleニュースの広域RSSからNPB動画を強引に探索"""
    print("🔍 NPB探索 (Googleニュース広域RSS)...")
    # 20以上のメディアを網羅するGoogleニュースの検索RSS
    url = "https://news.google.com/rss/search?q=プロ野球+動画+OR+ハイライト&hl=ja&gl=JP&ceid=JP:ja"
    candidates = []
    try:
        res = requests.get(url, timeout=15)
        root = ET.fromstring(res.content)
        items = root.findall('.//item')
        print(f"  👉 RSSから {len(items)}件 のニュースを検出しました。")
        
        for item in items:
            title = item.find('title').text
            v_url = item.find('link').text
            # GUIDをIDとして使用
            v_id = item.find('guid').text if item.find('guid') is not None else v_url
            
            if v_id not in history:
                # プレー映像である可能性が高いキーワードが含まれているか
                if any(k in title for k in ["動画", "再生", "ハイライト", "好プレー", "本塁打", "安打", "三振"]):
                    if not any(k in title.lower() for k in BLACK_KEYWORDS):
                        print(f"  ✅ NPB候補発見: {title[:30]}...")
                        candidates.append({"title": title, "url": v_url, "id": v_id, "type": "npb", "source": "NewsAggregator"})
        return candidates
    except Exception as e:
        print(f"  ⚠️ RSS取得失敗: {e}")
        return []

def get_mlb_video(history, is_test_mode):
    print("🔍 MLB探索 (過去4日間を調査)...")
    candidates = []
    for day_offset in range(4):
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
                                    candidates.append({"title": title, "url": v_url, "id": v_id, "type": "mlb", "source": "@MLBJapan"})
                    except: continue
        except: continue
    print(f"  👉 MLB未投稿候補: {len(candidates)}件")
    return candidates

def analyze_video_with_ai(video_path, title, source_account):
    """AI解析（執念のリトライ ＋ 詳細ログ出力）"""
    print(f"🧠 AIによる動画解析を開始...")
    try:
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING": time.sleep(2); video_file = genai.get_file(video_file.name)
        
        # モデル名のリトライ（1.5系で固定）
        target_models = ["models/gemini-1.5-flash", "models/gemini-1.5-flash-latest"]
        last_err = ""

        for m_name in target_models:
            try:
                print(f"  👉 AI試行中 ({m_name})...")
                model = genai.GenerativeModel(m_name)
                prompt = f"野球動画({title})を解析し、見どころ開始秒数を「[秒数のみ]」、本文を出力せよ。2ch風の鋭い解説。ですます禁止。ラベル禁止。引用：{source_account}を最後に。タグ25個。"
                response = model.generate_content([prompt, video_file])
                
                res_text = response.text
                genai.delete_file(video_file.name)
                
                # 強制ラベル除去
                clean_text = re.sub(r'(?i)(START|CAPTION|秒数|本文|開始|タイトル|見出し|概要|所感)[:：]\s*', '', res_text).strip()
                lines = [l.strip() for l in clean_text.split('\n') if l.strip()]
                start_sec = int(re.search(r"(\d+)", lines[0]).group(1)) if lines else 0
                ai_caption = "\n".join(lines[1:])
                
                print(f"  ✨ AI解析成功: 開始 {start_sec}s")
                return start_sec, ai_caption
            except Exception as e:
                last_err = str(e)
                if "429" in last_err: # クォータ制限なら少し待機
                    print("  ⚠️ AI制限(429)を検知。20秒待機します...")
                    time.sleep(20)
                continue
        
        print(f"  ❌ AI解析が最終的に失敗しました: {last_err}")
        return 0, None
    except Exception as e:
        print(f"  ❌ AIプロセス致命的エラー: {e}")
        return 0, None

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats(); history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    cleanup_gemini_storage()
    
    print(f"⚾️ 探索開始...")
    npb_list = get_npb_video(history)
    mlb_list = get_mlb_video(history, is_test_mode)
    candidates = npb_list + mlb_list
    
    if not candidates: print("😴 新着なし"); return

    total_posted = stats['npb'] + stats['mlb']
    mlb_ratio = stats['mlb'] / total_posted if total_posted > 0 else 0
    print(f"📊 MLB比率: {mlb_ratio*100:.1f}%")

    # NPBを最優先にソート
    candidates.sort(key=lambda x: 1 if x['type'] == 'npb' else 2)
    
    for video in candidates[:10]: # 上位10件までリトライ
        if not is_test_mode and video['type'] == 'mlb' and mlb_ratio > 0.25 and len(npb_list) > 0:
            continue

        print(f"🎯 ターゲット確定: {video['title']}")
        temp_input = "temp_video.mp4"
        
        # ダウンロード
        cmd = ['yt-dlp', '-o', temp_input, '--no-check-certificates', '--quiet', video['url']]
        res = subprocess.run(cmd)
        
        if res.returncode != 0 or not os.path.exists(temp_input) or os.path.getsize(temp_input) < 10000:
            print("  ❌ ダウンロード失敗。次の候補へ。"); continue

        start_sec, ai_caption = analyze_video_with_ai(temp_input, video['title'], video['source'])
        
        if ai_caption is None:
            # AIが失敗した動画はIDを記録せず、次回以降に望みを繋ぐ
            print("  ⏩ AI解析不発。次の動画を試します。")
            continue

        output_file = "output.mp4"
        filter_complex = "scale=1134:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
        subprocess.run(['ffmpeg', '-ss', str(start_sec), '-i', temp_input, '-t', '90', '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-b:v', '5M', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-y', output_file])
        
        try:
            with open(output_file, 'rb') as f:
                up_res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f}, timeout=60).json()
                if up_res.get('status') == 'success':
                    public_url = up_res['data']['url'].replace("http://", "https://").replace("tmpfiles.org/", "tmpfiles.org/dl/")
                    print(f"✅ 公開URL確保")
                    time.sleep(10)
                    post_res = requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media", data={'media_type': 'REELS', 'video_url': public_url, 'caption': ai_caption, 'access_token': ACCESS_TOKEN}).json()
                    
                    if 'id' in post_res:
                        creation_id = post_res['id']
                        for _ in range(20):
                            time.sleep(30)
                            status_res = requests.get(f"https://graph.facebook.com/v21.0/{creation_id}", params={'fields': 'status_code,status', 'access_token': ACCESS_TOKEN}).json()
                            status = (status_res.get('status_code') or status_res.get('status') or "").upper()
                            print(f"  API Response: {status}")
                            if status == 'FINISHED':
                                requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN})
                                print(f"🏁 投稿完了！")
                                with open(history_file, 'a') as fh: fh.write(video['id'] + "\n")
                                stats[video['type']] += 1; save_stats(stats); return
        except Exception as e: print(f"  ❌ エラー: {e}")
    print("😴 スキャン終了。")

if __name__ == "__main__":
    main()
