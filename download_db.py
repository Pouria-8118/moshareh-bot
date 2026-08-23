
import os
import requests
import sys

DB_URL = os.getenv(
    "DB_URL",
    "https://github.com/YOUR_USERNAME/moshareh-bot/releases/download/v1.0/bot_couplets.s3db"
)

DB_PATH = "bot_couplets.s3db"

def download_database():
    if os.path.exists(DB_PATH):
        size = os.path.getsize(DB_PATH)
        print(f"✅ Database already exists ({size / (1024*1024):.1f} MB)")
        return True

    print(f"📥 Downloading database from: {DB_URL}")

    try:
        response = requests.get(DB_URL, stream=True, timeout=300)
        response.raise_for_status()

        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0

        with open(DB_PATH, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        print(f"\r📊 Progress: {percent:.1f}%", end='', flush=True)

        print(f"\n✅ Database downloaded successfully ({os.path.getsize(DB_PATH) / (1024*1024):.1f} MB)")
        return True

    except requests.exceptions.RequestException as e:
        print(f"\n❌ Error downloading database: {e}")
        return False

if __name__ == "__main__":
    if not download_database():
        print("❌ Failed to download database. Exiting...")
        sys.exit(1)
    print("✅ Ready to start bot!")