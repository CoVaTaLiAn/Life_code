/**
 * Gmail 自動振り分け + 毎朝の要約メール（Google Apps Script）
 *
 * AIを使わずルールだけで動くため、Claudeのトークンは消費しない。
 * 使い方は同じフォルダの README.md を参照。
 */

// ===== 設定（ここを編集すれば振り分けルールを変えられる） =====

const CONFIG = {
  // 要約メールの送り先（空なら自分宛て）
  summaryTo: '',
  // 要約を送る時刻（0-23時）
  summaryHour: 7,
  // 1回の実行で処理する最大スレッド数
  maxThreads: 100,

  labels: {
    pick: '転職/注目',
    jobOther: '転職/その他',
    ad: '広告',
    notice: '通知',
    check: '要確認',
    reply: '要返信',
    keep: '残す',
  },

  // ルールで決まらないメールだけAIに判定させる（APIキー未設定ならAIは使わない）
  ai: {
    model: 'claude-opus-5-5', // 安くしたいなら 'claude-haiku-5-5'（約1/40の料金）
    effort: 'low',
    maxPerRun: 20, // 1回の実行でAIに回す上限（費用の暴走防止）
    bodyChars: 800, // AIに渡す本文の文字数
  },

  // AIに伝える判断基準（Obsidian「輝く環境.md」より）
  profile: [
    '受信者はデータサイエンティスト志望の転職活動中の人。',
    '注目すべき求人：データサイエンス・データ分析・ヘルスケアIT・医療・ゲノム領域、年収480万円以上、横浜から通勤90分以内、事業に嘘がない会社。',
    '避けたい求人：営業職、未経験歓迎の大量採用、根性論の社風、事業内容が怪しいもの。',
  ].join('\n'),

  // 転職サイト・エージェント（このどれかから来たら転職メール）
  jobSenders: [
    'bizreach.co.jp', 'doda.jp', 'direct-doda.jp', 'dm-doda.jp', 'persol.co.jp',
    'jac-recruitment.jp', 'openwork.jp', 'signate.jp', 'green-japan.com',
    'en-japan.com', 'r-agent.com', 'mynavi.jp', 'type.jp', 'wantedly.com',
  ],

  // 転職メールのうち、件名か本文冒頭にこれがあれば「注目」
  pickKeywords: [
    'データサイエンティスト', 'データサイエンス', 'データ分析', 'データアナリスト',
    '機械学習', 'AI', 'ヘルスケア', '医療', 'メディカル', 'ライフサイエンス',
    'ゲノム', '臨床', '面談確約', '公募',
    '野村総合研究所', 'SOMPO', 'メディア情報システム', 'GenMine', 'ビー・エム・エル',
    'エムスリー', 'シンクデータ',
  ],

  // 注目キーワードがあってもこれがあれば「その他」に落とす
  dropKeywords: [
    '未経験', '同期10名', '看護師', '医療事務', '営業職', '医療機器営業',
    '職務経歴書の書き方', '求人の探し方', '面談で話すべきこと', 'アンケート',
  ],

  // 広告として既読アーカイブする送信元
  adSenders: [
    'audible.co.jp', 'amazon.co.jp', 'amazonmusic.com', 'xmind.ai',
    'marketing.', 'newsletter', 'news@', 'store-news@',
  ],

  // 既読だけにして受信箱に残す送信元（領収書・自動タスク通知など）
  noticeSenders: ['tm.openai.com', 'invoice@', 'mail.anthropic.com'],

  // 未読のまま残して要約で知らせる（セキュリティ系）
  checkKeywords: [
    'Security alert', 'セキュリティ', 'new device', 'ログイン', 'shared some Google Account data',
    'パスワード', '不正',
  ],
};

// ===== 初回だけ手動で実行する =====

function setup() {
  Object.values(CONFIG.labels).forEach(getOrCreateLabel_);
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger('sortInbox').timeBased().everyHours(1).create();
  ScriptApp.newTrigger('sendSummary').timeBased().everyDays(1).atHour(CONFIG.summaryHour).create();
  sortInbox();
}

// ===== 1時間ごと：振り分け =====

