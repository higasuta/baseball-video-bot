import sys
# リアルタイムログ出力
print("🚀 プレイボール速報・システム最終形態 稼働中...")
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
JPN_KEYWORDS = ["大谷", "山本", "ダルビッシュ", "鈴木誠也", "吉田正尚", "今永", "松井裕樹", "千賀", "前田健太", "菊池雄星", "ohtani", "yamamoto", "imanaga", "菅野", "senga", "darvish"]

# 【特報キーワード】
HOT_MLB_KEYWORDS = ["home run", "hr", "grand slam", "stole", "stolen base", "steal", "record", "historic", "milestone", "perfect game", "no-hitter"]

# 【超厳選】地味な動画・データ動画・「非プレー」を徹底排除
BLACK_KEYWORDS = [
    "probable", "pitchers", "lineup", "interview", "press", "availability", 
    "roster", "update", "alignment", "summary", "preview", "warmup", 
    "positioning", "against", "at bat", "statcast", "recap", "daily",
    "measuring", "animated", "distance", "deep dive", "analyzing", "data viz",
    "condensed", "breaking down", "bat tracking", "talks", "more", 
    "first pitch", "pre-game", "ceremonial", "wild pitch" # 始球式やワイルドピッチも排除
]

def get_stats():
    if os.path.exists('stats.json'):
        try:
            with open('stats.json', 'r') as f: return json.load(f)
        except: pass
    return {"npb": 30, "mlb": 10} # 7.5:2.5 の比率をベースに設定

def save_stats(stats):
    with open('stats.json', 'w') as f:
        json.dump(stats, f)

def cleanup_gemini_storage():
    try:
        for f in genai.list_files():
            genai.delete_file(f.name)
        print("🧹 AIストレージを掃除しました。")
    except: pass

def get_available_flash_model():
    """使用可能な最新のFlashモデルを取得"""
    try:
        models = [m.name for m in genai.list_models() if 'flash' in m.name and 'generateContent' in m.supported_generation_methods]
        if models:
            # gemini-2.5-flashなど、より新しいものを優先
            models.sort(reverse=True)
            return models[0]
    except: pass
    return "models/gemini-1.5-flash"

def get_npb_candidates(history):
    """スポナビRSSスキャン（日本国外IPブロック対策強化版）"""
    rss_url = "https://sports.yahoo.co.jp/video/rss/baseball/npb"
    print(f"🔍 NPB動画を探索中 (スポナビRSS)...")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
        "Referer": "https://sports.yahoo.co.jp/"
    }
    
    candidates = []
    try:
        res = requests.get(rss_url, headers=headers, timeout=20)
        if res.status_code == 200:
            root = ET.fromstring(res.content)
            items = root.findall('.//item')
            print(f"  👉 RSSから {len(items)}件 の情報を取得しました。")
            for item in items:
                title = item.find('title').text
                v_id = item.find('guid').text if item.find('guid') is not None else item.find('link').text
                if v_id not in history:
                    if any(kw in title.lower() for kw in BLACK_KEYWORDS): continue
                    candidates.append({
                        "title": title, "url": item.find('link').text, "id": v_id, 
                        "type": "npb", "source": "スポーツナビ", "priority": 1, "is_hot": False
                    })
        else:
            print(f"  ⚠️ RSS取得失敗 (Status: {res.status_code})")
    except Exception as e:
        print(f"  ⚠️ NPBスキャン中にエラー: {e}")
    
    return candidates

def get_mlb_candidates(history, is_test_mode):
    """MLB APIスキャン"""
    print("🔍 MLB動画を探索中 (公式API)...")
    candidates = []
    for day_offset in [0, 1, 2]:
        date_str = (datetime.datetime.now() - datetime.timedelta(days=day_offset)).strftime('%Y-%m-%d')
        url = f"https://statsapi.mlb.com/api/v1/schedule/games/?sportId=1&startDate={date_str}&endDate={date_str}"
        try:
            res = requests.get(url, timeout=15).json()
            if 'dates' not in res: continue
            for date_data in res['dates']:
                for game in date_data.get('games', []):
                    content = requests.get(f"https://statsapi.mlb.com/api/v1/game/{game['gamePk']}/content").json()
                    highlights = content.get('highlights', {}).get('highlights', {}).get('items', [])
                    for item in highlights:
                        title = item.get('headline', '')
                        v_id = str(item.get('id'))
                        v_url = next((p['url'] for p in item.get('playbacks', []) if p['name'] == 'mp4Avc'), None)
                        if v_url and v_id not in history:
                            if any(kw in title.lower() for kw in BLACK_KEYWORDS): continue
                            is_jpn = any(kw in title.lower() for kw in JPN_KEYWORDS)
                            is_hot = any(kw in title.lower() for kw in HOT_MLB_KEYWORDS)
                            
                            if is_jpn:
                                candidates.append({"title": title, "url": v_url, "id": v_id, "type": "mlb", "source": "@MLBJapan", "priority": 1, "is_hot": is_hot})
                            elif is_test_mode or is_hot:
                                candidates.append({"title": title, "url": v_url, "id": v_id, "type": "mlb", "source": "@MLBJapan", "priority": 2, "is_hot": is_hot})
        except: continue
    return candidates

