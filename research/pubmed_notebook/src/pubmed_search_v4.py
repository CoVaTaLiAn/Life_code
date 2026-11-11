# PubMed 論文探索 Ver4
# Google Colab（無料枠）でそのまま動く。必要なのは biopython / pandas / openpyxl だけ。
# 入力: pubmed_inputdata.xlsx（または .csv）  列: No, Target, Category, PubMed Query, Query Intent
# 出力: pubmed_search_results.xlsx, pubmed_papers.md

import re
import time
from collections import Counter

import pandas as pd
from Bio import Entrez

# ===== 設定 =====
Entrez.email = "your.email@example.com"  # ご自身のメールアドレスに変更（NCBIの利用ルール）
Entrez.api_key = None                    # 無料のNCBI APIキーがあれば文字列で（3→10回/秒）
INPUT_FILE = "pubmed_inputdata.xlsx"     # .csv も可
MAX_DETAIL = 50                          # この件数以下のクエリだけ論文詳細を取る
OUTPUT_EXCEL = "pubmed_search_results.xlsx"
OUTPUT_MD = "pubmed_papers.md"
WAIT = 0.4 if Entrez.api_key else 1.0    # API呼び出しの間隔（秒）
EXCEL_CELL_MAX = 32000                   # Excelのセル上限(32767字)対策


# ===== 共通 =====
def call_entrez(func, retries=4, **kwargs):
    """通信エラー・混雑(429)のときは待って再試行する"""
    for i in range(retries):
        try:
            handle = func(**kwargs)
            data = Entrez.read(handle)
            handle.close()
            time.sleep(WAIT)
            return data
        except Exception as e:
            if i == retries - 1:
                raise
            wait = 2 ** (i + 1)
            print(f"    通信エラーのため {wait}秒後に再試行します: {e}")
            time.sleep(wait)


def check_query(query):
    """AIが作った検索式のよくあるミスを見つける"""
    notes = []
    if query.count("(") != query.count(")"):
        notes.append("括弧の数が合っていない")
    if query.count('"') % 2:
        notes.append('" の数が奇数')
    # 同じ語・同じフィールド（例 "x"[tiab] が2回）だけを重複とみなす
    terms = re.findall(r'"([^"]+)"(\[[^\]]+\])?', query.lower())
    dup = [t + f for (t, f), n in Counter(terms).items() if n > 1]
    if dup:
        notes.append("重複した語: " + ", ".join(dup))
    return "; ".join(notes)


def get_year(article, medline):
    """発行年。Year がない論文は MedlineDate（例 '2021 Jan-Feb'）や電子版の日付から取る"""
    pub_date = article.get("Journal", {}).get("JournalIssue", {}).get("PubDate", {})
    if pub_date.get("Year"):
        return str(pub_date["Year"])
    m = re.search(r"(19|20)\d{2}", str(pub_date.get("MedlineDate", "")))
    if m:
        return m.group(0)
    for d in article.get("ArticleDate", []):
        if d.get("Year"):
            return str(d["Year"])
    return str(medline.get("DateCompleted", {}).get("Year", ""))


def get_authors(author_list):
    authors = []
    for a in author_list or []:
        if "LastName" in a:
            authors.append(f"{a['LastName']} {a.get('Initials', '')}".strip())
        elif "CollectiveName" in a:
            authors.append(str(a["CollectiveName"]))
    return ", ".join(authors)


def get_abstract(abstract):
    """見出し付きアブスト（BACKGROUND: など）は見出しも残す"""
    parts = []
    for t in (abstract or {}).get("AbstractText", []):
        label = getattr(t, "attributes", {}).get("Label")
        parts.append(f"{label}: {t}" if label else str(t))
    return " ".join(parts)


def parse_papers(data):
    """通常の論文と書籍（PubmedBookArticle）の両方を読む"""
    out = []
    for p in data.get("PubmedArticle", []):
        med = p["MedlineCitation"]
        art = med["Article"]
        out.append({
            "PMID": str(med["PMID"]),
            "Title": str(art.get("ArticleTitle", "")),
            "Authors": get_authors(art.get("AuthorList")),
            "Year": get_year(art, med),
            "Journal": str(art.get("Journal", {}).get("Title", "")),
            "Abstract": get_abstract(art.get("Abstract")),
        })
    for b in data.get("PubmedBookArticle", []):
        doc = b["BookDocument"]
        book = doc.get("Book", {})
        out.append({
            "PMID": str(doc["PMID"]),
            "Title": str(doc.get("ArticleTitle", "") or book.get("BookTitle", "")),
            "Authors": get_authors(doc.get("AuthorList", [[]])[0] if doc.get("AuthorList") else []),
            "Year": str(book.get("PubDate", {}).get("Year", "")),
            "Journal": "(Book) " + str(book.get("BookTitle", "")),
            "Abstract": get_abstract(doc.get("Abstract")),
        })
    return out


# ===== 1. 入力の読み込み =====
if INPUT_FILE.lower().endswith(".csv"):
    df_input = pd.read_csv(INPUT_FILE, encoding="utf-8-sig")  # BOM付きUTF-8でも読める
else:
    df_input = pd.read_excel(INPUT_FILE)
df_input = df_input.dropna(subset=["PubMed Query"])
print(f"{INPUT_FILE} を読み込みました（{len(df_input)}本）。検索を開始します。\n")