function sortInbox() {
  const L = {};
  Object.entries(CONFIG.labels).forEach(([k, name]) => (L[k] = getOrCreateLabel_(name)));

  const threads = GmailApp.search('in:inbox is:unread has:nouserlabels', 0, CONFIG.maxThreads);
  const log = loadLog_();
  const apiKey = PropertiesService.getScriptProperties().getProperty('ANTHROPIC_API_KEY');
  const rows = [];
  let aiCalls = 0;

  threads.forEach(thread => {
    const msg = thread.getMessages().slice(-1)[0];
    const from = msg.getFrom().toLowerCase();
    const subject = msg.getSubject() || '';
    const body = msg.getPlainBody();
    const text = subject + ' ' + body.slice(0, 1500);
    let kind = classify_(from, subject, text);
    let by = 'ルール';
    let reason = '';

    if (kind === 'summary') {
      thread.addLabel(L.notice); // 自分の要約メールは未読のまま「通知」に入れるだけ
      return;
    }

    if (kind === 'none') {
      if (!apiKey || aiCalls >= CONFIG.ai.maxPerRun) {
        log.counts.other++;
        return; // 次の実行に回す（ラベルを付けないので再度対象になる）
      }
      aiCalls++;
      const r = classifyWithAI_(apiKey, msg.getFrom(), subject, body.slice(0, CONFIG.ai.bodyChars));
      kind = r.category;
      reason = r.reason;
      by = 'AI';
    }

    rows.push([new Date(), by, CONFIG.labels[kind] || kind, reason, msg.getFrom(), subject,
      'https://mail.google.com/mail/u/0/#all/' + thread.getId()]);

    switch (kind) {
      case 'pick':
        thread.addLabel(L.pick);
        log.pick.push({ s: subject, f: shortFrom_(msg.getFrom()), id: thread.getId() });
        break;
      case 'jobOther':
        thread.addLabel(L.jobOther).markRead().moveToArchive();
        log.counts.jobOther++;
        break;
      case 'ad':
        thread.addLabel(L.ad).markRead().moveToArchive();
        log.counts.ad++;
        break;
      case 'notice':
        thread.addLabel(L.notice).markRead();
        log.counts.notice++;
        break;
      case 'check':
        thread.addLabel(L.check);
        log.check.push({ s: subject, f: shortFrom_(msg.getFrom()), id: thread.getId() });
        break;
      case 'reply':
        thread.addLabel(L.reply);
        log.reply = log.reply || [];
        log.reply.push({ s: subject, f: shortFrom_(msg.getFrom()), id: thread.getId() });
        break;
      default: // keep：受信箱に未読のまま残す。再判定しないようラベルだけ付ける
        thread.addLabel(L.keep);
        log.counts.keep = (log.counts.keep || 0) + 1;
    }
  });

  appendToSheet_(rows);
  saveLog_(log);
}

// ===== AI判定（ルールに当たらないメールだけ） =====

const AI_CATEGORIES = ['pick', 'jobOther', 'ad', 'notice', 'check', 'reply', 'keep'];

function classifyWithAI_(apiKey, from, subject, body) {
  const prompt = [
    CONFIG.profile,
    '',
    '次のメールを1つのカテゴリに分類し、理由を30字以内の日本語で書いてください。',
    'pick=条件に合う求人・スカウト / jobOther=条件に合わない転職関連 / ad=広告・宣伝・メルマガ /',
    'notice=領収書や自動通知など読むだけでよいもの / check=セキュリティ・ログイン・支払い異常など本人確認が要るもの /',
    'reply=人から届き返信が必要なもの / keep=それ以外で本人が読むべきもの',
    '',
    '差出人: ' + from,
    '件名: ' + subject,
    '本文冒頭:',
    body,
  ].join('\n');

  const payload = {
    model: CONFIG.ai.model,
    max_tokens: 2048,
    output_config: {
      effort: CONFIG.ai.effort,
      format: {
        type: 'json_schema',
        schema: {
          type: 'object',
          properties: {
            category: { type: 'string', enum: AI_CATEGORIES },
            reason: { type: 'string' },
          },
          required: ['category', 'reason'],
          additionalProperties: false,
        },
      },
    },
    messages: [{ role: 'user', content: prompt }],
  };
  const headers = { 'x-api-key': apiKey, 'anthropic-version': '2026-10-21' };
  if (CONFIG.ai.model !== 'claude-haiku-5-5') {
    // 安全側で断られたとき、別モデルで自動再試行する（Haiku は非対応）
    payload.fallbacks = 'default';
    headers['anthropic-beta'] = 'server-side-fallback-2026-07-01';
  }

  try {
    const res = UrlFetchApp.fetch('https://api.anthropic.com/v1/messages', {
      method: 'post',
      contentType: 'application/json',
      headers: headers,
      payload: JSON.stringify(payload),
      muteHttpExceptions: true,
    });
    const data = JSON.parse(res.getContentText());
    if (res.getResponseCode() !== 200) return { category: 'keep', reason: 'AIエラー ' + res.getResponseCode() };
    if (data.stop_reason === 'refusal') return { category: 'keep', reason: 'AIが判定を拒否' };
    const textBlock = (data.content || []).find(b => b.type === 'text');
    const out = JSON.parse(textBlock.text);
    if (!AI_CATEGORIES.includes(out.category)) return { category: 'keep', reason: '不明なカテゴリ' };
    return out;
  } catch (e) {
    return { category: 'keep', reason: 'AI呼び出し失敗: ' + e.message.slice(0, 40) };
  }
}

