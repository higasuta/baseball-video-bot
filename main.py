import sys
# リアルタイムログ出力
print("🚀 プレイボール速報・新章（NPB 30ルート広域スキャン ＋ ラベル抹殺モード）起動...")
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

def get_npb_video(history):
    """【執念】30ルート以上のメディア、RSS、独自配信網からNPB動画を力技で探索"""
    candidates = []
    ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    headers = {"User-Agent": ua}
    
    # 1. RSSフィード・ルート（ブロックがほぼ不可能なXMLデータ）
    print("🔍 NPB Stage 1: RSSフィード一斉スキャン...")
    rss_targets = [
        "https://news.google.com/rss/search?q=プロ野球+video&hl=ja&gl=JP&ceid=JP:ja",
        "https://news.google.com/rss/search?q=パ・リーグ+video&hl=ja&gl=JP&ceid=JP:ja",
        "https://sports.yahoo.co.jp/video/rss/baseball/npb",
        "https://news.yahoo.co.jp/rss/categories/sports.xml",
        "https://baseballking.jp/feed",
        "https://full-count.jp/feed",
        "https://www.daily.co.jp/baseball/index.xml"
    ]
    for rss_url in rss_targets:
        try:
            res = requests.get(rss_url, timeout=10)
            root = ET.fromstring(res.content)
            for item in root.findall('.//item')[:10]:
                title = item.find('title').text
                v_url = item.find('link').text
                v_id = item.find('guid').text if item.find('guid') is not None else v_url
                if v_id not in history and not any(k in title.lower() for k in BLACK_KEYWORDS):
                    candidates.append({"title": title, "url": v_url, "id": v_id, "type": "npb", "source": "RSS_Aggregator", "priority": 1})
        except: continue

    # 2. 直撃スクレイピング・ルート（新聞・TV・専門誌30選）
    print(f"🔍 NPB Stage 2: 広域メディア30サイト・スキャン開始...")
    targets = [
        "https://www.nikkansports.com/baseball/video/", "https://www.sponichi.co.jp/baseball/",
        "https://www.sanspo.com/baseball/", "https://hochi.news/baseball/",
        "https://baseballking.jp/video", "https://full-count.jp/category/npb/",
        "https://sportsbull.jp/category/baseball/", "https://www.daily.co.jp/baseball/",
        "https://www3.nhk.or.jp/news/cat07.html", "https://news.tv-asahi.co.jp/news_sports/",
        "https://news.ntv.co.jp/category/sports", "https://newsdig.tbs.co.jp/category/sports",
        "https://www.fnn.jp/category/スポーツ", "https://mainichi.jp/baseball/",
        "https://www.asahi.com/sports/baseball/", "https://www.yomiuri.co.jp/sports/baseball/",
        "https://dot.asahi.com/dot/sports/baseball/", "https://the-ans.jp/category/baseball/",
        "https://cocokara-next.com/category/athlete/baseball/", "https://www.tokyo-sports.co.jp/baseball/",
        "https://pacificleague.com/video", "https://www.chunichi.co.jp/baseball",
        "https://www.nishinippon.co.jp/nsp/kyushu_baseball/", "https://www.kobe-np.co.jp/news/sports/",
        "https://kahoku.news/sports/rakuten/", "https://www.chugoku-np.co.jp/category/sports/carp",
        "https://www.daily.co.jp/tigers/", "https://www.sanspo.com/baseball/hanshin/",
        "https://www.nikkansports.com/baseball/news/giants/"
    ]

    for url in targets:
        try:
            domain = url.split('/')[2]
            # yt-dlpの汎用抽出に頼る
            cmd = ['yt-dlp', '--get-id', '--get-title', '--get-url', '--playlist-end', '2', '--no-check-certificates', '--user-agent', ua, '--quiet', url]
            output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=20).decode().split('\n')
            for i in range(0, len(output)-2, 3):
                title, v_id, v_url = output[i].strip(), output[i+1].strip(), output[i+2].strip()
                if v_id and v_id not in history and len(title) > 5:
                    print(f"    ✅ {domain} で発見: {title}")
                    candidates.append({"title": title, "url": v_url, "id": v_id, "type": "npb", "source": domain, "priority": 1})
                    return candidates # 1つ見つかれば即座に返す（高速化）
        except: continue
    
    return candidates

