#!/usr/bin/env python3
"""
Instagram Stories Fetcher (Minimalist & Anti-Addiction)
- Uses extracted browser cookies to bypass password-based login risk
- Uses curl_cffi to match real Chrome TLS/JA3 fingerprints
- Purely read-only; does not like, comment, or follow
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path
from curl_cffi import requests

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
DOWNLOADS_DIR = BASE_DIR / "downloads"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "X-IG-App-ID": "936619743392459",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://www.instagram.com/",
    "Accept": "*/*",
}

def load_config():
    if not CONFIG_FILE.exists():
        print("❌ 找不到 config.json 設定檔！")
        print("\n👉 請按照以下步驟建立：")
        print("1. 複製範本檔：")
        print("   cp config.example.json config.json")
        print("2. 打開 Chrome / Firefox 瀏覽器，登入 Instagram 網頁版。")
        print("3. 按下 F12 開啟開發者工具 -> 點擊 Application (應用程式) -> Cookies -> https://www.instagram.com")
        print("4. 複製以下三個值並填入 config.json：")
        print("   - sessionid")
        print("   - ds_user_id")
        print("   - csrftoken")
        sys.exit(1)

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    if (
        config.get("sessionid") == "請替換為你的_sessionid"
        or not config.get("sessionid")
    ):
        print("❌ 請先在 config.json 填入有效的 sessionid Cookie！")
        sys.exit(1)

    return config

def create_session(config):
    cookies = {
        "sessionid": config["sessionid"],
        "ds_user_id": config.get("ds_user_id", ""),
        "csrftoken": config.get("csrftoken", ""),
    }
    # 使用 chrome124 模擬現代 Chrome 瀏覽器的 TLS 指紋
    session = requests.Session(impersonate="chrome124")
    session.cookies.update(cookies)
    session.headers.update(HEADERS)
    return session

def fetch_reels_tray(session):
    url = "https://www.instagram.com/api/v1/feed/reels_tray/"
    print("📡 正在向 Instagram 請求限時動態清單 (reels_tray)...")
    res = session.get(url, timeout=15)

    if res.status_code == 401 or res.status_code == 403:
        print(f"❌ 授權失敗 (HTTP {res.status_code})：Session Cookie 可能已過期，請重新從瀏覽器複製最新的 Cookie。")
        sys.exit(1)
    elif res.status_code != 200:
        print(f"❌ 請求失敗 (HTTP {res.status_code}): {res.text[:300]}")
        sys.exit(1)

    try:
        data = res.json()
        return data.get("tray", [])
    except Exception as e:
        print(f"❌ 解析 JSON 失敗: {e}")
        print(res.text[:300])
        sys.exit(1)

def fetch_user_reels_media(session, user_id):
    """如果 tray 裡沒有直接給予 items，呼叫 reels_media 補抓"""
    url = f"https://www.instagram.com/api/v1/feed/reels_media/?user_ids={user_id}"
    res = session.get(url, timeout=15)
    if res.status_code == 200:
        data = res.json()
        reels = data.get("reels", {})
        user_reel = reels.get(str(user_id), {})
        return user_reel.get("items", [])
    return []

def download_file(session, url, target_path):
    if target_path.exists():
        return
    res = session.get(url, timeout=30)
    if res.status_code == 200:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "wb") as f:
            f.write(res.content)

def parse_media_items(items):
    results = []
    for m in items:
        media_id = m.get("id")
        taken_at = m.get("taken_at", 0)
        formatted_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(taken_at))
        is_video = m.get("media_type") == 2

        if is_video:
            versions = m.get("video_versions", [])
            media_url = versions[0]["url"] if versions else None
            ext = "mp4"
        else:
            candidates = m.get("image_versions2", {}).get("candidates", [])
            media_url = candidates[0]["url"] if candidates else None
            ext = "jpg"

        results.append({
            "id": media_id,
            "taken_at": formatted_time,
            "timestamp": taken_at,
            "is_video": is_video,
            "url": media_url,
            "ext": ext
        })
    return results

def main():
    parser = argparse.ArgumentParser(description="Instagram Stories CLI - 防成癮限時動態提取器")
    parser.add_argument("--download", action="store_true", help="自動下載限時動態圖片/影片至本機 downloads/ 目錄")
    parser.add_argument("--user", type=str, help="只查看或下載指定使用者帳號 (username)")
    parser.add_argument("--limit", type=int, default=30, help="最多獲取幾位好友的限動 (預設 30)")
    args = parser.parse_args()

    config = load_config()
    session = create_session(config)

    tray = fetch_reels_tray(session)
    if not tray:
        print("📭 目前你的好友動態中沒有任何未過期的限時動態。")
        return

    print(f"✨ 成功讀取！目前有 {len(tray)} 位好友有發布限時動態。\n")

    count = 0
    for item in tray:
        user = item.get("user", {})
        username = user.get("username", "unknown")
        user_id = user.get("pk")
        full_name = user.get("full_name", "")

        # 如果指定了 user 篩選
        if args.user and args.user.lower() != username.lower():
            continue

        raw_items = item.get("items", [])
        if not raw_items and user_id:
            # 有些帳號需要額外查詢 reels_media
            time.sleep(0.5)  # 禮貌延遲
            raw_items = fetch_user_reels_media(session, user_id)

        parsed_stories = parse_media_items(raw_items)
        if not parsed_stories:
            continue

        count += 1
        name_display = f"{username} ({full_name})" if full_name else username
        print(f"┌─ 👤 {name_display} [{len(parsed_stories)} 則限動]")

        for idx, story in enumerate(parsed_stories, 1):
            media_type = "🎬 [影片]" if story["is_video"] else "🖼️  [圖片]"
            print(f"│  ├─ {idx}. {media_type} 發布時間: {story['taken_at']}")

            if args.download and story["url"]:
                save_filename = f"{story['timestamp']}_{story['id'].split('_')[0]}.{story['ext']}"
                save_path = DOWNLOADS_DIR / username / save_filename
                try:
                    download_file(session, story["url"], save_path)
                    print(f"│  │  └─ 💾 已下載: downloads/{username}/{save_filename}")
                except Exception as err:
                    print(f"│  │  └─ ⚠️ 下載失敗: {err}")

        print("└────────────────────────────────────────")

        if count >= args.limit:
            break

    print(f"\n🎉 處理完成！共檢視了 {count} 位使用者的限動。")
    if not args.download:
        print("💡 提示：加上 `--download` 參數可直接將限動照片/影片下載到本機檢視（免開 IG）。")

if __name__ == "__main__":
    main()
