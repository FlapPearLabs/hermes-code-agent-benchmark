#!/usr/bin/env python3
import asyncio
import sys
import os
import yaml
from pathlib import Path

# Add hermes-agent root to sys.path
sys.path.insert(0, "/Users/songshiyao/.hermes/hermes-agent")

def load_hermes_env():
    env_path = Path("/Users/songshiyao/.hermes/.env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

async def send_notice(text: str):
    try:
        load_hermes_env()
        from gateway.platforms.weixin import send_weixin_direct
        config_path = Path("/Users/songshiyao/.hermes/config.yaml")
        with open(config_path) as f:
            cfg = yaml.safe_load(f)

        wx_cfg = cfg.get("platforms", {}).get("weixin", {})
        extra = wx_cfg.get("extra", {}) or {}
        if "account_id" not in extra and "WEIXIN_ACCOUNT_ID" in os.environ:
            extra["account_id"] = os.environ["WEIXIN_ACCOUNT_ID"]
        token = wx_cfg.get("token") or os.environ.get("WEIXIN_TOKEN")
        recipient = "o9cq800TF2Ep4kl3pnw2cpbbLVds@im.wechat"

        res = await send_weixin_direct(
            extra=extra,
            token=token,
            chat_id=recipient,
            message=text
        )
        print("Direct send result:", res)
        return res
    except Exception as e:
        print(f"Failed to send wechat notice: {e}", file=sys.stderr)
        return None

if __name__ == "__main__":
    msg = sys.argv[1] if len(sys.argv) > 1 else "Hermes Benchmark 通知测试"
    asyncio.run(send_notice(msg))
