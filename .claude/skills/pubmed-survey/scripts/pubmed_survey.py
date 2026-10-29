#!/usr/bin/env python3
"""PubMed 網羅検索ツール（標準ライブラリのみ）

サブコマンド:
  search  クエリ一覧で PubMed を検索し、ヒット数を記録。
          ヒット数が閾値(既定50)以下のクエリは論文情報とアブストを取得する。
          複数クエリで重複した論文は最初に見つかったクエリにだけ記録する。
  render  papers.json と scores.json(Claude が作成) と summary.md を合わせて
          report.md を作る。

使い方:
  python3 pubmed_survey.py search --queries queries.txt --out survey/ --email you@example.com
  python3 pubmed_survey.py render --out survey/
"""
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
    unscored = sum(1 for p in papers if p["pmid"] not in scores)
    print(f"wrote {path}  (papers={len(papers)}, unscored={unscored})")


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
    args = ap.parse_args()
    {"search": cmd_search, "render": cmd_render}[args.cmd](args)


if __name__ == "__main__":
    main()
