# 停止時のローカル運用helper参照snapshot

2026-10-22、DeepSeek作業の中止時点をDraft PRへ保存するための参照コピーです。配置元は `C:/Develop/AI/Strata-data/`、このdirectoryの `Strata-data/` 配下に同名ファイルをbyte単位で保存しています。既存の `control/strata_cli.py` はDeepSeek専用入口、ここにある同名ファイルは元の共通公開入口で、内容が異なります。

対象は公開CLI／cmdと、manager、catalog、official runtime、startup progress、TEMP probe、権限・既存authorityの小source依存です。各ファイルの実装・import・固定pathは変更していません。自動配備・実行・portable化を行う仕組みではありません。元のWindows配置、上流checkout、既存のprofile・registry・履歴receipt・Pi/Harness等を参照するため、このsnapshotだけでは動作しません。

profile、user config、registry、履歴receipt、モデルpath manifest、APIキー・secret、モデル、EXE/DLL、venv、配備runtime、実行logはコピーしていません。既存Huihui等の設定・機能を変更する目的でもありません。

正本計画は `C:/Develop/AI/Docs/Strata-add-deepseek/implementation-plan.md` のimpl115を、本文を変更せず [docs/implementation-plan.md](../docs/implementation-plan.md) に保存しました。文書内のローカル参照・過去の成功範囲・未実施範囲は元の履歴です。PR作成時に過去結果の再実行や新しい資格付けはしていません。

通常DSHの6379-token要求は300秒idle timeoutが2回、出力0で、Pi通常利用完走と原因修正は未完です。最新のCore観測追加もbuild成功報告までで、独立レビュー・実GPU動作確認は未完です。作業停止時の状態として保全し、完成版とは扱いません。