"""Jリーグ観客動員数: 実験の共通部品。

検証の考え方（本番と同じ形にする）
  本番: 2014年7月までの試合で学習 → 2014年8〜12月（後半戦）を予測
  検証: H2_2013 = 2013年7月までで学習 → 2013年8〜12月を予測（主）
        H2_2012 = 2012年7月までで学習 → 2012年8〜12月を予測（副。学習データが半年分しかない）
  観客数（目的変数）を使う「過去の実績」は、カットオフ（その年の8/1）より前のデータだけで作る。
  試合結果（スコア）から作る順位は、試合日より前の結果をすべて使う（本番でも試合日に分かる情報）。
"""
import json
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
D = ROOT / "data"
LOG_CSV = HERE / "experiments.csv"

FOLDS = {"H2_2012": pd.Timestamp("2012-08-01"), "H2_2013": pd.Timestamp("2013-08-01")}
TEST_CUTOFF = pd.Timestamp("2014-08-01")

# 都道府県庁所在地のおおよその緯度経度（移動距離の目安）
PREF_LL = {
    "北海道": (43.06, 141.35), "宮城県": (38.27, 140.87), "山形県": (38.24, 140.36), "福島県": (37.75, 140.47),
    "茨城県": (36.34, 140.45), "栃木県": (36.57, 139.88), "群馬県": (36.39, 139.06), "埼玉県": (35.86, 139.65),
    "千葉県": (35.61, 140.12), "東京都": (35.69, 139.69), "神奈川県": (35.45, 139.64), "新潟県": (37.90, 139.02),
    "富山県": (36.70, 137.21), "山梨県": (35.66, 138.57), "長野県": (36.65, 138.18), "岐阜県": (35.39, 136.72),
    "静岡県": (34.98, 138.38), "愛知県": (35.18, 136.91), "京都府": (35.02, 135.76), "大阪府": (34.69, 135.52),
    "兵庫県": (34.69, 135.18), "鳥取県": (35.50, 134.24), "岡山県": (34.66, 133.93), "広島県": (34.40, 132.46),
    "徳島県": (34.07, 134.56), "香川県": (34.34, 134.04), "愛媛県": (33.84, 132.77), "福岡県": (33.61, 130.42),
    "佐賀県": (33.25, 130.30), "長崎県": (32.74, 129.87), "熊本県": (32.79, 130.74), "大分県": (33.24, 131.61),
    "鹿児島県": (31.56, 130.56),
}
REGION = {
    "北海道": "北海道", "宮城県": "東北", "山形県": "東北", "福島県": "東北",
    "茨城県": "関東", "栃木県": "関東", "群馬県": "関東", "埼玉県": "関東", "千葉県": "関東", "東京都": "関東", "神奈川県": "関東",
    "新潟県": "北信越", "富山県": "北信越", "長野県": "北信越", "山梨県": "関東",
    "岐阜県": "東海", "静岡県": "東海", "愛知県": "東海",
    "京都府": "関西", "大阪府": "関西", "兵庫県": "関西",
    "鳥取県": "中国", "岡山県": "中国", "広島県": "中国",
    "徳島県": "四国", "香川県": "四国", "愛媛県": "四国",
    "福岡県": "九州", "佐賀県": "九州", "長崎県": "九州", "熊本県": "九州", "大分県": "九州", "鹿児島県": "九州",
}
CAT_COLS = ["stage", "home", "away", "stadium", "pref", "weekday", "weather_main", "referee"]


# ------------------------------------------------------------------ データ
def load_all():
    tr = pd.read_csv(D / "train_merged.csv", parse_dates=["date"])
    te = pd.read_csv(D / "test_merged.csv", parse_dates=["date"])
    te["y"] = np.nan
    df = pd.concat([tr, te], ignore_index=True)
    df["humidity"] = pd.to_numeric(df["humidity"].astype(str).str.rstrip("%"), errors="coerce")
    df["month"] = df["date"].dt.month
    df["doy"] = df["date"].dt.dayofyear
    df["occ"] = df["y"] / df["capacity"]
    df = df.merge(pd.read_csv(D / "standings.csv"), on="id", how="left")
    return df.sort_values(["date", "id"]).reset_index(drop=True)


