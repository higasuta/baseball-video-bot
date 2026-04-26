import requests
import datetime
import os
import time
import subprocess
import google.generativeai as genai
import json
import re

# ==========================================
# 【設定済み】各種キーとID
# ==========================================
INSTA_ID = '17841436151352537'
ACCESS_TOKEN = 'EAAN3eJp86t0BRFY4Eu9qiDAFwZCLAAVSP2bgSOmzKEKBZBF1namAjdGXVxlFDV5HAiPS5v2CNCq7L5dlLZCheYmvkBNyEWSsZBLZAk85ZAikHj1GG6hSsnJSY6b4pOUwV50vQOhn87dOastLOL2ZAqcl3RgzpSKWsV3ZB674cRb1XagsmdGlBzyzUnbWPK1lPCyr'
GEMINI_KEY = 'AIzaSyDx6Tly31o6xB_CoLlnVhHpPbvL0EloRY0'

genai.configure(api_key=GEMINI_KEY)

JPN_MLB_KEYWORDS = ["ohtani", "yamamoto", "imanaga", "darvish", "suzuki", "yoshida", "senga", "matsui", "maeda", "kikuchi"]
HOT_KEYWORDS = ["home run", "hr", "grand slam", "history", "record", "historic", "milestone", "walk-off"]

def get_stats():
    if os.path.exists('stats.json'):
        try:
            with open('stats.json', 'r') as f: return json.load(f)
        except: pass
    return {"npb": 7, "mlb": 3}

def save_stats(stats):
    with open('stats.json', 'w') as f: json.dump(stats, f)

def get_npb_video(history, is_test_mode):
    sources = ["https://www.youtube.com/@NPB.official/videos", "https://x.com/npb"]
    duration_limit = 600 if is_test_mode else 180
    for src in sources:
        try:
            cmd = ['yt-dlp', '--get-id', '--get-title', '--get-url', '--match-filter', f'duration < {duration_limit}', '--max-downloads', '1', src]
            output = subprocess.check_output(cmd).decode().split('\n')
            if len(output) >= 3:
                video_id = output[1]
                if is_test_mode or video_id not in history:
                    return {"title": output[0], "desc": "NPB公式動画", "url": output[2], "id": video_id, "type": "npb", "is_hot": False}
        except: continue
    return None

def get_mlb_video(history, is_test_mode):
    dates_to_check = [datetime.datetime.now().strftime('%Y-%m-%d'), (datetime.datetime.now() - datetime.timedelta(days=1)).strftime('%Y-%m-%d')]
    for date_str in dates_to_check:
        url = f"https://statsapi.mlb.com/api/v1/schedule/games/?sportId=1&startDate={date_str}&endDate={date_str}"
        try:
            response = requests.get(url).json()
            if 'dates' not in response or not response['dates']: continue
            for game in response['dates'][0]['games']:
                content_url = f"https://statsapi.mlb.com/api/v1/game/{game['gamePk']}/content"
                content_data = requests.get(content_url).json()
                if 'highlights' not in content_data['highlights']: continue
                items = content_data['highlights']['highlights']['items']
                for item in items:
                    title = item.get('headline', '')
                    desc = item.get('description', '')
                    video_url = next((p['url'] for p in item['playbacks'] if p['name'] == 'mp4Avc'), None)
                    if not video_url: continue
                    is_jpn = any(name in title.lower() or name in desc.lower() for name in JPN_MLB_KEYWORDS)
                    if is_jpn or (is_test_mode and item['id'] not in history):
                        is_hot = any(kw in title.lower() or kw in desc.lower() for kw in HOT_KEYWORDS)
                        return {"title": title, "desc": desc, "url": video_url, "id": item['id'], "type": "mlb", "is_hot": is_hot}
        except: continue
    return None

def process_video_v5(input_url):
    input_file = "input.mp4"
    output_file = "output.mp4"
    subprocess.run(['curl', '-L', input_url, '-o', input_file])
    filter_complex = "scale=1134:-2,crop=1080:ih,pad=1080:1920:0:(1920-ih)/2:color=black,setsar=1"
    cmd = ['ffmpeg', '-i', input_file, '-vf', filter_complex, '-r', '30', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'fast', '-crf', '23', '-c:a', 'aac', '-b:a', '128k', '-y', output_file]
    subprocess.run(cmd)
    return output_file

