import requests
import datetime
import os
import time
import subprocess
import google.generativeai as genai

# GitHub Secrets
INSTA_ID = os.getenv('INSTA_BUSINESS_ID')
ACCESS_TOKEN = os.getenv('INSTA_ACCESS_TOKEN')
GEMINI_KEY = os.getenv('GEMINI_API_KEY')

genai.configure(api_key=GEMINI_API_KEY)

def get_mlb_video():
    """MLB公式から最新動画を取得"""
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    url = f"https://statsapi.mlb.com/api/v1/schedule/games/?sportId=1&startDate={today}&endDate={today}"
    try:
        response = requests.get(url).json()
        if not response['dates']: return None
        game_pk = response['dates'][0]['games'][0]['gamePk']
        content_url = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/content"
        content_data = requests.get(content_url).json()
        item = content_data['highlights']['highlights']['items'][0]
        video_url = next(p['url'] for p in item['playbacks'] if p['name'] == 'mp4Avc')
        return {"title": item['headline'], "desc": item.get('description', ''), "url": video_url}
    except: return None

def process_video_simple(input_url):
    """
    1. 動画を105%ズーム
    2. 9:16の垂直キャンバス(黒)に配置
    """
    print("🎬 動画加工（105%ズーム＆縦長化）を開始...")
    input_file = "input.mp4"
    output_file = "output.mp4"
    
    # 動画をダウンロード
    subprocess.run(['curl', '-L', input_url, '-o', input_file])

    # ffmpegでズームとキャンバス作成
    # scale=iw*1.05:-1 : 105%ズーム
    # pad=1080:1920 : 1080x1920の黒背景の中央に配置
    filter_complex = "scale=iw*1.05:-1,pad=1080:1920:(1080-iw)/2:(1920-ih)/2:color=black"

    cmd = [
        'ffmpeg', '-i', input_file,
        '-vf', filter_complex,
        '-c:a', 'copy', '-y', output_file
    ]
    
    subprocess.run(cmd)
    return output_file

def upload_to_catbox(file_path):
    """加工済み動画を一時URL化"""
    print("☁️ 外部サーバーへアップロード中...")
    with open(file_path, 'rb') as f:
        res = requests.post('https://catbox.moe/user/api.php', 
                            data={'reqtype': 'fileupload'}, 
                            files={'fileToUpload': f})
    return res.text

def generate_caption(title, desc):
    """GeminiでYouTubeまとめ動画風キャプションを生成"""
    model = genai.GenerativeModel("gemini-1.5-flash")
    prompt = f"""
    あなたは野球まとめ動画の制作管理人です。ニュース：「{title}」「{desc}」
    
    【構成ルール】
    1. 見出し：【朗報】や【悲報】から始まるインパクト重視の30字以内。
    2. 概要：要約ではなく「〜だ」調の語り口調で2行。
    3. 所感：アナリスト視点の熱い語り。
    
    【掟】
    ・「ですます」禁止。「だ、である」調にせよ。
    ・全登場人物を#タグ化。合計25個以上のタグ。
    出力はInstagramのキャプション本文のみ。挨拶不要。
    """
    try:
        return model.generate_content(prompt).text.strip()
    except:
        return f"【衝撃】MLB最新速報！\n\n注目のプレーが登場。詳細はプロフィールから。\n#MLB #プロ野球"

def post_reels(video_url, caption):
    """Instagramへリール投稿"""
    base_url = f"https://graph.facebook.com/v21.0/{INSTA_ID}/media"
    payload = {'media_type': 'REELS', 'video_url': video_url, 'caption': caption, 'access_token': ACCESS_TOKEN}
    res = requests.post(base_url, data=payload).json()
    
    if 'id' not in res:
        print(f"❌ 投稿予約失敗: {res}")
        return
    
    creation_id = res['id']
    print(f"⏳ Instagram側の処理を待機中 (ID: {creation_id})...")
    
    status_url = f"https://graph.facebook.com/v21.0/{creation_id}"
    for _ in range(15): # 最大5分待機
        time.sleep(20)
        status = requests.get(status_url, params={'fields': 'status_code', 'access_token': ACCESS_TOKEN}).json()
        print(f"   現在の状態: {status.get('status_code')}")
        if status.get('status_code') == 'FINISHED':
            break
        elif status.get('status_code') == 'ERROR':
            print("❌ Instagram側で動画処理エラーが発生しました。")
            return
    
    publish_url = f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish"
    return requests.post(publish_url, data={'creation_id': creation_id, 'access_token': ACCESS_TOKEN}).json()

def main():
    history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read()

    print("⚾️ プレイボール速報・動画スキャン開始...")
    video_data = get_mlb_video()
    
    if video_data and video_data['url'] not in history:
        print(f"🚀 新着動画: {video_data['title']}")
        
        # 1. ズーム加工
        processed_file = process_video_simple(video_data['url'])
        
        # 2. 一時URL発行
        public_url = upload_to_catbox(processed_file)
        print(f"🔗 公開URL: {public_url}")
        
        # 3. AIキャプション
        caption = generate_caption(video_data['title'], video_data['desc'])
        
        # 4. Instagram投稿
        result = post_reels(public_url, caption)
        print(f"🏁 最終結果: {result}")
        
        # 履歴保存
        with open(history_file, 'a') as f: f.write(video_data['url'] + "\n")
    else:
        print("😴 新着動画はありません。")

if __name__ == "__main__":
    main()
