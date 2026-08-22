"""从 cloudflared.log 提取公网 URL，拼上 access token 打印完整分享链接。

用法：uv run python tunnel_url.py
"""
import os
import re


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    log_path = os.path.join(base, "cloudflared.log")
    url = ""
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8", errors="ignore") as f:
            text = f.read()
        m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", text)
        url = m.group(0) if m else ""

    token = ""
    env_path = os.path.join(base, ".env")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("ACCESS_TOKEN="):
                    token = line.split("=", 1)[1].strip()

    if url and token:
        print(f"{url}/?token={token}")
    elif url:
        print(url)
    else:
        print("(no tunnel url found)")


if __name__ == "__main__":
    main()
