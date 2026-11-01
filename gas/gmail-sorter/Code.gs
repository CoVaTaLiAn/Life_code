/**
 * Gmail 自動振り分け + 毎朝の要約メール（Google Apps Script）
 *
 * 判定は3段階：
 *   1. ルール（送信元・キーワード、あなたが過去に決めた送信元）… 無料
 *   2. ルールで決まらないものだけ AI（Claude）が判定
 *   3. AI も自信がないものは「要判断」ラベルを付けて、あなたに聞く
 * あなたが「要判断」のメールにカテゴリのラベルを付けると、その送信元を覚えて次から自動で振り分ける。
 * 判定結果はすべてスプレッドシート「Gmail振り分けログ」に残る。
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
    ask: '要判断',
  },

  // ルールで決まらないメールだけAIに判定させる（APIキー未設定ならAIは使わず、すべて「要判断」になる）
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

  // 既読にしてゴミ箱へ移す送信元（30日でGmailが完全に削除する）
  trashSenders: ['contract-one.com'],

  // 既読だけにして受信箱に残す送信元（領収書・自動タスク通知など）
  noticeSenders: ['tm.openai.com', 'invoice@', 'mail.anthropic.com', 'linkedin.com'],

  // 未読のまま残して要約で知らせる（セキュリティ系）
  checkKeywords: [
    'Security alert', 'セキュリティ', 'new device', 'ログイン', 'shared some Google Account data',
    'パスワード', '不正',
  ],
};

// あなたが付けられるカテゴリ（「要判断」以外）
const KINDS = ['pick', 'jobOther', 'ad', 'notice', 'check', 'reply', 'keep'];

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
  const log = loadLog_();
  const learned = loadLearned_();
  const rows = [];

  learnFromUser_(L, learned, log, rows);

  const threads = GmailApp.search('in:inbox is:unread has:nouserlabels', 0, CONFIG.maxThreads);
  const apiKey = PropertiesService.getScriptProperties().getProperty('ANTHROPIC_API_KEY');
  let aiCalls = 0;

  threads.forEach(thread => {
    const msg = thread.getMessages().slice(-1)[0];
    const fromRaw = msg.getFrom();
    const subject = msg.getSubject() || '';
    const body = msg.getPlainBody();
    let kind = classify_(fromRaw.toLowerCase(), subject, subject + ' ' + body.slice(0, 1500), learned);
    let by = 'ルール';
    let reason = '';

    if (kind === 'summary') {
      thread.addLabel(L.notice); // 自分の要約メールは未読のまま「通知」に入れるだけ
      return;
    }

    if (kind === 'none') {
      if (apiKey && aiCalls >= CONFIG.ai.maxPerRun) {
        log.counts.other++;
        return; // 上限超え：ラベルを付けずに次の実行に回す
      }
      if (!apiKey) {
        by = 'ルール';
        kind = 'ask';
        reason = 'ルールに当たらない（AIなし）';
      } else {
        by = 'AI';
        aiCalls++;
        const r = classifyWithAI_(apiKey, fromRaw, subject, body.slice(0, CONFIG.ai.bodyChars));
        kind = r.confident ? r.category : 'ask';
        reason = r.confident ? r.reason : 'AIの候補: ' + (CONFIG.labels[r.category] || '-') + '／' + r.reason;
      }
    }

    rows.push(logRow_(by, kind, reason, fromRaw, subject, thread));
    applyKind_(thread, kind, L, log, { s: subject, f: shortFrom_(fromRaw), id: thread.getId(), r: reason });
  });

  appendToSheet_(rows);
  saveLog_(log);
}

// 決まったカテゴリに応じてラベル付け・既読・アーカイブする
function applyKind_(thread, kind, L, log, item) {
  switch (kind) {
    case 'pick':
      thread.addLabel(L.pick);
      log.pick.push(item);
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
    case 'trash':
      thread.markRead().moveToTrash();
      log.counts.trash++;
      break;
    case 'check':
      thread.addLabel(L.check);
      log.check.push(item);
      break;
    case 'reply':
      thread.addLabel(L.reply);
      log.reply.push(item);
      break;
    case 'ask':
      thread.addLabel(L.ask); // 未読のまま受信箱に残し、要約であなたに聞く
      log.ask.push(item);
      break;
    default: // keep：受信箱に未読のまま残す。再判定しないようラベルだけ付ける
      thread.addLabel(L.keep);
      log.counts.keep++;
  }
}

// ===== あなたの判断を覚える =====

// 「要判断」のメールにあなたがカテゴリのラベルを付けていたら、その送信元を覚えて処理する
function learnFromUser_(L, learned, log, rows) {
  const threads = GmailApp.search('label:' + CONFIG.labels.ask, 0, CONFIG.maxThreads);
  let changed = false;

  threads.forEach(thread => {
    const names = thread.getLabels().map(l => l.getName());
    const kind = KINDS.find(k => names.includes(CONFIG.labels[k]));
    if (!kind) return; // まだ答えていない

    const msg = thread.getMessages().slice(-1)[0];
    const addr = senderAddress_(msg.getFrom());
    learned[addr] = kind;
    changed = true;

    thread.removeLabel(L.ask);
    rows.push(logRow_('あなた', kind, '次から ' + addr + ' は自動でこのカテゴリ', msg.getFrom(), msg.getSubject(), thread));
    applyKind_(thread, kind, L, log, { s: msg.getSubject() || '', f: shortFrom_(msg.getFrom()), id: thread.getId() });
  });

  if (changed) PropertiesService.getScriptProperties().setProperty('LEARNED', JSON.stringify(learned));
}

function loadLearned_() {
  const raw = PropertiesService.getScriptProperties().getProperty('LEARNED');
  return raw ? JSON.parse(raw) : {};
}

function senderAddress_(from) {
  const m = from.match(/<([^>]+)>/);
  return (m ? m[1] : from).trim().toLowerCase();
}

// ===== ルール判定 =====

function classify_(from, subject, text, learned) {
  // 送信元は小文字で比較、キーワードは大文字小文字を区別（"AI" が "mail" に当たらないように）
  const fromHas = list => list.some(k => from.includes(k.toLowerCase()));
  const has = (list, s) => list.some(k => s.includes(k));

  if (subject.startsWith('[Gmail要約]')) return 'summary';
  if (fromHas(CONFIG.trashSenders)) return 'trash';
  const addr = senderAddress_(from);
  if (learned && learned[addr]) return learned[addr];
  if (fromHas(CONFIG.jobSenders)) {
    if (has(CONFIG.pickKeywords, text) && !has(CONFIG.dropKeywords, text)) return 'pick';
    return 'jobOther';
  }
  if (fromHas(CONFIG.noticeSenders)) return 'notice';
  if (has(CONFIG.checkKeywords, subject)) return 'check';
  if (fromHas(CONFIG.adSenders)) return 'ad';
  return 'none';
}

// ===== AI判定（ルールに当たらないメールだけ） =====

function classifyWithAI_(apiKey, from, subject, body) {
  const prompt = [
    CONFIG.profile,
    '',
    '次のメールを1つのカテゴリに分類し、理由を30字以内の日本語で書いてください。',
    'pick=条件に合う求人・スカウト / jobOther=条件に合わない転職関連 / ad=広告・宣伝・メルマガ /',
    'notice=領収書や自動通知など読むだけでよいもの / check=セキュリティ・ログイン・支払い異常など本人確認が要るもの /',
    'reply=人から届き返信が必要なもの / keep=それ以外で本人が読むべきもの',
    'confident は、本人に聞かなくても間違いないと言えるときだけ true にしてください。',
    '迷う、情報が足りない、本人の好みや事情しだいで変わる場合は false にしてください。',
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
            category: { type: 'string', enum: KINDS },
            confident: { type: 'boolean' },
            reason: { type: 'string' },
          },
          required: ['category', 'confident', 'reason'],
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

  // 失敗したときは自信なし扱いにして、あなたに聞く
  const unsure = why => ({ category: 'keep', confident: false, reason: why });
  try {
    const res = UrlFetchApp.fetch('https://api.anthropic.com/v1/messages', {
      method: 'post',
      contentType: 'application/json',
      headers: headers,
      payload: JSON.stringify(payload),
      muteHttpExceptions: true,
    });
    if (res.getResponseCode() !== 200) return unsure('AIエラー ' + res.getResponseCode());
    const data = JSON.parse(res.getContentText());
    if (data.stop_reason === 'refusal') return unsure('AIが判定を拒否');
    const textBlock = (data.content || []).find(b => b.type === 'text');
    const out = JSON.parse(textBlock.text);
    if (!KINDS.includes(out.category)) return unsure('不明なカテゴリ');
    return out;
  } catch (e) {
    return unsure('AI呼び出し失敗: ' + String(e.message).slice(0, 40));
  }
}

// ===== 判定結果の記録（スプレッドシート） =====

function logRow_(by, kind, reason, from, subject, thread) {
  const name = kind === 'trash' ? '削除' : (CONFIG.labels[kind] || kind);
  return [new Date(), by, name, reason, from, subject || '',
    'https://mail.google.com/mail/u/0/#all/' + thread.getId()];
}

function appendToSheet_(rows) {
  if (!rows.length) return;
  const props = PropertiesService.getScriptProperties();
  const id = props.getProperty('SHEET_ID');
  let ss;
  if (id) {
    ss = SpreadsheetApp.openById(id);
  } else {
    ss = SpreadsheetApp.create('Gmail振り分けログ');
    ss.getSheets()[0].appendRow(['日時', '判定者', 'カテゴリ', '理由', '差出人', '件名', 'リンク']);
    props.setProperty('SHEET_ID', ss.getId());
  }
  const sh = ss.getSheets()[0];
  sh.getRange(sh.getLastRow() + 1, 1, rows.length, rows[0].length).setValues(rows);
}

// ===== 毎朝：要約メール =====

function sendSummary() {
  const log = loadLog_();
  const link = id => 'https://mail.google.com/mail/u/0/#all/' + id;
  const c = log.counts;
  const lines = [];
  const section = (title, list, withReason) => {
    lines.push('【' + title + '】' + list.length + '件');
    list.forEach(m => lines.push('- ' + m.s + '（' + m.f + '）' + (withReason && m.r ? '\n  ' + m.r : '') + '\n  ' + link(m.id)));
    if (!list.length) lines.push('- なし');
    lines.push('');
  };

  // 今も「要判断」のまま残っているものだけを聞く
  const pending = GmailApp.search('label:' + CONFIG.labels.ask, 0, 50).map(t => t.getId());
  const ask = log.ask.filter(m => pending.includes(m.id));

  section('あなたの判断待ち', ask, true);
  if (ask.length) {
    lines.push('→ Gmailでメールを開き「ラベルを変更」から次のどれかを付けてください。');
    lines.push('  ' + KINDS.map(k => CONFIG.labels[k]).join(' / '));
    lines.push('  1時間以内に処理し、同じ送信元は次から自動で振り分けます。', '');
  }
  section('転職/注目', log.pick, false);
  section('要返信', log.reply, true);
  section('要確認', log.check, false);

  lines.push('【自動処理】',
    '- 転職/その他：' + c.jobOther + '件（既読・アーカイブ）',
    '- 広告：' + c.ad + '件（既読・アーカイブ）',
    '- 通知：' + c.notice + '件（既読）',
    '- 削除：' + c.trash + '件（既読・ゴミ箱）',
    '- 残す：' + c.keep + '件（受信箱に未読のまま）',
    '- 未判定：' + c.other + '件（AIの上限超え。次回に判定）');

  const sheetId = PropertiesService.getScriptProperties().getProperty('SHEET_ID');
  if (sheetId) lines.push('', '判定ログ: https://docs.google.com/spreadsheets/d/' + sheetId);

  const to = CONFIG.summaryTo || Session.getActiveUser().getEmail();
  const date = Utilities.formatDate(new Date(), 'Asia/Tokyo', 'M/d');
  GmailApp.sendEmail(to, '[Gmail要約] ' + date + ' 判断待ち' + ask.length + '件・注目' + log.pick.length + '件',
    lines.join('\n'));

  // 判断待ちは答えが出るまで翌日の要約にも載せる
  const fresh = emptyLog_();
  fresh.ask = ask;
  saveLog_(fresh);
}

// ===== 補助 =====

function getOrCreateLabel_(name) {
  return GmailApp.getUserLabelByName(name) || GmailApp.createLabel(name);
}

function shortFrom_(from) {
  return from.replace(/<.*>/, '').replace(/"/g, '').trim() || from;
}

function emptyLog_() {
  return { pick: [], check: [], reply: [], ask: [], counts: { jobOther: 0, ad: 0, notice: 0, trash: 0, keep: 0, other: 0 } };
}

// 要約用の記録は一覧ごとに別のプロパティへ保存する（1つあたり9KBの上限を超えないように）
const LOG_LISTS = ['pick', 'check', 'reply', 'ask'];

function loadLog_() {
  const props = PropertiesService.getScriptProperties();
  const log = emptyLog_();
  LOG_LISTS.forEach(k => {
    const raw = props.getProperty('log_' + k);
    if (raw) log[k] = JSON.parse(raw);
  });
  const counts = props.getProperty('log_counts');
  if (counts) Object.assign(log.counts, JSON.parse(counts));
  return log;
}

function saveLog_(log) {
  const props = PropertiesService.getScriptProperties();
  // 件名・差出人・理由は短くし、各一覧は直近15件まで
  const trim = list => list.slice(-15).map(m => ({
    id: m.id, s: (m.s || '').slice(0, 40), f: (m.f || '').slice(0, 25), r: (m.r || '').slice(0, 40),
  }));
  LOG_LISTS.forEach(k => props.setProperty('log_' + k, JSON.stringify(trim(log[k]))));
  props.setProperty('log_counts', JSON.stringify(log.counts));
}