// ===== 判定結果の記録（スプレッドシート） =====

function appendToSheet_(rows) {
  if (!rows.length) return;
  const props = PropertiesService.getScriptProperties();
  let id = props.getProperty('SHEET_ID');
  let ss;
  if (id) {
    ss = SpreadsheetApp.openById(id);
  } else {
    ss = SpreadsheetApp.create('Gmail振り分けログ');
    ss.getSheets()[0].appendRow(['日時', '判定者', 'カテゴリ', 'AIの理由', '差出人', '件名', 'リンク']);
    props.setProperty('SHEET_ID', ss.getId());
  }
  const sh = ss.getSheets()[0];
  sh.getRange(sh.getLastRow() + 1, 1, rows.length, rows[0].length).setValues(rows);
}

function classify_(from, subject, text) {
  // 送信元は小文字で比較、キーワードは大文字小文字を区別（"AI" が "mail" に当たらないように）
  const fromHas = list => list.some(k => from.includes(k.toLowerCase()));
  const has = (list, s) => list.some(k => s.includes(k));

  if (subject.startsWith('[Gmail要約]')) return 'summary';
  if (fromHas(CONFIG.jobSenders)) {
    if (has(CONFIG.pickKeywords, text) && !has(CONFIG.dropKeywords, text)) return 'pick';
    return 'jobOther';
  }
  if (fromHas(CONFIG.noticeSenders)) return 'notice';
  if (has(CONFIG.checkKeywords, subject)) return 'check';
  if (fromHas(CONFIG.adSenders)) return 'ad';
  return 'none';
}

// ===== 毎朝：要約メール =====

function sendSummary() {
  const log = loadLog_();
  const link = id => 'https://mail.google.com/mail/u/0/#all/' + id;
  const c = log.counts;
  const lines = [];

  lines.push('【転職/注目】' + log.pick.length + '件');
  log.pick.forEach(m => lines.push('- ' + m.s + '（' + m.f + '）\n  ' + link(m.id)));
  if (!log.pick.length) lines.push('- なし');

  const reply = log.reply || [];
  lines.push('', '【要返信】' + reply.length + '件');
  reply.forEach(m => lines.push('- ' + m.s + '（' + m.f + '）\n  ' + link(m.id)));
  if (!reply.length) lines.push('- なし');

  lines.push('', '【要確認】' + log.check.length + '件');
  log.check.forEach(m => lines.push('- ' + m.s + '（' + m.f + '）\n  ' + link(m.id)));
  if (!log.check.length) lines.push('- なし');

  lines.push('', '【自動処理】',
    '- 転職/その他：' + c.jobOther + '件（既読・アーカイブ）',
    '- 広告：' + c.ad + '件（既読・アーカイブ）',
    '- 通知：' + c.notice + '件（既読）',
    '- 残す：' + (c.keep || 0) + '件（受信箱に未読のまま）',
    '- 未判定：' + c.other + '件（AIキー未設定または上限超え。次回に再判定）');

  const sheetId = PropertiesService.getScriptProperties().getProperty('SHEET_ID');
  if (sheetId) lines.push('', '判定ログ: https://docs.google.com/spreadsheets/d/' + sheetId);

  const to = CONFIG.summaryTo || Session.getActiveUser().getEmail();
  const date = Utilities.formatDate(new Date(), 'Asia/Tokyo', 'M/d');
  GmailApp.sendEmail(to, '[Gmail要約] ' + date + ' 注目' + log.pick.length + '件', lines.join('\n'));

  PropertiesService.getScriptProperties().deleteProperty('log');
}

// ===== 補助 =====

function getOrCreateLabel_(name) {
  return GmailApp.getUserLabelByName(name) || GmailApp.createLabel(name);
}

function shortFrom_(from) {
  return from.replace(/<.*>/, '').replace(/"/g, '').trim() || from;
}

function loadLog_() {
  const raw = PropertiesService.getScriptProperties().getProperty('log');
  return raw ? JSON.parse(raw)
    : { pick: [], check: [], reply: [], counts: { jobOther: 0, ad: 0, notice: 0, keep: 0, other: 0 } };
}

function saveLog_(log) {
  // プロパティの容量上限（9KB）を超えないよう、件名は60文字・各一覧は直近20件まで
  const trim = list => list.slice(-20).map(m => ({ ...m, s: m.s.slice(0, 60) }));
  log.pick = trim(log.pick);
  log.check = trim(log.check);
  log.reply = trim(log.reply || []);
  PropertiesService.getScriptProperties().setProperty('log', JSON.stringify(log));
}