def schedule_all():
    """全試合の日程（観客数のない 2014_add・無観客試合も含む）。ホーム最終戦などの判定用。"""
    import unicodedata
    fr = []
    for f in ["train.csv", "train_add.csv", "test.csv", "2014_add.csv"]:
        t = pd.read_csv(D / f)[["id", "year", "gameday", "home"]]
        fr.append(t)
    s = pd.concat(fr, ignore_index=True)
    s["home"] = s["home"].map(lambda v: unicodedata.normalize("NFKC", v).strip())
    md = s["gameday"].str.extract(r"(\d{2})/(\d{2})")
    s["date"] = pd.to_datetime(s["year"].astype(str) + "-" + md[0] + "-" + md[1])
    return s


# ------------------------------------------------------------------ 過去の実績（カットオフ対応）
def _asof(df, hist, keys, cols, lookup):
    """keys が同じ hist 行のうち、lookup 日より前の最後の行の cols を持ってくる。"""
    left = df[keys].copy()
    left["_lk"] = lookup.values
    left["_i"] = np.arange(len(df))
    left = left.sort_values("_lk")
    h = hist[keys + ["date"] + cols].rename(columns={"date": "_lk"}).sort_values("_lk")
    for k in keys:
        left[k] = left[k].astype(str)
        h[k] = h[k].astype(str)
    m = pd.merge_asof(left, h, on="_lk", by=keys, allow_exact_matches=False)
    return m.sort_values("_i")[cols].set_index(df.index)


def lookup_dates(df, cutoff, mode="expanding"):
    """過去の実績を「いつまでのデータで」作るか。
    expanding: 試合日の直前まで（ただしカットオフ以降はカットオフまで）
    stale    : 本番の鮮度に揃える。後半戦（8/1以降）の行はその年の 8/1 まで、前半戦の行は前年末まで"""
    d = df["date"]
    if mode == "stale":
        aug1 = pd.to_datetime(df["year"].astype(str) + "-08-01")
        jan1 = pd.to_datetime(df["year"].astype(str) + "-01-01")
        lk = aug1.where(d >= aug1, jan1)
    else:
        lk = d
    return lk.where(lk < cutoff, cutoff)


def past_stats(df, keys, val, name, cutoff, last_n=None, ewm=None, mode="expanding"):
    """keys ごとの val の「過去の平均・件数（・直近 n 件の平均・指数平滑）」。
    行ごとに lookup = min(試合日, cutoff) より前の観客数だけを使う。"""
    hist = df[df["y"].notna()].sort_values("date").copy()
    g = hist.groupby(keys)[val]
    hist[name] = g.cumsum() / (g.cumcount() + 1)
    hist[name + "_n"] = g.cumcount() + 1
    cols = [name, name + "_n"]
    if last_n:
        hist[f"{name}_last{last_n}"] = g.transform(lambda s: s.rolling(last_n, min_periods=1).mean())
        cols.append(f"{name}_last{last_n}")
    if ewm:
        hist[f"{name}_ewm"] = g.transform(lambda s: s.ewm(alpha=ewm).mean())
        cols.append(f"{name}_ewm")
    return _asof(df, hist, keys, cols, lookup_dates(df, cutoff, mode))


def prev_season(df, team_col, val, name, by_home=True):
    """前年シーズン全体の平均（カットオフより前なので常に使える）。"""
    side = "home" if by_home else "away"
    h = df[df["y"].notna()].groupby([side, "year"])[val].mean().rename(name).reset_index()
    h["year"] = h["year"] + 1
    h = h.rename(columns={side: team_col})
    return df[[team_col, "year"]].merge(h, on=[team_col, "year"], how="left")[name].values


# ------------------------------------------------------------------ 特徴量
DEFAULT_CFG = dict(
    hist=True,           # ホーム/アウェイ/スタジアム/カードの過去の実績（基本セット）
    hist_season=False,   # 同じシーズン内の過去平均
    hist_last=False,     # 直近5試合・指数平滑
    hist_prev=False,     # 前年シーズン平均・前年のディビジョン
    standings=True,      # 試合日時点の順位
    distance=False,      # 本拠地間の距離
    away_fanbase=False,  # アウェイチームのホームでの集客力
    schedule=False,      # 前回ホーム試合からの日数・同じ日の同じ県の試合数
    calendar=False,      # 連休（GW・お盆・シルバーウィーク）、ナイター
    season_pos=False,    # ホーム開幕戦・ホーム最終戦・何試合目のホーム戦か
    region=False,        # 同じ地方どうし、普段より小さい会場
    tv=True, weather=True, referee=True,
    hist_mode="expanding",  # 過去の実績の鮮度（lookup_dates を参照）
    drop=(),             # 外す列
)


