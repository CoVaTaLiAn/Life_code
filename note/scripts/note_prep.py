#!/usr/bin/env python3
"""Obsidian の記事を note に貼れる形に整える（Python 3 標準ライブラリのみ）。

使い方:
  python3 note_prep.py 記事.md            # チェック → プレビューHTMLを作ってブラウザで開く
  python3 note_prep.py 記事.md --copy     # さらにクリップボードへ（Mac のみ。書式つき）
  python3 note_prep.py 記事.md --done https://note.com/xxx/n/yyy   # 投稿済みにする

やること:
  - Obsidian 独自の書き方（[[リンク]]、==強調==、%%コメント%%、コールアウト）を note 向けに直す
  - <!-- paywall --> の位置を見て「有料ラインをどこに引くか」を教える
  - NGワード（実名など）が入っていないか確認する
"""
import argparse
import datetime
import html
import os
import re
import subprocess
import sys
import tempfile
import webbrowser

PAYWALL = "<!-- paywall -->"
NG_FILE = os.path.expanduser("~/.note_ng_words.txt")


# ---------- frontmatter ----------

def split_frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    if not m:
        return {}, "", text
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, m.group(0), text[m.end():]


def parse_tags(raw):
    raw = raw.strip().strip("[]")
    return [t.strip().strip("'\"#") for t in raw.split(",") if t.strip()]


def set_frontmatter(path, updates):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    meta, fm, body = split_frontmatter(text)
    if not fm:
        sys.exit("frontmatter（--- で囲まれた部分）がありません")
    lines = fm.strip().split("\n")[1:-1]
    for key, val in updates.items():
        for i, line in enumerate(lines):
            if re.match(rf"^{key}\s*:", line):
                lines[i] = f"{key}: {val}"
                break
        else:
            lines.append(f"{key}: {val}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("---\n" + "\n".join(lines) + "\n---\n" + body)


# ---------- Obsidian → 素の Markdown ----------

def clean_obsidian(body, warnings):
    body = body.replace(PAYWALL, "\x00PAYWALL\x00")
    body = re.sub(r"%%.*?%%", "", body, flags=re.S)          # %%コメント%%
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)        # HTMLコメント
    if re.search(r"!\[\[.*?\]\]|!\[.*?\]\(.*?\)", body):
        warnings.append("画像があります。画像は note の編集画面で手動アップロードしてください（本文からは外しました）")
    body = re.sub(r"!\[\[.*?\]\]", "", body)
    body = re.sub(r"!\[.*?\]\(.*?\)", "", body)
    body = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", body)  # [[a|b]] → b
    body = re.sub(r"\[\[([^\]#]+)(#[^\]]*)?\]\]", r"\1", body)  # [[a]] → a
    body = re.sub(r"==(.+?)==", r"**\1**", body)               # ==強調== → 太字
    body = re.sub(r"^(>\s*)\[![^\]]+\][+-]?\s*", r"\1", body, flags=re.M)  # コールアウト
    body = re.sub(r"(?<![A-Za-z0-9#/&])#(?!\d+(\s|$))[^\s#、。，．！？!?)）]+", "", body)  # 本文中の #タグ
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


# ---------- Markdown → HTML（note が対応する範囲だけ） ----------

def inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"~~(.+?)~~", r"<s>\1</s>", s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', s)
    return s


def md_to_html(md):
    out, para, lst, quote = [], [], None, []

    def flush():
        nonlocal para, lst, quote
        if para:
            out.append("<p>" + "<br>".join(inline(x) for x in para) + "</p>")
            para = []
        if lst:
            tag, items = lst
            out.append(f"<{tag}>" + "".join(f"<li>{inline(i)}</li>" for i in items) + f"</{tag}>")
            lst = None
        if quote:
            out.append("<blockquote><p>" + "<br>".join(inline(x) for x in quote) + "</p></blockquote>")
            quote = []

    for line in md.split("\n"):
        s = line.rstrip()
        if s == "\x00PAYWALL\x00":
            flush()
            out.append('<div class="paywall"></div>')
            continue
        if not s.strip():
            flush()
            continue
        m = re.match(r"^(#{1,6})\s+(.*)", s)
        if m:
            flush()
            tag = "h2" if len(m.group(1)) <= 2 else "h3"   # note は大見出し/小見出しの2段階
            out.append(f"<{tag}>{inline(m.group(2))}</{tag}>")
            continue
        if re.match(r"^(-{3,}|\*{3,})$", s.strip()):
            flush()
            out.append("<hr>")
            continue
        m = re.match(r"^\s*([-*+]|\d+\.)\s+(?:\[[ x]\]\s*)?(.*)", s)
        if m:
            tag = "ol" if m.group(1)[0].isdigit() else "ul"
            if para or quote or (lst and lst[0] != tag):
                flush()
            if not lst:
                lst = (tag, [])
            lst[1].append(m.group(2))
            continue
        if s.startswith(">"):
            if para or lst:
                flush()
            quote.append(s.lstrip(">").strip())
            continue
        if lst or quote:
            flush()
        para.append(s)
    flush()
    return "\n".join(out)


def plain_len(md):
    t = md.replace("\x00PAYWALL\x00", "")
    t = re.sub(r"[#>*_~\-]|\[|\]\(.*?\)", "", t)
    return len(re.sub(r"\s", "", t))


# ---------- チェック ----------