def analyze_video_with_ai(video_path, title, source_account, model_name):
    """Geminiによる動画解析"""
    print(f"🧠 AIによる動画解析中 (使用モデル: {model_name})...")
    try:
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING": time.sleep(2); video_file = genai.get_file(video_file.name)
        model = genai.GenerativeModel(model_name)
        prompt = f"""
        野球動画({title})を解析し、以下の形式で出力せよ。
        プレー映像（投球、打撃、守備、走塁）がない地味な動画は CAPTION:SKIP と出力せよ。
        START:[秒]
        CAPTION:[内容]
        構成：一段目【 】入りの鋭い見出し。要約。鋭い所感。
        ネットスラング禁止。だ・である調。タグ25〜29個。引用：{source_account}
        """
        response = model.generate_content([prompt, video_file])
        res_text = response.text
        genai.delete_file(video_file.name)
        if "SKIP" in res_text: return None, "SKIP"
        start_match = re.search(r"START:(\d+)", res_text); start_sec = int(start_match.group(1)) if start_match else 0
        caption_match = re.search(r"CAPTION:(.*)", res_text, re.DOTALL); ai_caption = caption_match.group(1).strip() if caption_match else None
        print(f"  ✨ AI解析成功: 開始 {start_sec}s")
        return start_sec, ai_caption
    except Exception as e:
        print(f"  ⚠️ AI解析失敗: {e}")
        return None, None

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats(); history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    cleanup_gemini_storage()
    flash_model = get_available_flash_model()
    
    print(f"⚾️ 探索開始... (テストモード: {is_test_mode})")
    candidates = get_npb_candidates(history) + get_mlb_candidates(history, is_test_mode)
    
    if not candidates:
        print("😴 新しい動画が見つかりませんでした。")
        return

    # 比率計算
    total_posted = stats['npb'] + stats['mlb']
    mlb_ratio = stats['mlb'] / total_posted if total_posted > 0 else 0
    print(f"📊 現在のMLB比率: {mlb_ratio*100:.1f}% (目標: 25%以下)")

    candidates.sort(key=lambda x: x['priority'])
    
    for video in candidates[:15]:
        is_hot = video.get('is_hot', False)
        # MLB比率制限 (Hotニュースまたはテストモードなら無視)
        if not is_test_mode and video['type'] == 'mlb' and mlb_ratio > 0.25 and not is_hot:
            print(f"🛑 比率制限につきスキップ: {video['title']}")
            continue

        print(f"🎯 ターゲット確定: {video['title']}")
        temp_input = "temp_video.mp4"
        subprocess.run(['curl', '-L', video['url'], '-o', temp_input])
        if not os.path.exists(temp_input) or os.path.getsize(temp_input) < 10000: continue

        start_sec, ai_caption = analyze_video_with_ai(temp_input, video['title'], video['source'], flash_model)
        if ai_caption == "SKIP" or ai_caption is None:
            with open(history_file, 'a') as fh: fh.write(video['id'] + "\n")
            continue

        output_file = "output.mp4"
        filter_complex = "scale=1134:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
        subprocess.run(['ffmpeg', '-ss', str(start_sec), '-i', temp_input, '-t', '90', '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-b:v', '5M', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', '-y', output_file])
        
        try:
            with open(output_file, 'rb') as f:
                res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f}, timeout=60).json()
                if res.get('status') == 'success':
                    public_url = res['data']['url'].replace("http://", "https://").replace("tmpfiles.org/", "tmpfiles.org/dl/")
                    print(f"✅ 公開URL確保: {public_url}")
                    time.sleep(10)
                    post_res = requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media", data={'media_type': 'REELS', 'video_url': public_url, 'caption': ai_caption, 'access_token': ACCESS_TOKEN}).json()
                    
                    if 'id' in post_res:
                        creation_id = post_res['id']
                        for _ in range(20):
                            time.sleep(30)
                            status_res = requests.get(f"https://graph.facebook.com/v21.0/{creation_id}", params={'fields': 'status_code,status', 'access_token': ACCESS_TOKEN}).json()
                            status = (status_res.get('status_code') or status_res.get('status') or "").upper()
                            print(f"  ステータス: {status}")
                            if status == 'FINISHED':
                                requests.post(f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish", data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN})
                                print(f"🏁 投稿完了！: {video['title']}")
                                with open(history_file, 'a') as fh: fh.write(video['id'] + "\n")
                                stats[video['type']] += 1
                                save_stats(stats); return
        except Exception as e: print(f"  ❌ エラー: {e}")
    print("😴 終了。")

if __name__ == "__main__":
    main()