def build_features(df, cutoff, cfg=None):
    cfg = {**DEFAULT_CFG, **(cfg or {})}
    X = pd.DataFrame(index=df.index)
    for c in ["capacity", "kickoff_hour", "section", "last_section", "holiday", "same_pref", "main_stadium",
              "year", "month", "doy"]:
        X[c] = df[c].astype(float)
    X["dow"] = df["date"].dt.dayofweek.astype(float)
    X["is_saturday"] = (df["weekday"] == "土").astype(float)
    X["weekend_or_holiday"] = (df["weekday"].isin(["土", "日"]) | (df["holiday"] == 1)).astype(float)
    cats = ["stage", "home", "away", "stadium", "pref", "weekday"]
    if cfg["tv"]:
        for c in ["tv_count", "tv_nhk_general", "tv_nhk_bs", "tv_free_count", "tv_recorded"]:
            X[c] = df[c].astype(float)
    if cfg["weather"]:
        X["temperature"] = df["temperature"].astype(float)
        X["humidity"] = df["humidity"].astype(float)
        X["weather_rain"] = df["weather_rain"].astype(float)
        cats.append("weather_main")
    if cfg["referee"]:
        cats.append("referee")
    for c in cats:
        X[c] = pd.Categorical(df[c].astype(str))

    if cfg["hist"]:
        h = past_stats(df, ["home", "stage"], "y", "home_past_y", cutoff, mode=cfg["hist_mode"])
        X["home_past_y"], X["home_past_n"] = h["home_past_y"], h["home_past_y_n"]
        X["home_past_occ"] = past_stats(df, ["home", "stage"], "occ", "home_past_occ", cutoff, mode=cfg["hist_mode"])["home_past_occ"]
        X["away_past_y"] = past_stats(df, ["away", "stage"], "y", "away_past_y", cutoff, mode=cfg["hist_mode"])["away_past_y"]
        X["card_past_y"] = past_stats(df, ["home", "away"], "y", "card_past_y", cutoff, mode=cfg["hist_mode"])["card_past_y"]
        X["stadium_past_occ"] = past_stats(df, ["stadium"], "occ", "stadium_past_occ", cutoff, mode=cfg["hist_mode"])["stadium_past_occ"]
        X["expected_y"] = X["capacity"] * X["home_past_occ"]
    if cfg["hist_season"]:
        h = past_stats(df, ["home", "year"], "occ", "home_season_occ", cutoff, mode=cfg["hist_mode"])
        X["home_season_occ"], X["home_season_n"] = h["home_season_occ"], h["home_season_occ_n"]
        X["away_season_y"] = past_stats(df, ["away", "year"], "y", "away_season_y", cutoff, mode=cfg["hist_mode"])["away_season_y"]
    if cfg["hist_last"]:
        h = past_stats(df, ["home", "stage"], "occ", "home_occ", cutoff, last_n=5, ewm=0.2, mode=cfg["hist_mode"])
        X["home_occ_last5"], X["home_occ_ewm"] = h["home_occ_last5"], h["home_occ_ewm"]
    if cfg["hist_prev"]:
        X["home_prev_occ"] = prev_season(df, "home", "occ", "home_prev_occ")
        X["home_prev_y"] = prev_season(df, "home", "y", "home_prev_y")
        X["away_prev_y"] = prev_season(df, "away", "y", "away_prev_y", by_home=False)
        st_prev = df.groupby(["home", "year"])["stage"].first().reset_index()
        st_prev["year"] += 1
        st_prev = st_prev.rename(columns={"stage": "prev_stage"})
        ps = df[["home", "year", "stage"]].merge(st_prev, on=["home", "year"], how="left")
        X["promoted"] = ((ps["prev_stage"] == "J2") & (ps["stage"] == "J1")).astype(float).values
        X["relegated"] = ((ps["prev_stage"] == "J1") & (ps["stage"] == "J2")).astype(float).values
    if cfg["standings"]:
        for c in [c for c in df.columns if c.startswith(("home_", "away_")) and c not in ("home", "away")
                  and c.split("_", 1)[1] in ("rank", "pts", "played", "ppg", "gd", "behind_leader", "title_alive",
                                              "form5", "vs_releg_line", "vs_promo_line")]:
            X[c] = df[c].astype(float)
        for c in ["remaining_games", "rank_sum", "top_clash"]:
            X[c] = df[c].astype(float)
        late = df["remaining_games"] <= 8
        X["title_race"] = (((df["home_title_alive"] == 1) | (df["away_title_alive"] == 1)) & late).astype(float)
    if cfg["distance"]:
        home_pref = df.groupby("home")["pref"].agg(lambda s: s.value_counts().idxmax())
        ap = df["away"].map(home_pref)
        a = np.array([PREF_LL.get(p, (np.nan, np.nan)) for p in ap])
        b = np.array([PREF_LL.get(p, (np.nan, np.nan)) for p in df["pref"]])
        lat1, lon1, lat2, lon2 = map(np.radians, [a[:, 0], a[:, 1], b[:, 0], b[:, 1]])
        h = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
        X["away_distance_km"] = 6371 * 2 * np.arcsin(np.sqrt(h))
        kanto = {"茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県"}
        X["away_from_kanto_to_kanto"] = (ap.isin(kanto) & df["pref"].isin(kanto)).astype(float).values
    if cfg["away_fanbase"]:
        # アウェイチームがホームで集める観客（同じディビジョン、カットオフ前）
        h = df[df["y"].notna()].sort_values("date").copy()
        g = h.groupby(["home", "stage"])["y"]
        h["fan"] = g.cumsum() / (g.cumcount() + 1)
        h = h.drop(columns="away").rename(columns={"home": "away"})
        lookup = lookup_dates(df, cutoff, cfg["hist_mode"])
        X["away_fanbase"] = _asof(df, h, ["away", "stage"], ["fan"], lookup)["fan"].values
    if cfg["schedule"]:
        s = df.sort_values("date")
        X["days_since_home"] = s.groupby("home")["date"].diff().dt.days.reindex(df.index)
        long = pd.concat([df[["id", "date"]].assign(team=df["home"], side="h"),
                          df[["id", "date"]].assign(team=df["away"], side="a")]).sort_values("date")
        long["rest"] = long.groupby("team")["date"].diff().dt.days
        rest = long.pivot_table(index="id", columns="side", values="rest", aggfunc="first")
        X["home_rest_days"] = df["id"].map(rest["h"]).astype(float).values
        X["away_rest_days"] = df["id"].map(rest["a"]).astype(float).values
        X["same_day_same_pref"] = df.groupby(["date", "pref"])["id"].transform("count").astype(float) - 1
        X["same_day_games"] = df.groupby("date")["id"].transform("count").astype(float)
    if cfg["calendar"]:
        m, d = df["date"].dt.month, df["date"].dt.day
        X["gw"] = (((m == 4) & (d >= 29)) | ((m == 5) & (d <= 6))).astype(float)
        X["obon"] = ((m == 8) & (d >= 12) & (d <= 17)).astype(float)
        X["silver_week"] = ((m == 9) & (d >= 19) & (d <= 24) & (df["holiday"] == 1)).astype(float)
        X["summer_vacation"] = (((m == 7) & (d >= 20)) | (m == 8)).astype(float)
        X["night_game"] = (df["kickoff_hour"] >= 18).astype(float)
        X["weekday_night"] = ((~df["weekday"].isin(["土", "日"])) & (df["holiday"] == 0)).astype(float)
    if cfg["season_pos"]:
        sch = schedule_all()
        sch = sch.sort_values("date")
        sch["home_game_no"] = sch.groupby(["home", "year"]).cumcount() + 1
        sch["home_games_total"] = sch.groupby(["home", "year"])["id"].transform("count")
        m = df[["id"]].merge(sch[["id", "home_game_no", "home_games_total"]], on="id", how="left")
        X["home_game_no"] = m["home_game_no"].values.astype(float)
        X["home_last_game"] = (m["home_game_no"] == m["home_games_total"]).values.astype(float)
        X["home_first_game"] = (m["home_game_no"] == 1).values.astype(float)
    if cfg["region"]:
        home_pref = df.groupby("home")["pref"].agg(lambda s: s.value_counts().idxmax())
        ar = df["away"].map(home_pref).map(REGION)
        X["same_region"] = (ar == df["pref"].map(REGION)).astype(float)
        X["region"] = pd.Categorical(df["pref"].map(REGION).astype(str))
        main_cap = df.groupby("home")["capacity"].agg(lambda s: s.value_counts().idxmax())
        X["cap_ratio_main"] = df["capacity"] / df["home"].map(main_cap)
    for c in cfg["drop"]:
        if c in X:
            X = X.drop(columns=c)
    return X