def check(meta, md, warnings):
    if not meta.get("title"):
        warnings.append("title が空です（frontmatter の title: に入れてください）")
    price = int(re.sub(r"\D", "", meta.get("price", "0")) or 0)
    if price and "\x00PAYWALL\x00" not in md:
        warnings.append(f"price={price}円 なのに <!-- paywall --> がありません。どこから有料にするか決めてください")
    if price and not (100 <= price <= 50000):
        warnings.append("note の有料記事は 100〜50,000円 の範囲です")
    if "\x00PAYWALL\x00" in md:
        free, paid = md.split("\x00PAYWALL\x00", 1)
        if plain_len(free) < 300:
            warnings.append(f"無料部分が {plain_len(free)} 字と短めです。300字以上あると買われやすくなります")
        if plain_len(paid) < 500:
            warnings.append(f"有料部分が {plain_len(paid)} 字です。値段に見合う量か確認してください")
    if os.path.exists(NG_FILE):
        with open(NG_FILE, encoding="utf-8") as f:
            words = [w.strip() for w in f if w.strip() and not w.startswith("#")]
        hits = [w for w in words if w in md]
        if hits:
            warnings.append("NGワードが入っています: " + "、".join(hits) + "（実名・会社名などは伏せましょう）")
    return price


def paywall_hint(md):
    if "\x00PAYWALL\x00" not in md:
        return None
    free = md.split("\x00PAYWALL\x00", 1)[0].strip().split("\n")
    last = next((l for l in reversed(free) if l.strip()), "")
    last = re.sub(r"^[#>\-*\s]+|\*\*", "", last)
    return last[:40]


# ---------- 出力 ----------

PAGE = """<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>
body{{max-width:680px;margin:40px auto;padding:0 16px;font:17px/1.9 "Hiragino Sans",sans-serif;color:#222;background:#fff}}
.bar{{background:#f3f6f5;border-radius:8px;padding:12px 16px;font-size:14px;line-height:1.7;margin-bottom:32px}}
.bar b{{color:#2cb696}} .warn{{color:#c0392b}}
h1{{font-size:28px}} h2{{font-size:22px;margin-top:2em}} h3{{font-size:18px}}
blockquote{{border-left:3px solid #ccc;margin:0;padding-left:16px;color:#555}}
.paywall{{margin:32px 0;border-top:2px dashed #2cb696;position:relative}}
.paywall::before{{content:"ここに有料ライン（この線はコピーされません）";position:absolute;top:-12px;left:50%;
transform:translateX(-50%);background:#fff;padding:0 8px;color:#2cb696;font-size:13px}}
</style></head><body>
<div class="bar" contenteditable="false">{info}</div>
<div id="article">{body}</div>
<script>
// 本文だけを選択状態にする（そのまま ⌘C → note に ⌘V）
const r=document.createRange();r.selectNodeContents(document.getElementById('article'));
const s=getSelection();s.removeAllRanges();s.addRange(r);
</script></body></html>"""


def copy_mac(html_body, md):
    if sys.platform != "darwin":
        return False
    hexed = html_body.encode("utf-8").hex()
    script = f"set the clipboard to «data HTML{hexed}»"
    try:
        subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
        return True
    except Exception:
        try:  # 書式なしでも最低限コピー
            subprocess.run(["pbcopy"], input=md.replace("\x00PAYWALL\x00", "").encode(), check=True)
        except Exception:
            return False
        return True


def main():
    ap = argparse.ArgumentParser(description="Obsidian の記事を note 用に整える")
    ap.add_argument("file")
    ap.add_argument("--copy", action="store_true", help="クリップボードにコピー（Mac）")
    ap.add_argument("--no-open", action="store_true", help="ブラウザで開かない")
    ap.add_argument("--done", metavar="URL", help="投稿済みにして URL を記録")
    a = ap.parse_args()

    if a.done:
        set_frontmatter(a.file, {"status": "published", "url": a.done,
                                 "published": datetime.date.today().isoformat()})
        print("✅ 投稿済みにしました:", a.done)
        return

    with open(a.file, encoding="utf-8") as f:
        meta, _, body = split_frontmatter(f.read())
    warnings = []
    md = clean_obsidian(body, warnings)
    price = check(meta, md, warnings)
    tags = parse_tags(meta.get("tags", ""))
    title = meta.get("title") or os.path.splitext(os.path.basename(a.file))[0]
    hint = paywall_hint(md)
    body_html = md_to_html(md)

    info = [f"<b>タイトル</b>：{html.escape(title)}（タイトル欄に別で入れる）",
            f"<b>価格</b>：{price}円" if price else "<b>価格</b>：無料",
            f"<b>ハッシュタグ</b>：{html.escape(' '.join('#' + t for t in tags))}",
            f"<b>文字数</b>：{plain_len(md)}字"]
    if hint:
        info.append(f"<b>有料ライン</b>：「{html.escape(hint)}」の段落の直後")
    info += [f'<span class="warn">⚠ {html.escape(w)}</span>' for w in warnings]

    out = os.path.join(tempfile.gettempdir(), "note_preview.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(PAGE.format(title=html.escape(title), info="<br>".join(info), body=body_html))

    print(f"■ タイトル  : {title}")
    print(f"■ 価格      : {price}円" if price else "■ 価格      : 無料")
    print(f"■ タグ      : {' '.join('#' + t for t in tags)}")
    print(f"■ 文字数    : {plain_len(md)}字")
    if hint:
        print(f"■ 有料ライン: 「{hint}」の段落の直後に引く")
    for w in warnings:
        print("⚠", w)
    print("■ プレビュー:", out)

    if a.copy:
        clip_html = body_html.replace('<div class="paywall"></div>', "")
        print("📋 クリップボードにコピーしました" if copy_mac(clip_html, md)
              else "📋 コピーできませんでした。プレビューで ⌘A ではなく本文を選んでコピーしてください")
    if not a.no_open:
        webbrowser.open("file://" + out)


if __name__ == "__main__":
    main()
