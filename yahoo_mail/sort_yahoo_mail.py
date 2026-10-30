#!/usr/bin/env python3
"""Yahoo!メール（Yahoo! JAPAN）の受信箱を自動で振り分けるスクリプト。

使い方:
    python3 sort_yahoo_mail.py            # お試し（何も動かさず、振り分け結果だけ表示）
    python3 sort_yahoo_mail.py --run      # 実際に振り分ける
    python3 sort_yahoo_mail.py --run --delete-old 90
                                          # 振り分け後、メルマガフォルダの90日より古いメールを削除

事前準備:
    Yahoo!メールの「設定 → IMAP/POP/SMTPアクセス」で
    「Yahoo! JAPAN公式サービス以外からのアクセスも有効にする」をオンにする。
"""
import argparse
import base64
import datetime
import email
import email.header
import getpass
import imaplib
import os
import re

HOST = "imap.mail.yahoo.co.jp"

# 上から順に判定し、最初に当たったフォルダへ移動する。
# "subject" は件名、"from" は差出人（名前・アドレス）に含まれる語。
RULES = [
    ("要確認", {
        "subject": ["認証", "確認コード", "ワンタイム", "パスワード", "ログイン", "本人確認", "セキュリティ"],
    }),
    ("買い物", {
        "subject": ["注文", "ご購入", "発送", "出荷", "領収書", "お支払い", "決済", "配達"],
        "from": ["amazon", "rakuten", "mercari", "yodobashi", "zozo"],
    }),
    ("会員登録", {
        "subject": ["登録完了", "会員登録", "ようこそ", "仮登録", "本登録"],
    }),
    ("メルマガ", {
        "subject": ["メールマガジン", "メルマガ", "キャンペーン", "セール", "クーポン", "ポイント", "お知らせ", "限定", "プレゼント"],
        "from": ["newsletter", "magazine", "info@", "news@", "noreply", "no-reply", "mailmag"],
    }),
]

# メルマガ以外でも、本文に「配信停止」系の文言があるものはメルマガ扱いにしたいときはここに足す
JUNK_FOLDER = "メルマガ"


def imap_utf7_encode(s):
    """フォルダ名を IMAP 用の文字コード（modified UTF-7）に変換する。"""
    out, buf = [], []

    def flush():
        if buf:
            b = base64.b64encode("".join(buf).encode("utf-16-be")).decode().rstrip("=")
            out.append("&" + b.replace("/", ",") + "-")
            buf.clear()

    for ch in s:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            buf.append(ch)
    flush()
    return "".join(out)


def decode_header(value):
    if not value:
        return ""
    parts = []
    for text, enc in email.header.decode_header(value):
        if isinstance(text, bytes):
            try:
                parts.append(text.decode(enc or "utf-8", errors="replace"))
            except LookupError:
                parts.append(text.decode("utf-8", errors="replace"))
        else:
            parts.append(text)
    return "".join(parts)


def classify(subject, sender):
    s, f = subject.lower(), sender.lower()
    for folder, cond in RULES:
        if any(k.lower() in s for k in cond.get("subject", [])):
            return folder
        if any(k.lower() in f for k in cond.get("from", [])):
            return folder
    return None


def quote(name):
    return '"' + imap_utf7_encode(name).replace("\\", "\\\\").replace('"', '\\"') + '"'


def main():
    ap = argparse.ArgumentParser(description="Yahoo!メールの自動振り分け")
    ap.add_argument("--run", action="store_true", help="実際に移動する（付けないとお試しのみ）")
    ap.add_argument("--delete-old", type=int, metavar="日数",
                    help=f"「{JUNK_FOLDER}」フォルダの、指定日数より古いメールを削除")
    args = ap.parse_args()

    user = os.environ.get("YAHOO_USER") or input("Yahoo! JAPAN ID またはメールアドレス: ")
    password = os.environ.get("YAHOO_PASS") or getpass.getpass("パスワード: ")

    m = imaplib.IMAP4_SSL(HOST, 993)
    m.login(user, password)
    print("ログインしました")

    if args.run:
        for folder, _ in RULES:
            m.create(quote(folder))  # すでにあれば失敗するだけなので無視

    m.select("INBOX")
    typ, data = m.uid("search", None, "ALL")
    uids = data[0].split()
    print(f"受信箱のメール: {len(uids)} 通")

    plan = {}
    for i in range(0, len(uids), 200):
        chunk = b",".join(uids[i:i + 200])
        typ, resp = m.uid("fetch", chunk, "(UID BODY.PEEK[HEADER.FIELDS (SUBJECT FROM)])")
        for item in resp:
            if not isinstance(item, tuple):
                continue
            uid = re.search(rb"UID (\d+)", item[0]).group(1)
            msg = email.message_from_bytes(item[1])
            folder = classify(decode_header(msg.get("Subject")), decode_header(msg.get("From")))
            if folder:
                plan.setdefault(folder, []).append(uid)

    for folder, _ in RULES:
        print(f"  {folder}: {len(plan.get(folder, []))} 通")
    print(f"  受信箱に残る: {len(uids) - sum(len(v) for v in plan.values())} 通")

    if not args.run:
        print("\nお試しモードなので何も動かしていません。実行するには --run を付けてください。")
        m.logout()
        return

    for folder, ids in plan.items():
        for i in range(0, len(ids), 200):
            chunk = b",".join(ids[i:i + 200])
            typ, _ = m.uid("copy", chunk, quote(folder))
            if typ == "OK":
                m.uid("store", chunk, "+FLAGS", r"(\Deleted)")
    m.expunge()
    print("振り分けが終わりました")

    if args.delete_old:
        since = (datetime.date.today() - datetime.timedelta(days=args.delete_old)).strftime("%d-%b-%Y")
        m.select(quote(JUNK_FOLDER))
        typ, data = m.uid("search", None, "BEFORE", since)
        old = data[0].split()
        for i in range(0, len(old), 200):
            m.uid("store", b",".join(old[i:i + 200]), "+FLAGS", r"(\Deleted)")
        m.expunge()
        print(f"「{JUNK_FOLDER}」の古いメール {len(old)} 通を削除しました")

    m.logout()


if __name__ == "__main__":
    main()