def get_mlb_video(history, is_test_mode):
    """MLB日本人15名完全網羅"""
    print("🔍 MLB動画を探索中（日本人15名完全網羅）...")
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
                                if any(kw in title.lower() for kw in JPN_KEYWORDS):
                                    return {"title": title, "url": v_url, "id": v_id, "type": "mlb", "source": "@MLBJapan"}
                    except: continue
        except: continue
    return None

def analyze_video_with_ai(video_path, title, source_account):
    """AI解析（ラベル抹殺仕様）"""
    print(f"🧠 AIによる動画解析中...")
    try:
        # ストレージ掃除
        try:
            for f in genai.list_files(): genai.delete_file(f.name)
        except: pass
        
        video_file = genai.upload_file(path=video_path)
        while video_file.state.name == "PROCESSING": time.sleep(2); video_file = genai.get_file(video_file.name)
        
        model = genai.GenerativeModel("gemini-2.0-flash")
        prompt = f"""
        野球動画({title})を解析し、以下の2つのみを出力せよ。
        1. 開始秒数(数値1つ)
        2. インスタのリール用キャプション本文
        【ルール】
        ・一段目：【 】付きの鋭い見出し。二段目：要約。三段目：アナリストの鋭い所感（だ・である調）。
        ・[0:05] 自然なタイムスタンプを組み込め。
        ・START: や CAPTION: などのラベル、技術的単語、ネットスラングは禁止。
        ・引用：{source_account} を最後に。ハッシュタグ25個以上。
        """
        response = model.generate_content([prompt, video_file])
        res_text = response.text
        genai.delete_file(video_file.name)

        # ラベル(START:, CAPTION:等)を物理的に削り取る
        clean_text = re.sub(r'(?i)(START|CAPTION|秒数|本文|開始|タイトル|見出し|概要|所感)[:：]\s*', '', res_text).strip()
        lines = [l.strip() for l in clean_text.split('\n') if l.strip()]
        
        start_sec = 0
        first_line_match = re.search(r"(\d+)", lines[0]) if lines else None
        if first_line_match:
            start_sec = int(first_line_match.group(1))
            ai_caption = "\n".join(lines[1:])
        else:
            ai_caption = "\n".join(lines)
            
        print(f"  ✨ AI解析成功: 開始 {start_sec}s")
        return start_sec, ai_caption
    except: return 0, None

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats(); history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    print(f"⚾️ 探索開始...")
    npb_list = get_npb_video(history)
    video_data = npb_list[0] if npb_list else get_mlb_video(history, is_test_mode)

    if video_data:
        print(f"🎯 ターゲット確定: {video_data['title']}")
        temp_input = "temp_video.mp4"
        
        # 二段構えダウンロード
        cmd = ['yt-dlp', '-o', temp_input, '--no-check-certificates', '--quiet', video_data['url']]
        res = subprocess.run(cmd)
        if res.returncode != 0 or not os.path.exists(temp_input) or os.path.getsize(temp_input) < 10000:
            print(f"  ⚠️ yt-dlp失敗。curlでリトライ...")
            subprocess.run(['curl', '-L', video_data['url'], '-o', temp_input])

        if not os.path.exists(temp_input) or os.path.getsize(temp_input) < 10000:
            print("❌ ダウンロード全ルート失敗。"); return

        start_sec, ai_caption = analyze_video_with_ai(temp_input, video_data['title'], video_data['source'])
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
                                print(f"🏁 投稿完了！")
                                with open(history_file, 'a') as fh: fh.write(video_data['id'] + "\n")
                                stats[video_data['type']] += 1; save_stats(stats); return
        except Exception as e: print(f"  ❌ エラー: {e}")
    else: print("😴 投稿対象なし。")

if __name__ == "__main__":
    main()