# ------------------------------------------------------------------ 目的変数の変換
def t_forward(kind, y, X):
    if kind == "occ":
        return y / X["capacity"].values
    if kind == "log":
        return np.log1p(y)
    if kind == "sqrt":
        return np.sqrt(y)
    if kind == "ratio_expected":  # 期待観客数に対する倍率
        return y / X["expected_y"].fillna(X["capacity"] * 0.4).values
    return y


def t_inverse(kind, p, X):
    if kind == "occ":
        return np.clip(p, 0, 1.05) * X["capacity"].values
    if kind == "log":
        return np.expm1(p)
    if kind == "sqrt":
        return np.clip(p, 0, None) ** 2
    if kind == "ratio_expected":
        return np.clip(p, 0, None) * X["expected_y"].fillna(X["capacity"] * 0.4).values
    return p


# ------------------------------------------------------------------ モデル
LGB_PARAMS = dict(n_estimators=5000, learning_rate=0.03, num_leaves=31, min_child_samples=20, subsample=0.8,
                  subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, verbose=-1, n_jobs=4)


def fit_predict(model, Xtr, ytr, Xva, seed, params=None):
    """早期終了には学習データの最後の15%（時間順）を使う。検証データは見ない。
    返り値: (予測, 使った木の本数)"""
    params = params or {}
    n = len(Xtr)
    order = np.arange(n)  # Xtr は時間順に並んでいる
    cut = int(n * 0.85)
    fit, es = order[:cut], order[cut:]
    if model == "lgb":
        import lightgbm as lgb
        p = {**LGB_PARAMS, **params, "random_state": seed}
        if "fixed_rounds" in p:
            r = p.pop("fixed_rounds")
            m = lgb.LGBMRegressor(**{**p, "n_estimators": r}).fit(Xtr, ytr)
            return m.predict(Xva), r
        m = lgb.LGBMRegressor(**p)
        m.fit(Xtr.iloc[fit], ytr[fit], eval_set=[(Xtr.iloc[es], ytr[es])],
              callbacks=[lgb.early_stopping(200, verbose=False)])
        best = m.best_iteration_
        m2 = lgb.LGBMRegressor(**{**p, "n_estimators": int(best * 1.1) + 1}).fit(Xtr, ytr)  # 全データで学習し直す
        return m2.predict(Xva), best
    if model == "cat":
        from catboost import CatBoostRegressor
        cats = [c for c in Xtr.columns if str(Xtr[c].dtype) == "category"]
        A, B = Xtr.copy(), Xva.copy()
        for c in cats:
            A[c], B[c] = A[c].astype(str), B[c].astype(str)
        p = dict(iterations=5000, learning_rate=0.05, depth=6, loss_function="RMSE", verbose=0, random_seed=seed,
                 allow_writing_files=False,
                 thread_count=4)
        p.update(params)
        m = CatBoostRegressor(**p, cat_features=cats)
        m.fit(A.iloc[fit], ytr[fit], eval_set=(A.iloc[es], ytr[es]), early_stopping_rounds=200)
        best = m.get_best_iteration() + 1
        p2 = {**p, "iterations": int(best * 1.1) + 1}
        m2 = CatBoostRegressor(**p2, cat_features=cats).fit(A, ytr)
        return m2.predict(B), best
    if model == "xgb":
        import xgboost as xgb
        p = dict(n_estimators=5000, learning_rate=0.03, max_depth=6, subsample=0.8, colsample_bytree=0.8,
                 enable_categorical=True, tree_method="hist", random_state=seed, n_jobs=4, early_stopping_rounds=200)
        p.update(params)
        m = xgb.XGBRegressor(**p)
        m.fit(Xtr.iloc[fit], ytr[fit], eval_set=[(Xtr.iloc[es], ytr[es])], verbose=False)
        best = m.best_iteration + 1
        p2 = {**p, "n_estimators": int(best * 1.1) + 1}
        p2.pop("early_stopping_rounds")
        m2 = xgb.XGBRegressor(**p2).fit(Xtr, ytr)
        return m2.predict(Xva), best
    if model == "ridge":
        from sklearn.compose import ColumnTransformer
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import Ridge
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import OneHotEncoder, StandardScaler
        cats = [c for c in Xtr.columns if str(Xtr[c].dtype) == "category"]
        nums = [c for c in Xtr.columns if c not in cats]
        A, B = Xtr.copy(), Xva.copy()
        for c in cats:
            A[c], B[c] = A[c].astype(str), B[c].astype(str)
        pre = ColumnTransformer([
            ("n", make_pipeline(SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True),
                                StandardScaler()), nums),
            ("c", OneHotEncoder(handle_unknown="ignore", min_frequency=3), cats)])
        m = make_pipeline(pre, Ridge(alpha=params.get("alpha", 3.0))).fit(A, ytr)
        return m.predict(B), 0
    raise ValueError(model)


