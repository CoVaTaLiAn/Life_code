#!/usr/bin/env python3
"""PubMed 網羅検索ツール（標準ライブラリのみ）

サブコマンド:
  search  クエリ一覧で PubMed を検索し、ヒット数を記録。
          ヒット数が閾値(既定50)以下のクエリは論文情報とアブストを取得する。
          複数クエリで重複した論文は最初に見つかったクエリにだけ記録する。
  chunk   papers.json を N 分割したテキストにする（並列採点用）
  merge   scores_*.json を scores.json にまとめ、採点漏れ・重複を確認する
  render  papers.json と scores.json(Claude が作成) と summary.md を合わせて
          report.md と top.md（優先度上位だけの軽量版）を作る。
  email   summary.md と上位論文一覧を HTML メール本文 (email.html) にする

使い方:
  python3 pubmed_survey.py search --queries queries.txt --out survey/ --email you@example.com
  python3 pubmed_survey.py chunk  --out survey/ --n 4
  python3 pubmed_survey.py merge  --out survey/
  python3 pubmed_survey.py render --out survey/
  python3 pubmed_survey.py email  --out survey/ --min-score 5
"""
import glob
import html
import re
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
TOOL = "pubmed_survey"


# ---------- PubMed API ----------

def _request(endpoint, params, retries=4):
    params = {k: v for k, v in params.items() if v}
    data = urllib.parse.urlencode(params).encode()
    delay = 2
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(EUTILS + endpoint, data=data,
                                         headers={"User-Agent": TOOL})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:  # ネットワーク・429 などは再試行
            if attempt == retries:
                raise RuntimeError(f"{endpoint} failed: {e}") from e
            time.sleep(delay)
            delay *= 2
        finally:
            time.sleep(API_WAIT)


def esearch(term, retmax, auth):
    raw = _request("esearch.fcgi", {"db": "pubmed", "term": term, "retmode": "json",
                                    "retmax": str(retmax), "sort": "relevance", **auth})
    res = json.loads(raw)["esearchresult"]
    return int(res.get("count", 0)), res.get("idlist", []), res.get("querytranslation", "")


def efetch(pmids, auth):
    out = []
    for i in range(0, len(pmids), 200):
        raw = _request("efetch.fcgi", {"db": "pubmed", "id": ",".join(pmids[i:i + 200]),
                                       "retmode": "xml", **auth})
        out.extend(parse_pubmed_xml(raw))
    return out


# ---------- XML 解析 ----------

def _text(el):
    return " ".join("".join(el.itertext()).split()) if el is not None else ""


def parse_pubmed_xml(raw):
    root = ET.fromstring(raw)
    papers = []
    for art in root.iter("PubmedArticle"):
        mc = art.find("MedlineCitation")
        a = mc.find("Article")
        parts = []
        for ab in a.findall("Abstract/AbstractText"):
            label = ab.get("Label")
            t = _text(ab)
            parts.append(f"{label}: {t}" if label else t)
        authors = []
        for au in a.findall("AuthorList/Author"):
            name = " ".join(x for x in [_text(au.find("LastName")), _text(au.find("Initials"))] if x)
            authors.append(name or _text(au.find("CollectiveName")))
        pd = a.find("Journal/JournalIssue/PubDate")
        year = _text(pd.find("Year")) if pd is not None else ""
        if not year and pd is not None:
            year = _text(pd.find("MedlineDate"))[:4]
        doi = ""
        for aid in art.findall("PubmedData/ArticleIdList/ArticleId"):
            if aid.get("IdType") == "doi":
                doi = _text(aid)
        pmid = _text(mc.find("PMID"))
        papers.append({
            "pmid": pmid,
            "title": _text(a.find("ArticleTitle")),
            "authors": authors,
            "journal": _text(a.find("Journal/Title")),
            "year": year,
            "doi": doi,
            "pub_types": [_text(p) for p in a.findall("PublicationTypeList/PublicationType")],
            "abstract": "\n".join(parts),
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        })
    return papers


