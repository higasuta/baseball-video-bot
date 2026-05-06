def get_npb_video(history):
    """スポーツナビ(Yahoo)を全力でスキャン"""
    # ターゲットURL
    url = "https://sports.yahoo.co.jp/video/list/promo/live/baseball/npb"
    print(f"🔍 スポーツナビをスキャン中: {url}")
    
    try:
        # 日本のユーザーになりすますための追加引数
        cmd = [
            'yt-dlp', 
            '--get-id', '--get-title', '--get-url', 
            '--playlist-end', '5',
            '--geo-bypass', # 検閲回避の試み
            '--add-header', 'Accept-Language:ja,en-US;q=0.9,en;q=0.8',
            '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            url
        ]
        # タイムアウトを設定してフリーズを防止
        process = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
        
        if process.returncode != 0:
            print(f"  ⚠️ スポナビが応答しません（海外IPブロックの可能性があります）: {process.stderr[:100]}")
            return None

        output = process.stdout.split('\n')
        lines = [l for l in output if l.strip()]
        print(f"  👉 取得成功！ {len(lines)//3}件の動画が見えます。")

        for i in range(0, len(lines)-2, 3):
            title, v_id, v_url = lines[i], lines[i+1], lines[i+2]
            if v_id not in history:
                print(f"✅ スポナビで未投稿動画を発見: {title}")
                return {"title": title, "url": v_url, "id": v_id, "type": "npb", "source": "スポーツナビ"}
    except Exception as e:
        print(f"  ❌ スポナビ取得中にエラー: {e}")
    
    return None