# ------------------------------------------------------------------ 評価と記録
_FEAT_CACHE = {}


def features_for(df, cutoff, cfg):
    key = (str(cutoff), json.dumps(cfg, sort_keys=True, default=str))
    if key not in _FEAT_CACHE:
        _FEAT_CACHE[key] = build_features(df, cutoff, cfg)
    return _FEAT_CACHE[key]


def evaluate(df, cfg=None, model="lgb", target="occ", params=None, seeds=(0, 1, 2), return_preds=False, by_stage=False):
    """各 fold で学習→後半戦を予測し、RMSE を返す。seeds の平均予測で評価。"""
    out, preds = {}, {}
    for fold, cutoff in FOLDS.items():
        X = features_for(df, cutoff, cfg)
        tr = (df["y"].notna() & (df["date"] < cutoff)).values
        va = (df["y"].notna() & (df["date"] >= cutoff) & (df["year"] == cutoff.year)).values
        Xtr, Xva = X[tr], X[va]
        ytr = t_forward(target, df.loc[tr, "y"].values, Xtr)
        ps = []
        for s in seeds:
            if by_stage:  # J1 と J2 で別々に学習
                p = np.zeros(len(Xva))
                for st in ("J1", "J2"):
                    mt = (df.loc[tr, "stage"] == st).values
                    mv = (df.loc[va, "stage"] == st).values
                    p[mv], _ = fit_predict(model, Xtr[mt], ytr[mt], Xva[mv], s, params)
            else:
                p, _ = fit_predict(model, Xtr, ytr, Xva, s, params)
            ps.append(t_inverse(target, p, Xva))
        p = np.mean(ps, axis=0)
        yva = df.loc[va, "y"].values
        out[fold] = float(np.sqrt(np.mean((yva - p) ** 2)))
        preds[fold] = pd.Series(p, index=df.index[va])
    out["mean"] = float(np.mean([out[f] for f in FOLDS]))
    return (out, preds) if return_preds else out


