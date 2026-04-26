import requests
import datetime
import os
import time
import subprocess
import google.generativeai as genai
import json

# ==========================================
# 【設定済み】各種キーとID
# ==========================================
INSTA_ID = '17841436151352537'
ACCESS_TOKEN = 'EAAN3eJp86t0BRFY4Eu9qiDAFwZCLAAVSP2bgSOmzKEKBZBF1namAjdGXVxlFDV5HAiPS5v2CNCq7L5dlLZCheYmvkBNyEWSsZBLZAk85ZAikHj1GG6hSsnJSY6b4pOUwV50vQOhn87dOastLOL2ZAqcl3RgzpSKWsV3ZB674cRb1XagsmdGlBzyzUnbWPK1lPCyr'
GEMINI_KEY = 'AIzaSyDx6Tly31o6xB_CoLlnVhHpPbvL0EloRY0'

genai.configure(api_key=GEMINI_KEY)

# 日本人メジャーリーガー判定用キーワード（英語）
JPN_MLB_KEYWORDS = ["Ohtani", "Yamamoto", "Imanaga", "Darvish", "Suzuki", "Yoshida", "Senga", "Matsui", "Maeda", "Kikuchi"]
# ★最優先で投稿すべき「大ニュース」キーワード（本塁打・記録達成など）
HOT_KEYWORDS = ["Home Run", "HR", "Grand Slam", "History", "Record", "Historic", "Milestone", "Walk-off"]

def get_stats():
    if os.path.exists('stats.json'):
        with open('stats.json', 'r') as f: return json.load(f)
    return {"npb": 7, "mlb": 3}

def save_stats(stats):
    with open('stats.json', 'w') as f: json.dump(stats, f)

def get_npb_video(history):
    """【最優先】NPB公式YouTube/Xから最新動画を取得"""
    sources = ["https://www.youtube.com/@NPB.official/videos", "https://x.com/npb"]
    for src in sources:
        print(f"🔍 NPBスキャン中: {src}")
        try:
            # 最新の2分以内の動画を取得
            cmd = ['yt-dlp', '--get-id', '--get-title', '--get-url', '--match-filter', 'duration < 120', '--max-downloads', '1', src]
            output = subprocess.check_output(cmd).decode().split('\n')
            if len(output) >= 3:
                video_id = output[1]
                if video_id not in history:
                    return {"title": output[0], "desc": "NPB公式最新動画", "url": output[2], "id": video_id, "type": "npb", "is_hot": False}
        except: continue
    return None

def get_mlb_video(history):
    """【二番手】MLB公式APIから日本人選手を探す（大ニュースはフラグを立てる）"""
    print("🔍 MLB日本人選手スキャン中...")
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    url = f"https://statsapi.mlb.com/api/v1/schedule/games/?sportId=1&startDate={today}&endDate={today}"
    try:
        response = requests.get(url).json()
        if not response.get('dates'): return None
        for game in response['dates'][0]['games']:
            game_pk = game['gamePk']
            content_url = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/content"
            content_data = requests.get(content_url).json()
            if 'highlights' not in content_data['highlights']: continue
            
            for item in content_data['highlights']['highlights']['items']:
                title = item.get('headline', '')
                desc = item.get('description', '')
                
                # 1. 日本人選手かチェック
                if any(name in title for name in JPN_MLB_KEYWORDS):
                    video_url = next((p['url'] for p in item['playbacks'] if p['name'] == 'mp4Avc'), None)
                    if video_url and item['id'] not in history:
                        # 2. 本塁打や大記録（Hot）かチェック
                        is_hot = any(kw in title or kw in desc for kw in HOT_KEYWORDS)
                        return {
                            "title": title, "desc": desc, "url": video_url, 
                            "id": item['id'], "type": "mlb", "is_hot": is_hot
                        }
    except: return None
    return None

def process_video(input_url):
    """105%ズーム ＆ 9:16縦長加工"""
    input_file = "input.mp4"
    output_file = "output.mp4"
    subprocess.run(['curl', '-L', input_url, '-o', input_file])
    filter_complex = "scale=iw*1.05:-1,pad=1080:1920:(1080-iw)/2:(1920-ih)/2:color=black"
    subprocess.run(['ffmpeg', '-i', input_file, '-vf', filter_complex, '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23', '-c:a', 'aac', '-y', output_file])
    return output_file

def upload_to_catbox(file_path):
    with open(file_path, 'rb') as f:
        res = requests.post('https://catbox.moe/user/api.php', data={'reqtype': 'fileupload'}, files={'fileToUpload': f})
    return res.text

def generate_caption(title, desc):
    model = genai.GenerativeModel("gemini-1.5-flash")
    prompt = f"""
    あなたはYouTubeの野球2chまとめ解説動画の管理人です。
    ニュース：『{title}』
    詳細内容：『{desc}』
    
    【絶対に守るルール】
    1. 標準語の語り口調（〜だ、〜である、〜だろう）で3段構成にする。
    2. 見出しは20-30文字で【朗報】や【驚愕】から始める。ラベル名は書かない。
    3. 解説はコピペせず自分の言葉で。
    4. 登場人物を全員#ハッシュタグ化（中黒・は消して詰める）。
    5. 合計25個以上の大量のタグ。
    出力はInstagramキャプション本文のみ。
    """
    try:
        return model.generate_content(prompt).text.strip()
    except: return f"【速報】{title}\n#プロ野球 #MLB"

def post_reels(video_url, caption):
    base_url = f"https://graph.facebook.com/v21.0/{INSTA_ID}/media"
    res = requests.post(base_url, data={'media_type': 'REELS', 'video_url': video_url, 'caption': caption, 'access_token': ACCESS_TOKEN}).json()
    if 'id' not in res: return None
    creation_id = res['id']
    print(f"⏳ 動画処理中 (ID: {creation_id})...")
    time.sleep(60) 
    publish_url = f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish"
    return requests.post(publish_url, data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN}).json()

def main():
    stats = get_stats()
    history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    video_data = None
    
    # 手順1: NPB(最優先)をスキャン
    video_data = get_npb_video(history)
    
    # 手順2: NPBがない場合、MLBをスキャン
    if not video_data:
        mlb_item = get_mlb_video(history)
        if mlb_item:
            total = stats['npb'] + stats['mlb']
            ratio = stats['mlb'] / total if total > 0 else 0
            
            # 特例ルール：ホームラン等の「Hot」ニュースなら比率を無視
            if mlb_item['is_hot']:
                print(f"🔥 MLB日本人選手の特大ニュース(HomeRun等)を検知！比率を無視して投稿します。")
                video_data = mlb_item
            # 通常のMLBニュースなら比率(30%)をチェック
            elif ratio < 0.3:
                video_data = mlb_item
            else:
                print(f"📊 比率調整：MLB(通常)は30%を超えているため、NPBの更新を待ちます。")

    if video_data:
        print(f"🚀 投稿決定: {video_data['title']}")
        processed_file = process_video(video_data['url'])
        public_url = upload_to_catbox(processed_file)
        caption = generate_caption(video_data['title'], video_data['desc'])
        result = post_reels(public_url, caption)
        
        if result and 'id' in result:
            print(f"🏁 投稿完了: {result}")
            with open(history_file, 'a') as f: f.write(video_data['id'] + "\n")
            stats[video_data['type']] += 1
            save_stats(stats)
        else: print(f"❌ 投稿失敗: {result}")
    else:
        print("😴 新着の対象動画はありません。")

if __name__ == "__main__":
    main()