def upload_video(file_path):
    try:
        with open(file_path, 'rb') as f:
            res = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f})
            if res.status_code == 200:
                return res.json()['data']['url'].replace('https://tmpfiles.org/', 'https://tmpfiles.org/dl/')
    except: return None

def generate_caption(title, desc):
    """【こだわり全抽出】YouTubeまとめ動画風キャプション生成"""
    try:
        # 最新の 2.0-flash を使用
        model = genai.GenerativeModel("gemini-2.0-flash")
        prompt = f"""
        あなたはプロ野球・MLB専門SNS「プレイボール速報」の管理人です。
        以下のニュースを元に、フォロワーを惹きつけるInstagram投稿を作成してください。

        【ニュース】: {title} / {desc}

        【絶対に守るべきルール】
        1. 構成：以下の3段構成にすること。
           ・一段目：【朗報】【悲報】【驚愕】等から始まる、インパクトある20-30文字の見出し。
           ・二段目：ニュースの核心を2-3行で簡潔にまとめる。
           ・三段目：専門家・ファンの視点からの熱い所感。
        2. 文体：標準語の語り口調（〜だ、〜である、〜だろう）を徹底。敬語（ですます）禁止。
        3. ラベル：項目名（見出し、概要、所感など）は一切出力しない。
        4. ハッシュタグ：記事内の全人物名、全チーム名を個別にハッシュタグに。タグ内のドット（・）は削除して詰めろ。
        5. タグ量：野球関連タグ含め、合計28個程度の大量のハッシュタグを並べろ。
        
        文章のみ出力してください。
        """
        response = model.generate_content(prompt)
        caption = response.text.strip()
        
        # 万が一のドット削除（念押し）
        caption = caption.replace("・", "")
        return caption
    except Exception as e:
        print(f"AIエラー: {e}")
        return f"【衝撃】{title}\n\n注目のニュースが入った。今後の活躍から目が離せない。\n#プロ野球 #MLB #野球ファン #野球好きな人と繋がりたい"

def post_reels(video_url, caption):
    base_url = f"https://graph.facebook.com/v21.0/{INSTA_ID}/media"
    res = requests.post(base_url, data={'media_type': 'REELS', 'video_url': video_url, 'caption': caption, 'access_token': ACCESS_TOKEN}).json()
    if 'id' not in res: return None
    creation_id = res['id']
    status_url = f"https://graph.facebook.com/v21.0/{creation_id}"
    for _ in range(30):
        time.sleep(20)
        status = requests.get(status_url, params={'fields': 'status_code', 'access_token': ACCESS_TOKEN}).json()
        if status.get('status_code') == 'FINISHED': break
        elif status.get('status_code') == 'ERROR': return None
    publish_url = f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish"
    return requests.post(publish_url, data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN}).json()

def main():
    is_test_mode = os.getenv('TEST_MODE') == 'true'
    stats = get_stats()
    history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read().splitlines()

    # 1. NPBスキャン
    video_data = get_npb_video(history, is_test_mode)
    
    # 2. なければMLBスキャン
    if not video_data:
        mlb_item = get_mlb_video(history, is_test_mode)
        if mlb_item:
            total = stats['npb'] + stats['mlb']
            ratio = stats['mlb'] / total if total > 0 else 0
            if is_test_mode or mlb_item['is_hot'] or ratio < 0.3:
                video_data = mlb_item

    if video_data:
        processed_file = process_video_v5(video_data['url'])
        public_url = upload_video(processed_file)
        if public_url:
            caption = generate_caption(video_data['title'], video_data['desc'])
            result = post_reels(public_url, caption)
            if result and 'id' in result:
                print(f"🏁 投稿成功！ ID: {result['id']}")
                if not is_test_mode:
                    with open(history_file, 'a') as f: f.write(video_data['id'] + "\n")
                    stats[video_data['type']] += 1
                    save_stats(stats)
    else: print("😴 新着なし")

if __name__ == "__main__":
    main()
