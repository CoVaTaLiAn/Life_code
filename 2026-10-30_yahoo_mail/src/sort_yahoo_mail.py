#!/usr/bin/env python3
"""Yahoo!メール（Yahoo! JAPAN）の受信箱で、緊急なもの以外の未読メールを既読にする。

使い方:
    python3 sort_yahoo_mail.py                    # お試し（何も変えず、件数と残すメールの件名を表示）
    python3 sort_yahoo_mail.py --run              # 実際に既読にする
    python3 sort_yahoo_mail.py --restore-folders  # 以前の振り分けで作ったフォルダのメールを受信箱に戻し、フォルダを消す

「緊急」の判定は URGENT_SUBJECT / URGENT_FROM（件名・差出人に含む語）で変えられる。
ALWAYS_READ に当たるメールは、緊急っぽくても必ず既読にする。

ログイン情報は、環境変数 YAHOO_USER / YAHOO_PASS → macOS キーチェーン
（setup_mac.sh で保存）→ 画面での入力、の順に探す。

事前準備:
    Yahoo!メールの「設定 → IMAP/POP/SMTPアクセス」で IMAP を「利用する」にし、
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
import subprocess
import sys

HOST = "imap.mail.yahoo.co.jp"
KEYCHAIN_SERVICE = "yahoo-mail-sorter"

# これらを件名に含む未読メールは、既読にせず残す
URGENT_SUBJECT = [
    "緊急", "至急", "重要", "警告",
    "認証", "確認コード", "認証コード", "ワンタイム", "パスワード", "本人確認",
    "ログイン", "サインイン", "セキュリティ", "不正", "不審", "ロック", "停止",
    "支払い期限", "お支払い期限", "未払い", "延滞", "督促", "期限切れ",
]
# これらを差出人に含む未読メールも残す（例: "bank", "@example.co.jp"）
URGENT_FROM = []

# これらを件名か差出人に含むメールは、緊急っぽい語があっても必ず既読にする
ALWAYS_READ = [
    "路線情報",                                # Yahoo!路線情報
    "ベネフィット", "m3-benefit", "benefit.m3",  # M3ベネフィット
]

# 以前の振り分け機能で作ったフォルダ（--restore-folders で受信箱に戻す）
OLD_FOLDERS = ["要確認", "買い物", "会員登録", "メルマガ"]


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


def quote(name):
    return '"' + imap_utf7_encode(name).replace("\\", "\\\\").replace('"', '\\"') + '"'


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


def is_urgent(subject, sender):
    s, f = subject.lower(), sender.lower()
    if any(k.lower() in s or k.lower() in f for k in ALWAYS_READ):
        return False
    return any(k.lower() in s for k in URGENT_SUBJECT) or any(k.lower() in f for k in URGENT_FROM)


def keychain_login():
    """macOS のキーチェーンから ID とパスワードを読む。なければ (None, None)。"""
    try:
        info = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE],
                              capture_output=True, text=True)
        pw = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
                            capture_output=True, text=True)
    except FileNotFoundError:
        return None, None
    m = re.search(r'"acct"<blob>="([^"]*)"', info.stdout)
    if info.returncode or pw.returncode or not m:
        return None, None
    return m.group(1), pw.stdout.rstrip("\n")


def get_login():
    user, password = os.environ.get("YAHOO_USER"), os.environ.get("YAHOO_PASS")
    if user and password:
        return user, password
    user, password = keychain_login()
    if user and password:
        return user, password
    if not sys.stdin.isatty():
        sys.exit("ログイン情報が見つかりません。setup_mac.sh を実行してキーチェーンに保存してください。")
    return input("Yahoo! JAPAN ID またはメールアドレス: "), getpass.getpass("パスワード: ")


def chunks(items, n=200):
    for i in range(0, len(items), n):
        yield b",".join(items[i:i + n])


def restore_folders(m):
    for folder in OLD_FOLDERS:
        typ, _ = m.select(quote(folder))
        if typ != "OK":
            continue
        typ, data = m.uid("search", None, "ALL")
        uids = data[0].split()
        moved = 0
        for chunk in chunks(uids):
            typ, _ = m.uid("copy", chunk, "INBOX")
            if typ == "OK":
                m.uid("store", chunk, "+FLAGS", r"(\Deleted)")
                moved += chunk.count(b",") + 1
        m.expunge()
        m.close()
        if moved == len(uids):
            m.delete(quote(folder))
            print(f"「{folder}」の {moved} 通を受信箱に戻し、フォルダを消しました")
        else:
            print(f"「{folder}」: {len(uids)} 通中 {moved} 通だけ戻せました（フォルダは残しています）")


def mark_read(m, run):
    m.select("INBOX")
    typ, data = m.uid("search", None, "UNSEEN")
    uids = data[0].split()
    keep, to_read = [], []
    for chunk in chunks(uids):
        typ, resp = m.uid("fetch", chunk, "(UID BODY.PEEK[HEADER.FIELDS (SUBJECT FROM)])")
        for item in resp:
            if not isinstance(item, tuple):
                continue
            uid = re.search(rb"UID (\d+)", item[0]).group(1)
            msg = email.message_from_bytes(item[1])
            subject = decode_header(msg.get("Subject"))
            if is_urgent(subject, decode_header(msg.get("From"))):
                keep.append(subject)
            else:
                to_read.append(uid)

    print(f"受信箱の未読: {len(uids)} 通")
    print(f"  既読にする: {len(to_read)} 通")
    print(f"  緊急として未読のまま残す: {len(keep)} 通")
    for s in keep[:20]:
        print(f"    - {s[:60]}")
    if len(keep) > 20:
        print(f"    …ほか {len(keep) - 20} 通")

    if not run:
        print("\nお試しモードなので何も変えていません。実行するには --run を付けてください。")
        return
    for chunk in chunks(to_read):
        m.uid("store", chunk, "+FLAGS", r"(\Seen)")
    print("既読にしました")


def main():
    ap = argparse.ArgumentParser(description="Yahoo!メールの、緊急なもの以外を既読にする")
    ap.add_argument("--run", action="store_true", help="実際に既読にする（付けないとお試しのみ）")
    ap.add_argument("--restore-folders", action="store_true",
                    help="以前の振り分けフォルダのメールを受信箱に戻し、フォルダを消す")
    args = ap.parse_args()

    user, password = get_login()
    print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "開始")
    m = imaplib.IMAP4_SSL(HOST, 993)
    m.login(user, password)

    if args.restore_folders:
        restore_folders(m)
    else:
        mark_read(m, args.run)
    m.logout()


if __name__ == "__main__":
    main()