# ---------- search ----------

def load_queries(path):
    qs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                qs.append(line)
    return qs


def cmd_search(args):
    os.makedirs(args.out, exist_ok=True)
    auth = {"tool": TOOL, "email": args.email or os.environ.get("NCBI_EMAIL", ""),
            "api_key": args.api_key or os.environ.get("NCBI_API_KEY", "")}
    global API_WAIT
    API_WAIT = 0.11 if auth["api_key"] else 0.34  # NCBI の上限: 10/秒 or 3/秒

    queries = load_queries(args.queries)
    hits, papers, seen = [], {}, set()
    for n, q in enumerate(queries, 1):
        count, ids, translated = esearch(q, args.max, auth)
        rec = {"no": n, "query": q, "translation": translated, "count": count,
               "fetched": count <= args.max and count > 0, "new": 0, "dup": 0}
        if rec["fetched"]:
            new_ids = [i for i in ids if i not in seen]
            rec["dup"] = len(ids) - len(new_ids)
            rec["new"] = len(new_ids)
            for p in efetch(new_ids, auth) if new_ids else []:
                p["found_by"] = n
                papers[p["pmid"]] = p
            seen.update(ids)
        hits.append(rec)
        status = "取得" if rec["fetched"] else ("0件" if count == 0 else "多すぎ→スキップ")
        print(f"[{n}/{len(queries)}] {count:>8} 件  {status}  新規{rec['new']} 重複{rec['dup']}  {q}",
              file=sys.stderr)

    meta = {"date": date.today().isoformat(), "max": args.max, "queries": len(queries),
            "unique_papers": len(papers)}
    with open(os.path.join(args.out, "hits.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "hits": hits}, f, ensure_ascii=False, indent=2)
    with open(os.path.join(args.out, "papers.json"), "w", encoding="utf-8") as f:
        json.dump(list(papers.values()), f, ensure_ascii=False, indent=2)
    print(json.dumps(meta, ensure_ascii=False))


# ---------- render ----------

def _load(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f) if path.endswith(".json") else f.read()
    return default


def _cell(s):
    return str(s).replace("|", "\\|").replace("\n", " ")


def cmd_render(args):
    d = args.out
    hits = _load(os.path.join(d, "hits.json"), None)
    if hits is None:
        sys.exit("hits.json がありません。先に search を実行してください。")
    papers = _load(os.path.join(d, "papers.json"), [])
    scores = {str(s["pmid"]): s for s in _load(os.path.join(d, "scores.json"), [])}
    summary = _load(os.path.join(d, "summary.md"), "")
    meta = hits["meta"]

    for p in papers:
        s = scores.get(p["pmid"], {})
        p["score"] = s.get("score", 0)
        p["reason"] = s.get("reason", "")
    papers.sort(key=lambda p: (-p["score"], -int(p["year"] or 0)))

    L = [f"# 論文調査レポート", "",
         f"- 調査日: {meta['date']}  /  クエリ数: {meta['queries']}  /  "
         f"取得閾値: {meta['max']}件以下  /  ユニーク論文数: {meta['unique_papers']}", ""]
    if summary:
        L += [summary.strip(), ""]

    L += ["## 1. 検索クエリとヒット数", "",
          "| # | クエリ | ヒット数 | 取得 | 新規 | 重複 |", "|---|---|---:|:---:|---:|---:|"]
    for h in hits["hits"]:
        L.append(f"| {h['no']} | `{_cell(h['query'])}` | {h['count']:,} | "
                 f"{'○' if h['fetched'] else '—'} | {h['new']} | {h['dup']} |")

    L += ["", "## 2. 優先度順 論文一覧", "",
          "| 優先 | 年 | タイトル | 雑誌 | 理由 | クエリ# |", "|---:|---|---|---|---|---:|"]
    for p in papers:
        L.append(f"| {p['score']} | {p['year']} | [{_cell(p['title'])}]({p['url']}) | "
                 f"{_cell(p['journal'])} | {_cell(p['reason'])} | {p['found_by']} |")

    L += ["", "## 3. 論文詳細（優先度順）", ""]
    for i, p in enumerate(papers, 1):
        au = ", ".join(p["authors"][:5]) + (" ほか" if len(p["authors"]) > 5 else "")
        L += [f"### {i}. {p['title']}", "",
              f"- 優先度: **{p['score']}**  {p['reason']}",
              f"- 著者: {au}", f"- 雑誌: {p['journal']} ({p['year']})",
              f"- PMID: [{p['pmid']}]({p['url']})" + (f"  DOI: {p['doi']}" if p["doi"] else ""),
              f"- 種別: {', '.join(p['pub_types'])}", f"- 検出クエリ: #{p['found_by']}", "",
              "<details><summary>Abstract</summary>", "", p["abstract"] or "(アブストなし)", "",
              "</details>", ""]

    path = os.path.join(d, "report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    # 軽量版: まとめ + 優先度4以上の一覧（アブストなし）
    i2 = L.index("## 3. 論文詳細（優先度順）")
    top = [l for l in L[:i2] if not (l.startswith("| ") and l.split("|")[1].strip().isdigit()
                                       and "](" in l and int(l.split("|")[1]) < args.top_min)]
    with open(os.path.join(d, "top.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(top))
    unscored = sum(1 for p in papers if p["pmid"] not in scores)
    print(f"wrote {path}  (papers={len(papers)}, unscored={unscored})")


# ---------- chunk / merge ----------

def cmd_chunk(args):
    papers = _load(os.path.join(args.out, "papers.json"), [])
    cdir = os.path.join(args.out, "chunks")
    os.makedirs(cdir, exist_ok=True)
    size = (len(papers) + args.n - 1) // args.n or 1
    for k in range(args.n):
        part = papers[k * size:(k + 1) * size]
        if not part:
            break
        with open(os.path.join(cdir, f"chunk{k}.txt"), "w", encoding="utf-8") as f:
            for p in part:
                f.write(f"PMID {p['pmid']} | {p['year']} | {p['journal']} | {', '.join(p['pub_types'])}\n"
                        f"TITLE: {p['title']}\nABSTRACT: {p['abstract'] or '(none)'}\n\n")
        print(f"{cdir}/chunk{k}.txt  papers={len(part)}  -> {cdir}/scores{k}.json")


def cmd_merge(args):
    papers = {p["pmid"] for p in _load(os.path.join(args.out, "papers.json"), [])}
    files = sorted(glob.glob(os.path.join(args.out, "chunks", "scores*.json")))
    merged = {}
    for fp in files:
        for s in _load(fp, []):
            merged[str(s["pmid"])] = {**s, "pmid": str(s["pmid"])}
    missing, extra = papers - merged.keys(), merged.keys() - papers
    with open(os.path.join(args.out, "scores.json"), "w", encoding="utf-8") as f:
        json.dump(list(merged.values()), f, ensure_ascii=False, indent=1)
    dist = {k: sum(1 for s in merged.values() if s["score"] == k) for k in range(5, 0, -1)}
    print(f"files={len(files)} scored={len(merged)} missing={sorted(missing)} extra={sorted(extra)} dist={dist}")


# ---------- email ----------

def _inline(t):
    t = html.escape(t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"`(.+?)`", r"<code>\1</code>", t)
    return re.sub(r"\[(.+?)\]\((https?://[^)]+)\)", r"<a href='\2'>\1</a>", t)


def md_to_html(md):
    out, lst, tbl = [], None, []

    def flush():
        nonlocal lst, tbl
        if lst:
            out.append(f"</{lst}>")
            lst = None
        if tbl:
            rows = [r for r in tbl if not re.fullmatch(r"\|[\s:|-]+\|", r)]
            cells = lambda r, t: "".join(f"<{t}>{_inline(c.strip())}</{t}>" for c in r.strip("|").split("|"))
            out.append("<table border='1' cellpadding='4' style='border-collapse:collapse'>"
                       + f"<tr>{cells(rows[0], 'th')}</tr>"
                       + "".join(f"<tr>{cells(r, 'td')}</tr>" for r in rows[1:]) + "</table>")
            tbl = []

    for line in md.splitlines():
        s = line.strip()
        if s.startswith("|"):
            if lst:
                out.append(f"</{lst}>"); lst = None
            tbl.append(s); continue
        m_ul, m_ol, m_h = re.match(r"[-*] (.*)", s), re.match(r"\d+\. (.*)", s), re.match(r"(#{1,4}) (.*)", s)
        if m_ul or m_ol:
            kind = "ul" if m_ul else "ol"
            if tbl or lst != kind:
                flush(); out.append(f"<{kind}>"); lst = kind
            out.append(f"<li>{_inline((m_ul or m_ol).group(1))}</li>"); continue
        flush()
        if m_h:
            n = min(len(m_h.group(1)) + 1, 4)
            out.append(f"<h{n}>{_inline(m_h.group(2))}</h{n}>")
        elif s:
            out.append(f"<p>{_inline(s)}</p>")
    flush()
    return "\n".join(out)


def cmd_email(args):
    d = args.out
    papers = {p["pmid"]: p for p in _load(os.path.join(d, "papers.json"), [])}
    scores = [s for s in _load(os.path.join(d, "scores.json"), []) if s["score"] >= args.min_score]
    scores.sort(key=lambda s: (-s["score"], -int(papers[str(s["pmid"])]["year"] or 0)))
    meta = _load(os.path.join(d, "hits.json"), {"meta": {}})["meta"]
    items = "".join(
        f"<li>[{s['score']}] {papers[str(s['pmid'])]['year']} "
        f"<a href='{papers[str(s['pmid'])]['url']}'>{html.escape(papers[str(s['pmid'])]['title'])}</a>"
        f" — {html.escape(s['reason'])}</li>" for s in scores)
    body = (f"<div style='font-family:sans-serif;font-size:14px;line-height:1.6'>"
            f"<p>PubMed 調査 {meta.get('date', '')}：検索式 {meta.get('queries', '?')} 本 → "
            f"ユニーク論文 {meta.get('unique_papers', '?')} 本</p>"
            + md_to_html(_load(os.path.join(d, "summary.md"), ""))
            + f"<h3>優先度 {args.min_score} 以上の論文 ({len(scores)} 本)</h3>"
            f"<ul style='font-size:13px'>{items}</ul></div>")
    path = os.path.join(d, "email.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"wrote {path}  ({len(body):,} chars, papers={len(scores)})")


API_WAIT = 0.34


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("--queries", required=True, help="1行1クエリのテキスト (#はコメント)")
    s.add_argument("--out", required=True)
    s.add_argument("--max", type=int, default=50, help="この件数以下なら論文を取得")
    s.add_argument("--email", default="")
    s.add_argument("--api-key", default="")
    r = sub.add_parser("render")
    r.add_argument("--out", required=True)
    r.add_argument("--top-min", type=int, default=4, help="top.md に載せる最低優先度")
    c = sub.add_parser("chunk")
    c.add_argument("--out", required=True)
    c.add_argument("--n", type=int, default=4)
    m = sub.add_parser("merge")
    m.add_argument("--out", required=True)
    e = sub.add_parser("email")
    e.add_argument("--out", required=True)
    e.add_argument("--min-score", type=int, default=5)
    args = ap.parse_args()
    {"search": cmd_search, "render": cmd_render, "chunk": cmd_chunk,
     "merge": cmd_merge, "email": cmd_email}[args.cmd](args)


if __name__ == "__main__":
    main()
