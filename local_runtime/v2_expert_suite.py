"""Frozen synthetic, disjoint training/heldout material for the private experiment."""
TRAINING = [
 ('learn-ja', 'APIの冪等性と競合状態の設計を日本語で詳細に説明してください。',
  '注文システム。受付キーはUUID。注文作成と残高更新は同じトランザクション。通信切断後は受付キーで状態確認する。'
  '二重送信でも注文は一件。期限切れのキーと処理中のキーは区別する。タイムアウトは処理失敗を意味しない。'),
 ('learn-python', 'JSONLを集計するPython関数を説明付きで実装してください。',
  'Python入力仕様: 各行はtimestamp, route, status, elapsed_msを持つJSON。壊れた行は別件数へ集計。'
  '時刻はUTC、出力はrouteごとの件数とエラー率。空集合でゼロ除算しない。generatorで大きな入力を処理する。'),
 ('learn-ts', '古い応答を破棄できるReact hookをTypeScriptで実装してください。',
  'type SearchHit = { title: string; score: number }; 検索欄は入力ごとにqueryを変更する。'
  'useEffect内でAbortControllerを作る。入力AよりBの応答が先に来る可能性がある。unmount後の更新は禁止。'),
 ('learn-log', 'ログから競合する障害仮説と確認方法を詳細に列挙してください。',
  '00:01 request=a queue_ms=20 decode_ms=400 cache_hit=0.92 files=2; '
  '00:02 request=b queue_ms=600 decode_ms=410 cache_hit=0.91 files=3; '
  '00:03 request=c queue_ms=2 decode_ms=1700 cache_hit=0.51 files=90; CPU=87% disk_busy=96%.'),
 ('learn-long', 'キャッシュ整合性と永続化の設計上の問題を分析してください。',
  '分散キャッシュはレコード版番号を保持する。DB書込み後に通知する。通知欠落には期限と再照合を使う。'
  '古い版の通知で新しいキャッシュを消さない。障害復旧時はメッセージの重複と順序反転を考慮する。'),
 ('learn-code', '入力検証とPython/TypeScript境界の安全な設計を説明してください。',
  'Schema v3: idは空でない文字列、valueはfiniteな数値、tagsは重複しない配列。boolを整数と混同しない。'
  'Python json.loadsとJavaScript JSON.parseでは数値の範囲が異なる。未知fieldと欠損fieldの扱いを定義する。')]

EVALUATION = [
 ('cold', '日本語で80項目の詳細な設計考察を続けてください。',
  '図書貸出サービスは冊子ID、会員ID、返却期限を管理する。予約待ち順序は受付時刻と予約番号で決定する。'
  '同じ冊子を同時貸出できない。返却と予約取消は監査履歴に残す。休館日には返却期限を翌開館日へ移す。'),
 ('warmup', '80項目の詳細なデータ構造分析を続けてください。',
  '道路グラフの辺には距離と通行可能時間帯を付す。Dijkstraは非負重みを仮定する。'
  '地図更新は世代別snapshotを作り、検索中に世代を混ぜない。経路再計算時は出発位置の変化も記録する。'),
 ('heldout-ja', '以下の設計文書を日本語で80項目、詳細にレビューしてください。',
  '気象観測局は地点番号、観測時刻、気圧、湿度、雨量を送信する。欠測とゼロ雨量は区別する。'
  'センサー校正後は補正履歴を保存する。時差のある地点でも日次集計の境界を明示する。異常値は原値を保持して注釈する。'),
 ('heldout-code', 'このコードを型安全性、非同期、例外処理から80項目詳しくレビューしてください。',
  'async function loadPage(cursor?: string): Promise<Page> { const r = await fetch(`/items?cursor=${cursor}`); '
  'const page = await r.json(); cache.set(cursor, page); return page; } '
  'interface Page { items: {key:string; updatedAt:number}[]; next?:string; } '
  'def dedupe(items): return list({item["key"]: item for item in items}.values())'),
 ('heldout-tech', 'ストレージとネットワークの性能について80項目の詳細な考察を続けてください。',
  '列指向分析基盤は圧縮ブロックとmin/max統計を持つ。選択率が低い検索では不要ブロックを読まない。'
  '遠隔ストレージは帯域だけでなく要求往復回数が支配する。小さいrange requestの併合は不要bytesとのトレードオフ。'),
 ('long', '技術文書の整合性と可観測性について80項目の詳細な分析を続けてください。',
  '衛星画像処理pipeline。受信画像は撮影UTC、軌道番号、校正version、checksumを持つ。'
  '工程は解凍、幾何補正、雲検出、タイル分割、索引作成。中間成果物は工程versionと入力hashを記録する。'
  '再処理で旧タイルを原子的に置換する。観測間隔の偏りを品質評価に含める。欠落packetと雲による欠損を区別する。')]

QUALITY = [
 ('quality-ja', '「東京の現在時刻は午後3時です。」を意味を保って英訳してください。', ['Tokyo', '3']),
 ('quality-python', 'Python関数 unique_sorted(values) を書いてください。整数の重複を除き昇順listを返します。コードだけ。', ['def unique_sorted', 'sorted', 'set']),
 ('quality-ts', 'TypeScriptで function isFiniteNumber(x: unknown): x is number を実装。NaNとInfinityは拒否。コードだけ。', ['typeof', 'Number.isFinite']),
 ('quality-long', '次の資料から唯一の承認コードを返してください。説明不要。\n' +
  ('通常コード=NONE。工程は受信、検査、保管。\n' * 600) + '\n承認コード=V2-CHECK-7319\n', ['V2-CHECK-7319'])]
