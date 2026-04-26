import requests
import datetime
import os

# GitHubの「隠し金庫」からキーを読み込む設定
INSTA_ID = os.getenv('INSTA_BUSINESS_ID')
ACCESS_TOKEN = os.getenv('INSTA_ACCESS_TOKEN')

def get_mlb_video():
    """MLB公式APIから今日のハイライト動画URLを探す関数"""
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    # MLB公式のデータエンドポイント（今日行われた試合のデータ）
    url = f"https://statsapi.mlb.com/api/v1/schedule/games/?sportId=1&startDate={today}&endDate={today}"
    
    try:
        response = requests.get(url).json()
        # 最初の試合の「動画まとめID(contentId)」を探す
        game = response['dates'][0]['games'][0]
        game_pk = game['gamePk']
        
        # 試合のコンテンツ（動画）の詳細を取得
        content_url = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/content"
        content_data = requests.get(content_url).json()
        
        # ハイライト動画の中からMP4のURLを抽出
        highlights = content_data['highlights']['highlights']['items']
        for item in highlights:
            for playback in item['playbacks']:
                if playback['name'] == 'mp4Avc': # 高画質なMP4を選択
                    return playback['url']
    except Exception as e:
        print(f"動画取得エラー: {e}")
    return None

def main():
    print("⚾️ MLB動画スキャン開始...")
    video_url = get_mlb_video()
    if video_url:
        print(f"✅ 動画を発見しました: {video_url}")
        # ここにInstagramへの投稿処理やMoviePyの編集処理を書き足していきます
    else:
        print("😴 まだ新しい動画がアップロードされていません。")

if __name__ == "__main__":
    main()
