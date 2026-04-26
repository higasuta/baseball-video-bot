import requests
import datetime
import os
import time
import google.generativeai as genai

# GitHub Secretsから環境変数を取得
INSTA_ID = os.getenv('INSTA_BUSINESS_ID')
ACCESS_TOKEN = os.getenv('INSTA_ACCESS_TOKEN')
GEMINI_KEY = os.getenv('GEMINI_API_KEY')

# Geminiの設定
genai.configure(api_key=GEMINI_KEY)

def get_mlb_video():
    """MLB公式APIから最新の動画情報を取得"""
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    url = f"https://statsapi.mlb.com/api/v1/schedule/games/?sportId=1&startDate={today}&endDate={today}"
    try:
        response = requests.get(url).json()
        if not response['dates']: return None
        game = response['dates'][0]['games'][0]
        game_pk = game['gamePk']
        
        content_url = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/content"
        content_data = requests.get(content_url).json()
        
        # 最新のハイライトを取得
        item = content_data['highlights']['highlights']['items'][0]
        title = item['headline']
        desc = item.get('description', '')
        video_url = next(p['url'] for p in item['playbacks'] if p['name'] == 'mp4Avc')
        
        return {"title": title, "desc": desc, "url": video_url}
    except:
        return None

def generate_caption(title, desc):
    """Gemini 1.5 FlashでYouTubeまとめ風キャプションを生成"""
    model = genai.GenerativeModel("gemini-1.5-flash")
    prompt = f"""
    あなたはプロ野球・MLB専門のSNS編集長です。
    ニュース：{title} / {desc}
    
    【ルール】
    1. 標準語の語り口調（〜だ、〜である）で、YouTubeの2chまとめ動画風の3段構成にする。
    2. 見出しは20-30字で【朗報】や【驚愕】から始める。
    3. 全登場人物を#ハッシュタグにする（中黒・は削除）。
    4. 合計25個以上のタグを付ける。
    
    出力はInstagramのキャプション本文のみ。
    """
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except:
        return f"【速報】{title}\n\n注目のプレーが登場！詳細はプロフィールから。\n#MLB #野球"

def post_reels(video_url, caption):
    """Instagram Graph APIでリールを投稿"""
    # 1. 投稿の初期化（動画のアップロード予約）
    base_url = f"https://graph.facebook.com/v21.0/{INSTA_ID}/media"
    payload = {
        'media_type': 'REELS',
        'video_url': video_url,
        'caption': caption,
        'access_token': ACCESS_TOKEN
    }
    res = requests.post(base_url, data=payload).json()
    if 'id' not in res:
        print(f"❌ 初期化失敗: {res}")
        return
    
    creation_id = res['id']
    print(f"⏳ 動画処理中 (ID: {creation_id})...")
    
    # 2. 処理完了を待機（リールは時間がかかるため最大2分待つ）
    status_url = f"https://graph.facebook.com/v21.0/{creation_id}"
    params = {'fields': 'status_code', 'access_token': ACCESS_TOKEN}
    
    for _ in range(12): # 10秒おきに12回確認
        time.sleep(10)
        status = requests.get(status_url, params=params).json()
        print(f"   現在のステータス: {status.get('status_code')}")
        if status.get('status_code') == 'FINISHED':
            break
    
    # 3. 公開（パブリッシュ）
    publish_url = f"https://graph.facebook.com/v21.0/{INSTA_ID}/media_publish"
    publish_res = requests.post(publish_url, data={
        'creation_id': creation_id,
        'access_token': ACCESS_TOKEN
    }).json()
    return publish_res

def main():
    # 履歴チェック
    history_file = "history.txt"
    if not os.path.exists(history_file): open(history_file, 'w').close()
    with open(history_file, 'r') as f: history = f.read()

    print("⚾️ MLB最新動画スキャン開始...")
    video_data = get_mlb_video()
    
    if video_data and video_data['url'] not in history:
        print(f"🚀 新着動画を検知: {video_data['title']}")
        
        # キャプション生成
        caption = generate_caption(video_data['title'], video_data['desc'])
        
        # Instagram投稿
        result = post_reels(video_data['url'], caption)
        print(f"🏁 投稿完了: {result}")
        
        # 履歴を更新（このファイルはActionsの実行が終わると消えますが、
        # 後でGitHubに自動保存させる設定を追加します）
        with open(history_file, 'a') as f: f.write(video_data['url'] + "\n")
    else:
        print("😴 新着動画はありません。")

if __name__ == "__main__":
    main()
