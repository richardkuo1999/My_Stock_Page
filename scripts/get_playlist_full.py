import sys
import os

# 將 yt-dlp 套件所在的目錄加入系統路徑，這樣腳本就能自動找到它
current_dir = os.path.dirname(os.path.abspath(__file__))
lib_path = os.path.join(current_dir, 'lib')
sys.path.insert(0, lib_path)

try:
    import yt_dlp
except ImportError:
    print("❌ 錯誤：找不到 yt-dlp 模組，系統可能尚未完成安裝或下載失敗。")
    sys.exit(1)

def extract_playlist_urls(url):
    ydl_opts = {
        'extract_flat': True,       # 只提取清單資訊，不下載影片
        'quiet': True,              # 不顯示多餘的下載日誌
        'ignoreerrors': True,       # 如果某個影片失效，忽略它並繼續
    }
    
    print(f"⏳ 正在深入解析播放清單 (這可以突破 100 首的限制，請稍候): {url} ...")
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            if 'entries' in info:
                entries = list(info['entries']) # 將迭代器轉為列表
                print("-" * 50)
                count = 0
                for entry in entries:
                    if entry and entry.get('url'):
                        count += 1
                        print(f"{count}. {entry['url']}")
                print("-" * 50)
                print(f"✅ 成功！總共擷取了 {count} 部影片。")
            else:
                print("❌ 找不到播放清單的項目，這可能不是一個有效的播放清單網址。")
        except Exception as e:
            print(f"❌ 發生錯誤: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("❌ 錯誤：請提供 YouTube 播放清單網址！")
        print(f"💡 使用方法: python3 {sys.argv[0]} <youtube_playlist_url>")
        sys.exit(1)
        
    playlist_url = sys.argv[1]
    extract_playlist_urls(playlist_url)