results_summary = []
papers_list = []   # クエリ×論文（重複も含む）
unique = {}        # PMID -> 論文情報（初出の通し番号と、ヒットしたクエリ一覧）
paper_counter = 1

# ===== 2. クエリの実行 =====
for index, row in df_input.iterrows():
    query_no = str(row.get("No", index + 1))
    target = str(row.get("Target", "Unknown"))
    query = str(row["PubMed Query"]).strip()
    print(f"No.{query_no} (Target: {target}) を検索中...")

    summary = {
        "No": query_no, "Target": target, "Category": row.get("Category", ""),
        "PubMed Query": query, "Hit Count": None, "Status": "",
        "Query Check": check_query(query), "PubMed Warning": "", "Query Translation": "",
    }
    if summary["Query Check"]:
        print(f"    ※検索式の注意: {summary['Query Check']}")

    try:
        record = call_entrez(Entrez.esearch, db="pubmed", term=query, retmax=MAX_DETAIL)
        count = int(record["Count"])
        summary["Hit Count"] = count
        # PubMed がどう解釈したか／見つからなかった語（AIの検索式の確認に使う）
        summary["Query Translation"] = str(record.get("QueryTranslation", ""))
        warn = []
        for key in ("ErrorList", "WarningList"):
            for k, v in (record.get(key) or {}).items():
                if v:
                    warn.append(f"{k}: {', '.join(map(str, v))}")
        summary["PubMed Warning"] = "; ".join(warn)
        print(f" -> {count}件ヒット")

        if 0 < count <= MAX_DETAIL:
            summary["Status"] = "詳細取得"
            data = call_entrez(Entrez.efetch, db="pubmed", id=",".join(record["IdList"]), retmode="xml")
            for p in parse_papers(data):
                pmid = p["PMID"]
                dup_of = ""
                if pmid in unique:
                    dup_of = unique[pmid]["Paper_No"]
                    unique[pmid]["Queries"].append(query_no)
                    unique[pmid]["Targets"].append(target)
                else:
                    unique[pmid] = {**p, "Paper_No": paper_counter,
                                    "Queries": [query_no], "Targets": [target]}
                papers_list.append({
                    "Paper_No": paper_counter, "Query_No": query_no, "Target": target,
                    "PMID": pmid, "Title": p["Title"], "Authors": p["Authors"],
                    "Year": p["Year"], "Journal": p["Journal"],
                    "Duplicate_of_No": dup_of,
                    "Abstract": "" if dup_of else p["Abstract"][:EXCEL_CELL_MAX],
                })
                paper_counter += 1
        elif count > MAX_DETAIL:
            summary["Status"] = f"{MAX_DETAIL}件超のためスキップ"
            print(f"    ※{MAX_DETAIL}件を超えているため、詳細取得をスキップしました。")
        else:
            summary["Status"] = "0件"
    except Exception as e:
        summary["Status"] = f"ERROR: {e}"
        print(f"    エラー（Target: {target}）: {e}")

    results_summary.append(summary)

# ===== 3. Excel出力 =====
df_summary = pd.DataFrame(results_summary)
df_papers = pd.DataFrame(papers_list)
df_unique = pd.DataFrame([{
    "Paper_No": u["Paper_No"], "PMID": u["PMID"], "Title": u["Title"],
    "Authors": u["Authors"], "Year": u["Year"], "Journal": u["Journal"],
    "Found_in_Queries": ", ".join(u["Queries"]),
    "Found_in_Targets": ", ".join(dict.fromkeys(u["Targets"])),
    "Hit_Times": len(u["Queries"]),
    "PubMed_URL": f"https://pubmed.ncbi.nlm.nih.gov/{u['PMID']}/",
    "Abstract": u["Abstract"][:EXCEL_CELL_MAX],
} for u in unique.values()])

with pd.ExcelWriter(OUTPUT_EXCEL) as writer:
    df_input.to_excel(writer, sheet_name="Original_Queries", index=False)
    df_summary.to_excel(writer, sheet_name="Summary", index=False)
    df_papers.to_excel(writer, sheet_name="Paper_Details", index=False)
    df_unique.to_excel(writer, sheet_name="Unique_Papers", index=False)
print(f"\nExcelファイルを保存しました: '{OUTPUT_EXCEL}'")

# ===== 4. Markdown出力（重複なし） =====
entries = []
for u in unique.values():
    entries.append(f"""## [{u['Paper_No']}] {u['Title']}
- **PMID**: [{u['PMID']}](https://pubmed.ncbi.nlm.nih.gov/{u['PMID']}/)
- **Target**: {', '.join(dict.fromkeys(u['Targets']))} (Query No: {', '.join(u['Queries'])})
- **Journal**: {u['Journal']} ({u['Year']})
- **Authors**: {u['Authors']}

### Abstract
{u['Abstract'] or '*(No abstract available)*'}

---""")

with open(OUTPUT_MD, "w", encoding="utf-8") as f:
    f.write("# PubMed 検索ヒット論文一覧（ユニーク）\n\n")
    f.write(f"総ユニーク論文件数: {len(entries)} 件\n\n")
    f.write("\n\n".join(entries))
print(f"Markdownファイルを保存しました: '{OUTPUT_MD}'")

errors = df_summary[df_summary["Status"].str.startswith("ERROR")]
if len(errors):
    print(f"\n※{len(errors)}本の検索でエラーがありました。Summaryシートの Status 列を確認してください。")