def log(exp_id, group, name, desc, res, cfg=None, model="lgb", target="occ", params=None, note=""):
    row = {"exp_id": exp_id, "time": time.strftime("%Y-%m-%d %H:%M"), "group": group, "name": name,
           "description": desc, "H2_2012": round(res["H2_2012"], 1), "H2_2013": round(res["H2_2013"], 1),
           "mean": round(res["mean"], 1), "model": model, "target": target,
           "cfg": json.dumps({k: v for k, v in (cfg or {}).items()}, ensure_ascii=False, default=str),
           "params": json.dumps(params or {}, ensure_ascii=False), "note": note}
    pd.DataFrame([row]).to_csv(LOG_CSV, mode="a", header=not LOG_CSV.exists(), index=False)
    print(f"[{exp_id}] {name}: H2_2012={res['H2_2012']:.0f} H2_2013={res['H2_2013']:.0f} mean={res['mean']:.0f}", flush=True)
    return row


def predict_test(df, cfg=None, model="lgb", target="occ", params=None, seeds=(0, 1, 2)):
    X = features_for(df, TEST_CUTOFF, cfg)
    tr = df["y"].notna().values
    te = df["y"].isna().values
    ytr = t_forward(target, df.loc[tr, "y"].values, X[tr])
    ps = [t_inverse(target, fit_predict(model, X[tr], ytr, X[te], s, params)[0], X[te]) for s in seeds]
    return pd.Series(np.mean(ps, axis=0), index=df.index[te])
