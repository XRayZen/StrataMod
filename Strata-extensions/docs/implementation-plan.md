# StrataへのDeepSeek V4.1 Flash 1017導入計画

- 文書版: v1.12r1-impl115
- 更新日: 2026-10-22 JST
- 状態: 計画事前レビューの未解決重要指摘0、Main承認済み。文書版と対象内容は以下の通り。 現在進捗は必須37/46=80.4%、任意T42除外、必須残9。元47task構成と過去37/47履歴は保持し、未実施を加算しない。
- 実装着手日: 2026-10-21 JST。ユーザー依頼により全47taskの実装を依存順で開始。T01は最小実行案r1の独立レビュー重要0・Main承認後に実装し、実装r1の独立レビュー重要0を確認。
- 現在の成果物: T01契約、T02環境/storage記録、T03の9header/小fixture、T04の独立N-RMS/Q-format参照、T06の早期Windows host bundle、T07のHIP build/両GPU個別小fixture、T08のWindows host reader/scalar、T34のnative measurement API、T09実型kernel、T16 declared-set/primary owner-event、T23 protocol/DTO、T17 host span-provider、T24 owner/bootstrap fixtureを実施し各scope独立review重要0。T27 Windows公式CPUcodecも限定完了。T10構造資格とT11/T12/T13/T14/T15の元component scopeは全source対応の個別独立確認重要0/Main受理で完了。T18/T19/T21も変更後owner必要subsetの独立重要0/Main判断で元component scope完了。T20有限wave1 Coreは全40実G/同時owned/defaultlast/audit対/失敗freshの独立最終重要0/Main scope完了受理。T25/S5-2数値componentはsmallstate deep復元r2と全20anchorの独立最終重要0/Main scope完了受理。全9原本取得・T05 receiptとT10 full-source構造資格は独立重要0/Main受理済み。T26固定primary text全40TF資格も独立最終重要0/Main scope完了受理。T28 primary text producer/公式Recipe/既HTTP元scopeとT29 provider/catalog/profile/ownedpackage宣言は独立最終重要0/Main完了受理。T44元expert-assist componentも独立最終重要0/Main完了受理。T30通常CLI/manager・新owned環境の元component scopeも独立最終重要0/Main完了受理（32/47）。T31元WebUI/chat接点も独立最終重要0/Main scope完了受理（33/47）。T45元layer-split componentも独立最終重要0/Main完了受理（34/47）。T32元Pi/Harness接点もlossless epoch補完後の独立最終重要0/Main完了受理（35/47）。T35元eager測定scopeも正式3pairの独立最終重要0/Main完了受理（36/47）。T22 production cache-only元scopeも独立最終重要0/Main完了受理（37/47）。T33全client統合・追加Xolotl最適化/biasは未了。最新版のscope/証拠は§4。
- 保存場所: C:\Develop\AI\Docs\Strata-add-deepseek\implementation-plan.md
- 今後の壁打ち結果は同じファイルを更新する。元HTMLと会話txtは保存し、変更しない。

## 1. 合意済み事項と今回の提案

本節はv1.12r1までの合意・計画策定履歴を保持する。「未実施」「全task未着手」「実装開始ではない」等は当該版の策定時点で、2026-10-21のユーザー実装依頼後の現在地は§4のtask表/実装証拠を参照する。

### 合意済み: v1.1 / v1.2 / v1.4 / v1.5 / v1.6

- モデル原本の保存先は C:\Develop\AI\Model。
- 今回のdeploymentはprimary_compute_device = R9700、optional secondary_device = RX 7900 XTX 24GB。single / cache-onlyを維持し、expert-assistとlayer-splitの両方式でも第二GPUを演算に使い、通常CLIで運用時に選択する。
- ユーザー指定のUnsloth公開Q4、UD-Q4_K_XLを初回の取得・実機検証対象とする。
- Q4というラベルでloaderを分岐させず、共通GGUF reader、実型dispatch、DeepSeek構造adapterを分ける。
- 原本のnative MXFP4 / MXFP8 / Q8_0等の配合を維持し、別quantへの全量再量子化を本線にしない。
- StrataのWindows / HIP基盤、mmngaのDeepSeek実装を土台に、Mayaを第一移植候補、LuceBoxを追加参照にする。
- 実装先はStrata。MayaやLuceBoxへのruntime変更を意味しない。
- Huihuiの既存default・profile・artifact・稼働経路を保護する。新engineは隔離source / build先で準備する。
- commit、push、PR作成はそれぞれ個別承認。無関係な変更を保護し、Mainが担当間の範囲と完了条件を判断する。

### 合意済みの段階4方針（v1.4r2）

- SSD→RAM→GPUの供給にsecondary_device容量cacheを加え、容量会計、lease、queue、公平性、cancel / drain、測定方法を具体化する。
- 容量配分と帯域は実測前の試算。公式既定、新たな通常headroom、出力・context・起動条件へ昇格させない。
- 既存の安全なbuffered / mmap fallbackを維持する。未計測だけを理由に利用不可にしない。
- DSpark停止、短い出力枠、小chunk等は試験内の条件とし、通常利用の制限へ移さない。
- 段階4方針はユーザー合意済み。実装・実測は未実施で、配分数値は試算として管理する。

### 合意済みの段階5方針（v1.5r3）

- 独立N / Q / G参照と許容差を固定し、小operator / state / layer fixtureから必要な全40層teacher forcingへ数値検証を進める。
- 段階4と既存保護を維持し、数値coreから通常CLI / 公式provider / codec / clientへ直接統合する。実装・検証実行は未実施。

### 合意済みの段階6方針（v1.6r3）

- 通常CLI / WebUI / chat / Pi / DSHをmodel別providerへ接続し、公式管理、owner保護、既存Huihui、通常model選択と安全cleanupを維持する。
- Fork元更新に備え、上流固定source、project-owned共通処理 / model adapter、小さい版付きhook、build / bundle、資産 / profile / stateを分ける。

### 維持する段階7方針（v1.7r2）

- 数値・配置の正しさ → eager baseline → 供給 / secondary_device → 長文 → DSpark単独 → graph単独 → 組合せ → 要求単位のfault / cancel・資源確認の順に実証する。
- 性能の比較条件、実token数、終了状態、長文到達長、各要求の資源確認、失敗時の切分けを固定し、未実施をPASSにしない。
- ユーザー指定により、旧版runtimeへ戻す運用機能・手順・検証・復元のための保管要件は本計画から削除する。
- Huihuiの確認は、今回変える共通CLI / 起動管理 / clientが既存動作を壊さないための限定確認とする。性能・品質全面の再測定を追加しない。
- 段階4 / 5の数値・寿命契約を維持する。今回の文書化は実装・取得・検証実行の開始ではなく、未実施範囲を含む計画の更新である。

### 維持する公式参照の調査結果（v1.8r1）

- DeepInferを公式仕様・状態・数値fixtureの第一参照候補、deepseek-recipeをserver側CPU codecの第一参照 / 採用候補として追加する。
- Windows / HIP・指定native GGUF・上記deploymentと7段階を維持する。全engine置換や全最適化再実装は追加せず、source読取で分かった採用境界と未確認事項を記録する。
### 維持するタスク整理（v1.9r1）

- 実装をT01～T47の成果物・完了依存・証拠へ分解する。全task未着手で、調査済み・設計案・再利用候補を実装完了と数えない。
- 段階5は数値検証とし、生成・終了・安全停止の受入は通常機能testで確認する。段階番号は分類、実行依存はsection 4のtask DAGとする。
- 数値core、補助device cache、通常入口、個別資格と必須scope完了を分け、未達scopeは通常機能利用とは別に報告する。

### 維持する簡素化（v1.10r1、device roleはv1.11で拡張）

- 型 / API / folder / taskはprimary_compute_device、任意のsecondary_deviceという役割名を使う。HIPのprimary＋0または1 secondaryに限定し、cache部品はsecondary_device_cacheへ分離する。N台・他vendor・万能plugin基盤へ広げない。
- 基本primary＋RAM / SSDの通常入口と、選択したsecondary modeの開発時資格を分ける。cache-only、expert-assist、layer-splitの実装・必要な数値 / 寿命・通常切替の証拠を納品scopeに残す。
- 既存allocator / stream / event / request ID / 公式managerを最小拡張し、別の所有管理やlifecycle基盤を追加する前提を置かない。
- 独立N→Q全model品質、公式最大 / 全候補contextは補助評価。必要な小N / Q / G、今回対象長文のstate・境界・再利用と通常機能の検証は維持する。

### 維持する第二GPU演算追加（v1.11r1）

- execution_modeはsingle / cache-only / expert-assist / layer-split。expert補助演算とMaya型の連続2区間の層分割を両方実装し、速い方を事前に決めない。
- modeとexpert assignment / layer partitionは起動時に固定する。運用切替は通常CLIの明示switchで安全停止→新mode起動とし、無停止hot migrationや自動最速選択を要件にしない。
- layer-splitの担当weight全量VRAM常駐は要求せず、両演算deviceへ既存有限RAM / SSD供給を接続する。旧single / cache-onlyと通常機能・設定を維持する。
- 速度は当機未測定。性能効果未達でも片方の実装を省略せず、正しさ・機能合否と比較速度を分けて報告する。

### 今回の全体再監査（v1.12r1）

- 現Huihui V2のplain登録経路と現存source / owner保護を区別し、削除済み検査を再導入しない。
- T44 / T45で両GPUのtrunk数値を確認し、T46で基本modeのCLI資格、T47で既存DSpark / graph・consumer結合を扱う。T47は旧T46の責務分割で、新機能・suite・台帳・承認段階を増やさない。
- 独立して実装・実証したmode / flagsの可用性を、他modeや全結合・M-ALL未完だけで一括禁止しない。全体納品では従来どおりcacheと両演算方式・必要な結合証拠を揃える。

## 2. 対象版と計画策定時点のsnapshot

以下は固定版と2026-10-20の計画策定用読取snapshot。実装後の検証・進捗や現runtime状態へ自動更新する表ではなく、現在の実装証拠は§4に分ける。

| 対象 | 固定版 / 確認値 | 扱い |
|---|---|---|
| 現local Strata | 477ac13cbe8e582c20484871ce459d20d82df09d / v0.1.45 | source再確認時clean。DeepSeek専用実装は未導入 |
| mmnga DeepSeek分岐 | d4c07dde710cd009c47f36a8d002ff938b0eef67 | DeepSeek engine / CUDA演算の移植元 |
| Maya | 8d9a9b5d705049a87da853717cdc59440252de30 / v1.1.17 | native GGUF / HIP / Windows / cache部品の第一移植候補 |
| LuceBox | 81940128d118f4d2bc0070e4c772542938c7a5c3 | 構造・fixture・cache寿命管理の参照 |
| Unsloth GGUF | f924b94f19c1fea02c06a65c8475b0a45e2b88b1 / UD-Q4_K_XL | 全9 shard、合計500,707,576,573B |
| 公式モデル参照 | 1bae0e1088993b9b82de08f59de5be5a34e42170 | config / encoding / 数値参照の根拠 |
| DeepInfer | 774ce244b87cc0eb8d4b94ab9f5de2ab22049f01 | 公式model / 状態 / 数値契約の参照。現機で実行・検証していない |
| deepseek-recipe | 935817c66f5d6e64838f419692545f06787e485f | 公式encoding / token-ID parserのCPU codec候補。当機build未実施 |
| 既存公開catalog（2026-10-20読取） | huihui-ud-q4_k_xl_v2 / 262144 | V2・4 shard、rev1130c24fabf6eacffe701306ebd16c7b04a9f942。原Strataはtext-only、V2 GPU実証は未実施 |

現catalog / profile / CLIはV2のpack / PLE、共有MTP、Strata\engine\strata.exe等を固定している。
旧IQ4_XS assets / profile / Model固有receiptは削除済みで、旧成功記録をV2の実証へ引き継がない。保護対象は現V2のdefault / 262144 / 実効profile / 通常経路である。
現require_readyはpack / MTPの必要file存在を確認し、require_registrationはprepared profileのplain mirror。撤去済みreceipt / registry / profile content-hash照合をlegacy共通化で復活させない。native()に残るMCP / setup固定source hashとPID / cohort / tracking保護は維持する。
実262144 profileのresident-budget24 / prefill512 / reasoning noneはREADME説明と差がある。本件では一方を公式既定と断定せず両fileを変更しない。現profileを保護し、その値をDeepSeek既定へ転用しない。
新model行の追加だけではDeepSeekを実行できない。familyごとのartifact / tokenizer / binary / 管理契約が必要になる。
資料の新共通基盤や最新upstreamを自動採用せず、必要差分とbackend影響を評価して実装版を固定する。
local VmmRangeはHIP時stub。新upstreamのHIP VMMを現物に導入済みとは扱わず、採用時は別差分として検証する。
既存HIPの実績、MayaのGLM / APU測定、LuceBoxの別構成測定は、当機のDeepSeek実証に転用しない。

### 原資料の版差

- 元HTMLは2026-10-18基準、共通基点477ac13…、GGUF dc788bd…、29課題の旧案。
- 会話txtは共通基盤e88ee39…、GGUF f924b94…、I01～I03追加後の32課題を説明する。
- その改訂本文は同梱HTMLに反映されていない。今回の計画では両者の記述を現物と照合し、合意を上記へ整理した。
- HTML SHA256: fa71325ae52cb8bf452e5bbaca7e2c7021907eb00a17c5c5afa8afc1b7773970
- 会話txt SHA256: 4ddd1c6c085dfc627358409e83eaac11e29be8a2466420664a638e4b423e5d22

## 3. 汎用化と再利用境界

| 区分 | 内容 |
|---|---|
| 共通GGUF reader | shard、metadata、tensor一覧、shape、offset、境界検査、mmap / I/O |
| 型ごとの共通処理 | block layout / code / scaleを検証し、MXFP4 / MXFP8 / Q8_0等のdecoder / kernelへdispatch |
| DeepSeek adapter | tensor名・shape、Engram、attention、mHC、router、state ownerの構造契約 |
| 初回検証範囲 | 指定UD-Q4_K_XL。別variantは不足型・backend対応と検証を追加して拡張可能 |

MXFP8の数値IDだけで互換判定しない。Mayaは旧67 / 新43、LuceBoxは117を扱う。
固定revisionのheader、converter方言、block配置、code / scale、shape / strideを確認して共通表現へ写す。
v1.12r1計画策定時点では全9shardの完全header inventoryは未取得だった。以下のshape由来算定は当時の根拠として保持し、2026-10-21の実header取得/実型確認は§4 T03の固定receiptを参照する。
Qwen tokenizer / PLE / 共有MTPをDeepSeekへ流用しない。DSparkもmodel固有artifactとstateを別会計にする。

| 分類 | 具体的な資産 | 追加作業 |
|---|---|---|
| ほぼ流用 | Strata cmake/hip_backend.cmake、HIP runtime / BLAS shim、Windows build / DLL同梱 | DeepSeek targetと実行identityの接続 |
| ほぼ流用・拡張 | Strata alloc / stream / event / pinned / graph、GGUF reader、DirectFile | DeepSeek型・構造、容量と寿命の契約 |
| 拡張・一般化 | Strata RemotePrefillSource / copy_cached_blobs、peer_experts、RemoteExperts | cache-onlyの保存providerと共通転送を再利用。expert computeはtop10 / Q8固定をtop6 / native型へ別適合し、不要dense / stateを一括確保しない |
| 修正・移植 | mmnga src/deepseek41 のengine / kernels / mxfp4 | HIP、Windows、CUB / PTX / wave32 / 同期、数値・構造差 |
| 第一移植候補 | Maya ds4_gguf.cu、ds4_kernels.cu、ds4_os.hpp | native MXFP4 / Q8_0、mHC / attention、Windows処理をStrataへ適合 |
| 第一移植候補 | Maya ds4_engram_io.hpp、ds4_model.cuのflow / layer group | MXFP8 row cache、staging / ring、連続層・境界payload / 追加shared rows / DSpark tapを対象経路へ適合 |
| 追加参照 | LuceBox loader / candidates / Engram / mHC / tests、MoeStreamedExpertCache / hybrid FFN | expert実行分配とcanonical joinを参照。V4.1層分割は共有 / staggered未実装で拒否する範囲があり、完成実装とは扱わない |
| 公式仕様の参照候補 | DeepInfer V4.1 model / state / sampler / tests | 固定1017 configと精度・状態契約を照合。GPU依存の一括移植はしない |
| CPU codecの候補 | deepseek-recipe Conversation / token IDs / DSML parser | server adapterの最小hookとtoken来歴・設定伝搬を検討 |
| 新設する統合契約 | 共通tensor adapterと既allocator / stream / event / request IDのledger / lease / 世代・有限queue拡張 | model別profile / receipt / CLIまで一貫させる。独立resource brokerは前提にしない |

Mayaのnon-GPU expert decodeにはCPU演算経路がある。
Mayaのstaging / ringは該当flow / prefill等の移植候補であり、decode全cold expertが既存H2D経路とは記載しない。
single / cache-onlyでは全routed expertをprimaryへ、expert-assistでは選択routeをsecondaryへ、layer-splitでは担当層の演算deviceへ接続する。CPU演算へ暗黙fallbackせず、各modeを同じnative量子化・演算精度契約で検証する。
LuceBoxの独自quant、router bias変更、近似bounded replay、特定ハード用profileは合意外に持ち込まない。
移植時はMaya MIT、LuceBox Apache-2.0、同梱ggml MIT等のlicense / noticeを保持する。

### DeepInferの参照価値と実装採用境界

公開実行環境はLinux / GCC13以上 / Python3.12、CUDA13のNVIDIA SM100またはCANN9.2のAscend950。4 / 64GPUの性能を当機へ外挿しない。
公開はoffline engineで、完全なservice用KV system等は別。cache_engine.pyのC1 / C2・shared KV・SWA ring・compressor stateは存在し、local cache皆無という意味ではない。

| 固定source / 契約 | 本計画への参照先・未確認事項 |
|---|---|
| cross_layer.py SharedLayerTopology / builder.py | KV / index-topk / index-Kの別map、segment / consumer config / candidate source / NextNを段階3 / 5の共有writer・負例fixtureへ |
| compress.py / attn.py | ratio1のBF16 projected・state無しとratio超1のFP32 score / latent・state、pre-RoPE index-K / post-RoPE KV、別の共有sourceを精度表へ |
| engram_metadata.py / engram.py | 語彙正規化、layer / head順の素数、layer別NumPy seed・bound・odd multiplierをhash goldenへ。FP8 E4M3FN / BF16のDeepEP / userbuffer経路はGGUF MXFP8 SSD row cacheと別 |
| mhc_modeling.py / mhc_ops.py / moe.py | BF16 residualとFP32 fn / scale / base、各epsilon / 還元順をcaller・configと照合。Sinkhorn helper default10で既契約20を上書きせず、原checkpointの学習済routing bias保持と独自bias改変を区別 |
| weights loader _TensorReader / linear.py | header / offset / bytes / short read / full coverage / shapeの検査を参照。起動時local expert常駐fillはdecode SSD demand cacheではない |

expertのE2M1 packed int8＋別UE8M0 scaleとbackend int32 / int16 column-major、Engramの別scale付きFP8→FP32復元・再packを区別する。
lossless unpack / repackとrequantを混同せず、指定GGUFのQ8 / MXFP8原本を公式内部layoutへ勝手に置換しない。全asset / layout対応は未照合。
Strata / mmnga / Maya / LuceBoxの既役割を維持し、CUDA / TileLang / DeepGEMM / FlashMLA等は実依存・shape・精度・backendを個別評価する。
### 第二GPU演算の固定sourceと不足部分

| 参照 | 確認事実 / 採用境界 |
|---|---|
| Maya ds4_model.cu:1864–1975 / 7003–7056 | dense＋expertの連続range、head最終側 / drafter先頭側。各deviceのlayer実行とh / pre / topk / candのpinned bounce＋event |
| Maya ds4_model.cu:7119–7160 / 5278–5318 | 他group writerの新compressed KV / index rows受信・serial pinned複製、DSpark tap転送。固定1017のshared edgeと数値・寿命へ適合する |
| Strata RemoteExperts::begin:261 / 320–330 | k!=10拒否とQ8_1 / Q8_0経路。別GPU compute / compact結果は資産だが、DeepSeek top6 / native MXFP4へ新対応が必要 |
| Luce moe_hybrid_ffn_eval.cpp:1481–1498 / 1154–1191 | primary / secondary / streamed expertの実branchとcanonical route join。独自quant / precisionをそのまま本指定へ採用しない |
| Luce deepseek4_backend.cpp:1963–1991 / loader:2209–2216 | V4.1 layer-splitのcache sharing / staggered未実装、跨cut shared KVを拒否。完成したV4.1層分割の証明にはならない |

Mayaの単sequence decodeは全層直列で、prefillは最遅stageが支配する構造。sourceの存在と当機Windows / HIP・指定native GGUFでの成立や性能を区別する。

### 全段階共通の実装レイヤーとフォルダ案

以下はv1.12r1の最終配置設計案。現在作成済みの隔離worktree/試験bundleと将来配備先の対応は§4 staging map/証拠に記す。Strataを実行先とし、独自native実装を上流forkへ大量コピーしない。
既存Huihuiのsource / assets / profile / 登録config / receiptは移動せず、legacy providerから現経路を参照する。

~~~text
C:\Develop\AI\
  Strata\                         既存Huihui source / runtimeを維持
  Strata-extensions\              新設: project-owned source
    control\                     providers/legacy_huihui・deepseek41、official_adapters
    native\                      artifact、quant、io、cache（secondary_device_cacheを含む）の共通処理
      device\                    primary / secondary identity、有限転送・同期の共通部品
    models\deepseek41\            tensor構造、state、routing、server codec
      execution\                 mode / placement計画、expert_assist、layer_split
    clients\                     family binding、reasoning codec、epoch保護
    patches\strata\<base-sha>\    小さいhook / CMake / dispatch差分
    tests\                       contract、numerics、lifecycle、backend、clients
  Strata-data\                    既存CLI入口と既存Huihui経路を維持
    vendor\strata\<sha>\          新設案: pristine固定上流、直接改変しない
    build\<bundle-id>\            生成: patch適用checkout / CMake / build
    bundles\<bundle-id>\          生成後固定: engine / server / runtime / manifest
    profiles\<version>\           新profileの固定snapshot、参照中の内容を上書きしない
    records\                     mutable owner / attempt / receipt
    official-state\<runtime-id>\  mutable公式tracking、candidateとliveを隔離
    logs\                        mutable log
  Model\<model>\<revision>\<variant>\  新規raw assets、全量pack複製を避ける
~~~

- 共通CLI / client → control / provider → 版付きofficial adapter / 固定bundleを依存方向とする。
- DeepSeek model layer → generic nativeを基本とし、generic nativeは特定familyやUIへ逆依存しない。
- 上流hookから外部family / engineを登録する。共通reader / 実型dispatch、Windows I/O、RAM / primary_compute_device / secondary_device_cache、数値fixturesを各層へ配置する。
- 上流との接点は下表の少数patchとして基準shaとともに管理する。完全無改変・無競合を保証せず、必要差分を隠さない。
- candidate専用の固定profile / configとmutable state / recordsを用意する。稼働中 / 管理中attemptの参照先と既存stateを資格確認で上書きしない。
- build / bundleの作業容量は運用前に再算定する。500GB原本の再pack / 全量複製は不要とし、v1.3容量snapshotを最新実測として扱わない。

| 上流との接点 | 小さい版付き変更と契約 |
|---|---|
| CMake / backend target | 外部source / target登録。触れたCUDA / HIP / SYCLの必要buildを維持 |
| engine / family dispatch | 外部DeepSeek adapterと実型kernel登録。既存Huihui分岐を保持 |
| serve family factory | tokenizer / encoding / DSML / EOS / parser / capabilityをserver adapterへ集約 |
| 公式managerの注入点 | config / state / launcher / engine descriptorの不足hookのみ追加し、公式lifecycleへ委譲 |

現公式MCPはrootにconfig探索やstate_dirを結び、launcher / bootstrapも固定する箇所がある。
現在の実装が自由なcandidate注入に対応済みとは扱わず、既存属性と不足hookを版付きadapterで明示する。
PATH / sys.pathの差替えやglobal monkeypatchの増殖で混在を隠さず、engine / server / Python / profileを同じbundleへ束縛する。
既存allocator / stream / event / request IDを拡張して必要なlease / bytes / 古いcompletion防止を実装する。全buffer wrapper、新resource broker、第二owner authority / owner DB、複数global registry、daemon / plugin / 依存環境管理やlifecycleの再実装を前提にしない。既存公式managerと必要descriptor / adapterを使う。
## 4. 7段階の実装計画

1. 版・保存先・必要storage・Windows toolchainを固定する。新共通基盤は必要差分を評価して採否を決める。
2. Strata HIP基盤へ小さなDeepSeek targetを接続し、Maya native型処理を実weight fixtureで比較する。
3. 共通reader / 実型dispatch / DeepSeek adapterを実装し、全shard・tokenizer・artifactの同一性を検証する。
4. 有限容量SSD→RAM→GPU供給、cache-only、expert-assist、layer-splitを実装し、配置・演算数値、state所有、資源寿命と失敗処理を検証する。
5. 独立N / Q / Gの契約・許容差を先に固定し、operator / state / layerと必要な全40層teacher forcingを数値検証する。
6. 通常CLI / status / WebUI / chat / Pi / DSHへmodel別providerを接続し、family codec、owner / epoch、model切替・安全cleanupとHuihui既存動作を確認する。
7. 性能・長文・DSpark / graphを個別から組合せへ検証し、各要求の資源・fault / cancel・通常入口の実証範囲を公開する。

各変更段階は、作成担当と別のレビュアーが版を固定して確認し、重要指摘修正後の最新版を再レビューする。
共有ファイルが影響するCUDA / HIP / SYCLは、Strata AGENTSに従いbuildしてから実装レビューへ渡す。
toolchain / 実機がない検証は未実施として影響を報告し、成功やルール免除とは扱わない。
小規模試験を全取得より先に行う。Windowsが成立しなければ原因と代替案を示し、勝手にOSを変更しない。
7段階は実装領域の分類で、全段階を番号順に完了するgateではない。実際の完了依存は以下のtask DAGを使う。


### task表の読み方・共通完了条件

T01は完了（offline契約scope・独立実装review重要0）。T02は環境・有界storage記録scope完了、独立review重要0。T03は最小実行案r1の独立review重要0・Main承認後に実装、9header/小fixture・offline契約scope完了、独立実装review重要0。T06は早期Windows host試験bundle scope完了・独立review重要0（HIP/GPU/fullengine/server等は未実施）。T04はN-RMS/Q-format参照・wrapper scope完了、13test/独立review重要0。T07はprimary HIP基盤小fixtureとsecondary個別同fixture scope完了、独立review重要0（peer同時multiGPU/DeepSeek実型数値等未実施）。T08はWindows host reader/scalar scope完了、host build/67cases成功・独立実装review重要0。T09は実native型kernel限定scope完了、r2両GPU各213job・独立review重要0。T34はnative measurement API限定scope完了、51cases成功・独立実装review重要0。T05は依存成立/Main承認後に着手、offline19testsと実shard1中断再開成功、取得前コードr2独立review重要0で全9取得中、全receipt未了。T10はpre r1重要0・T05依存待ちでコード未着手。T16はdeclared-set sidecar/primary既owner-event限定scope完了、独立review重要0。T23はprotocol/DTO限定scope完了、host62cases成功・独立実装review重要0。それ以外は未着手。既存source・調査・本計画作成をtask完了と数えない。

T03 raw保存map: prefix / 小binary fixtureは `C:/Develop/AI/Strata-data/records/deepseek-v41/t03-20261021/{headers,fixtures}/` のみに保存しGit追跡しない。source / tests / inventory / receiptは開発worktreeの `Strata-extensions/native/artifact/` と `tests/artifact/` で追跡し、revision / file identity / span / SHAでrawをbindする。

開発staging map: OWNの将来配備先は `C:/Develop/AI/Strata-extensions` を維持する。開発sourceはユーザー指定のGit worktree `C:/Develop/AI/Strata-data/build/deepseek-v41`（branch `deepseek-v41`、base `477ac13cbe8e582c20484871ce459d20d82df09d`）内の `Strata-extensions/` で追跡する。将来配備先や現live管理へコピー・junction・自動接続しない。commit / push / PRは未実施。
OWNはC:\Develop\AI\Strata-extensions、DATAはC:\Develop\AI\Strata-data、MODELはC:\Develop\AI\Model。model処理はOWN/models/deepseek41、fixtureはOWN/tests配下（section 3）。
完了依存は全てtask IDへの依存で、段階・milestoneへ逆依存させない。非依存branchは並行できるが、合格には必要な完了証拠を揃える。

- 共通完了条件は各taskに適用する項目だけを要求する。成果物path / 契約版、実装差分と該当fixture / raw結果を固定し、使用するsource / binary / assets / tokenizer / context / shape / actual flagsを結ぶ。契約taskに後続GPU / 全model実証を要求しない。
- 影響するCUDA / HIP / SYCLの必須build、未実施範囲、作成担当とは別のレビューで重要指摘0を伴う。探索済み・実装しただけ・skipを完了にしない。
- 固定試験bundleを検証前に生成し、証拠を同bundleへbindする。source変更後は影響taskを再検証し、別bundleの古い証拠を最新合格へ混ぜない。
- 性能taskは正しい測定と効果達成 / 未達 / 未判定を成果物にし、速度未達を機能故障や通常禁止へ変換しない。数値・寿命FAILは完了にしない。
- 試験の短枠 / off flags / samplingを通常の出力・思考・retry・context・compact・選択肢へ移さず、固定絶対TPSを新SLOにしない。

| ID | 段階・成果物layer | 完了依存 | 実装内容・完了証拠（DoD） | 状態 |
|---|---|---|---|---|
| T01 | 1・OWN/control契約 / provenance | - | 既authority / descriptorへ必要な固定refs・owned層・hook / manifest / asset / role / epoch項目を版固定。DeepInfer / Recipe採用境界とnotice対応をレビューし、別registry / owner DBを前提にしない（§2/3/10）。 | 完了（offline契約scope、独立review重要0） |
| T02 | 1・DATA環境 / storage記録 | T01 | 着手時inventory / toolchain / DLL、physical / commit / WDDM、原本 / build / 比較用を含む最大同時disk bytesを再確認。MODEL固定、全量pack複製回避と未成立点を明示（§6）。 | 完了（環境・有界storage記録scope、独立review重要0） |
| T03 | 1/3・OWN/native/artifact / quant契約 | T01,T02 | 全9headerで型方言 / block / scale / name / shape / span整列 / tokenizerを固定。小fixture実weightをbounded span取得しrevision / file identity / offset / layout / fixture hashをreceipt化。trunk必須とdraft / 画像を分離。 | 完了（9header・小fixture・offline契約scope、独立review重要0） |
| T04 | 1/5・OWN/tests/numerics独立参照 | T01,T03 | 独立N / Q、known vectors、dtype / cast / 還元 / tie / finite、事前許容差 / expected manifest / 負例wrapperを固定。公式GPU環境を必須にしない（§9）。 | 完了（N-RMS/Q-format参照・wrapper scope、独立review重要0） |
| T05 | 1/3・MODEL固定9shard / receipt | T02,T03,T09 | 基盤成立後に全量取得し全SHA / layout / trunk必須assetsを検査。T03の少量fixtureと全量証拠を区別。通常start毎の全hash追加なし（§2/6）。 | 完了（全9原本500707576573B/9LFS・1873ranges・current identity/header/1043/実6span、独立重要0/Main受理。数値/runtime等未資格） |
| T06 | 2・OWN/patches / CMake / DATA試験bundle | T01,T02 | pristine vendor / 外部source / 少数patch / 生成stateを分離。早期native試験target・依存DLL・manifestを固定し、検証を同artifactへ束縛。server / runtime bundle整合は該当provider統合時に追加（§3/10）。 | 完了（早期Windows host試験bundle scope、独立review重要0。HIP/GPU/fullengine/server等未実施） |
| T07 | 2・OWN/native HIP土台 / backend fixture | T02,T06 | init / alloc / BLAS / stream / event / pinned / 同device timingとWindows DLLを小fixture検証。DeepSeek全演算成功とは区別。 | 完了（primary HIP基盤小fixture＋secondary個別同fixture scope、独立review重要0。peer同時/DeepSeek数値等未実施） |
| T08 | 2/3・OWN/native/artifact / quant reader | T03,T04,T06 | shard / index / offset / 範囲 / short read / coverageと実型scalar decode、lossless repackとrequantの区別を独立参照・負例で確認。 | 完了（Windows host reader/scalar scope、独立review重要0。GPU/T09/fullsource/fullmodel未実施） |
| T09 | 2・OWN/native/quant HIP kernel / parity | T04,T07,T08 | T03の少量real MXFP4 / MXFP8 / Q8等で実H5120 / F2304 / top6・1/2/4/8tokenをQ/G比較。全量T05を待たず、不足型 / wave / PTX依存を解消。 | 完了（native型kernel限定scope、r2両GPU各213job・独立review重要0） |
| T10 | 3・OWN/models/deepseek41 artifact adapter | T03,T05,T08 | 全headerとtrunk assetsを再照合し各matrix span / shape / typeを索引化。誤Qwen PLE / MTP / tokenizer、未知layoutを拒否。 | 完了（r7 full-source構造資格、1043 index/416assertions/240expert/96head/5binding拒否、独立重要0/Main受理。数値/生成未資格） |
| T11 | 3・OWN/models dense / router / expert | T04,T09,T10 | 学習済bias / score / top6、gate-up-down、route / cast / down QDQ / combineを独立fixture照合。実minimum atomic working setのshape / 型 / span / 同時bytesを確定。 | 完了（元FFN/router/expert component scope、全source91span対応の個別独立重要0/Main受理。T20変更後API/同時full-core会計は別途未資格） |
| T12 | 3・OWN/models mHC / norm | T04,T09,T10 | HC4 / Sinkhorn20、epsilon区別、BF16 / FP32 / 還元 / staggeredを実形状fixtureで確認（§9）。 | 完了（元mHC/norm component scope、13jobs/5506648値＋全source対応の独立重要0/Main受理。実attention/FFN接続・T20変更後資格は別） |
| T13 | 3・OWN/models Engram hash / gather | T04,T09,T10 | token map / 語彙 / seed / hash / table layout / 実8heads / 履歴をgolden照合。row供給interfaceを定義し公式userbufferとSSD cacheを区別。 hash/history・MXFP8 row gather/供給まで。gate/KV/norm/cast/残差全forwardはT20-owned bounded helper、独立N/Q/GはT25（helperを当該検証前に実装/実G実行）。 | 完了（元hash/history/gather scope、qualified final8の96row/25344B対応・own3source不変を独立確認重要0/Main受理。全Engram forward/実層連続性は別） |
| T14 | 3・OWN/models compression / SWA / shared KV | T04,T09,T10,T12 | ratio2 / 1、pre/post RoPE、共有writer、127/128/129・partial / append / resetのstateを検証。 | 完了（元compression/SWA/shared KV component scope、48jobs/14497896値・737state＋全source対応の独立重要0/Main受理。T20 resident実接続は別） |
| T15 | 3・OWN/models indexer / CSA2 / attention | T04,T10,T14 | source20 / 共有index / block8 / top512、visible rows16383/16384/16385、mask / near tie / 候補集合・順序を正負fixture確認。 | 完了（元indexer/attention component scope、58jobs/184772313値・76会計/12出力拒否＋全source対応の独立重要0/Main受理。T20変更後API/全coreは別） |
| T16 | 4・OWN/native/cache ledger / lease / queue | T07,T08,T09,T34 | 既allocator / stream / event / request IDへ必要な世代 / source-DMA-kernel lease / credits / bytes会計を拡張し合成declared-set fixtureを検証。実working setはT11、実進行はT18 / T20。全buffer wrapperやbroker新設は前提にしない（§7）。 | 完了（declared-set/primary既owner-event限定scope、r2独立review重要0） |
| T17 | 4・OWN/native/io Windows span provider | T08,T16 | aligned read / gather / overread、bounded outstanding、short read / error / drain、安全buffered / mmap fallbackとOS cache会計を検証。 | 完了（Windows host span-provider scope、r2独立review重要0・Main受理） |
| T18 | 4・OWN/native/cache primary_compute_device / RAM / SSD | T11,T16,T17 | bounded hot / cold / pageable / pinned、demand予約 / prefetch / evict禁止。T11実working setとT16実bytes予約 / allocationを照合し有限進行、bit同値 / cancel / late completion / 次要求を確認。 resident device view/既stream-event接点を既kernelへ最小接続し、host-wrapper再uploadをdevice cache hit資格へ数えない。 | 完了（元resident weight owner scope＋T20変更後必要subset492033値/hot補完22040値・4KiB/noissue/取消lastuseが独立重要0/Main受理。全Core/wholeworking-setは別） |
| T19 | 4・OWN/native/cache Engram row / scheduler | T13,T16,T17 | native MXFP8 row hit / miss / dedup / evict、expertとの公平性、small read / lease / errorを確認。全table常駐前提なし。 | 完了（元row owner scope＋qualified fullfile8任意row/EOF・実公平credit/借用取消返却/次要求の変更後subset独立重要0/Main受理。全Engram/Core層接続は別） |
| T20 | 4・OWN/models / native 有限prefill / core | T11,T12,T14,T15,T18,T19 | 小wave / layer unionと全40層stateを接続し因果 / 還元 / 実working setの有限進行を確認。全union常駐や入力 / context / output縮小を要求しない。 Engram全forward bounded helperをT25 Engram検証前に実装/実G実行し、全core完了を新依存にしない。 | 完了（有限wave1 primary text Core scope。全40 normalprefill2+append1の387840logits/40state/route/owned19591605B、defaultlast/audit同入力対/失敗fresh補完が独立最終重要0/Main受理。T26/性能/longcontext/他modeへ拡張しない） |
| T21 | 4・OWN/native/device / secondary roles・transfer | T07,T16,T17,T18 | primary＋任意secondary（0/1）の実identity・選択roleに必要なalloc / stream / event / 方向copy・bounce / capabilityを確認。cache-onlyに演算kernel合格を要求しない。実native型演算資格はT44 / T45、商品名 / ordinal whitelistなし。 | 完了（元role/local/bounce/PAGEABLE scope＋変更lease必要subset独立重要0/Main受理。peer両方向can0で直送未試行/未資格、T22/T44/45は別） |
| T22 | 4・OWN packedcache / CoreProjection / normal cache-only routeと資格 | T19,T20,T21,T24,T25,T30 | production packedcache接点とCoreProjection/normalproducer cache-only実route・profileRoleを最小実装し、指定cacheの実機でlocal / RAM / SSD対P2P又はbounceのbit・数値同値、drain不能dst隔離 / bypass / 次要求、重複bytes / physical unknownを確認。P2P不可はbounceで検証。通常startに機種別receipt / 全suiteを追加しない。 | pre25f33c41…独立0/Main承認18source。元scope完了（final b990d74d…/coverage e2a23171…独立最終0/Main受理37/47）。4small1392値＋normal role/数値/typedcancel1-1→HTTP2-2・正規close、通常6profileへのT22native配備は別接点。T21 primitive/T44 secondary計算でstorage-only実providerを代用しない。T33とは分離、両compute通常modeはT46、最適化結合はT47 |
| T23 | 3/6・OWN/native protocol / control DTO | T01,T03,T06 | 元生成token IDs / 固定tokenizer identity / finish / count / request epochを保持。frame fixtureで欠落 / 改変 / epoch不一致 / 再tokenize来歴偽装を検出。consumer結合はT28 / T33。 | 完了（host protocol/DTO限定scope、独立review重要0。actualproducer/consumer結合未実施） |
| T24 | 3/6・OWN/control owner / bootstrap / receipt | T01,T06 | 固定binary / profile / attempt / PID / create / cohort / port、安全stop / cleanup、未知ownerとcleanup未完表示を機能fixture確認。独立の全model生成工程は作らない。 | pre r1重要0・Main承認、完了（host owner/bootstrap fixture scope、r3独立重要0・Main受理） |
| T25 | 5・OWN/tests/numerics operator / layer / state | T04,T09,T11,T12,T13,T14,T15 | 固定bundleでexact / FP契約、負例wrapper、route / HC / Engram / CSA2 / shared state・層内driftを合格receipt化。小shape / zero-scale / skipを実対象PASSにしない。 Engram全forwardはT20-owned helperの実Gを独立事前N/Q期待と比較し、T13/mocksで代用しない。 | 完了（元T25/S5-2数値component scope。helper/actual bounded3rangeとsmallstate deep復元r2 final9029ca46…・全20anchor66ceeea5…/d09726fb…の独立最終重要0/Main受理。Core公開restore/全40復元/T42へ拡張しない） |
| T26 | 5・OWN/tests/numerics 全40層TF receipt | T05,T20,T25,T34 | trunk全assets / 9shard、binary / 入力token IDs / position / BOS / logits / state / actual flagsを固定しQ→G照合。native資源寿命と適用receiptを確認。非HTTP runnerは生成frame / 公式bootstrap不要、HTTP使用時は既owner保護を適用。draft / 画像 / 全N→Q / secondary cache / 全clientは不要依存。 | 完了（固定primary text全40TF scope。receiptde015333…、同runtime独立7tests/別dirqualify全field同SHA・15refs/20anchors/現9source/1043構造/387840logits/flags/lifetime重要0/Main受理。生成/T42/他mode/normalserverへ拡張しない） |
| T27 | 6・OWN/control / tests Recipe Windows codec | T01,T03,T06 | Windows依存 / API版 / 公式tokenizer、alias strata、params / reasoning、literal DSML対special IDをfixture化。mock / renderingを実推論合格にせず既出力枠を縮小しない。 | 完了（Windows公式CPUcodec限定scope）、r1独立35assertions＋公式48tests/1772bindings重要0・Main受理 |
| T28 | 6・OWN/models server codec / serve hook | T10,T23,T27 | 最小hookで元IDs / tokenizer来歴をRecipeへ渡しOpenAI正規化 / EOS / parser / capsを統合。UTF8再tokenizeで来歴を復元せず権限 / owner / epochはcontrol / clientへ。 | final80c7fa0f…/37anchors64df225a…独立最終重要0/Main元primary-text producer/Recipe/既HTTP scope完了。実4IDs→4482/您/LPtop3/length1/defaultauto/165PP。provider前後変化は原wrapper失敗保持＋非消費独立probe/新CPU別bindingで解消。新owned環境/CLI/複数生成TPOT/他modeは別 |
| T29 | 6・OWN/control/providers / DATA catalog・profile | T01,T05,T24,T28 | family assets / binary / tokenizer / context / caps、primary / optional secondaryとmode / placementを記述。基本登録をsecondary演算資格待ちにしない。未取得理由 / 再確認 / 選択、Huihui固定契約、試験短枠 / off不昇格を確認。 | 元provider/catalog/assets/context/profile/ownedpackage宣言scope完了。公開final617003af…/package aab2…/public9/Huihui4不変と受理T28をcompletion2d9b011d…へbind、独立最終重要0/Main受理。T30通常CLI/新環境実modelは別で追加依存化しない |
| T30 | 6・OWN/control / DATA manager・共通CLI | T24,T26,T29 | mode / assignment / partitionを起動snapshotへbindし、明示switchで安全停止→新起動。reuse / 二層lock内confirmed identityと固定target / cohort / port、既公式READY期限・再試行、actual mode / phase / attemptを検証。hot migrationなし。 | 完了（元通常CLI/manager component。統合06b73b23…独立最終重要0/Main受理、C4096/newowned環境HTTP/reuse/stop/status/models。全clientT33/他context・mode/性能は別） |
| T31 | 6・OWN/clients / WebUI・chat接点 | T28,T30 | 実providerでSSE / EOF / cancel、遅延stream / history commit / tool断片防止、旧履歴保持 / 通常選択 / alias互換を確認。 | 完了（元WebUI/chat接点scope）。final8c0af059…独立最終重要0/Main受理、実SSE/両client再生/新6profile/通常chatquit・staticHTTP/stop復帰。browserはユーザー明示skip・後日まとめ、未実施PASS化0。T33全client/性能は別 |
| T32 | 6・OWN/clients / Pi・Harness実依存接点 | T27,T28,T30 | family reasoning / caps / authority probe、既DSH route guard、tool権限・実行直前epoch、実provider往復を確認。retry / compact等を狭めない。 | 完了（元Pi/Harness component）。finalr2 3bf061ab…/losslessa02cc208…独立最終重要0/Main受理。実Pi/DSH各1HTTP/您/length/usage4+1・通常stop復帰、旧unsafe epoch丸めをexact Python/nativeargv＋新decimal authorityで別CPU補完。T33実reasoning/tool/全agent・性能は別 |
| T33 | 6・OWN/tests/lifecycle・clients / 資格receipt | T30,T31,T32 | 基本compute＋RAM / SSDで通常CLI / 全clientのtext / reasoning / tool、終了・停止・次操作を実provider確認。Huihui共通変更限定。同bundleへ証拠bind後activation資格を確定しcandidateのlive上書きを負例検証。cache-only scopeはT22、両演算modeの基本資格はT46、影響する全通常consumerと最適化結合はT47の別scopeへ置き、T33完了を後続mode資格待ちにしない。 | 既component/r4 cleanup・通常CLI/SDK r2 sourceCPU、publication017624…の正式de662 8target更新受理を維持。最新ユーザー指定でT33全client/Pi・DSHはDSpark/graph等の最終統合build後へ延期。旧Pi保存HTTP0は送信有無不明、2026-10-21 22:56:34UTC metrics03はreading331/2791・生成0/available独立28332425216Bの過去観測（現在値/ETA/性能因果でない）。user-cancel860e9167…/3fb39a96…は未完中止、DSH GO撤回・未実行。通常stop1/status1 exit0・元41496/44116/18924不在、SDK07窓だけ返却。dispose/fetchflush/独立Node exit未観測、全GPU空き/SDK成功未。実reasoning/tool/自然終了・activation全資格未、通常設定不縮小 |
| T34 | 横断・OWN/native stats / tests measurement API | T01,T03,T04,T06 | native bytes / clock / ledger / fixture metadataの最小APIと負例を早期実装し供給・数値試験へ。元IDs / 生成count / SSE欠落 / usage0等はT23 / T28 / T31 / T33 / T35の該当consumer結合時に証明し、server完成待ちにしない。 | 完了（native measurement API限定scope、独立review重要0。実consumer結合未実施） |
| T35 | 7・OWN/tests/backend / perf eager基準 | T20,T26,T34 | 試験限定offでnative eager、primary_compute_device / RAM / SSD、cold / warm、実token count結合、TTFT / TPOT / paired ABと追加memoryを記録。全client / secondary cache全資格は不要依存。 | 現在（impl115）: 元eager測定scope完了は保持、追加完了数0。5系統＋C32/persistentの具体受理deltaは旧9420へ反映済み（当該未反映0）。Perf binderの旧R4 literal/observerON固定→統合handoff/plan435bと実boolへの局所authority修正はRootTinyhigh0/Main sourceCPU subset受理（handoff9bda/validator7a1b/CPU9da3/manifest64ff/delta8a57）。一般速度効果未判定。追加wave全完了/未確定44全件採用とはしない。任意routing biasは別限定patch r2のBCrypt buffer lifetime P2修正、CPU226項目再確認・実Win32 8case・両gfx build/link・独立再review完了を経て、新canonical Source b1ccd…の通常build完了へ接合。既定0/target decode/既math・learned bias保持/0 exact/opt-inを維持。候補package/6profile組立とCLI identity確認はMain報告で完了、測定接合・性能測定は進行中。通常client実生成/全scope品質・性能/最終配備は未確認。補正0/ありの整理を独立準備task/review待ちにせず既存条件で測り、補正値を結果に添える。新canonical b1ccd…通常build exit0をMainが確認しPerf既存条件の有限1Fresh採取と原owner回収を完了、他範囲は未確認。 Main保存結果: 新Source b1ccd…/ABI b949…/EXE01dac…のactual INFO routing(0,0,0)/effective exact/reason zero_coefficientsで有限1Freshを採取。旧9420→新を各1回、host pipe TTFT116.531→118.391秒/token間27.516→29.000秒/GEN→DONE144.078→147.406秒、IDs[4482,55753]/lengthlimit。host pipe/ambient差があり因果・統計速度効果は断定不可、今回速度向上の観測なし。actual payload P16481061592/S12354322432/R49477026712Bは旧と同じ。runrootはC:\Develop\AI\Strata-data\build\deepseek-v41\build-deepseek-t35\integrated-routing-perf-measurement-r1\run-r1（pre-t33-perf-port-r1配下ではない）、raw812aa498…/resultd56044ce…/outcomed7800333…はMain提供短SHA。exec37250/native21396のwait exit0・原handle/wrapper close・retained=false/postquiescent/window return、Main outcome有限readbackでsuccess/error=null/resource_return_ready=true/original_owners_closed=true/recovered exit0を確認。DRAM READY→post: WS50018443264→50150346752B、PrivateBytes78909739008→79577387008B、OS available14607134720→14116859904B（終点約13.15GiB）。samplerはC:\Develop\AI\Strata-data\build\deepseek-v41\build-deepseek-t39\production-native-integration-r1\dram-sampling-r1\result-perf-routing-r1.json（SHA256 2dccd2a80ce11a0cb9e91385f91e92d05d591d91a86fbb9bcd1e47e314317057）、2samples中稼働1有効、loading peak/PrivateWS未測。有限採取を全scope性能・品質・全client成功へ広げない。 以下は先行版の受理・失敗・未実施履歴（当時の記述）: 完了（元eager測定scope、正式3AB/独立0/Main受理）。00pair faf5…の限定受理（Fresh TTFT449.250→296.016s/total478.766→322.594s）を維持。11 actual ef27dab0…/handoff399371f7…/map485c077c…はRootTinyhigh最終0/Main正式受理、両arm Fresh[288,16]/Logits[16]独立IDs・Append[342]は新baseline相対、16LP F32bit一致/同actual cache。Primarygen2・request replay9562/0/4705・marker/DSknown、candidateUnprepared0/registry451でr5非適格。Fresh pipeTTFT188.890→100.594s（1順序pair46.7%短縮）/total244.890→130.890s（46.6%）/Append total55.953→31.359s。原native2＋wrapper回収・窓返却。空RAM最小baseline7085395968/candidate6743433216B・各4samples report-only。単一順序生観測で一般統計/成分因果/r5効果/hidden全数値・通常package/default採用未、追加高速化preT33・原37/47加算0 S-RR24a6bb90…はRootTinyhigh0/Main sourceCPU/build受理、効果AB未。共用binder89f5…はsourceCPU受理、Graph auto binder1ce3…はsourceCPU正式受理、実接合CPU tuple/list fix中（Root relay）・採用効果未確定。 |
| T36 | 7・OWN/tests/numerics / perf 対象長文資格 | T25,T26,T34,T35 | 事前固定した今回対象の長文 / 境界 / append / reuse / resetを実測し、真のtemplate / tool込みtoken数・生成予約とstate精度を確認。公式最大 / 全試験点候補の到達・品質は補助scopeで別記し、その未評価を必須実装完了や通常禁止へ連鎖させない。 | 現在（impl113）: 旧Aは自然終了・両native/outer exit0・原handle wait/close/postquiescent/資源返却・5checkpoint127..131比較成功の作者有限結果（Source4542…/SerialCompatibilityのみ）。旧B/HTTP未開始。旧A完了を新統合版機能資格にしない。旧expert actual9GEN=7complete/1typedcancel/1failed・full14 FAIL/layer未・根因unknown、r4は元例外露出の観測修正のみで根因fix未。旧A/individual fixture/standalone expert診断/parent join/Bや全旧suite完了を統合前提にせず、受理referenceは適切authorityで再用し通常r5追加suite gateを作らない。統合Source9420bd4b…の必要長文/state/lifetimeは同版検証debugへ接続、T36全scope未完。 以下は先行版の受理・失敗・未実施履歴（当時の記述）: TapUnion/paired9fb236…等の旧有限資格と代表plan8b28…/sourceCPU r234267413…等の受理subsetを維持、130長文/retainedExpert/HTTP/production・一般性能未。最新Root relayをauthorityにA candidate継続、A reference/B DATA準備はhigh0/Main受理だがA全比較/原native＋outer回収/全成功の正式受理未。B autoGOは保留・未起動、準備受理を維持して次窓再割当待ち。具体tuple未提供は未記載。A完走・全比較・原native＋outer回収後は受入済expert3GEN診断をB長文より優先し、以後の窓はRootがready状況と短case unlock効果で選ぶ。A referenceは将来必要oracleへ再用しbaseline再計算を避け、通常r5長文の新gateを追加しない。captureSerialCompatibilityと通常r5資格を分離、8GiBは目安report-only、T36完了未 |
| T37 | 7・OWN/models DSpark契約 / fixture | T03,T04,T05,T10,T23 | draft3層weights / confidence / encoding / 型 / 精度 / sampling / RNG / 因果を固定し不足artifactを解消。default5は層数でも通常limitでもない。trunk数値検証の依存にしない。 | 完了（元artifact/host契約/bounded fixture scope、独立最終重要0/R1実part.lock修正/Main受理。fixed7965746848B fullLFS/rename・124span654051値/10tests/755native拒否、旧captureと新CPUvalidator別binding）。Core/共有math/通常設定/G0、T38実draft演算/採否/通常DSparkは別 |
| T38 | 7・OWN/models / tests DSpark単独 | T20,T25,T35,T37 | graph off試験で採否 / bonus / 確定tail state / 分布 / 終了の正しさと追加memoryを確認。accepted率を速度PASSにせず、1M / graph単独は不要依存。 | 現在（impl113）: 実統合先は既WT Strata-extensions。Graph native/Integration CLI・control・profiles・packagingがsolewriter、DS/Perfがpatch supportし受理成果を合成。通常29TU Release/strict/両gfx/normal observer=false/normal trace=falseのconfigure/compile/link0＋GLOBALActor compile/link0、S-RR統合CPU13case/330assert0はRootCapture最終high0/Main native SOURCE/BUILD・必要CPU subset正式受入済み。tuple内review pendingは生成当時metadataで、今回の受入根拠はMain最終引継ぎ。同統合版のDS必要機能/数値/state/lifetime/性能は未資格。旧A/individual fixture/standalone expert診断/parent join/Bや全旧suite完了を統合前提にせず、受理referenceは適切authorityで再用し通常r5追加suite gateを作らない。 以下は先行版の受理・失敗・未実施履歴（当時の記述）: seed/proposal既有限greedy、独立CPU132f3c…/943248…と最終expected b242…/5bc1…/87fb…（y288/z16/joined61440B/元authority）の受理を維持。normalActor＋graph統合9e3a906d…/e4696ff4…はRootTinyhigh0/Main sourceCPU・最終ON/OFF compile/link限定受理。4file変更/100same、CPU095b7e…は15checks/10JSON・境界ad46…は7case/9checks、Core/math/sampling不変。ON6build0/EXE5ab44e…/Source374dea…/ABI8f1d…、OFFnormal29TU両gfx0/EXEb8434…/ABI3ec5…（7744…/5269…/5114…）。有限normal GEN4cell4ede0f27…/7b89d29e…はRootCapturehigh0/Main受理、Fresh[288,16]/Logits[16]/Append[342]は構造・crosscell表示LP同一/C4,4,5・reuse0,4,4まで、normal rawtensor未。host寿命fix/altjoint/aggregate/finalDATAを経たActor03 actual-r2 c315a201…/7c8d00…はRootTinyhigh0/Main P3/C4/max2/W5/seed0 greedy1run限定受理。4raw1095688B・3独立FPfield全word/signedzero exact・IDs288,16、E2/G1/C4 pending16/length/completionknown、元handle wait/close/exit0・Actor窓だけ返却。保存pre/postのSDK継続は後のT33中止前の観測。optionalcompletefalse/PrivateWS null/RNGdraw未、通常GEN全般/全T38/統合採否bonus/nonGreedy/新targettap/長文/rate/peak・性能未資格 残T38 A/B/C handoff004cf6a9…は独立high0/Main全diff・sourceCPU/build受理、Source35b47e3f…/EXEd659404f…は有限sourceCPU/build資格のみ。ABC prep d84a45b3…/freezee8541340…はRootTinyhigh0/Main fullprepared受理、窓t38-remaining-abc-r1-20261022/割当UTC02:11:40・Primary07/HIP1でA→B-fresh→C各1 MainGO、ABC実観測はSystem32 runtime限定subsetをRootTinyhigh0/Main正式受理・全T38未、CDF診断2差は元ID順と降順のdomain差でRootTiny原因切分け済み・sampler修正/期待retune不要。CDF補足b84a…/e9e3…もhigh0/Main原因受理。SDKfix64dfe…は同P2再review0/Main受理・disk adjacency配置P2解消、SDK_A2516bc6d…/freezeec054b…/outcome2541352a…はRootCapturehigh0/Main有限actual受理、6DLL全actual path/size/diskSHA canonical・旧A13raw同値、E[288,16,342]/G2C5/pending342・条件付きRNG/ledger、原nativewaitclose/outer15943exit0・窓返却。memory-imagehash/observer全域complete/wrapper別originalhandle/globalT38未、旧System32ABCは不変。global mapping r2 9ff2a2e2…はRootTinyhigh0/Main mappingsubset受理、原v3強制reject中途末尾/SWA draft等のDSglobal plan726b1d79…はRootCapturehigh0/RootMain計画受理後、831705…＋r2a72d42c5…で2P2解消・sourceCPU/build正式受理。execution binding4995f5be…は準備受理/actualG0（Root最新relay authority）。CDF/DLL既受入subsetをwhole DSglobalへ昇格しない。T36trunkをDS draft境界へ流用しない。native3件は原waitexit0/close/postquiescent、旧wrapperはsession90992exit0のみでbirth/別originalhandleclose未計測。DhelperはIntegration担当。旧base65fa…/Source4900dd…/ABIba98…の有限証拠を新DSglobal/T47資格へ流用せず、残case実資格未。 |
| T39 | 7・OWN/native graph / model adapter・tests | T20,T25,T35 | DSpark offでkey / shape / address / slot owner / dynamic data / recapture / cache miss / cancel / drainをeager照合。対象境界を確認し全長context / DSpark完了を要求しない。 | 現在（impl115）: 新canonical通常buildはMain報告でexit0完了。tupleはC:\Develop\AI\Strata-data\build\deepseek-v41\build-deepseek-t39\production-native-routing-integration-r1\production-tuple.json（1375B/SHA256 281441294861e568d3445bdb0516a3a59669e4905a9b49bf05f7aaf1eec2f495、中央全文read/hash一致）、Source b1ccd0eb44bf5634b2f31e6d7509863941708dd520004c0c673fdc773b835d7f/ABI b94972e73cd79e4ff7a7b404d140ba5d989f2870c48be35665faa7d176a29e52/EXE保存metadata SHA256 01dac3de813b21259acf1f922848afc1df266f0509425d694565ee221294afa0・2846720B。normal29TU/O3/gfx1100+gfx1201/observer=false/trace=false。tupleのnative_executed=false/GPU=false/independent_review pendingはfreeze時metadataで、実測成功は推定しない。既r2 native14fileのcode high0を全面再reviewせず、候補package/6profile組立完了をMainが報告、Perfは旧build固定参照/DLL配置調整後、既存条件の有限1Freshを採取し原owner回収・窓返却済み、他範囲は未確認。旧9420/8920/25fb＋50047のexpert/CLI GEN0/DRAM等有限証拠は旧tupleに保持し新b1ccdへ付替えない。既存の旧tuple証拠: Main受入plan SHA256 435bfb70e27794a9240cb104fee975a73ffc2038c0bfb13f4f14c5dde0104b80、旧tupleはbuild-deepseek-t39/production-native-integration-r1/production-tuple.json（1795B/SHA256 50047e06bf02efad94a3027f63df7b1e35e7f76fcb556580fc7cbe4133f8a5ee）。Source9420bd4b3eabbc9d67241d03b8fa352b88659f490956ec8d1321e13bd33c7c91/ABI8920750454ac7fe7b69b3d776bb666cad081f6a5245b22af7f8b66ac010320f8/EXE保存metadata SHA256 25fbf37f5b29a1619367db555627768f14736639c69750de5f317a2740fd455a。通常29TU Release/strict/両gfx/normal observer=false/normal trace=falseのconfigure/compile/link0＋GLOBALActor compile/link0、S-RR統合CPU13case/330assert0はRootCapture最終high0/Main native SOURCE/BUILD・必要CPU subset正式受入済み。tuple内review pendingは生成当時metadataで、今回の受入根拠はMain最終引継ぎ。旧tupleの必要Q/LP/state/lifetime/性能・全client/modeの検証debugは未資格。通常CLI起動/health/status/停止の確認は完了したが、GEN0で数値・生成・性能の証拠へ拡張しない。旧helper observerON誤ラベルはactual commands authorityで訂正済み。fec66/e199/92a8 tupleは先行版履歴で付替えない。 新b1ccd/ABI b949/EXE01dacのrouting(0,0,0)/effective exact/zero_coefficientsで有限1Fresh採取・原owner回収済み（T35現在status、Main有限readback受入）。旧9420→新各1回のTTFT116.531→118.391秒/token間27.516→29.000秒/GEN→DONE144.078→147.406秒で今回速度向上観測なし。host pipe/ambient差があり因果・統計速度効果は未判定、他の性能・品質・client範囲は未確認。 以下は先行版の受理・失敗・未実施履歴（当時の記述）: normal graph6b157…/package eb25…の既sourceCPU受理を維持。observerON EXE2a2a…の保存identityとgraph aggregate d851…/package93de…のfull63 CPUassembly・実candidate fakeRuntimepreviewは独立0/Main限定受理。defaultOFF/unknown・owner-generation保持。通常public CLI配備/実native OFFON数値/firstReplay・replay/cancel→fresh/HTTP/owner寿命/性能未資格。共通AV根因/通常Core資格も未。統合9e3a906d…/e4696ff4…はRootTinyhigh0/Main sourceCPU・ON6build/OFFnormal29TU両gfx compile/link限定受理、ON/OFF共通Source374dea…・別ABI8f1d…/3ec5…、defaultOFF維持。独立照合は必要42refs、971全照合は作者検証のみ。有限4cell4ede0f27…/summary281ef78c…はRootCapturehigh0/Main受理、graph.request_delta.replaysはFresh/Logits/Append順で01=9418/0/4633・11=9406/0/4627、fallbacks0/Logits追加work0、DS10/11 completionknown。原owner wait/close/postquiescent・wrapperexit0、窓返却済。rawtensor/全T39・cancel長文/速度effect/通常CLI配備未。 |
| T40 | 7・OWN/tests/numerics / perf 2×2・効果 | T34,T35,T38,T39 | 基本供給の同じ統合buildで必要な00/10/01対照（DSpark/graphの対象単独scope）を取得後、11の組合せ正しさ→必要paired AB、実transfer / 追加owned bytes / memory / cache減少 / 償却を評価。T38/T39全体完了を着手gateにしない。同budgetを同allocation数の強制としない。cache有効scopeはT22の必要資格と別receiptで採用flagsを検証し、基本PASSを流用しない。効果達成 / 未達 / 未判定と機能合否を分離。 | preplan11ad847…と最新ユーザー順の受理を維持。有限normal GEN4cell finalhandoff4ede0f27…/map7b89d29e…/summary281ef78c…/outcome19bbea…はRootCapturehigh最終重要0/Main正式受理、00→10→01→11各1回・全Fresh[288,16]/Logits[16]/Append[342]と表示LP同一、C4/4/5・reuse0/4/4の構造/crosscell整合まで（Append342独立新Qなし）。graph01/11 replay・DSknownと原owner wait/close/postquiescent・wrapperexit0を保存、窓返却済。16RAMsamples WS46.548–46.650GiB/空き5.658–9.234GiB・8GiB report-only。rawtensor/採否bonus/nonGreedyRNG/cancel長文第二GPU/速度効果・全T38T39未、追加高速化必要pairedは別・37/47加算0 |
| T41 | 7・OWN/tests/lifecycle・backend・clients要求fixture | T33,T38,T39,T40 | 基本供給で各要求前中後のledger / 上限 / lease / cancel / drain / 次要求 / 停止を検証。T33依存は最終consumer証拠の集約依存で、着手/代表runtime実行gateではない。cache有効scopeはT22と採用flagsの証拠を追加。persistent充填許容、drain不能dst隔離、context損傷errorを確認。他consumer停止や期間型試験なし。 | 現在（impl114）: 必要な要求/取消/次Fresh/state/lifetime検証は同統合版へ接続、同版必要数値・寿命資格は当該有限subset以外未。expert actual3GEN result196df88d…/outcomebabfba41…はRootCaptureの機能＋原owner回収subset重要0/Main outcome読戻し受入済み。同版single相対/LP/fullscope性能/旧根因解消/cancel後Freshは未で、旧9GEN/full14 FAILを当該有限成功で上書きしない。旧Aは自然終了・両native/outer exit0・原handle wait/close/postquiescent/資源返却・5checkpoint127..131比較成功の作者有限結果（Source4542…/SerialCompatibilityのみ）。旧B/HTTP未開始。旧A完了を新統合版機能資格にしない。旧expert actual9GEN=7complete/1typedcancel/1failed・full14 FAIL/layer未・根因unknown、r4は元例外露出の観測修正のみで根因fix未。旧A/individual fixture/standalone expert診断/parent join/Bや全旧suite完了を統合前提にせず、受理referenceは適切authorityで再用し通常r5追加suite gateを作らない。同版debug修正/独立review loop後にT33全clients/PiDSHとT46通常切替へ進み同証拠を集約。 以下は先行版の受理・失敗・未実施履歴（当時の記述）: preplan11ad847…/共有helper r281b2…・3modeprepff02c9de…の限定受理を維持。3mode c5caf…/a011…/0518…はRootCapturehigh0/Main計10request（7complete/3cancel）・actual mode work/IDLP/Fresh/原4native cleanup subset受理、cache hits0/SDK3DLL観測・全6loaded未知。D e809…/summary5c396…/mapa92e…は同high0/Main有限5typed chain受理：P3 IDs[288,16]→ActorACK後usercancel[288]→Fresh同IDs→recipe stop[288]→Fresh同IDs、sameowner/known core4/reuse0/原nativewaitclose・outer80939exit0/窓返却。HTTP Recipe実発火/GPU-inflight/独立rawQ/outer別originalhandle/wholeT38T41未。T33後の最終consumer証拠集約依存を着手gateにしない。T47 helper r2 317ae42c…/freeze5a050724…/finite533045b6…はRootTinyhigh0/Main受理、postDONE明示owner_completion_known=false後の次GEN P2解消、startupunknown/null deltaは許容し通常制限を追加しない。。T47最新14GEN試行は9GEN（7complete/1cache typedcancel/1expert拒否）でfull14 FAIL・acceptedfalse、layer未起動。expert Append2-2 DONE2/postINFO成功後のcancel-target3-3 GENでownercompletionunknown ERR。予定tokenACK STOPは未発火だがERR後原frames finally cleanupSTOPをraw239で実送信、成功取消と扱わない。原3nativewaitexit0-handleclosed/retained0/postquiescent＋outer81429exit1は数値FAILと別、resource正式判断はRoot。修正済T47必要caseと残graph/DSは共通生成/取消/次FreshでT41証拠共用し、旧成功再走は変更影響範囲だけ。 T47観測r4とexpert3GEN診断はsourceCPU/build・準備まで、実機未。共用binder89f5…sourceCPU受理、Graph auto binder1ce3…正式sourceCPU受理・実接合CPU tuple/list fix中（Root relay）をwhole寿命資格へ昇格しない。 |
| T42 | 5/7・OWN/tests/numerics 独立N・補助品質評価 | T04,T05,T26,T34 | 独立N trace / bounded reference、corpus、TF NLL / KL / critical invariantを事前固定しN→Q品質を補助評価。未確保は未完了 / 未判定で、Q/Gや自己比較を代用せず巨大GPU / 原本全量追加取得を必須にしない。必須scope完了の依存にしない。 | 未着手 |
| T43 | 横断・OWN/control 資格manifest・実証report | T22,T33,T35,T36,T40,T41,T46,T47 | 最新bundle / 必要backend build / 独立review0を照合。指定cache-onlyとexpert-assist / layer-split両方式の実機・通常切替・採用flags組合せの数値 / 寿命証拠を含める。速度未達で方式を落とさず、補助T42 / 最大候補の未判定は別表示。 | 未着手 |
| T44 | 4/5・OWN/models/deepseek41/execution/expert_assist | T11,T20,T21,T25,T26,T34 | secondary実shape / native型kernel、top6不変の有限dispatchと論理route結果の単一採用 / canonical combineを実装。実両GPU routeを含む全40層TF / state / selectionをQ→G契約で照合。返却順入替 / 欠落 / 二重結果 / cast / QDQ / lease・進行を検証し、単GPUT26のPASSを代用しない。 | 完了（元expert-assist component。final-r2 5c5c6de4…/19anchors独立最終重要0/Main受理。5micro465920＋full16057056値/120frame、355S365P/1065copy/取消fresh/会計。T46通常mode/速度・T47draft/peer/physicalは別） |
| T45 | 4/5・OWN/models/deepseek41/execution/layer_split | T12,T13,T14,T15,T20,T21,T25,T26,T34 | 連続2区間 / head配置、secondary native型kernelとMaya境界payload / 追加shared rowsを1017 trunk契約へ実装。全40層TF / 境界state / append / reuse / reset / 有限供給・寿命を検証。tapはT03 / T04由来shape / 型 / 位置 / ownerの最小ABI・合成fixtureまで、実draft結合はT47。 | final0beee42a…/独立90b09bea…重要0/Main元component完了受理。full120frame16057056値・境界65298値とsmall transport/API/cancel→freshの事前Qexact。通常modeT46/実draftTapT47/性能/peerphysical未資格 |
| T46 | 6/7・OWN/tests/backend・control 基本mode資格 / 比較 | T30,T34,T35,T44,T45 | mode別の最小代表caseで通常CLI選択 / 明示切替 / actual mode・placement / 履歴継続、生成終了 / cancel / 安全停止を実証。eager同条件paired ABを比較し速度未達でも両実装を納品。他mode・全client・最適化完成を独立scopeの通常利用gateにしない。 | 現在（impl115）: Main報告では新通常buildを含む候補package739cd90057df7a5564acf3bc4dd879605e388b4be9dae9171feaab172d501900と6profileの組立を完了。CLIによる6profile/identity実exit0・new native一致を確認済みとの報告で、Main有限readback中。manifestはC:\Develop\AI\Strata-extensions\runtime\deepseek41\739cd90057df7a5564acf3bc4dd879605e388b4be9dae9171feaab172d501900\evidence\package-manifest.json（SHA256 41d61c9666f2a0487ff05309b463aefb8bc7f5e48303fc3df21076b635b153a6）、candidate-contextはC:\Develop\AI\Strata-data\build\deepseek-v41\build-deepseek-t46\actual-mode-runner\production-routing-package-r1\normal-candidate-context\candidate-context.json（SHA256 70570e4074a4a165dc81f9eeb3853a6bf5767ca6fafc692f777f85b3df3660f4）。r2 source/保存CPU high重要0をMain受領済み。候補packageの通常client実生成/全scope品質性能/最終配備は未。最新production tupleはT39現在statusのSource b1ccd…/ABI b949…/EXE保存metadata01dac…、通常build exit0完了。CLI routing forwarding r2はC:\Develop\AI\Strata-data\build\deepseek-v41\build-deepseek-t46\actual-mode-runner\production-routing-forwarding-r2、handoff c4f92370d1a63d9cbe1550de5938060afe8a88aac7acbeb1774974378af209f3/source-freeze e29eac38c866b11e01f299b5a1c06707d1150804e2c0dfe13cda52db2e3b2a89/finite-map 7c12ddd688ec007a4fe336cf132a11dc1a13612bcaf7e2fa11d56492a2ee3562。hook290612fb…/testdc052c59…の保存CPU6（0.435s）/16refs/current hash一致を同high正式再review SOURCE/保存CPU subset重要0で受理。with_shared496-497で3keyを事前validateし、shared非空null拒否/explicit0/temperature legacy継承で通常入口迂回P2を解消。候補package組立完了はMain報告の別scopeとして扱い、通常client実生成/全scope品質性能/最終配備は未。測定接合を並行し待ちgateを作らない。以下のCLI GEN0/DRAM実績は旧9420/8920/25fb＋50047に限定し新tupleへ付替えない。通常production buildのsource/必要CPU/build subsetはRoot最終high0/Main受理、旧9420のCLI lifecycle成功を別scopeとして保持。CLI fe366…/context6dd…のsourceCPU high0/Main受入後、TEMP child環境欠落P2をcontext6fb…/repair5d52…/stage65eb…で修正しhigh0/Main受入。修正後の通常CLI経路でSource9420…/ABI8920… single/graph OFF、native7708/server20020がREADY、GEN0。start/READY status/stop/post-stop statusは全exit0、2026-10-22 16:58:16 JSTにserver/conhost/native終了・18080 listener無しを確認し窓返却。READY後DRAM実sample5回はprocess PID/FILETIME/image一致・error0、起動時peakは未観測で、前expert窓の継続sample0欠測を後付けで埋めない。LPの既public accepted server処理継承/旧local RED patch二重適用不要は維持し、通常CLI成功を全client接合・全mode・最終配備資格にしない。直近は全実装統合（DS canonical14file/CLI routing forwarding優先）→通常build→性能比較、必要確認は最後の通常動作へ集約する。独立代表数値1case/取消後次要求1caseは人間指示で取消し、旧9420新3mode batch GOも撤回済み。必要機能/数値/state/lifetime/性能・T33全clients/PiDSH・T46通常選択/切替の残scopeは保持し、既証拠再用・既成功の全面再走/全組合せ/新検証基盤不要、未実施は未確認と表示する。追加stage・packet・proof体裁/文書gateで統合buildやCLI接合を止めない。全client接合・最終配備・全mode資格未、必須37/46=80.4%・残9・未実施加算0。 Mainは6profile context4096/32768/131072/262144/524288/1048576が全てpackage739cd900…/EXE01dac…と一致する設定identityを実読済み。設定identityを全context実動作資格にしない。新b1ccd/ABI b949/EXE01dacのrouting(0,0,0)/effective exact/zero_coefficientsで有限1Fresh採取・原owner回収済み（T35現在status、Main有限readback受入）。旧9420→新各1回のTTFT116.531→118.391秒/token間27.516→29.000秒/GEN→DONE144.078→147.406秒で今回速度向上観測なし。host pipe/ambient差があり因果・統計速度効果は未判定、他の性能・品質・client範囲は未確認。 以下は先行版の受理・失敗・未実施履歴（当時の記述）: 旧de662 single/正式8targetsと4900の3mode10request・D5typedchainの既限定受理は不変、過去managed停止と独立nativeを区別。新T47 b7bb/f04a/f5c823の14GEN試行は9GEN=7complete/1cache typedcancel/1expert拒否、full14 FAIL/acceptedfalse・layer未起動。expert Append2-2 DONE2/postINFO成立後、cancel-target3-3 GENでownercompletionunknown ERR。予定tokenACK STOP未発火、ERR後frames finally cleanupSTOP実送信（raw239）をr2 4458ed69…/f8e7771e…/d9713f46…/833c19dc…へ訂正。原3nativewaitexit0-handleclosed/retained0/postquiescent＋outer81429exit1 receipt45fa0658…は回収証拠、resource正式判断はRoot・現GPU=T36AはRoot relay。最終統合buildでT46通常切替＋T33全client/PiDSHをまとめ、managed/通常package-default採用・全mode数値資格未。現在必須37/46=80.4%（T42任意除外）/必須残9、未実施加算0 publisher plan99c88…は正式受理、sameID再bind残留P2のr2 e846efe3…/freezea90710f8…/CPU56eafc30…/finite2f09b50c…は修正固定READY・focused CPU2＋3成功。RootCapturehigh0/Main正式sourceCPU準備subset受理。final tuple/actual identity/new numericは未確定、assembly/publication/T46/T33/G0。 |
| T47 | 6/7・OWN/models/deepseek41/execution・tests secondary mode結合 | T22,T33,T38,T39,T40,T41,T46 | T37→T38由来の実draft weights / tap / 採否・確定stateと、mode別graph key / owner / lease / 再captureを実装・検証。T33依存は最終consumer証拠の集約依存で、着手/代表runtime実行gateではない。影響する全通常consumer、必要flags組合せ / epoch / fault / 次要求を宣言した代表case・共有境界で確認。旧T46の結合scopeで、総当り / 新suite基盤は追加しない。 | 現在（impl115）: 全実装統合（DS canonical14file/CLI routing forwarding優先）→通常build→性能比較、必要確認は最後の通常動作に集約する。独立した代表数値1case/取消後次要求1caseは人間指示により取消し、旧9420の新3mode batch GOも撤回済み。既証拠を再用し、成功試験の全面再走/全組合せ/新検証基盤/追加stage・packet・proof体裁や文書gateは追加せず、DS canonical14file統合buildとCLI routing forwardingを止めない。既実績・契約依存・既未完scopeを保持し、残るT33全clients/PiDSH/T46通常切替・T43証拠集約も後段の通常動作でまとめて確認する。未実施はPASSにせず未確認と表示する。必要な計画/実装差分reviewは既手順内で最小に行う。新b1ccd統合版は有限1Fresh以外の必要Q/LP/state/lifetime/性能・全client/mode確認が残る。旧9420/ABI8920/EXE25fb＋tuple50047に対する通常CLI起動/health/status/停止GEN0の成功は旧tuple有限実績であり、新b1ccdの数値・生成・性能資格へ付替えない。旧9420 tuple有限証拠のexpert actual3GEN result196df88d…/outcomebabfba41…はRootCaptureの機能＋原owner回収subset重要0/Main outcome読戻し受入済み。同版single相対/LP/fullscope性能/旧根因解消/cancel後Freshは未で、旧9GEN/full14 FAILを当該有限成功で上書きしない。任意routing biasは別限定patch r2のBCrypt buffer lifetime P2修正、CPU226項目再確認・実Win32 8case・両gfx build/link・独立再review完了を経て、新canonical Source b1ccd…の通常build完了へ接合。既定0/target decode/既math・learned bias保持/0 exact/opt-inを維持。候補package/6profile組立とCLI identity確認はMain報告で完了、測定接合・性能測定は進行中。通常client実生成/全scope品質・性能/最終配備は未確認。補正0/ありの整理を独立準備task/review待ちにせず既存条件で測り、補正値を結果に添える。旧A/individual fixture/standalone expert診断/parent join/Bや全旧suite完了を統合前提にせず、受理referenceは適切authorityで再用し通常r5追加suite gateを作らない。旧9GEN/full14 FAIL/layer未・根因unknownを履歴として保持しr4を根因fixにしない。whole T47未完。新canonical b1ccd…通常build exit0完了、CLI forwarding r2は通常入口迂回P2解消/SOURCE保存CPU subset重要0、候補package/6profile組立完了をMainが報告、既存条件の有限1Freshを採取済み、他範囲は未確認。 新b1ccd/ABI b949/EXE01dacのrouting(0,0,0)/effective exact/zero_coefficientsで有限1Fresh採取・原owner回収済み（T35現在status、Main有限readback受入）。旧9420→新各1回のTTFT116.531→118.391秒/token間27.516→29.000秒/GEN→DONE144.078→147.406秒で今回速度向上観測なし。host pipe/ambient差があり因果・統計速度効果は未判定、他の性能・品質・client範囲は未確認。 以下は先行版の受理・失敗・未実施履歴（当時の記述）: 実装中。native6bf13…/a67c…/d4ec…・helper317ae42c…・prepared94e5298b…と14GEN差の既sourceCPU/build/準備受理は維持。14GEN actualはr2 handoff4458ed69…/summaryf8e7771e…/proofd9713f46…/map833c19dc…：9GEN（7complete/1cache typedcancel/1expert拒否）/full14 FAIL/acceptedfalse、layer0。expert Append2-2 DONE2/postINFO成功後の3-3 GENがownercompletionunknown ERR、予定ACK STOPは未発火・ERR後cleanup STOP送信をraw239で確認。根因未断定。観測r4 fbbcbbb5…/Source9936…/ABIb464…/EXE486876…は同high0/Main sourceCPU/build受理、診断plan97332…受理後のexpert3GEN prep/guardCPU10は準備のみ・actualG0。Graph auto binder1ce3…sourceCPU正式受理→実接合CPU tuple/list fix中（Root relay）、元expert FAILの修復/実機資格は未。原3nativewaitexit0/handleclosed/retained0/postquiescent＋outer81429exit1は回収のみで数値受理と別、wholeT47未。通常partitiontap担当/T36非着手gate/元依存契約は維持、T33後回し |

### milestone・主経路・並行branch

milestoneは指定taskと全完了祖先の集合要約であり、taskからmilestoneへの逆依存は作らない。

| milestone | 完了集合 | 達成範囲 |
|---|---|---|
| M-NUM | T26と全祖先 | trunk全40層TF数値core。T21～T24、T27～T33、T35以降は不要。固定入力IDs / binary / assets / native寿命・適用receiptと計測T34を使う |
| M-CACHE | T22と全祖先 | 指定secondary cacheの実機配置・故障 / profile結合資格。P2P不可なら明示host bounceで検証可能。P2P未実施 / 非対応は別記。通常startの機種別資格gateではない |
| M-NORMAL | T33と全祖先 | 基本primary＋RAM / SSDの通常CLI / 全client / 実providerとHuihui共通変更確認。T21 / T22 / T44～T47、補助T42 / 最大候補 / 最適化性能は含まない。選択secondary modeは別証拠 |
| M-MULTI | T46と全祖先 | expert-assist / layer-split両実装の基本数値 / state / 寿命・通常CLI資格とeager比較。DSpark / graph・全consumer結合T47の完了待ちにしない。mode別証拠も個別報告 |
| M-QUAL | T36,T38,T39,T40,T41,T42,T47それぞれと各祖先 | 対象context・各機能・secondary結合・性能効果と補助N→Q品質を別集計。mode / flagsのscopeを区別し、他scope未判定で独立scopeの達成を取り消さない |
| M-ALL | T43と全祖先 | 必須実装scopeの証拠が揃った完了。指定cacheと両演算方式納品は含むが、速度向上・補助T42 / 公式最大・全候補達成は必須化しない。部分reportをM-ALL完了とは呼ばない |

T42はT30 / T33 / T43 / M-NORMAL / M-ALLの依存ではない。独立N未確保をPASSや新GPU必須環境にせず、補助評価として未判定を明示する。
T21は選択roleの共通device / transfer基盤、T22はcache-only資格、T44 / T45は各trunk演算方式、T46は基本CLI資格 / eager比較、T47は既最適化・全consumer結合である。基本T29 / T33 / T40 / T41の閉包は維持し、選択modeの開発時資格を通常start毎の全suiteにしない。T43はcacheと両演算方式の納品証拠を要求し、基本合格を他modeへ流用しない。
部分進捗とM-NORMAL / 個別M-QUALの結果はいつでも報告でき、T43 / M-ALLの完了を待たない。最大context未実施、P2P不可、最適化速度未達だけで通常機能を新たに禁止しない。

- 主経路: T01 / T02 / T03 → T04 / T06 / T07 / T08 → T09 → T05 → T10。model T11～T15と供給T16～T20を接続し、T25 / T26 → T30 → T31 / T32 → T33へ進む。
- 並行可能: 通常provider T23 / control T24 / native計測T34、Recipe T27→server T28→catalog T29、secondary基盤T21。T22はT30等とのjoin。T26後にT44 / T45は並行でき、T46で基本CLIとjoinし、既最適化 / 全consumerとのjoinはT47へ分ける。native数値をserver完成待ちにしない。
- 資格branch: T35基準から長文T36、DSpark T37 / T38、graph T39へ。T36最大到達をT38 / T39 / T40の依存にせず、T40は同統合buildの対象4cellに必要な00/10/01対照scopeを確認して11へ進む。両単独とは当該10/01証拠で、T38/T39全体完了を要求しない。
- 真のjoinは完了依存列で判定する。T41/T47のT33依存は最終consumer証拠の集約依存で、着手/代表runtime実行gateではない。T33自身は後続mode/T47完了待ちにせず、T43の最終全証拠依存を維持する。この主経路は所要時間保証や追加順序制約ではない。
- 現在の進行順（impl115、Main最新指示）: 全実装統合（DS canonical14file/CLI routing forwarding優先）→通常build→性能比較、必要確認は最後の通常動作に集約する。独立した代表数値1case/取消後次要求1caseは人間指示により取消し、旧9420の新3mode batch GOも撤回済み。既証拠を再用し、成功試験の全面再走/全組合せ/新検証基盤/追加stage・packet・proof体裁や文書gateは追加せず、DS canonical14file統合buildとCLI routing forwardingを止めない。既実績・契約依存・既未完scopeを保持し、残るT33全clients/PiDSH/T46通常切替・T43証拠集約も後段の通常動作でまとめて確認する。未実施はPASSにせず未確認と表示する。必要な計画/実装差分reviewは既手順内で最小に行う。新canonical通常buildはMain報告でexit0完了。tupleはC:\Develop\AI\Strata-data\build\deepseek-v41\build-deepseek-t39\production-native-routing-integration-r1\production-tuple.json（1375B/SHA256 281441294861e568d3445bdb0516a3a59669e4905a9b49bf05f7aaf1eec2f495、中央全文read/hash一致）、Source b1ccd0eb44bf5634b2f31e6d7509863941708dd520004c0c673fdc773b835d7f/ABI b94972e73cd79e4ff7a7b404d140ba5d989f2870c48be35665faa7d176a29e52/EXE保存metadata SHA256 01dac3de813b21259acf1f922848afc1df266f0509425d694565ee221294afa0・2846720B。normal29TU/O3/gfx1100+gfx1201/observer=false/trace=false。tupleのnative_executed=false/GPU=false/independent_review pendingはfreeze時metadataで、実測成功は推定しない。既r2 native14fileのcode high0を全面再reviewせず、候補package/6profile組立完了をMainが報告、Perfは旧build固定参照/DLL配置調整後、既存条件の有限1Freshを採取し原owner回収・窓返却済み、他範囲は未確認。CLI routing forwarding r2はC:\Develop\AI\Strata-data\build\deepseek-v41\build-deepseek-t46\actual-mode-runner\production-routing-forwarding-r2、handoff c4f92370d1a63d9cbe1550de5938060afe8a88aac7acbeb1774974378af209f3/source-freeze e29eac38c866b11e01f299b5a1c06707d1150804e2c0dfe13cda52db2e3b2a89/finite-map 7c12ddd688ec007a4fe336cf132a11dc1a13612bcaf7e2fa11d56492a2ee3562。hook290612fb…/testdc052c59…の保存CPU6（0.435s）/16refs/current hash一致を同high正式再review SOURCE/保存CPU subset重要0で受理。with_shared496-497で3keyを事前validateし、shared非空null拒否/explicit0/temperature legacy継承で通常入口迂回P2を解消。候補package組立完了はMain報告の別scopeとして扱い、通常client実生成/全scope品質性能/最終配備は未。測定接合を並行し待ちgateを作らない。新通常buildを含む候補package739cd900…/6profileの組立とCLI identity実exit0・new native一致はMain報告で完了、Main有限readback中。r2 source/保存CPU high重要0はMain受領済み。候補packageの通常client実生成/全scope品質性能/最終配備は未。実統合先は既WT Strata-extensions。Graph native/Integration CLI・control・profiles・packagingがsolewriter、DS/Perfがpatch supportし受理成果を合成。5系統＋C32/persistentの具体受理deltaは旧9420へ反映済み（当該未反映0）。Perf binderの旧R4 literal/observerON固定→統合handoff/plan435bと実boolへの局所authority修正はRootTinyhigh0/Main sourceCPU subset受理（handoff9bda/validator7a1b/CPU9da3/manifest64ff/delta8a57）。一般速度効果未判定。追加wave全完了/未確定44全件採用とはしない。任意routing biasは別限定patch r2のBCrypt buffer lifetime P2修正、CPU226項目再確認・実Win32 8case・両gfx build/link・独立再review完了を経て、新canonical Source b1ccd…の通常build完了へ接合。既定0/target decode/既math・learned bias保持/0 exact/opt-inを維持。候補package/6profile組立とCLI identity確認はMain報告で完了、測定接合・性能測定は進行中。通常client実生成/全scope品質・性能/最終配備は未確認。補正0/ありの整理を独立準備task/review待ちにせず既存条件で測り、補正値を結果に添える。旧9420の通常29TU Release/strict/両gfx/normal observer=false/normal trace=falseのconfigure/compile/link0＋GLOBALActor compile/link0、S-RR統合CPU13case/330assert0はRootCapture最終high0/Main native SOURCE/BUILD・必要CPU subset正式受入済み。tuple内review pendingは生成当時metadataで、今回の受入根拠はMain最終引継ぎ。新b1ccd統合版は有限1Fresh以外の必要Q/LP/state/lifetime/性能・全client/mode確認が残る。旧9420/ABI8920/EXE25fb＋tuple50047に対する通常CLI起動/health/status/停止GEN0の成功は旧tuple有限実績であり、新b1ccdの数値・生成・性能資格へ付替えない。旧9420 tuple有限証拠のexpert actual3GEN result196df88d…/outcomebabfba41…はRootCaptureの機能＋原owner回収subset重要0/Main outcome読戻し受入済み。同版single相対/LP/fullscope性能/旧根因解消/cancel後Freshは未で、旧9GEN/full14 FAILを当該有限成功で上書きしない。CLI fe366…/context6dd…のsourceCPU high0/Main受入後、TEMP child環境欠落P2をcontext6fb…/repair5d52…/stage65eb…で修正しhigh0/Main受入。修正後の通常CLI経路でSource9420…/ABI8920… single/graph OFF、native7708/server20020がREADY、GEN0。start/READY status/stop/post-stop statusは全exit0、2026-10-22 16:58:16 JSTにserver/conhost/native終了・18080 listener無しを確認し窓返却。READY後DRAM実sample5回はprocess PID/FILETIME/image一致・error0、起動時peakは未観測で、前expert窓の継続sample0欠測を後付けで埋めない。LPの既public accepted server処理継承/旧local RED patch二重適用不要は維持し、通常CLI成功を全client接合・全mode・最終配備資格にしない。旧A/individual fixture/standalone expert診断/parent join/Bや全旧suite完了を統合前提にせず、受理referenceは適切authorityで再用し通常r5追加suite gateを作らない。旧Aは自然終了・両native/outer exit0・原handle wait/close/postquiescent/資源返却・5checkpoint127..131比較成功の作者有限結果（Source4542…/SerialCompatibilityのみ）。旧B/HTTP未開始。旧A完了を新統合版機能資格にしない。旧expert actual9GEN=7complete/1typedcancel/1failed・full14 FAIL/layer未・根因unknown、r4は元例外露出の観測修正のみで根因fix未。最新版と必要検証を独立reviewし重要指摘を修正/re-reviewする。通常機能を未検証だけで削らずpublic/Huihui/defaults/deploy/commit・push・PRの既存保護/個別承認を保持。rollback/PoC/soak/長時間試験/新controller/通常制限/余計な台帳は追加しない。GPU一件とCPU build/review並行、旧成功再走は変更影響だけ、RAM8GiB目安report-only。必須37/46=80.4%・残9・任意T42別・追加完了数0。 新b1ccd/ABI b949/EXE01dacのrouting(0,0,0)/effective exact/zero_coefficientsで有限1Fresh採取・原owner回収済み（T35現在status、Main有限readback受入）。旧9420→新各1回のTTFT116.531→118.391秒/token間27.516→29.000秒/GEN→DONE144.078→147.406秒で今回速度向上観測なし。host pipe/ambient差があり因果・統計速度効果は未判定、他の性能・品質・client範囲は未確認。
### 未確定事項を解くtask・旧資料との対応

| 未確定 | 解消するtask・証拠 |
|---|---|
| Windows / HIP / toolchain・実storage | T02,T06,T07,T09の再確認・build / fixture |
| 全header / 型方言 / span / 全asset同一性 | T03,T05,T08,T09,T10の少量fixtureと全量receipt |
| 精度 / 独立性 / 実working set | T04,T11,T18,T20,T25,T26、全N→Q品質は別T42 |
| secondary mode / identity / P2P / bounce / drain | T21,T22、役割 / 切替はT29,T30、trunk演算 / stateはT44,T45、基本CLIはT46、最適化 / consumer結合はT47、最終証拠はT43 |
| Recipe Windows依存・元IDs / 実protocol | T23,T27,T28、consumer / 権限結合はT31,T32,T33 |
| draft / confidence / graph / 速度 / 最大context | T37,T38,T39,T40、長文scopeはT36 |

旧資料29 / 32課題とI01～I03の番号は新task IDとは別の実行分解である。
旧資料追加のmodel / 型 / candidate境界はT03,T08,T09,T10,T15,T25の契約に内包し、新機能を追加しない。詳しい数値・寿命・通常利用契約は後続章を参照する。


### T01実装証拠（2026-10-21、実装r1）

- 対象は開発worktreeの `Strata-extensions/control/contracts.py`、`control/deepseek41.contract.json`、`tests/test_contracts.py`、`README.md` の4成果物。外側の通常入口・catalog・profile・stateは変更していない。
- TDD red: validator未実装時の `ModuleNotFoundError: contracts`。green: `python -B -m unittest discover -s Strata-extensions/tests -v` の5test成功。作成者と別のreview担当が同5testを再実行し成功、launchのprimary / assignment / mode変化を拒否する追加read-only probe3件も成功。
- 実装r1の独立reviewで未解決重要指摘0。fixed refs、未確認inventory、native型維持、採用/notice境界、4mode/epoch、動的transfer path分離、既authorityの維持を確認。
- 固定SHA256: `control/contracts.py` = `6769f7e1e23247e19937171533e8a12fd5168b3dfa3ac17aae5b7db4ede5a9c1`、`control/deepseek41.contract.json` = `7629b7b5dde77a43b1110a1a777324d3b141f4ef8d5e8540ca8e03ceef8f32c4`、`tests/test_contracts.py` = `b5330dbf9beb425b622ebb5b80b2be3cf58c31851b082530d91ac0a2109eb957`、`README.md` = `d98e74229a9155a1adbdddaaa5112c2f2d6217723210b0fd2684e3b40690421a`。
- 変更はPython / JSON / Markdownだけで上流native source / CMake / backend hookは無変更のため、CUDA / HIP / SYCL buildはT01に非該当。実header・native型inventory・license text収集・native build・GPU・runtime・通常clientは未実施で、T01完了はそれらの成功を意味しない。契約JSONはprod registryや通常startの追加authorityではない。


### T02実装証拠（2026-10-21、記録r2・独立review重要0）

- 成果物は開発worktreeの `Strata-extensions/tests/environment/t02-inventory.json`、`t02-storage.json` と同README。Main承認済み最小実行案r1に従い、実測inventory・段階別有界見積・未知・実行前再確認を記録した。後続build実測をT02へ逆依存させず、task DAGは変更しない。
- fresh時点 `2026-10-21T00:38:04.2412988+09:00` のC空き609,457,401,856B、RAM total102,897,238,016B / available39,132,360,704B、commit120,613,797,888B / limit194,347,909,120B。環境担当の早い時点のsnapshotとは分け、自然変動を同時測定として扱わない。
- exact pathのStrataMod `.vision-venv-10.1/Scripts/hipcc.exe` はHIP7.16.26385・AMDclang24.0.0git・windows-msvc、同venvのCMake4.1.3 / Ninja1.13.0。別候補Strata `.venv/Scripts` はCMake4.4.3 / Ninja1.13.2。MSVC14.44・WindowsSDK26100とDLLのdisk存在を確認。shared環境は変更していない。
- 有界開発増分見積11,341,398,016B（既toolchain読取参照0、9header603,979,776B、実fixture536,870,912B、早期build8,589,934,592B、vendor1,073,741,824B、一時536,870,912B）。実測peakではなく、足りなければ実態を確認して見積を更新する。試行値を通常利用の制限・新headroomへ昇格させない。
- 原本1copy500,707,576,573B＋開発見積=512,048,974,589B、snapshotとの差97,408,427,267B。将来fullbuild / bundle / 比較 / temp / cache等の未知最大値を含まず、全将来容量PASSを示さない。全量2copy1,001,415,153,146Bは空き容量超過。各phaseとT05全量取得前に保持領域・必要増分・空きを再確認する。part直書き→同一volume rename/cache全量複製回避はT05で実装検証する仮定。
- JSON parse、合計・原本との和・snapshot差・2copy超過のreadback算術を確認。GPU dedicated値はDXGI属性のみ。WDDM budget・HIP context・compile・loaded DLL identity・native build・runtime操作は未実施。T02は有界開発記録scopeで、全量T05容量保証ではない。

- 記録r2の独立review重要指摘0。作成者と別の担当が8算術invariant・toolchain/DLL14file・Model root存在・hipcc/CMake/Ninja versionをread-only再確認し一致。README内の旧T02未実施文をT01 testsの証明範囲へ限定して矛盾を解消した。
- 固定SHA256: `tests/environment/t02-inventory.json` = `1e72915b451f9c24e4a698b4e7383e4011b66c80bf3e0cf313af246aeabf921f`、`t02-storage.json` = `f373c1102732464c15ef53225f9eb8d5a23bbb1ac1135af2ac1c6ec09612e39e`、T02追記・当該review時点の `README.md` = `d7cfeb4c3e60a428a1abd22d72a691aefb79abaa9fd538fe83d245342fdbe376`。T01節のREADME hashは当該T01版を示し、後続task追記後の共通READMEは別版としてreviewする。


### T03実装証拠（2026-10-21、実装r3・独立review重要0）

- source/test/receiptは開発worktree `Strata-extensions/native/artifact/{gguf.py,acquire.py,quant_layouts.json}` と `tests/artifact/{test_gguf.py,test_acquire.py,source-files.json,header-inventory.json,fixture-receipts.json}`。raw binaryは上記DATA保存mapへ限定しGit追跡しない。
- TDD red（reader/helper未実装）後、短read・誤Range/total/ETag・200body読前拒否・unknown型・shape・重複/重なり・file外span等の12test成功。実metadata-only shard1がpadding無しで終了する点も追加red→修正→greenで確認した。
- 全9header計5,960,813B、1043tensorのtype/name/shape/rowstride/absolute span/alignmentを検査。実型F32(0)、Q8_0(8)、MXFP4(39)、MXFP8(43)。固定Maya pack_gguf.py/ref_gguf.pyのsource SHA・行番号とblock/code/scaleをquant_layoutsへ記録し、別converterの数値ID単独互換は主張しない。
- shard1は全5,780,589BのLFS SHA一致、metadata-onlyで129280語tokenizer identityを固定。残8shardはprefixだけでfull SHA未検証。tokenizer pre宣言`joyai-llm`とMaya説明`deepseek3`の互換は未確定で、後続codecへ引き継ぐ。
- 6実fixture計18,826,824B（MXFP4 gate/up/down各1expert、MXFP8 Engram1row、Q8_0 token1row、F32 norm全vector）。revision/LFS fileidentity/絶対offset/layout/fixture SHA/HTTP来歴をreceipt化、非zero scale/scalarを確認。offline raw再読込で9header/1043tensor/6fixtureのSHAとspanを再derive成功。decoder/kernel数値合格ではない。T09実top6で追加distinct expert spanが必要なら同来歴schemaで取得する。
- 独立実装reviewの重要指摘1（fixture receiptのshape/layout/selection/HTTP/nonzero再照合不足）を修正。純粋validatorでheaderと選択規則から再deriveし、type/layout/dims/index/selection/rowbytes/fileidentity/span/HTTP5項目/nonzeroの16変造負例を追加。既rawを再利用し再DLなしで12testと実raw readback成功、header scalar/array要約・token_count/data_start/alignmentもrawから再deriveし、必要6fixture集合の欠落/重複を拒否する負例を追加。独立再review重要0。
- 固定9shardはtrunk0–39層とDeepSeek Engramで、現名前/header分類では独立draft/vision tensorは未検出。DSpark target37/38/39のtrunk共有/reuseを含む実asset対応は未確認でT37が照合する。metadataをweightの代用にせず、絶対欠如や通常の恒久無効化を断定しない。画像はtrunkと別scope。Qwen PLE/共有MTPを流用せず、未対応を恒久的な通常利用禁止へ変換しない。

- r3の独立review重要0。別担当が12unittestと実9header/1043tensor/6fixture readbackを再実行し成功、元fixture6変造・header count/config2変造・empty/missing/duplicate3変造の実receipt in-memory11負例を全拒否。固定Maya sourceのblock/code/scale仕様も独立照合した。
- r3固定SHA256: `native/artifact/acquire.py`=`02696974a395ee3b7abb169928c1708a346274de378259af103e50f5731d86bf`、`gguf.py`=`4b22d136443bb89cccae06cc19c9172e5c2309baff634a3ed997408e25c3dead`、`quant_layouts.json`=`92be7dfe162dbc4cad846332f65d7b365a41d5947609b93cc5fe6d82d3436c67`、`tests/artifact/test_acquire.py`=`1be54410e99cc6bc212611083e99f6df28708453840d48dfebabc6672db25ef7`、`test_gguf.py`=`830b30c04f4307c97569d3d344ad3d14c32a7c1553eaebfcef45572e0e86afe0`、`source-files.json`=`3c226d451f4b3a0b6b12b69fab492e559226bc23c6d02fcf926964bf33178ec6`、`header-inventory.json`=`08583c5cff84627962517db22ec877a69fd1aed3a811eb010d2f2f3e2f84366b`、`fixture-receipts.json`=`209bd9447056589998024b5cdb5a9d23c4a29fad281e11db30f201cd048df88b`。当該review時点README=`4e796bface0a4bae598ab731064a02b7dde346c3912f7ca4089edbbee5911670`。
### T06実装証拠（2026-10-21、実装r2・独立review重要0）

- 別担当の合意5fileでstandalone C++17・MSVC /MTの早期host targetを隔離build。compiled3fileとrecipe2file、固定base/upstream参照を区別し、tracked上流sourceは無変更・patches=[]。/MTはfixture target限定。
- 検証前にbundle manifestを固定→同source/binary/toolchain bindingで18case（hashlibとの6正例・7拒否・5binding case（正例1 / 改変負例4））→検証後同binding確認。独立担当も固定exeをrebuildせず18case再実行成功、7tool/2直接DLL disk SHA・前後binding一致を確認し重要0。
- worktree `build-deepseek-t06/bundle/manifest.json` SHA=`4a75f774b8b595dd29d72d2082de755ec2592f0405ac74ad45c27b6c81c0d92d`、exe SHA=`81a6461d28218d96d36f05c9afa299f0131f3889f2cea49f705666c9b993d1bf`、verification.json SHA=`e1eeff36ac7a901c700fd36d818382572e6abcbf544424f8daf3b45d397718fa`。生成32files logical1,746,530B（先行RED/失敗configure記録を含む）。
- 直接PE importsはKERNEL32/bcryptのみ、System32 disk identityでありloaded DLL証明ではない。完了は早期Windows host試験bundle scopeのみ。HIP/GPU/fullengine/数値/server/runtime整合は未実施、server/runtime bundle整合は該当provider統合時に追加する。通常startのgate追加0。


### T04実装証拠（2026-10-21、実装r3・独立review重要0）

- 最小実行案v2は独立計画review重要0・Main承認。成果物は `Strata-extensions/tests/numerics/{reference.py,compare.py,reference-contract.json,known-vectors.json,n-rms-trace.json,test_reference.py,test_compare.py}` の7file。NとQ format oracleを別scopeにし、native/将来G decoderをimportしない。
- Nは固定HF1017 `inference/model.py` SHA `e5decd76fe70fd56ef2f10124d245c6f64fb6a0003cc9068a1d3182a168b8d2d` 281–293のRMSNorm可読数学CPU参照。H5120、BF16in/weight→FP32 square/mean/add-eps1e-20/rsqrt/weight multiply→BF16out。zero/unit/小振幅±2^-32・重み33/32の3caseについて、候補/Q/Gを使わずDecimal100桁と明示IEEE丸めからliteral中間/最終traceを先固定。定振幅2の冪fixtureのsquare和はexactで、一般の公式GPU還元順序とは区別する。
- Q formatはF32/Q8_0/MXFP4/MXFP8の18literal knownvectors、BF16 tie3case。finite FP32bit一致・明示nonfinite分類一致を分け、N公式operatorの証拠へ数えない。T03固定receipt SHAと6実fixture SHAにbindして各先頭/末尾blockをscalar復号・finite確認。実weightのN→Q品質/G parity未証明。
- strict expected manifestとsmall exact baseline/holdoutをG実装前に固定。shape/vocab長/IDs/position/next token/BOS/全長/finite/derived metricを確認し、empty/truncatedを救済しない。ゼロnormの明示絶対fallbackは正例と負例で確認。router/tie/mHC/Engram/attention/state/実shape GEMV等のoperator baseline/閾値は当該T11–15/T25比較前に固定するpending、全N→Q品質(T42)も未実施。
- TDD red（未実装import）→green13test成功。誤epsilon1e-6・早期BF16castを最終bitで実検出し、format/nibble/scale/cast差・不正block・shape/vocab/length/ID/position/BOS・NaN/derived overflow・不正expected manifestを拒否。通常出力/retry/context/起動gateは変更していない。Python/JSONだけでCUDA/HIP/SYCL source変更なし、T04のGPU/backend buildは非該当。

- r1/r2で受けた独立review重要R1/R2/R3/R4をr3で修正し、独立再review重要0。R1: expected/observed双方へstrict integer schemaを適用しbool/float同値のIDs/shape/BOS通過を拒否、special oracleはisinf/isnan/finiteを正しく区別し有限代用品の負例を追加。R2: 合成rounded-score/有効mask/candidate/mandatory/tie境界集合を実導出してnear-tieを含む正負fixtureを追加（実router baselineは後段）。R3: native MXFP4 nibble0/8は固定GGML/Maya整数LUTの+0復号に訂正し、理想E2M1符号zeroとF32/MXFP8符号保持を分離した。G結果に合わせたgolden調整ではなく固定一次sourceの契約是正。raw storageのbitは変更していない。R4: 固定Maya MXFP8候補のFP32scale生成→code乗算を明示し、e255のzero→NaN/half・nonzero→inf、e254高finite境界5vectorと誤finite代用品拒否を追加。理想OCP/reserved規則・別converterへ一般化せず、G結果に依存しないsource契約訂正。r3は13test成功、独立再review重要0。別担当も13test成功、observed bool/float5変造・不正mandatory2・nonfiniteをfinite代用1の8probe拒否。Ntrace3caseはreference.py不使用のDecimal100/独立RNE再構成でも全中間/最終bits一致。
- T04 r3固定SHA256（当該review時点版）:
  - `tests/numerics/compare.py`=`78f422d36ae596c224d8abc068ad2cd07cc3a22e0bb11d2981bafb45390725bc`
  - `tests/numerics/known-vectors.json`=`9869a63d078a2866f6419e5b0c06445d94aa21b560bea73657cdd42108b16acd`
  - `tests/numerics/n-rms-trace.json`=`d5907b35e814e28e3aec237d16b91e79811269500ac1b21f58a012da62c429d4`
  - `tests/numerics/reference-contract.json`=`f04eff0d305090d821e824dd703c16bee2f90a8dd68651a879d5bdf00519e007`
  - `tests/numerics/reference.py`=`ff9beda527de68db92984f76754e0294e94b4f76a995a62b32b96db9f6e6d2e8`
  - `tests/numerics/test_compare.py`=`5f859be916eb97f67eafb50fb04d967a91f7dd35dc6ee6ba94c2ae624067f30f`
  - `tests/numerics/test_reference.py`=`cd0c4c304344528b5e668df22c401a4a52396ca8bc33828bca13cf8cfc5c7698`

### T07実装記録（2026-10-21、別担当r2・独立review重要0）

- Main承認済みpre v3に従い `native/hip` と `tests/hip` のみ別担当が実装。T06固定files/bundle・T03artifact配下は変更しない。AMDclang24でgfx1100/gfx1201両archをcompile/linkしcode objectを確認、source/recipe/aggregate/binary改変の4disk-only負例を検証。この着手時点ではprimary小GPU試行/独立reviewは未了だった。最終結果は下記r2固定版。
- 別時点snapshot `2026-10-21 01:03:27 JST` で生成458files logical412,198,144B、task-local bundle411,053,315B、C空き610,457,063,424B。既共有toolchain読取参照0増分とは別に、HIP/BLAS実DLL/kernel assetsのtask-local copy約411MBを実測増分として記録。T02過去snapshot/見積を上書きせず、全toolchain copyは行っていない。この01:03時点では実GPU/API/loaded DLL等は未検証だった。以後のr2固定結果は下記に記す。

- 後続attempt3はMain直前status停止確認後の小fixtureで両GPU各4096vector完全一致、16x16SGEMM maxabs0、injected cleanup後の次op maxabs0・invalid ordinal拒否、5loaded DLL path/SHA一致・stderr空を別担当が報告。初回のHIPBLASLT_TENSILE_LIBPATH試験override誤配置とgfx1100 assets不足は失敗記録を保持し、公式arch resolver/同版AMD10.1.0 wheelのtask-local限定展開で修正。attempt3報告時点は独立review未了だった。最終のr2固定scopeだけを下記で完了とし、DeepSeek演算・同時peer/multiGPU成功へ転用しない。
- attempt3依存追加はwheel201,201,815B＋選択250assets74,377,625B（両方保持する増分275,579,440B）。publisher SHA未掲載は未確認と明記し、取得SHA・同版RECORD/ZIP境界を検証、shared package登録/driverは変更しない。別時点 `2026-10-21 01:12 JST` 生成688,540,780B / bundle485,589,714B / C空き610,630,758,400B。T02過去snapshotや01:03 snapshotと区別する。


- T07最終r2は4sourceのHIP-only差分で上流tracked base無変更。primary R9700 PCI07/gfx1201とsecondary7900 XTX PCI03/gfx1100を個別に実行し、init/alloc/BLAS/stream/event/pinned/timing/4096vector・16x16SGEMM・invalid device拒否・注入cleanup後の次op、各5loaded DLL実path/SHAを確認。CPU doubleとのSGEMM maxabs0・次op0、両stderr空。local/shared WDDM照会は各HRESULT0、unknownはnullに分離し片側failure2負例も確認した。
- T07独立review重要0。reviewerは固定677bundle hashes/実行receipt/source binding等のread-only検査で、独立GPU再実行は0。担当の実GPU成功と独立artifact reviewを区別する。Main最終確認済み。fixed manifest SHA=`97f03ea51572d22785705cc3ea70d7273766ffad293db8c839f3fabea3e8b058`、exe SHA=`b80c6d7c592db1e1d7fac8ff74bf8e1fe77c28018233d7c435873c2f7869e6f2`、verification SHA=`ab9fadabdbdbc443d61daaaa7fd3161a0e89ce1a6371f58ffca27705e06ff68c`。wheel固有license/publisher SHAは未確認、同版component noticeを保持しlocal fixture依存として利用、再配布未実施。
- 未実施はDeepSeek実shape/全数値・model生成・peer同時multiGPU・server/full DLL closure・個別BLAS kernel asset read paths。T21/T44/T45等の最終両GPU資格へこの小fixtureを代用しない。T06固定host bundle/source、T03 raw/receipt、shared SDK登録・driver・現live管理は変更していない。

### T08実装記録（2026-10-21、実装r1・独立review重要0）

- 承認pre r1のnew6file: `native/artifact/{native_reader.hpp,native_reader.cpp,NOTICE.md}` と `tests/artifact/native/{CMakeLists.txt,reader_main.cpp,build_verify.py}`（開発worktreeのStrata-extensions内）。既T03/T04/T06/T07固定source/receipt/bundleは変更しない。
- 固定base GgufFileとQ8 dequant/FP16変換をunmodified include再利用。T03 strict/SHA prefix caller条件は固定T03 validatorの子processで再verifyし、上流metadata emplace/一般Unicode等まで全面妥当と主張しない。prefix mmapを原source全量に見せずpayload pointerは使わない。owned側で原logical sourceに対する型/shape/block/stride/alignment/overflow/span/overlap/split/全1043tensorを検査。
- ABIは `TensorSpan` の原tensor全spanと `FixtureView{path,source_absolute_offset,bytes}`。read_exactはlogical-baseの物理offset、logical/physical範囲・size・shortreadを検査。0/8/39/43 C++scalarはT04Qと実装を共有せず、nativeMXFP4+0/MXFP8先FP32scale等18literal、実6fixture先頭末尾・3expert row境界をQとbit照合。全raw staging copyはSHA一致で、FP32decodeをlossless requant/repackと呼ばず自動requantもない。
- TDD redはmissing native_reader.hpp、初期CMakeのWindowsバックスラッシュescape failureをtask-local posix pathへ修正（先行cache保存）。MSVC C++17 /MT host build→事前manifest freeze→67cases成功→同binding確認。scopeはnative reader/scalarだけ、HIP/GPU/fullmodel/model生成なし。
- bundle manifest SHA=`94d9b285e4586decfbc55f751902907434f59f02eed6ef873f87d939dbc768dc`、exe SHA=`9f230dda9f7beb5dfa25ed6d1b3f91240037d9698b44dea76dabd7e9f8c4fc82`、verification SHA=`ecfbb2ef11476c47e12607b0c411a77aed39daf4a8d0f05e7325cf6a97d9caa3`。compiled owned3/vendor5、recipe5、input66、tool8、license4をbind、直接DLLはSystem32 KERNEL32のみ。Strata/ggml MIT全文をsource noticeとbundleへ保持し、通常start authority/gateを追加しない。
- 独立実装review重要0。別担当が固定exeをrebuildせず --verify-only の67casesを再実行し成功、owned3/vendor5/recipe5/input66/tool8/license4/directDLL1の全92file SHA、compiled aggregate/identity、6全byte copy SHAを独立照合し一致。検証前後のmanifest/exe/verification SHAも不変。build.logは直近configure/no-work照会のみでcompile出力全文の保存とは扱わない。
- 開発中の別時点 `2026-10-21T01:36:18.6621106+09:00` にC空き610,798,706,688B、T08生成logical21,415,371Bを観測（初期build後・最終67case freeze前）。T02/07の過去snapshotと区別し、全将来build容量保証にしない。T09追加expert1..5=94,003,200Bの取得writerは環境担当だけ、別receipt/rawでpre承認後、T03原6fixture集合不変更。
### T34実装記録（2026-10-21、実装r2・独立review重要0）

- pre r2独立review重要0・Main承認後、`native/stats/measurement.hpp/.cpp` と `tests/measurement/{CMakeLists.txt,measurement_fixture.cpp,build_verify.py}` の5fileを作成。旧source/生成bundleとT09領域は不変更。
- identity/phase付きのplain byte/ledger snapshotと純粋関数のみ。累積counterは同producer `counter_source`・増加sequence・非減少を照合してdelta化し、snapshot/deltaのmergeを提供しない。ledgerは単一gauge内owned host/deviceだけを加算、pinned subset・queue/lease・OS physical/commit/WDDMを重複加算しない。logical requestedをphysical実測と呼ばずunknown/実0を分ける。
- host完了monotonic区間と同device event区間は別型。非正分母・非finite・未完了・低分解能・跨domain/deviceは理由付き未判定。Windows QPC/frequencyからnsとceil名目tick量子を取得（今回100ns）；実測clock精度や全区間正確さの証明ではない。reader thread合計時間をwall/overlapへ換算しない。
- TDD missing source REDを`build-deepseek-t34/tdd-red.log`に保存、MSVC C++17 /MT /fp:strict実compile/linkを`build.log`に保存。事前manifest固定→51cases成功→事後binding一致。40native正負case、実norm20,480B read/short/missing3case、4observed clock変造拒否、4binding改変拒否。r1独立review重要1のwrapper分解能0受理をr2で修正し、positive secondsには正のresolution/elapsedを必須化した。実readはfixture/asset/bundle/request/epoch/phaseにbind、physical I/Oはunknown。実GPU/allocator/transfer計測・token IDs/count/usage0/TTFT/TPOT/SSE/percentile/paired AB/server結合は後段consumer時の未実施scopeで、通常起動gateを追加しない。
- r2独立再review重要0。別担当が固定exeをrebuildせず51cases再実行成功、元の実出力resolution0変造拒否を再現。source5と全19boundfile SHA、compiled identity、前後manifest/exe/verification binding不変を独立照合。実GPU再実行は0。
- 固定bundle manifest SHA=`3090c6b43f76beb5d2d00a088acbd7ee899f30d5ca349230756c97a5a7ee9e78`、exe SHA=`8dddb809a1ce65932bc3bc610a56277b8c2f357b2aa5096f3d57ce0427e8e43b`、verification SHA=`fe0d6b53a8dd4864847173f18964c8762a28a26706e25d730bc8b7cd4b4c85d4`。source3/recipe3/input3/tool8/license1/directDLL1をbind、固定T06toolchain helperをread-only再利用。直接DLLはSystem32 KERNEL32のみで全loaded closureではない。

### T09実装証拠（2026-10-21、別担当r2・独立review重要0）

- `native/quant`3fileと`tests/quant`6fileでnative0/8/39/43のHIP packeddecode/projectionを実装。T03原6fixtureは不変更、新15span94,003,200Bでlayer0 expert0..5 gate/up/downの6distinct集合を取得。Q期待はG前に固定し、FP32dyadic整数/8192の2入力族、B1/2/4/8、gate/up H5120→F2304・down F2304→H5120、Q8 embedding H5120・Engram MXFP8 H256・F32 norm H5120の実1rowも比較。
- Main直前status確認後、R9700 PCI07 gfx1201/7900XTX PCI03 gfx1100を個別実行し各213job成功、stderr空。各GPU realdecode212,347,136値・realprojection1,751,130値・storage literal514値・runtime boundary6値の全bits/classが独立Qと一致。Q5tests/34negative成功。入力は一般BF16exactではなくFP32dyadicで、公式activation cast/QDQ/fullFFN/router/後段engine供給・stream寿命・fullmodelは未資格。
- r1の独立重要R1(Krow block32)/R2(output exact bytes)/R3(追加receiptのT03原tensorbase+expertID×bytes・fileidentity・HTTP再導出)をr2で修正し再実行、独立最終review重要0。reviewerは全213出力/両roleの長さ・SHA・全bits/classesを独立再照合、独立GPU再実行0。担当GPU実行と独立出力照合を分離する。
- fixed `build-deepseek-t09/bundle/manifest.json` SHA=`6cbfebb0ba8b9472c7235f4342962eb099449cd2da6aab936024824f8d04d6fc`、exe=`54f70bfe9b10b06447ef6d6bde01cbe5fb885cb847df8697e2e3bf271f26428f`、G前Q期待=`a76e5bc46b75d8aae50713c94953918437a10601994a7779640c5d2df0935735`、`build-deepseek-t09/verification.json`=`790117fadeb6616feb0fe0a6eb471e44dc587b5ab142744b307e5c6e5e2de022`。旧r1出力保持を含むbuild4,566,713,932B/raw別94,003,200B、担当観測Cfree606,111,838,208B。ownGPUpeak53,452,800B/nativehostPeak124,329,984/124,153,856B、Q process/context内部peakunknown。T05前fresh freeには既保持が算入済みなので二重減算しない。

### T05着手記録（2026-10-21、検証/全9取得未了）

- pre r1独立review重要0・checkpoint小tmp追補・Main承認/T09依存成立後、`native/artifact/full_acquire.py` と `tests/artifact/test_full_acquire.py`を実装。`full-model-receipt.json`は全9SHA/header/trunk対応/原本6fixture再照合成立後だけ生成し、現在は未生成。
- 保存先は `C:/Develop/AI/Model/DeepSeek-V4.1-Flash-1017-GGUF/f924b94f19c1fea02c06a65c8475b0a45e2b88b1/UD-Q4_K_XL`。同dirの各file.part/.part.json/.part.json.tmpとMain承認追補の小file.part.lockを使い、最大256MiB HTTP206 rangeをbody前identity/length/encoding検査、1MiB bufferで直書。committed prefixは再開時1回だけSHA再計算、その後running SHAを継続してO(N²)再hashを避ける。全SHA成立後のみ同volume rename、既存不一致/不明partは保存停止。通常startへ全hash gateを追加しない。
- missing module RED→19offline tests成功。実shard1で1MiB commit後の計画中断→再開→残4,732,013B取得→LFS SHA/同file rename一致を確認。取得前r2独立review重要0後に全量取得を開始、全9SHA/fullreceiptは未了。
- 取得前r1独立重要1の同時resume競合をr2で解消、取得前code/protocol scope独立review重要0。同fileのprefix検査/truncate→write/checkpoint→renameをCreateFileW share0/delete-on-closeの小`.part.lock`で一括保護し、第二processはbusyでpart/stateを変更しない実interleave負例に成功。これは明示取得内の排他で通常runtime gate/registryではない。正常な旧checkpointとraw prefixを確認後、同source所有prefixが完全な小tmpの中断bodyだけを除去して再開する。未知tmp/所有prefix自体が不完全なtmpは保存停止し、無関係fileを削除しない。
- Main承認でfixed download_fileを変更せず末尾shard9だけ追加worker1本を17:19:54UTCに開始し、最大2file並列とした。globalreceipt writerは元mainだけ。各fileのOS lock/stateは独立、追加開始前にも全9残必要量とcode bindingを確認。mainは2→8後に9finalを明示SHA再検査して再利用する想定で、同fileactive衝突はbusy停止として扱う。44.484秒窓aggregate24.939MB/s、次79.594秒窓24.662MB/sは同時physical part size差分の参考値（commit/モデル速度ではない）。3本目以降は未起動。
- 追加worker9は17:31:08.65UTCにexit0、9,165,923,392B/LFS `c21ad6105a780bc2f44eb7dd41f9b1a1efb4e8ec87618f60b733bc2652bd2ffe`/35range/同file rename/codebinding一致。全9receiptは未成立で、元mainが後で既finalを明示SHA再検査する。Main承認で17:31:56.87UTCに末尾8だけ追加workerへ交替し最大2fileを維持。開始freshfree582,729,768,960B/既model22,861,912,237B/残477,845,664,336B＋metadata=増分477,862,441,552B/差104,867,327,408B、source/runtime不変更。
- 残8の開始直前`2026-10-20T17:16:04.651542+00:00` free606,106,820,608B/既原本5,780,589B/必要増分500,718,573,200B/差105,388,247,408B。Main取得GO後17:16:16UTCに開始、最初のshard2 256MiBを17:16:29.57UTCにcommit。初区間約20.2MB/sはHTTP/SHA/fsync込みの参考値で、モデル性能/持続帯域保証ではない。取得中のsource/runtime設定は不変更。
- fresh `2026-10-20T17:07:04.368725+00:00` free606,108,205,056B/原本既保持0/残500,707,576,573B＋metadata見積16,777,216B=増分500,724,353,789B/差105,383,851,267B。小shard後`17:08:21.809963+00:00` free606,099,693,568B/既保持5,780,589B/残500,701,795,984B＋metadata見積=500,718,573,200B/差105,381,120,368B。T09等既buildをfreeから再減算せず、各shard前もfresh再確認する。全将来build容量保証や通常headroomではない。

### T16実装証拠（2026-10-21、別担当r2・独立review重要0）

- 承認7files `native/cache/{CMakeLists.txt,lease_queue.hpp,lease_queue.cpp}`、`tests/cache/{ledger_fixture.cpp,hip_lease_fixture.hip,declared-set.json,build_verify.py}`のみ。既owner-instanceの固定1472B sidecarでsource→DMA→kernel lease/世代/credits、取消/解放、late非公開と元lease回収、duplicate無二重free、quarantine容量保持、prefetchのdemand count/bytes/slot予約・2class交互進行を合成declared setで検証。host135assertionsとbinding/formatter7負例成功。T34 callerIdentityはmetadata借用でauthorityではない。
- 実primary PCI0000:07:00.0 gfx1201で既DeviceArena/PinnedRing/stream-event、4distinct stageの実Host属性/cap64KiBにbindし16op全byte/checksum一致、drain後owner解放。device capacity135168B、host buffers393216B（pinned subset262144B）、sidecar1472B別。試験PAGEABLE=1子processはreserve=trueでも実stageなし/query未実施status/type null、direct1copyは別成功、hostaggregate/pinned gauge unknown（0にしない）。r1のquery失敗unknown表現を修正済み。
- callerがowner/Identity/outstanding/quarantine寿命を保持、同owner coordinator/既外側lockの直列呼出しで、standalone thread-safe/実worker統合は未資格。fixtureの16buffers/8jobs/64KiB等は小pipelineの試験値であり、通常モデルcontext/output/全hotcache上限へ昇格させない。T11実working set、T17実I/O、T18–20供給/row/fullmodel、secondary/実driverfault/OScache全cap/server ID/perfは未実施。通常pinned強制/512cap/newbroker/新IDauthorityを追加しない。
- fixed manifest=`af858f4d192e61b9a99b04447f9d786838f87cf07c17b58d1bb2ef828cd7650e`、HIPexe=`3ec2ed6324426bed821e021f9551d0d43acbbfbe3cda7a2324c858f968ca1df3`、総verification=`d8f1305303c874341a15852c06deb3cc1ac20200c894af6a57363e0960fbf9a0`。独立review重要0、host135assertions独立再実行・通常16op/属性とfallback証拠/source4/recipe3/deps14/bundle16/tool8/前後bindingを確認、独立GPU再実行0。生成283,446,556Bはr1証拠保持を含む（256MiB初期見積超過を実測で記録）。担当Cfree590,613,409,792BはT05取得並行時点で、帯域や全将来容量保証ではない。

### T23実装記録（2026-10-21、実装r1・独立review重要0）

- pre r1/family・producer補足の独立重要0/Main承認後、`native/protocol/{generation.hpp,generation.cpp}`、`control/generation_frames.py`、`tests/protocol/{CMakeLists.txt,frame_fixture.cpp,build_verify.py}`の6filesを実装。baseのT/BT元ID・DONE count/finish・server int yieldは読取参考のみで、旧server/Huihui/engineを変更しない。
- begin/token_batch/finishの3frameでlaunch/tokenizer/request epoch・連番・元uint32 IDs・実generated_count/finishを保持。元ID列uint32LEのSHAはnative BCrypt対Python hashlibで事故整合を検査し、native生成来歴/owner真正性の証明とはしない（実producer bindingはT28/T24）。text再tokenize経路を持たず、re-tokenized/synthetic origin偽装を契約拒否。実0/count欠落、partial cancel/error/nonfinite、EOF/finish後を区別し、既通常出力/retry等を縮小しない。
- missing source REDを保存、隔離`build-deepseek-t23`でMSVC C++17 /MT /utf-8実compile/link、検証前manifest固定→62cases→事後同binding。native元ID/Unicode opaque requestIDとJSON escape、strict expected/observed bool/float拒否、schema/family/tokenizer/bundle/epoch/seq/count/rolling ID hash/欠落・重複・改変の負例を検証。実モデル生成/accepted DSpark/Recipe/server/SSE/usage/TTFT/TPOT結合は未実施でT28/T33/T35等へ残し、通常start gateを追加しない。
- r1独立実装review重要0。別担当が固定exeをrebuild/GPUなしで62cases再実行成功、compiled3/interpreted1/recipe3/input2/tool8/license1/DLL2の20boundfile SHA・compiled identity/前後bindingを照合。追加in-memory4probe(False ID0/True epoch1/float terminal seq/vocabfloat同値)も拒否。
- fixed manifest=`9e4453062be54a68beb8c78fd11095d5f5f85a4967ceac28a98b41c34aaa61f3`、exe=`f9c2371e886081a2a9b3a541168a557d74764af0039a7201e07895c15998eb63`、verification=`0d4f8a0b16e9e721a897c8ecd446680f8e46c24a226f2ec147749b105ab766db`。compiled3/interpreted1/recipe3/input2/tool8/license1/直接System32 DLL2をbind。T05取得source/原本と他固定taskのsource/bundleは不変更。

## 5. 段階4: 現sourceにあるもの / 足りないもの

| source | 確認した資産 | 追加が必要な契約 |
|---|---|---|
| Strata FileExpertSource | GGUF原本参照、Windows mapping / direct read、stage、note_async_readのDMA event | DeepSeek adapter、strict byte cap、lease / 世代、需要予約 |
| Strata claim_stage | pinned再利用時のevent待機 | 必要時に増設。512個は警告でhard capではない |
| Strata set_io_prefetch | worker / pread最適化 | この経路はLinux限定。Windowsでは別の既存I/O部品へ接続 |
| Strata DirectFile | NO_BUFFERING / OVERLAPPED / IOCP、aligned submit / completion | queueは呼出側予約なしでは非bounded。取消・drain / bytes上限 |
| Strata resident / pinned / memory | physical / commit、WDDM shared budget、register / event | 全model常駐を要求せず、小さい転送poolとcacheを会計 |
| Strata RemotePrefillSource / RemoteExperts | cache blob取得と別GPU expert計算 / compact結果。beginはk!=10拒否、Q8_1 / Q8_0経路 | cache-onlyを維持し、演算はtop6 / native MXFP4・activation精度へ適合。D2H drain不能dst再使用や既精度の無検証流用をしない |
| Maya flow | stage_ev / ring_fill / ring_free、RAM tier、cold / warm測定部品 | 対象経路を限定し、Strata request / error / ownershipへ適合 |
| Maya EgReader / EgRowCache | MXFP8 row読取、dedup、clock cache、token確定後先行read | queue cap、管理bytes、request世代、expert I/Oとの公平性 |

既存event待機があることを、新経路全consumerのleaseが完成している証拠としない。
既存guardを外すだけの対応や、全RAMをpinned化する設計にしない。

## 6. 容量とデータ量

### v1.3作成時のinventory snapshotと保存先（運用前再確認）

- v1.3作成時snapshot: RAM 102,897,238,016B = 95.83052063GiB。96GB decimalと96GiBを同一視しない。
- CはNVMe Samsung SSD 980 PRO 2TB。空き621,583,478,784B = 約621.58GB。
- 原本取得後の単純差分: 120,875,902,211B = 約120.88GB。これはbuild等の使用前の値。
- C:\Develop\AI\Model は空の通常directoryで、junctionではない。製品名から実効帯域を決めない。
- 前の空き約528.6GBは古いsnapshot。変化原因は推測しない。
- 原本 / index / build / log / temporary / 比較用領域の最大同時bytesを工程1で積算する。勝手な削除はしない。
- 公式原本や比較用の全量copyを追加保存すると余裕を超える可能性がある。必要範囲fixture / streaming比較を予算化する。

原本配置案:

    C:\Develop\AI\Model\DeepSeek-V4.1-Flash-1017-GGUF\
      f924b94f19c1fea02c06a65c8475b0a45e2b88b1\UD-Q4_K_XL\全9 shard

### shape由来の算定

| 項目 | 数値 / 条件 |
|---|---|
| backbone / routed | hidden5120、40層、384 experts / layer、top6、FFN2304 |
| native MXFP4 1expert | 3 × 5120 × 2304 × 17 / 32 = 18,800,640B = 17.9296875MiB |
| routed全体 | 40 × 384 × 18,800,640 = 288,777,830,400B = 268.9453125GiB |
| cache前decode routed論理量 A | 40 × 6 × 18,800,640 = 4,512,153,600B/token = 4.5121536GB/token |
| Engram row / lookup | 256code + 8scale = 264B、2層 × 3ngram × 8heads = 48lookup/token |
| Engram論理量 | 48 × 264 = 12,672B/token。全table payload 202,758,032,400B |
| Engram shardとの差 | shard 202,758,032,592Bとの192Bはpayload外。物理read増幅と別 |
| stage payload例 | 256MiBに14expert、512MiBに28expert。alignment / metadata / 一時領域を含まない |

non-Engram payloadとroutedの差分約8.54GiBを、定常dense VRAMの確定値にしない。
BF16 / F16→FP32展開、Q8_0保持、prefill用別コピー、startup scratchを選定経路ごとに記録する。
Mayaの共有4source ratio2/2/2/1、packed CKV288B + index80Bなら約920B/context tokenという参考算定がある。
128Kで約115MiB + SWA ring約2.58MiBの例は、Strata移植後の実allocation・数値保証ではない。

### RAM配分例: 全て仮値

| 相互に重複しない用途 | ある実行位相での試算 |
|---|---:|
| OS / 既存application等の使用分 | 16GiB |
| host非cache: 当該位相のmodel/state/tokenizer/request等 | 8GiB |
| expert pageable RAM cache | 60GiB |
| Engram cache: payload / 管理情報 / block丸め込み | 0.25GiB |
| pinned転送pool: expert / Engram staging等の合計 | 1GiB |
| index / queue / scheduler等 | 0.5GiB |
| 未割当・変動分 | 10.08052063GiB |
| 合計 | 95.83052063GiB |

16GiBや未割当分を新たな強制headroomにせず、60GiBを通常の固定cache量にしない。
startup / 定常decode / prefill / DSpark有効時を別ledgerにし、同じ8GiB枠を複数位相で同時加算しない。
最大同時allocationを位相ごとに積み、startup scratch解放後の再配分も実測する。
pinnedは上表のRAM内。登録済cacheを直接DMAする場合、その同じbytesを別RAM容量として再加算しない。
physical RAM、commit余裕、WDDM shared budgetを別条件で確認する。

### single / cache-onlyのprimary GPU感度例: 全て仮値

| 用途 | DSpark追加前の例 | DSparkを追加8GiBと仮定した例 |
|---|---:|---:|
| 使用可能local budgetという仮定 | 32GiB | 32GiB |
| dense実行形式・別コピー | 9GiB | 9GiB |
| KV / context state | 1GiB | 1GiB |
| scratch / runtime / library等 | 4GiB | 4GiB |
| 未割当・変動分 | 2GiB | 2GiB |
| cold実行slot | 0.5GiB | 0.5GiB |
| DSpark追加分 | 0GiB | 8GiB |
| hot expert cacheに残る額 | 15.5GiB | 7.5GiB |

使用可能32GiBもdense9GiB等も未測定。WDDM / 他consumer / context / backendで変わる。
先に必須allocationを実測して残量をhot / coldへ配分する。例の2GiBを起動条件にしない。
cold0.5～1GiBはpayloadだけなら約28～57expertであり、全layer unionの同時常駐は条件にしない。
DSparkを通常無効化せず、有効時のweight / state / scratchと必要slotを同じledgerへ追加する。

### cache-onlyのsecondary_device感度例: primary基準表とは別枠（今回deploymentの仮値）

- secondary_device側cache予算20GiBという仮例を置く。公称24GBを全量usableとせず、WDDM / display / 他consumerを先に観測する。
- 20GiBはpayloadだけなら最大1142expertの例。cache metadata / 整列 / 転送一時領域を別計上し、20GiBや余剰分を新しいheadroom / 起動条件にしない。
- primary_compute_deviceのhot cache、secondary_device cache、RAM cacheの重複を除いた有用bytesを記録する。primary_compute_deviceのlocal cache容量が20GiB増えたとは扱わない。
- secondary_device→host→primary_compute_deviceのpinned bounceは既存1GiB仮poolの内訳に含める。増額する試算ではRAM cache / 未割当等から差し引き、RAM総budgetを守る。
- fill / evict移動も転送と一時bytesを消費する。必須の全量warm fillを追加せず、必要なnative bytesをcacheする。
- Engram等へ適用する場合も同じ型・構造・source契約を使い、その有用性と転送を測定する。table全体を収める前提は置かない。

演算modeではこの20GiB cache例を転用しない。expert-assistはsecondaryのexpert slot / native kernel scratch / 入出力と転送pool、layer-splitは担当dense / experts / KV / compressor / mHC / Engram状態を追加し、両deviceの実残量からcacheを配分する。
startup / prefill / decode / DSpark / graphの位相別に、head / drafter配置、共有row複製、重複weight / stateと一時activationを会計する。必要allocationは実測前で、両GPUの公称容量を合算したusable量や新headroomを約束しない。

## 7. 供給・寿命・backpressure

single / cache-onlyの基本経路はGPU hot hit、RAM hit、SSD missのいずれもprimary expert executorへ渡す。演算modeでは同じ有限供給を選択ownerのsecondary実行slotにも接続する。
SSD missは原GGUFの必要範囲だけを読み、RAM / aligned staging / GPU slotへ接続する。
1expertの17.93MiBはgate / up / downの合計で、原GGUFの1連続spanとは限らない。
小index adapterに各tensorのspan / offset / shape / 型 / 整列を記録し、必要な3span等をread / gatherする。aligned roundup / overread bytesもphysical budgetへ計上する。

- cache keyにmodel revision、tensor / layer / expertまたはEngram row、layout identityを含める。
- host sourceはstaging copy完了まで保持。登録済RAMから直接H2Dする場合はDMA完了までevict / 書換え禁止。
- pinned stagingはH2D完了eventまで保持。GPU slotはfill完了後だけ公開し、最後のkernel完了まで再利用禁止。
- read前にdestination buffer / I/O creditsを予約し、H2D前にGPU slotを予約する。予約待ちで無制限増設しない。
- queueは件数とbytesを制限し、発行済I/O、staging、DMA、slot、管理情報を総会計に含める。
- 最小atomic working setを実kernel契約から確定し、それ以上の有限slotで進行できることを検証する。
- 必須予約を取り切れないprefetchは待機 / 撤回し、demand用credits / slotsを残す。予約循環によるdeadlockを試験する。
- cancelは未発行jobを取消し、発行済read / DMA / kernelは完了回収してdrainする。
- OS取消要求の返却だけでbufferを解放しない。古い世代のcompletionは新requestへ公開せず、元資源の回収は行う。
- drain失敗のpool / slotは再利用せず、既存runtime失敗処理へ接続して状態を報告する。

Engramはtoken確定後に必要rowが分かる。expertはrouter後に確定し、未来expertの先読みは予測である。
critical expert demandとEngram demandの双方へ進行保証を設け、少量rowを大きいexpert readで飢餓にしない。
長いreadをaligned chunkへ分け、発行済readが即取消できないことを含め、需要待ちの上界 / 実測を扱う。
prefetchは需要より下位。coalesce / dedupは同じartifactの必要bytesだけを共有し、出力・数値順序を変えない。
Engramのrow cache上限はpayloadだけでなくmap / key / block丸めを含む。大きなtable全走査は行わない。

### cache-only providerと共通secondary device binding・転送

- 既存RemotePrefillSourceは別GPUのexpertをcopy_blob(s)で取得し、missを既存ExpertSourceへ戻す近い資産である。
- copy_cached_blobsのcache GPU→host stream / syncを土台に、DeepSeek decodeも使えるstorage-only providerへ一般化する。
- cache-onlyへ第二GPU演算や不要dense / stateを混ぜない。expert-assistはRemoteExperts / Luce hybrid FFN、layer-splitはMaya group / state handoffを別のmodel execution部品として適合する。
- 現Huihuiのmask1ではR9700がlogical0となりRX 7900 XTXは隠れる。この既存profileとglobal maskを維持し、DeepSeekのsecondary選択profileだけ必要な両deviceを可視化する。
- 役割はprimary_compute_device / optional secondary_device、modeはsingle / cache-only / expert-assist / layer-splitとする。HIPのprimary＋0/1 secondary、実PCI / UUIDと選択roleのcapabilityで結び、商品名 / ordinal / 公称容量whitelistにしない。
- 既profile / state / receiptへmode、device identity、expert assignment / layer partitionとvisibilityを拡張し、起動時placementを固定する。実効transfer pathは動的観測。Huihui / global mask / 既存receiptは変更しない。
- secondary_deviceはcache-onlyでもallocation / copyを対象runtimeで確認する。busy GPUやdisplay / 他consumerを勝手に停止しない。
- 運用時にowner / busy状態を確認し、他consumerによるbudget変動とcache pressureを観測する。
- peer queryは転送方向ごと、enableはcurrent deviceを正しく選択して行い、実copy / 読返し / event依存 / 整合fixtureを確認する。
- 既存peer probeの試験不能時trust扱いをcache完全性証明へ転用しない。WinのGPU個別対応と、このpairのP2P成立は別である。
- HIPはpeer copy API内部でhost stagingを使う場合がある。API成功やpeer availabilityだけでphysical P2P / READY / 高速と認定しない。
- physical転送経路を確認できないsampleはunknownと記録し、P2P帯域の実証や予測へ混ぜない。
- P2P成立時はsecondary_device cacheからprimary_compute_device実行slotへcopyする。P2P不可時もsecondary_device→小host pinned→primary_compute_deviceの明示bounceで利用できる。
- bounceはD2HとH2Dの2転送。source、共有pinned staging、primary_compute_device slotの各leaseとcommit / WDDM使用を会計する。
- source handle / cache key / graph / event / slotにowner device / contextを結び、fill完了から最終copy / kernel完了まで保持する。
- cross-device event依存は実検証し、未対応ならhost bridgeで安全に順序化する。cross-device event間のelapsed比較は禁止する。
- copy時間は同device eventまたはhost monotonic end-to-endで測り、GPUごとの時計を直接差し引かない。

### cache-only故障・late completion・fallback

- allocation / copy / read失敗やeviction時は、有効な元copyを保持するか原GGUFを再readし、既存RAM / SSD経路へ安全にfallbackする。
- 既存copy_cached_blobsのD2H失敗→drain失敗→hit0→同じdst再充填を、そのまま新providerへ移植しない。
- 旧D2H DMAが書き込む可能性のあるpinned dstは、drain確認まで隔離し、RAM / SSD fallbackで上書き・free・再利用しない。
- drain成功後は同bufferを再利用できる。未完了時に独立した安全buffer / sourceを選ぶ場合も、旧bufferを保持して完了回収する。
- cancel時はsecondary_device source、D2H、host staging、H2D、primary_compute_device slotを跨deviceでdrainし、古い世代のcompletionを公開しない。
- cache単体のcopy failureとprimary_compute_device context損傷を区別する。後者は継続を保証せず、既存error / quarantineと再確認・再選択へ戻す。
- 補助cache不在 / pressure / 一時unavailable / P2P不可でも、computeが健全で宣言済RAM / SSD経路と必要lease / drainが成立すればcacheをbypassして継続する。P2P不可時は明示bounceも選べる。
- P2P→bounce→RAM / SSDの安全な実効path変更だけでmodel / bundle / runtime epoch変更とは扱わず、client / history拒否や再起動へ波及させない。固定compute owner / tokenizer / context等の不一致は従来通り別に照合する。
- actual cache path / device identity / 理由をstatus / metrics / receiptへ観測記録する。通常startに商品名別資格receiptや全suiteを新必須にせず、必要capability / identity / 実資源 / 転送安全を確認する。

### expert-assist / layer-splitの演算・state契約

| mode | 実装・転送・所有の契約 |
|---|---|
| single | primaryだけで演算。secondary未使用でも基本経路が成立する |
| cache-only | secondaryはweight等を保存し、primaryへcopyする。既cache / RAM / SSD fallbackを維持 |
| expert-assist | router / top6 / 学習済biasは変更せずrouteの実行先だけを分配。primaryの規定cast / QDQ / combine契約へgatherする |
| layer-split | まず連続2区間の一cutとし、各層のdense / expert / stateを担当deviceが実行。全担当weight常駐を要件にしない |

- expert jobはrequest epoch / layer / token / expert / route、layout / dtypeとsource ownerをbindし、論理route結果を一度だけ採用 / commit / combineする。物理kernel実行回数を一回に限定する保証ではない。有限bandでprimary→secondaryの入力と返却結果を送る。
- 入力activation、route係数を適用する位置、down入力QDQ等はT11契約を維持する。返却順が変わってもtoken / routeへcanonical gatherし、欠落 / 二重combineを検出する。compact partial結果や別還元順は独立数値検証なしで同値としない。
- layer-splitはMaya候補のhead最終側 / drafter先頭側を起点に配置を固定する。層境界ではh / pre / topk / candを実1017契約へ対応付け、mHC全residualと必要metadataを含める。
- shared KV / indexのwriter→consumer edgeと世代・可視位置を明記し、Mayaの新compressed KV / index row受信・serial pinned複製を参照する。全KV / tableの毎境界copyでもhiddenだけのhandoffでもない。
- Engram履歴 / hash / row、compressor / SWA / mHC、共有writerを担当ownerへ結び、append / reuse / reset / cancel後も最新の必要stateだけを渡す。共有consumerの重複writerを作らない。
- 基本layer-splitのT45ではhead配置・trunk stateとtapの最小ABI / 合成境界を確認する。実draft3層 / tap転送 / 採否後の確定state、graphのmode / partition / device / shape / address / ownerと跨device leaseは、T37→T38を祖先に持つT47で結合検証する。
- cache bypassと演算故障を混同しない。expert再実行は未公開結果、有効入力、必要owner / drainが成立する場合だけ安全なprimary再実行を検討し、modeを黙って変えず実効placementを記録する。再実行時は旧試行の結果 / late completionを採用せず、既存route key・世代 / 採用状態で二重commit / combineを防ぐ。新しいretry基盤は追加しない。
- layer state損傷やdrain不能ではslot / dstを隔離し既存error / cleanup・再確認 / 再選択へ戻す。途中の自動state移動や必ず継続を約束しない。

### buffered / mmap fallbackと会計

- expert大量payloadはunbuffered aligned readを第一候補にし、別pack複製とOS cacheへの余分な二重保持を避ける。
- 既存の安全なbuffered / mmap fallbackを維持し、選択・実効経路、fallback理由、allocationを明示する。
- 未計測だけでfallbackを拒否しない。新たなfallback無効化、追加headroom / 起動条件は導入しない。
- 実I/O / allocation失敗や既存保護不一致は通常error処理へ戻し、再確認・再選択・中止を可能にする。
- 独自queue / staging / pinnedはstrict budgetで管理する。OS global file cacheを同じhard capで完全制御できるとは言わない。
- buffered readのbufferがboundedでもOS cache全体がboundedになったとは扱わない。
- mapping全長をRAM使用とせず、同じshared file pageをworking setとsystem cacheで二重加算しない。
- private commit、mapped resident、pinned、global available / commitを分け、OS reclaimable cacheも区別する。

## 8. Prefillと性能の判定

B tokenのlayer unionは U_l <= min(384, 6B)、論理供給量は sum(U_l) × expertBytes。
B=4096で全384expertを各層一度だけ読む理想例は288.78GB/pass、約70.50MB/input token。
これは小waveでの再読、追加cache、転送増幅を含まない。実際のunion / 再読 / bytesを計測する。
有限slotでexpert単位 / 小waveへscheduleし、attention因果順序、還元順、state / consumer寿命を検証する。
input / context / outputを試験都合で削って収めない。context変更時は必要allocationを再算定する。

次のhGと単GPU表はsingle / cache-onlyでprimaryが全expertを演算する基準。secondary cache hitをhGへ加算せず、cache-only二GPUでは後述の転送別式を使う。演算modeへこのweight転送式を直接適用しない。
prefetch無効の基準では、hUはprimary_compute_deviceまたはRAM等のunionでSSDを回避したbyte比率、hGはprimary_compute_device localでH2Dを回避したbyte比率。
同じexpertが複数tierにあってもunionで一度だけ数える。capacity比をhit率へ置き換えない。

    Bssd = A × (1 - hU) × readAmplification + prefetchWaste + EngramPhysical
    Bh2d = A × (1 - hG) + 追加転送
    T >= max(Bssd / SSD実効帯域, Bh2d / H2D実効帯域, GPU計算時間)

| 仮の実効帯域 | zero-hit時の転送だけの楽観速度上限 | 5token/sの必要条件 |
|---|---:|---:|
| SSD 2GB/s | 0.443token/s | union hit 91.135%以上 |
| SSD 5GB/s | 1.108token/s | union hit 77.838%以上 |
| H2D 12GB/s | 2.659token/s | GPU hit 46.81%以上 |
| H2D 24GB/s | 5.319token/s | GPU hit 0%以上 |

表はAのみ、readAmplification=1、追加転送等なしの試算。製品仕様・当機の測定値・速度保証ではない。
Tの式は完全pipelineを仮定した楽観的な時間下限。40層の依存、CPU copy、SSD / PCIe競合、同期を実測する。
Engram論理量12,672B/tokenとphysical readは異なる。alignment / cache / coalesceで増幅・回避が変わる。
prefetch有効時は予測失敗も含むSSD / H2D総bytes、useful / waste、warmupを別記録する。
physical I/O countersを取得できない場合はunknownとし、logical requested bytesをphysical測定と呼ばない。

### cache-only二GPUの転送別式

mode確定時の有用bytesを排他的に分ける。rはprimary_compute_device local、xpはsecondary_device P2P、xbはsecondary_device host bounce、mはhost供給、sはSSD供給の比率。
mは同じbytesを既にGPUで供給した場合と重複せず、hUは全tierによる実SSD回避を表す。secondary_device hitはprimary_compute_device local hitではない。

    r + xp + xb + m + s = 1
    hU = r + xp + xb + m
    Bpeer = A × xp
    BD2H = A × xb
    BH2D_primary = A × (m + s + xb)
    BSSD = A × s × readAmplification + prefetchWaste + EngramPhysical

これはuseful routed supplyの式。cache fill / evict移動、Engram、他の追加転送をそれぞれ別加算する。
同じexpertの両GPU / RAM重複、途中で失敗して再転送したbytesも別記録し、hitで転送量を隠さない。
PCIe root / DMI / SSDを共有する転送は競合するため、各GPU / SSDの帯域を単純加算しない。CPU copyとoverlapも実測する。
unknownのphysical modeをP2Pとして分類せず、整合成功と転送経路・速度の実証を区別する。

expert-assistではownerへ供給するweight bytesに加え、dispatch activation / route metadata・返却結果 / gather待ちを別計上する。secondaryで消費したweightをprimaryへのpeer weight転送と同じ式で扱わない。
layer-splitでは各ownerへのweight供給と、cutのactivation、必要な追加KV / index rows、draft tap等を計上する。単一sequence decodeの層は基本直列で、二GPU並列による単純2倍を約束しない。prefillの最遅stage・帯域競合も実測する。

## 9. 段階5: 数値検証

この段階の対象は固定UD-Q4_K_XLのtrunk40層を使うtext生成。DSpark draft3層とは分ける。
段階2～4の対象契約を満たし、realweight小fixture→operator / state / layer→必要な全40層teacher forcingへ進む。完了依存はT04 / T25 / T26とその祖先で判定する。
T03の少量実weightで全量取得前に小fixtureを検証できる。全40層数値検査のT26では全9 shard SHAとtrunk必須assets、binary / tokenizer / profile / layout identityを前提とする。

### N / Q / G / Aと参照独立性

| 系統 | 役割と契約 |
|---|---|
| N: 公式演算参照 | 固定公式revisionの演算、activation dtype / QDQ、丸め、selectionを基準にする |
| Q: 指定GGUF参照 | 同じUD-Q4_K_XLを独立scalar / 可読参照で復号し、明記した演算精度契約で評価する |
| G: 移植Windows / HIP | primaryと選択modeのsecondaryで演算。Qと同じ精度契約で実装差を判定し、cache-only配置差と演算分配差を分ける |
| A: 近似profile | 近似replay等を導入する場合だけ別fingerprint / 別品質判定とする |

N→Qの重み・精度差、Q→Gの実装差、G内の配置差を分ける。MayaのQ8 activation等を公式FP8と同一視しない。
dtype / cast / activation QDQ / accumulation / 還元順 / 選択規則を対照表へ明記し、契約が異なる比較を同一実装の許容誤差に隠さない。
同じdecoder / kernel / 期待値生成のbugを共有し得る二実装の一致だけで公式同値としない。
Nは小型CPU / 可読PyTorch参照、固定独立trace等も選べる。公式CUDA / TileLangの当機実行や公式原本全量の追加取得を必須にしない。

Nの仕様照合は固定HF config / 公式参照とDeepInferの該当non-approx経路を優先する。ただしasset / dtype / cast / config / batch条件未照合の公式GPU出力は無条件goldenにしない。
Qは指定GGUFの独立復号、GはStrata HIPのまま。DeepInferとHF1bae…の全weight対応は未確認で、公式GPU環境の導入や原本全量追加取得を数値検証・通常統合の新必須条件にしない。
Q&Aがapproximate SWA KVとするbounded replayはA / 将来別opt-in候補へ隔離し今回採用しない。keep_tokens140やprefill truncateを通常defaultへ導入しない。
DeepInferのdeterministic samplingはNVIDIA、batch-invariant、MTP varlen off、固定seq_seed等の条件付き。比較fixtureのmodeと通常設定を分ける。
### 既存testの選択集合とcoverageの限界

| 参照test / harness | 実行条件・流用範囲 | 追加 / 限界 |
|---|---|---|
| Strata gguf_split_test / expert_layout_test | syntheticのCPU側shard / layout検査、実model不要 | 公開DeepSeek全tensor inventoryの証明とは別 |
| Strata file_expert_source_test | test_native_variable_layout / test_unbuffered_reads等。--rotation-gpuは追加GPU検査 | I/OのskipをPASSにしない。DeepSeek型・跨deviceは追加 |
| Strata hip/intrinsics.cpp / expert_cache_staging.cpp / dma_batch_parity.cu | AMD GPU / GPU runtimeが必要、実model不要。wave32 / bytes / event順序 | 新しいsecondary_device経路・DeepSeek演算の証明ではない |
| mmnga deepseek41_artifact_test / serve/test_deepseek41.py | CPU fixtureのmetadata / Engram hash、mock中心のtoken / DSML検査 | real MXFP8 / 全model / 正式encoding goldenを追加 |
| mmnga cuda_test.cu / mxfp4_alu_test.cu / cache_test.cpp | 現状CUDA / Linux。HC / router / attention / decode点 / cache leaseを参照 | HIP / Windows移植、realweight / top6 / 公式数値契約が必要 |
| Maya tests/ds4_gguf_test.cu / tools/ds4/ref_gguf.py | GPU testはmodel不要、既定512×256。ref_ggufは同GGUFのQ参照候補 | 実5120×2304 / top6 / 精度契約 / 独立性を確認 |
| Luce test_ds4_engram.cpp / test_deepseek4_unit.cpp / HC test群 | CPU golden / hash / 履歴、candidate / causal / ring等を参照 | UNIX guardをWindowsへ移植。小形状、model / GPU不在skipを実対象PASSにしない |

mmnga native_testは1層 / H512 / top2のsyntheticで、実行用fixtureはzero-scale化されている。
Engine::check_batchはlookahead / expert_cache / streamedを退避し、同engineのserial / batchを比較する。独立oracle・配置同値とは別。
mxfp4_alu_testは4096 scale / nibble点、H5120 / F2304 / top3 / NT1～8の元実装対ALU bit比較。realweight / top6等を補う。
cpu_kquant / cpu_poolはCPU演算testでも現CMakeのDeepSeek CUDA target依存があり、そのままWindows offline可能とは扱わない。
既存CUDA ggml oracle用parity targetもCUDA build専用。HIPへCUDA libraryを混ぜず、必要な参照経路を分離する。
共有ファイルのCUDA / HIP / SYCL build要件を維持し、skip / 未実施 / unsupportedとPASSを別記する。

DeepInfer test_batch_invariantはbatched結果をgolden_token_idsへ入れてsingle再実行しlogprobs等を比較する。自由生成同seed一致試験ではない。
test_samplerのPIT / KSはall_pvがassert対象でnext1_pvは表示、test_klは同DeepInfer decode対re-prefillで独立oracleではなく、platform固有PPL / KL閾値をHIPへコピーしない。
test_state_cache_opsはweights不要でも実config / GPUを要する。多GPU前提やwholemodule GPU importsを当機の新必須環境にせず、検査仕様を独立小fixture / 固定traceへ抽出する。
### 数値契約と許容差をGの合格判定前に固定する

- fixture hash、shape、token / position、weight / activation / accumulation dtype、cast / QDQ / 還元順、参照版 / toolchainを記録する。
- integer / token ID / hash / mask / 範囲 / transport bytesは完全一致。finite条件と特殊値の期待動作はfixtureごとに定義する。
- floatはoperator・適用位置ごとのatol + rtol、NRMSE、必要なULP / max誤差、層ごとのdriftを独立baselineと精度仕様から固定する。
- 小fixtureの参照baselineを先に確定し、許容差表と対象holdoutをhashで固定する。Gの合格結果を見て閾値を広げない。
- baseline未確定は未判定。進行を止めるのは当該数値ゲートに必要な契約で、DSpark / 画像 / 1M等の未着手をtrunk数値coreや通常統合へ連鎖させない。
- N→Q全モデル品質の閾値も評価前にcorpus / metric / critical invariantと固定する。未確保の品質結果を「差なし」としない。

Maya既存testのGEMV 2e-5、token / window 1e-3、prefill 5e-5（light 1e-4）等は出典付き参考値。
そのexpectはmaxabs差 / maxabs参照値で、一般の要素別rtolではない。異なるshape / dtypeへ無根拠にコピーしない。
Maya ref.pyのF32 activationは公式BF16との差を明記し、そのまま完全独立のN oracleにしない。

### 比較wrapperの誤PASS防止

- Maya compare.pyはmetric表示・終了0と比較長min(ref, engine)を数値PASSの根拠にしない。shape / length / finite / 閾値wrapperを追加する。
- expected manifestで全長・vocab shape・token ID・position、各logitが予測するnext token、BOS shift等を一致させる。
- truncated / empty / wrong vocab / token-positionずれ / NaNを負例とし、切詰めや欠落行を黙って救済しない。
- 参照normがゼロ / 極小のときは絶対誤差fallback等を事前定義する。入力だけでなくKL / NRMSE等derived metricのNaNもPASS不可。
- logits / 中間drift / NLL / KL / top-k overlap / margin、text / reasoning / special等のchannelを対象に合わせて記録する。
- greedy token一致だけで品質としない。near tieは事前gap / tie規則、選択集合・順序・不可視maskを別判定する。
- 許可集合は丸め済score / 有効mask / candidate集合 / sourceの同点規則から定義し、既存near-tie skipを無条件PASSにしない。margin十分な不一致はFAIL。

### 小fixture / layerで補う検査

- real MXFP4 / MXFP8 blockとscale・特殊コード・layoutを、独立scalar decodeと照合する。1/2/4/8token、実H5120 / F2304 / top6を含む。
- route係数0.3 / 0.7、極小score、clamp境界、signed zero / subnormal、非有限値の規定動作を確認する。
- hidden×route weight→cast→down入力QDQ→downの位置と、combine二重適用防止、router分母をtraceする。
- HC4 / Sinkhorn20、HC epsilon 1e-6とRMS norm epsilon 1e-20を分け、実H5120 / staggered状態を確認する。
- Engramはtoken map / hash / 履歴、実8heads、row hit / miss / evict / dedup / short read / error / cancel-reset / async leaseを追加する。
- SWA128の127 / 128 / 129、ratio2 odd / even / 未完group / RoPE、prefill→decode接続、stateのsnapshot / restoreを検査する。
- shared KV writer [2,8,14,20]、index writer [2,8,14,20,24,28,32,36]を照合し、共有先の不正上書きを検出する。
- 係数位置・nibble・mask・positionを故意にずらした負例で、新しい検査が実際に失敗することを確認する。

CSA2はcandidate source layer20、block8、最大2048blocks、top512、partial block / 最新block強制保持を検査する。
visible compressed rows 16383 / 16384 / 16385等をsyntheticで先に跨ぐ。zero-based position pなら可視数はfloor((p+1)/ratio)。
source layer20はratio1なのでこの境界は対応する入力長付近。ratio2では換算が変わり、単なる16384入力を境界検査の代用にしない。
実入力による長文integrationは段階7のT36へ分け、最大context到達をT26 / 通常統合 / DSpark単独 / graph単独の依存にしない。

### 数値検証のゲート（T04 / T25 / T26）

| ゲート | 前提と合格条件 |
|---|---|
| S5-0: 参照契約 | 対象operatorのN golden、Q精度契約、fixture / 許容差 / expected manifestの固定 |
| S5-1: 小fixture | exact項目・operator float契約・負例が合格。全モデル取得前に実施可能 |
| S5-2: layer / state | real形状・selection・共有owner・state接続・因果順序と層内driftが合格 |
| S5-3: 短teacher forcing | 対象trunk必須artifact SHA / identity / tokenizer、段階2～4の必要契約を満たし、固定token列の全40層Q→Gが合格。実draft結合はT47へ分離 |

N→Q全モデル品質のT42は補助評価で、未確保をT26 / M-NORMAL / M-ALLの待ち条件にしない。Q→G同値や通常機能成功を公式品質同等と言い換えない。
Nのfull goldenはbounded referenceや固定独立trace等の実行可能な方法を選び、原本全量追加copyを隠れた前提にしない。
必要な数値ゲートの合格を、生成文の存在だけで代用しない。

### 配置同値とcore / 通常統合の境界

cache-onlyではprimary local / secondary P2P / host bounce / RAM / SSDの供給bytesをbit比較してから同一primary演算を比較する。両演算modeはT44 / T45で両GPUの実shape・native型kernelを検証し、full40 TF / state / selectionを単GPUQ→G契約と照合する。
transport bit同値とQ→Gのfloat許容差を混同しない。演算順を変えない配置試験ではdeterminismも確認する。
P2P非対応でもhost bounceでT22のsecondary_device cache integrationを検証できる。P2P skipをPASSにせず、T26の数値coreはsecondary_device資格を完了依存にしない。
段階4のlease / owner device / late completion / drain不能dst隔離は、そのまま全配置検証へ適用する。
operator / state / layer / teacher-forcing用の非HTTP native runnerは、固定binary / assets / tokenizer / 入力token IDs / position / actual flags、native資源寿命と適用receiptを使う。T23生成protocolやT24公式bootstrap・port / cohort / trackingの完成を前提にしない。
HTTP serverを使う試験はT23 / T24と既存owner / client / cohort / port保護を適用し、無所有起動や既稼働processの便宜停止を許さない。
coreから通常CLI / 公式provider / codec / clientへ直接統合する。生成と終了・正常停止の受入は通常機能testで確認し、既存clientやGPU利用者を勝手に停止しない。
試験用greedy / 短出力 / DSpark・graph off等は試験内に閉じ、通常の保存profile / 既定設定へ反映しない。

artifact不一致、必要契約未定義、許容外drift、予期しない非有限、margin十分なselection不一致、transport不一致、寿命 / 停止違反では該当ゲートを止め修正する。
1M全文 / 長文品質 / DSpark / graph / 画像 / 通常clientの実証scopeは別に記録し、数値coreだけで合格対象を拡張しない。

## 10. 段階6: 通常CLI・client統合とbundle切替

数値coreから通常CLI / 公式provider / codec / clientへ接続する工程である。以下は未実装・未実施の計画で、現在すべてのclientがDeepSeekへ対応するという意味ではない。
通常のstrata.cmd / 共通CLIを維持し、公式管理へ起動・停止を委譲する。公式retry 3回 / READY待機900秒を短縮しない。

### 現sourceの固定箇所とmodel別契約

| source / 関数 | 現状と変更方針 |
|---|---|
| Strata-data/model_catalog.py: validate_layout / require_ready | 現V2 pack / PLE / 共有MTP、固定engineと公開262144をfamilyごとに分ける。内部4profile存在と公開範囲を区別し、現必要file検査を保持。旧IQ4_XS / pack receipt必須へ戻さない |
| strata_cli.py: _validate_assets / _ready / start_selected / show_status | binary / tokenizer / profile / visibilityをprovider経由にする。target事前検証、同設定reuse、stop拒否時はnew startなし、新attemptだけcleanupという現契約を維持 |
| manage_runtime.py: validate_profile / _start / stop_owned | family別profile / device-role / bundleをbind。PID / create-time / exe / command / cohort / listener照合とunknown時の既存保護を維持 |
| official_runtime.py: require_registration / native / start / stop | 現V2のplain profile mirrorを維持し、撤去済receipt / registry / profile content-hash照合を復活させない。現存MCP / setup固定source hash、PID / cohort / tracking、busy / queue / unloadを版付きadapterへ接続 |
| server_bootstrap.py / startup_progress.py | 固定root / import / argv / config SHA / attempt / PID照合をbundle descriptorに対応。progressは診断でありREADYのauthorityにしない |
| Strata/tools/strata_mcp.py | root / config探索 / state_dir / Python / launcherの既存能力と制約を明示。不足する少数hookで注入し、公式lifecycle実装を独自コピーしない |
| Strata/serve/frontend.py / server.py | 現Qwen parser / capability / EOS / default familyの接点をfamily factoryへ。DeepSeek公式DSML / encoding処理をserver adapterに一元化 |

新modelのpublic context / capabilitiesはモデル仕様、実装範囲、実際のprobe結果と対応付けて登録する。
公式構造上の最大能力と当実装の実装・検証範囲は別表示する。試験の短出力 / 小context / off flagsを通常profileへ保存しない。
既存選択肢を未検証だけで縮めず、未取得・準備不足は理由と再確認 / 選択へ戻る導線を示す。
DeepSeek用tokenizer / encoding / draft artifactを束縛し、Huihui用PLE / MTPを誤流用しない。

### 全入口・family codec・会話の世代

| 入口と現source | 段階6で接続する内容 |
|---|---|
| strata.cmd / strata_cli.py / model_catalog.py | model選択 / start / stop / status / same設定reuse。alias strataは後方互換とし、canonical model id / bundle id / runtime epochは別項目 |
| client_selection.py: select_for_client / require_switch_clients_stopped | 現在このswitch経路は管理DSH web_instancesが1件以上なら終了を要求する。この既存条件を正確に引継ぎ、全direct CLIや全client在席への新たな一律禁止へ広げない |
| Strata WebUI app.js | health約2秒pollと共通strata.chat履歴へfamily / bundle / epochを接続。遅延streamの表示・history commitを防ぎ、旧履歴を保持 |
| Strata chat.py | alias strataを維持しauthority / epochを照合。異常EOF / error / cancelの未完了応答を完成履歴としてcommitしない |
| Pi policy.mjs: modelConfig / provider adapter・guard | high→xhigh等の固定mappingをfamily codecへ分け、Huihuiの現mappingを維持。送信前だけでなく応答commit / tool権限・実行直前も照合 |
| DSH / Harness runtime_binding.py / runtime_probe.py / web_instances | 固定reasoning mapping、official_mcp / Strata tracking / mask1 / text-only / toolcaps検査をfamily別にする。旧Huihui検査は緩めない |

DSH自身のSIGINT停止とmodel停止は別操作である。select_for_clientにある既存条件が全CLIへ適用済みとは記載しない。
server adapterが正規化したOpenAI応答を各clientへ渡し、clientにDSML等のraw tag処理を分散しない。
family codecは公式supported reasoning / tool / capabilityに対応付け、Pi / DSHのretry / compact等を試験都合で狭めない。
標準OpenAI互換を維持し、integrated clientのbindingは自動化する。external clientへ新たな必須custom手順を課さない。
旧履歴を消去せず、適切なmodelの再選択 / 新会話へ戻れる。partial draftは失敗状態として保持し、別epochの完成応答へ混ぜない。
SSE途中のDSML / tool断片、EOF / cancelを実行可能toolcallにしない。tool権限確認とside effect直前にepoch / authorityを再検査する。
旧streamや旧toolを新bundleへ自動replayせず、既存のtool権限policyを通す。

deepseek-recipeはChat / Responses / Messages→Conversation→token IDs→DSML / reasoning / tool streamの公式CPU codec候補で、with_model_aliasによるstrata互換を検討する。
Rust / Python版とWindows build資料はあるが当機buildは未実施。HTTP / 推論 / tool実行は提供せず、mock server例やconstraint renderingを実provider / constrained decodingの証明にしない。
token-IDに基づく特殊token判別には、engine→server adapterで元生成token IDsと固定tokenizer identityを保持・受渡す最小hook / metadata契約が必要で、現serve protocolの対応は未確認。
UTF-8文字列の再tokenizeでtoken来歴を復元できるとはしない。通常文字列のDSML tagをtoolと誤認しないfixtureを参照し、tool権限 / owner / epoch guardは既存control / clientに維持する。
Recipe版 / tokenizer / encodingと実設定伝搬を照合する。resolve_max_tokens既定8192 / 65536 / 131072等やreasoning mappingで既存出力枠を黙って狭めず、GPU / HIP・画像対応済みとも扱わない。
### 通常機能の生成・終了・安全停止の受入

T23 / T24のcore契約を通常経路へ接続したT30 / T33で、実providerの生成・終了・停止を確認する。
fixtureごとのexpected manifestにtoken列 / channel / raw finish reason / 正規化したcauseを固定し、text / reasoning / toolとEOS / length / cancel / errorを判別する。

- 短い試験枠で自然EOSしなかっただけではFAILにしない。EOS停止は対応fixture、cancelは取消目的の合否で確認する。
- 正常停止、全cohort終了、port解放、次request / 次操作の健全性を確認し、timeout / errorを正常length終了にしない。
- source / binary / assets / tokenizer / profile / fixture hash、device / backend / toolchain、actual flagsと未実施範囲をreceiptへ結ぶ。
- owner / client保護と既存tool権限を維持し、未知processの停止や不完全tool断片の実行をしない。

### bundle manifest・profile snapshot・runtime identity

- manifestへStrata base / patch / project-owned source、採用したmmnga / Maya / LuceBox / DeepInfer / Recipe component・固定revision・license / notice、公式encoding版を固定参照と対応付ける。
- toolchain / backend / Python runtime、engine / server hash、schema、asset revision / variant / shard identity、tokenizer / encoding / adapterを束縛する。DeepInfer Apache-2.0、Recipe MITとTokenizer別noticeは採用時に保持する。
- profileのeffective config、public context / capabilitiesもversion付きの固定snapshotにし、同じversionの内容を上書きしない。
- DeepSeekの既owner管理へattempt、PID / create-time / exe / cohort、起動config / visibility、実PCI / UUID、mode / placement / epochとhandshakeを結ぶ。試験manifest / receiptは同版・scopeの証拠であり通常startの追加authorityにしない。実効transfer pathは動的観測として記録する。
- Huihuiの現mask / logical device / global maskを維持。DeepSeekのsecondary選択profileだけ必要deviceを公開し、primary / secondary roleとexecution_mode / placementを実identityへ結んでordinal変更による役割逆転を防ぐ。
- selected candidate / 次回bundleと実稼働processのlaunch bundleを分ける。起動時manifest / profile snapshotを保持し、selector更新で稼働中のengine / import先を差し替えない。
- liveの起動時effective profile内容、config SHA、bundle / tokenizer / assets / device bindingのsnapshotはowner照合・安全停止のため保持する。last-readyは状態説明用identity情報として管理する。

取得 / 開発更新時の重いsource・asset hash / 資格suiteと、通常start / requestの既存identity / owner / READY・固定snapshot照合を分ける。通常start毎の500GB / 全source再hash、request毎の全manifest scanや全suiteを追加しない。現V2 plain経路の撤去済asset / registration検査を戻さず、現存MCP / setup source pinとprocess所有確認は維持する。

### model切替transaction・phase・所有権

1. targetのasset / layout / profile / binary / tokenizer / bundleの静的検証を旧server停止前に終える。
2. CLI mutation用operation_lockとmanager state_lockの二層責務・現行取得順を保持し、contract試験で固定する。manager directをCLI lockへ機械的再入させない。 lock内で既存confirmed_identity契約に従い、確認済み旧identity / epochと事前にfreezeしたtarget bundle / profile snapshotを再照合する。確認後・lock前にいずれかが変化した場合は停止せず、再確認 / 再選択へ戻る。現ownerが正当でも、確認対象と別なら停止しない。
3. 単一owner authorityの下でbusy / queued / ownerを確認し、呼出元に対応する現client guardを適用する。同一effective model / context / profile / bundle / device-role / execution_mode / assignment・partitionなら実READY照合後にreuseする。
4. 切替は旧serverの安全unload / 停止後に保存cohortの終了とport解放を確認する。停止拒否・所有権不明・残存processならnew startしない。
5. 新attempt intent / phase / target manifestをspawn前に保存し、Popen / child取得時にPID / create-time等の観測を保存する。create失敗やREADY前cancel / crashでもattemptを失わない。
6. 公式retry / READY処理後、health / models / server・engine handshake、listener / cohort、実bundle / device / attemptを照合してからlive-activeをatomic commitする。
7. requested / last-ready / live-activeを分け、STARTING / STOPPING / FAILED等を実態通り表示する。新server失敗で旧が停止済みなら旧READYを表示せず、無条件の旧server再起動もしない。
8. 失敗時は確認できた新attemptのcohortだけcleanupする。cleanup未完・owner不明・残存identityはFAILED / cleanup_pending等として記録し、停止済みへ丸めない。
9. 通常model選択、明示switch、再確認 / 中止へ戻れる。半書stateはatomic replace / schemaとlive照合で扱い、metadata adopt / resetで通さない。

現show_statusはactive falseで停止済みへ戻るなど詳細が不足する。loading / cleanup失敗 / cohort残存 / owner不明をREADYや停止済みに丸めない表示へ拡張する。
不明processの強制kill、保護不一致からの停止許可推定、未知のmetadata採用は行わず、既存error / quarantine方針へ戻す。

mode / placement変更は既transactionでtargetをfreezeし明示switchする。起動時modeはhandshake / status / receipt / graph keyへ反映し、要求中の無停止migrationや自動最速選択は実装要件にしない。P2P / bounce等の安全なcopy経路変更だけではmode / epochを変えない。
同model / tokenizerならmode変更だけで履歴破棄・新会話を強制せず、既clientの再接続と必要prefix再prefillで会話を継続できる。旧inflight応答 / toolのepoch保護は維持する。既receiptのmode / placement / actual path拡張で扱い、新validation frameworkや第二authorityを追加しない。

### candidate資格確認・activation

candidateは固定shaを明示して用意し、自動upstream追従は行わない。
資格確認はcandidate専用のimmutable profile / config snapshot・公式登録namespace / rootと、隔離したmutable official-state / attempt / recordsで行う。
稼働中 / 管理中attemptのprofile / 登録config、および既存tracking / owner stateやselector / live参照先をactivation前に上書きしない。
activationでもcurrent liveが所有・停止管理に使う起動時snapshotを改変しない。mutableな公式stateそのものをimmutableとは扱わない。

候補source → 版付きsmall patch → contract / backend build → 固定試験bundle生成 → 同bundleで必要な数値・transport・lifecycle・client・共通変更でのHuihui既存動作確認 → 証拠receiptの同bundleへのbind → 公開activation資格確定の順に進む。
触れたCUDA / HIP / SYCLの必須buildを維持し、toolchain不足は未実施として示す。これらの重い工程を通常startへ追加しない。
候補のbase / server / engine / assets / Python / profile不一致では当該start / activationを中断し、既存live processを勝手に停止・adoptしない。
既存liveのowner / guard不一致に対するerror / quarantineは現行policyに従う。
承認済みbundleは上記transactionで明示activateする。
資格・証拠の適用は当該mode / flagsのscope単位とし、T46 / T47全体やM-ALL未完だけで独立実装・実証済みscopeのactivation / 利用を一括禁止しない。片modeの証拠を他modeのPASSにはしない。最終T43の両方式納品は別に維持する。
DeepSeek candidate / manifest設計を現Huihui V2のplain登録へ追加authorityとして被せず、削除済みreceipt / registry / content-hash検査を復活させない。現source pinと所有 / 停止保護は従来通り維持する。
更新前後のmanifest、検証coverage、未実施backendを記録する。現稼働の所有・停止管理に必要な記録を保護する。

### 段階6の検証と合格条件

| 対象 | 必要な証拠 |
|---|---|
| offline contract | family assets / tokenizer / manifest / context / caps、誤PLE / MTP拒否、現V2 catalog / profile・plain登録の互換、公式retry / READY等の不変。撤去済検査非復活 |
| 既存testの継承 | test_strata_cli、test_official_runtime、test_runtime_safety、test_startup_progress、test_profile_defaultsを現sourceに照合し、現存owner / guard / reuse / failureを保持。過去fixtureの撤去済guardを復活させずfamily / bundleの負例を追加 |
| lifecycle fault | target不備はold停止前失敗、stop拒否時newなし、busy / queued / client-route保護、create / READY前cancel・crash・late child、READY後identity変化、cleanup失敗と次操作復帰 |
| race / state | 同時CLI / start-stop / manager direct、二層lock取得順・非deadlock、確認後・lock前の別switch / target snapshot変更では拒否し新旧processを変更しないこと、半書state、requested / last-ready / live分離、mixed bundleの新操作中断 |
| Windows HIP | 基本primary＋RAM / SSDで配置数値 / lease / drain / cancel、shutdown / cohort / portを確認。cache-onlyはT22、両演算modeはT44 / T45のtrunk数値とT46基本CLI、T47の最適化 / consumer証拠を別に結ぶ。基本入口を一括blockしない |
| 全通常入口 | CLI model選択 / start / stop / status、WebUI / chat / Pi / DSHで実providerのtext・reasoning・toolcall / 結果往復・capabilitiesを確認。mock / UI表示だけでPASSにしない |
| stream / history / tool | SSE / error / EOF / cancel、stale応答commit、旧履歴保持、epochとtool権限・実行直前照合、再選択 / 新会話、alias strata互換 |
| Huihui既存動作の限定確認 | 現V2のassets / default / profile / mask / plain登録・現存source / owner管理を保持し、共通変更に影響する入口の短いsmokeと通常切替を確認。V2未実証を旧記録でPASSにせず、全面品質・性能・長文再測定や撤去済receipt検査は追加しない |
| 更新 | candidateがlive / 管理中attemptと既存登録・stateを上書きしない、新bundle選択、selected / running分離と混在排除 |

画像 / 1M全文 / DSpark等の別達成基準を段階6基本統合の循環前提にせず、未対応・未実施を黙って合格にも変更しない。
段階4 / 5の数値・transport・寿命ゲートは維持する。上表はv1.12r1策定時点の計画で、その時点ではtests/build/runtime/client実機検証を行っていなかった。2026-10-21以降の限定検証は§4のtask scopeを参照する。
## 11. 段階7: 性能・長文・DSpark / graph・要求単位の機能検証

固定native UD-Q4_K_XL、Windows / HIPとsection 1の実機deploymentでsingle / cache-only / expert-assist / layer-splitを検証する。両演算方式とも実装必須で、以下は未実装・未実測の計画である。
性能測定の試行数と要求単位の機能検証は実証範囲の試験案であり、通常利用の起動条件ではない。1M等の未実施を基本text利用不可や成功へ変換しない。

### 検証の分類・実証例と各対象の合格条件

| 分類 | 検証・比較 | 合格対象 |
|---|---|---|
| S7-0: 正しさ / 配置 | 段階5のN / Q / G、finite / tie / state、段階4のtransport bit / lease、段階6のidentity / 入口 | 当該scopeの数値・配置・所有契約。未合格出力を速度PASSにしない |
| S7-1: eager baseline | 比較harnessだけDSpark off / graph offでload / prefill / decode / shutdown | 実weight・実機の数値と測定基準。試験offを通常profileへ移さない |
| S7-2: 供給 / secondary mode | single / cache-only配置、expert dispatch / gather、layer cut / shared rows・tap、cold / warm | mode別数値 / stateの合格後に同条件比較。実転送・両GPU memory / 待ちを記録し、P2P skipをPASSにしない |
| S7-3: prefill / 長文 | 今回対象length / chunk・append / reuse / reset・境界を事前固定。公式最大 / 全候補は補助scope | 対象長文の真のtoken長、打切りなし、position / state / logits整合。補助到達範囲は別記 |
| S7-4: DSpark単独 | graph offでdraft3層artifact / verify / 採否 / state / 終了 | target確定tokenとstateの正しさ、その後off対比の性能効果 |
| S7-5: graph単独 | DSpark offでcapture / replay / 動的値 / cache miss / cancel / 再capture | eagerとの数値同等、address / owner / lease / epoch、その後性能効果 |
| S7-6: 組合せ | 2×2のDSpark / graphと実供給 / secondary_device、window形状・prefill / decode遷移 | 追加memory / cache減少込みの組合せ。単独PASSを転用しない |
| S7-7: 要求単位の機能検証 | 固定fixtureの資源 / pressure / fault / cancelと通常入口 | 各要求前・中・後の上限 / 台帳 / lease / drain、次request、安全停止 / port / cohort |

S7番号は分類・安全な実証例で全直列の依存ではない。実完了依存はsection 4のtask DAGを使い、最大contextをDSpark / graph単独へ連鎖させない。T40 / T41の基本構成、T22のcache-only、T46の両演算mode基本資格、T47の最適化・consumer結合を分ける。
tier強制は小さいmicrofixtureとfullmodel実workloadを区別する。全500GBをGPU / RAMへ常駐させる不可能な比較は要求しない。
DSpark / graphのmode変更に再起動が必要なら、構成別の性能測定runとして起動時identityと測定条件を記録する。

### 既存sourceを使う範囲と不足する検査

| source | 流用候補と限界 |
|---|---|
| graph.hpp / graph.cpp | GraphRegistryはGDN / QSAとn_tokensをkeyにし、固定addressはcaller責任、bodyは初回のみ。動的kernel引数・0node・driver query待機の検査素材。DeepSeek graph完成の証明ではない |
| tests/hip/handoff.cpp、host_graph_launch_test.cu | 実GPUのpayload変化 / graph replay、wait解除 / error / drain / backpressureの素材。native DeepSeek / secondary_device lease / cancel資格は別途必要 |
| spec_prob.hpp / spec_verify_parity.cpp | sampled p / q採否・residual・RNG counterのhost参照とGPU照合。Qwen由来chain / k64等をDeepSeek仕様や通常制限へコピーしない |
| server.py / test_server.py / test_quiet_cancel.py | generated / prompt_read / reused / offered / accepted集計と取消契約。fake engine試験は実DSpark / 実機の正しさ・速度を証明しない |
| tools/strata_bench.py / needle_bench.py | 通信・測定の素材。pieces fallback、成功判定、文字数 / 3.2等の長さ近似をそのまま合格根拠へ使わない |
| Maya Stats / DS4_PROF、LuceBox state / sampling tests | Engram hit / read / wait / RAM移動 / draft位置採否、accepted-state / graph世代 / sampled分布の参照。stage合計をwall timeにせず、V4 fixtureをV4.1 ratio2 / 1・共有source・Engramへ適合 |

### 測定manifest・token数・時間の定義

- model / shard / tokenizer / encoding / binary / toolchain / backend / driver / OS / profile / device identities / epochを固定する。
- corpus hash、tokenizer後token列、sampling / RNG、output / stop、batch / parallel / chunk、cache状態 / transfer mode / 他consumer、clockとcount根拠を固定する。
- TTFTはrequest基準時刻から最初の実model token（reasoning含む）までと定義する。最初の可視text、queue、load / 初期化、純prefillを別名で計測する。
- aggregate TPOTは確定出力Nが2以上のfirst-token～last-token時間 / (N-1)。engine時間とclient end-to-endを混ぜず、SSE bundlingのchunk latencyをper-token latencyにしない。
- TPSはmanifestでcount範囲を固定した実target確定 / 生成token数から求める。draft offered / accepted / bonus / rejected、text / reasoning / EOS等を別表示する。
- usage=0と欠落を区別し、actual token IDs / 確定countとfinish_reason・DONE / EOF契約を照合する。SSE piece数やdraft数で出力token数を補わない。
- token数やclockの根拠欠落、分解能不足、分母非正、非finiteなderived metricは未判定で合格値に使わない。logits等の非finiteは段階5の数値FAILを維持する。
- 正常な短いEOSをlengthに変えず、N不足のTPOTは未判定にする。通信完了や最初のchunkだけを生成成功の根拠にしない。
- logical useful bytes / physical I/O bytes（取得不能はunknown）、read amplification / waste、SSD待ち、RAM copy、P2P / D2H / H2D、kernel / overlap、r / xp / xb / m / sを記録する。
- prefill新規 / reuse、TTFT / TPOT / tok/s、p50 / p95 / p99と標本数、RAM physical / commit / pinned、各GPU / WDDM、queue / lease / graph cacheを記録する。
- copyはcompletionを伴うhost monotonicと同device eventで計測し、跨deviceのelapsed eventを比較しない。
- coldはprocess / app cache / OS cacheを区別し、OS cache未確認をphysical coldと呼ばない。全hash確認のwarmingは別条件。cache flushや他consumer停止を必須化しない。
- 詳細traceはbounded / samplingし、詳細診断runと通常benchを分けて観測負荷を示す。

### 比較回数と性能効果の判定

短ケースはwarmup1回＋paired AB 5組、長ケースは3組を初期案とする。
pilotで分散を観測し、本測定前に回数 / AB順序 / 主指標 / 誤差許容帯 / 信頼区間の方法を固定する。結果を見て基準を緩めない。
tailの標本不足をp95 / p99保証に使わない。固定の絶対TPS / TTFTをユーザーSLOとして追加しない。
同条件の確定出力TTFT / TPOT / end-to-end、誤差・再現性、追加cache / memoryを含めて比較する。
speedupの事前指定信頼区間が1を跨げば効果未判定。未改善・悪化は最適化効果未達とし、数値・機能故障と分ける。
新機能のopt-in / 既存default path維持を基本とし、通常default変更はStrata AGENTSのmeasured faster等の既存条件を満たす場合に限る。

T46の基本eager比較とT47の最適化結合比較を区別する。両演算modeは同一model / native型 / tokenizer / workload / 出力・sampling / context / cache条件を記録し、同じ試験scopeでpaired ABする。expert割当・layer cut、両GPUの実compute / idle / transfer / gather / shared-state待ちと追加memoryを分け、TTFT / 確定token TPOT・throughputを比較する。速度未達・順位未判定でも両方式の実装を省略しない。
全context×全mode×全最適化の無差別総当りを要求せず、代表case・shared境界・必要DSpark / graph組合せを評価前に宣言して証拠をbindする。未検証範囲をPASSに拡張しない。

### Xolotl比較を踏まえた改善順序（impl81・計画レビュー対象）

比較対象は[Xolotl固定HEAD b3452666e07a6374d06bb8c2185dffa271e8f65f](https://github.com/Indras-Mirror/Xolotl/tree/b3452666e07a6374d06bb8c2185dffa271e8f65f)。比較v2の独立重要0は調査内容の確認であり、コード移植・数値意味変更の承認ではない。以下を既T35後続診断/T36/T38/T39/T40/T46/T47へ統合し、task・通常起動gate・全組合せsuiteを増やさない。既T22/T33/C32の承認済み作業は並行継続する。

1. **供給の寿命・粒度から改善する。** 既承認C32（provider-lifecycle-pre-r1、077a395e…）で同64KiB/同4worker/outstanding1/同32windowのA32対C32をACCA比較し、provider再使用だけを切り分ける。原本最大12MiB、既enqueue/take・世代/borrow/取消error→次要求/終端drain closeを維持する。結果後の最小production候補はPrimaryのtile内でfile/worker/providerを持続させる変更とし、累積counterは差分で会計する。live nativeはenvironment単独writerへexact before/afterと差分計画を渡す。以後、実routeで必要なspanのみの読込集約・有限並列read、既owner/event/leaseを使うI/O→H2D→compute重畳の順で評価する。Xolotl ds41_moe.cpp:1302/2384/3084は参考だが、32reader×8partやwhole-layer prefetchをそのまま既定へ移さない（同HEADのwhole-layer閾値既定はnever）。SSD/RAM/GPU hit・要求bytes・provider open/close・host待機を分け、host時刻を純SSD/GPU時間と呼ばない。
2. **既意味を保つHIP演算とtile利用率を先に確認する。** native_mmvq.cu:2523等の型dispatch/協調演算を参考に、現quantの1thread/1row・逐次full-Kとの違いを確認する。既T20のK昇順FP32/+0/FMAなし・actQDQなし/BF16又はF32 head・Qexactを基準とし、load/vector化/独立rowの協調や転送削減を先行候補にする。reduction順/FMA/追加QDQ/許容差の変更は同値最適化と呼ばず別提案に分ける。既test選択tile_bytes=2MiB/tile_rows=256と実full-K rowstrideを照合済みで、blk0型39 gate/upの256rowは696320B、downは313344Bに留まる。byte上限/最終端/full-K/実kernel shapeを守るtest geometry比較を小候補へ置き、未測定で通常defaultを変更しない。
3. **layer-major batched prefillとexpert unionを評価する。** 現active_batchだけでprefillがbatch化したと扱わず、token毎Core.stepとの対比を固定する。T36の選択長文/append/reuse/resetと既T20/T25のprefix・KV/compressor・Engram history・mHC・mask/positionを保持する。unionは同expert weightの読込/実行共有でありrouter/top6/合成順の変更を含めない。先に小batch/既Qで差分を確認し、271/276tokenの実tool promptを改善効果未測定のまま盲実行しない。通常context/思考/retry/compact/出力を試験都合で縮めず、真の原token数とsemantic初出までの観測を記録する。
4. **常駐索引・会話適応RAM arenaと正確prefix restoreを後続へ置く。** ds41_moe.cpp:5546/5719の頻度/slot互換・retire/read/publishを既cache ownerへ対応させる。background readはprompt/decodeとの競合を測り、未確認で常時有効化しない。prefix restoreはKV/ring/compressorのpartial/position/Engram historyを含む既T25/T36のexact復元責任で確認する。Engram ds41_engram.cpp:531/650のsort/unique・4KiB group・並列read・scatterは現T14/Row供給に同等処理がないか先に照合し、重複実装せず1～3の供給/計算候補へ組み込む。
5. **routing biasはユーザー指定の任意高速modeとして計画する。** 既定bias=0、現固定数値版へ混入せず、1～3の基礎最適化後に評価する。元router評価/重みと選択用補正を分離し、0で既存選択と重みへexactに戻る構成を選ぶ。Xの係数を固定移植せず、小補正・元top expert保護等を比較候補とし、その保護を通常の新gateにしない。cold/warmのexpert選択変更率・SSD logical read・TTFT/確定token速度と、日本語/コード修正/tool/長会話/反復の品質を同条件で比較する。品質同等・速度向上は未実証。modeの明示選択/identityはT46、影響consumer/既最適化との結合と品質比較はT47/T40の既scopeへ具体差分として束縛し、biasなしの基本mode資格をこの任意評価待ちにしない。

後続のpacked KV/fusion/HIP graphはT39、実DSpark draft/adaptive verifyはT38/T47へ重複統合する。Xの「モデル規定fakequant/FP4 KV exact」を現baselineと同義にせず、公式DeepInfer/RecipeとT03/T04の意味を照合し、追加QDQ/丸め差は別提案にする。draft reject後の未確定state破棄/確定state保持は既機能要件であり、運用上のrollback機構を追加するものではない。

指定UD-Q4_K_XL/MXFP4等の元型・Windows/AMD両GPU mode・通常context/思考/retry/samplerを維持する。GSQモデル置換/expert prune/固定32K思考/top256 sampler/Linux raw-device依存は採用しない。Xの約27tok/sは4090/Linux/別量子化等の観測で、今回との同条件速度比にしない。コードをコピーする場合は固定HEADのMIT LICENSEとcomponent別noticeを確認して保持する（本節は原理の比較計画のみ）。新A/Bは変更のある最小代表に絞り、既T35正式3pairを別実装の効果へ流用せず、未判定を速度PASSへしない。

#### 追加資料の重複整理と任意biasの境界（impl82・計画レビュー対象）

固定HEADの追加資料を現物SHAで照合した。[routing bias詳細案](xolotl-routing-bias-design-20261021.md)は6163323409849ab4d5d948a9bf8feda74a1affa5eb39c31c43b2aa6f9384147a、[全体調査](xolotl-optimization-survey-20261021.md)はb1218c61af310a004480589d92d3cc6ad39d46e74fd9770216ffec20d7b88dc2。資料の独立重要0はproposalの確認であり、44候補全部の実装・係数・数値許容変更・速度合格の承認ではない。元v1.12r1の37/47に追加Xolotl/biasの完了を含めず、元T35完了を維持したまま本追加waveを未了として最終M-ALL報告にも残す。

| 重複する候補群 | 既taskへ統合する差分と判断 |
|---|---|
| S01/S02/S11/S13、既C32 | 持続provider/file/worker・route union readとEngram sort/dedup/page集約を同じ供給waveへ。C32は同64KiBのlifecycle差だけ、モデル因果は後続production差分の同条件A/Bで確認。route/phase/time観測は必要接点だけ追加し新計測基盤を作らない |
| C03～C07/C13、C01/C02既融合 | matrix/attention/top-kの協調load/vector/tileを既数学順・BF16/QDQ/tie契約へ照合。既融合の存在を再実装せず、還元順変更/MMQ追加activationQ8は別数値提案。T36/T39/T40の変更差分へ必要数値を束縛 |
| C10～C12/C18/C19/S05/S07 | layer-majorと短turn、query tile、workspace/cache貸借を同prefill容量waveへ。alloc前だけの幅再選択とstate変更後の失敗を分け、OOMを通常context縮小で代用しない |
| S04/C16/S14 | freshCoreを作る現producerとweightcache保持を、全attention stateのprefix再利用と混同しない。全40層KV/ring/compressor/Engram/画像identity/position/数学由来をT25/T36へ結び、restore失敗は確定境界から再計算する |
| C21/C22/S06、C23 | draft stash/長prompt時の退避と再seedは同施策としてT38/T40/T47へ。prompt lookupも同target verifier/採否/bonus/確定state/RNGへ結ぶ。実draft成立前に新経路を実装済みとせず、DSparkを黙ってoffにしない |
| C08/C09/C15/C24/S08 | graph/shape/address/owner、配置適応、packed KVをT39/T40/T47へ。モデル規定丸め値の圧縮と元無QDQモデルへの同値を区別する。現HIPのstate形態にないbuffer/貸借を先回りで増やさない |
| S09/S10/S15～S17/C14/C25～C27 | multisession scheduler/CPU expert/GSQ変換/dense再量子化/Linux rawdevice/独自hardcap/Comfy停止は今回の採用範囲外又は用途別保留。Windows/既readerを丸コピーで置換しない。採用する差分だけlicense/thirdparty noticeを保持 |

任意biasの0は**追加cache/tier補正λ=0**であり、元learned correction/bias_vlをゼロ化しない。0では従来kernelへ直分岐し、補正用mul/add・追加sort・table read・meter D2Hを増やさない。λ0では従来の全順位/tie/weightsをexactに保つ。nonzeroは選択scoreだけに加え、合法top6集合/順位は変わり得る。ID安定tie・元rawscore由来weight式・明示した正規化順/canonical expert ID寄与順を保持し、同集合の場合は元順位/weightsを保持する。初期対象はtarget decode selection、prefill/appendは元routing。shared expert/Engram/attention index/draft routerへ無断拡張しない。P/N/M/margin・係数・品質閾値・標本数は未採用proposalで、全直積を必須化しない。

現cacheはrowtileであるため、元expertのgate/up/down必要spanからReady complete/partial/none/unknown coverageを既ownerのartifact/type/layout/generationへ束縛して先に確認する。partial/unknownをresident又は全SSDへ捏造せず、signalがなければ無効/未判定を報告する。追加sidecar索引は作らず、必要metadataの短い整合点からderiveする。request固定snapshot Sは詳細案の推奨候補として、target decode/verify/bonusで同じSを使い、speculative readやevictionで同要求のtargetを変えない設計をT38/T47で具体化する（全slot pinは不要）。元bias0targetと同分布という意味ではない。将来tokenごとの更新は別因果設計が必要で、snapshot方式の具体API/粒度/品質は未確定のままレビューする。

fastで生成したsuffixのstateは次のexact prefixとpolicydigestだけで数学同値にならない。確定数学境界までの保存stateを使い残suffixを元prefill規則で再計算するfallback等をT36/T47で設計し、会話継続を禁止しない。既API/CLI→request immutable policy/configured/effective/digest/epochを一箇所の解決順へ結び、次exact要求への復帰・cancel/unknown/空出力の残留0を確認する。未合意品質差・通常利用縮小はその部分だけ別提案とし、基礎最適化/T22/T33/C32を止めない。

### 長文・prefill・state再利用

- 4K / 32K / 128K / 256K / 512K / 1Mは試験点候補。今回実施する代表長文・境界・再利用のscopeと合格条件を事前固定し実測する。公式最大 / 全候補を必須化せず、対応する公開context / config最大と真の整数token数、補助未評価範囲を記録する。対象FAILを未評価へ付替えない。
- prompt数はencoding / chat template / tool定義等を含む実値と内訳を使う。context Cに対し生成予約と必要余白を明示し、含有済みprotocolを二重加算しない。
- 無断truncate / compactを全長成功にせず、EOS / length / cancel / errorを区別する。入力・context・outputを通常設定で勝手に縮小しない。
- 段階5のSWA127 / 128 / 129、ratio2 odd / even / partial、CSA2 compressed rows16383 / 16384 / 16385、source20 ratio1とratio2のposition換算を継承する。
- 長文prefill→decode、同prefix reuse / append、prefix変更 / reset、新会話で、mask / position / route / state ownerと共有writerが正しいことを確認する。
- selected positionsのteacher-forcing logits / finite / driftを独立bounded reference / 固定traceと比較し、長文state精度を確認する。
- 長距離参照課題や品質指標は別reportにし、一つのneedle成功を1M品質全体のPASSにしない。文字数近似を真のDeepSeek token数の代用にしない。

### DSpark単独・確定tokenとstateの正しさ

model固有draft3層artifact / encodingをtrunk40層と分け、Qwen MTPを流用しない。
accepted prefix、全accept / 全reject / 最初のreject / bonus、EOS / length / window端、prefill / append / cancelを検査する。
不採用draftのstateをcommitせず、compressedKV / SWA / Engram / HC / indexに棄却tokenが残らない確定位置のstate整合を確認する。
greedyはtarget決定と事前固定tie契約・確定tokenを照合する。floatは段階5のoperator別許容差を使う。
sampledは公式実装のsampling契約へp / q、penalty / top-k / top-p / min-p / temperature、RNG / residualを対応付ける。
pathwise一致が契約の経路だけ同seed / token完全一致を要求する。独立RNGのrejection samplingはtoy analytic golden・事前固定の分布検定とstate整合で確認する。
一つの文字列一致で分布正しさを証明せず、accepted率だけで高速PASSにしない。
off対比の確定tokens/sec / TPOTにdraft / verify / I/O / 追加VRAM / cache減少を含め、offは比較試験内に閉じる。

DeepInfer DFlash / ConfidenceHead、csrc/engine/mtp_varlen.hppとsampler.pyを、後続draft confidenceが先行draftのverify選択を左右しない因果条件・round rate・accepted prefixの参照にする。
既計画のdraft3層は構造、DEEPINFER_USE_NEXTN_DECODE default5はdraft生成 / verify長の設定で別概念。5を層数や当機の通常limitへコピーせず、hardware throughput curve依存の効果は当機未実証とする。
worker/cuda_graph_runner.pyの固定buffer / shape選択も検査仕様の参照であり、HIP移植済み・当機高速化済みとは扱わない。
### graph単独・captureと資源寿命

- capture keyに必要なexecution_mode / assignment・partition / owner device / shape / window / dtype / layout / context / bundle / epoch等をbindし、既存GDN / QSA keyだけで互換扱いしない。
- position / token / page-table等を動的device dataにし、address / slot世代を安全に固定・更新・再captureする。
- cache miss / secondary_device readは有限I/Oとleaseで同期し、capture初回だけhost処理が走って以後staleになることを防ぐ。
- 0node / capture失敗、shape変更、再capture、eviction / reallocation、cancelをeagerと比較する。
- in-flight graph完了までbuffer / slot / graphのownerを保持する。drain不能なら隔離し上書き・freeしない。
- capture / instantiate初期費用、replay速度、償却break-evenを分ける。実装済み安全fallbackを維持して実経路を記録し、失敗を高速PASSへ丸めない。
- DSparkとの組合せではverify windowや採否で変わるshape / stateを別途検証し、各単独のPASSを転用しない。

### 各要求の資源・pressure・fault

固定fixtureの各要求の前・中・後で、実allocation / queue / cache / handleとledgerを照合する。
一時資源と解放すべきlease / handleはdrain後に解放し、同一構成・同一位相の要求前後で確認する。
persistent expert / Engram / graph cacheと再利用poolは別会計とし、固定上限・eviction / 解放方針に沿う充填・保持を許容する。
許されたcache充填を失敗扱いせず、cold開始量への復帰も要求しない。上限逸脱、台帳不一致、解放すべき資源残存、不正leaseを機能FAILとする。
各試験内のqueue / memory pressure、commit / WDDM / OS reclaimable file cache / SSD / 他consumerを区別し、自主管理資源だけへ誤って加算しない。
fault注入は開発fixtureのtest所有資源へ限定し、driver resetや他利用者停止を通常試験にしない。
allocation / I/O / copy / graph / kernel failure、late completion、disconnect / cancel、owner / epoch変化を検査する。
cache故障の安全fallbackとcontext損傷の既存error / quarantineを分け、続行不能を必ず継続させる条件にしない。
安全停止、cohort / port、再確認 / 再選択、次requestの健全性まで確認する。

### 失敗時の切分けと報告

| 症状 | 最初に分ける対象 |
|---|---|
| 全modeで誤出力 | 段階5の最初のdivergence、artifact / tokenizer / 演算 |
| DSparkのみ | draft identity / 採否、未確定tail stateと確定位置 |
| graphのみ | shape / address / lease / owner / capture epoch |
| 長文のみ | 実token count / position / 圧縮可視範囲 / append / reset |
| 各試験内のmemory / queue pressure・資源不整合 | 自主管理allocation / queue / ledger / leaseとOS file cache / commit / WDDM / SSD / 他consumerの内訳 |

小さい境界fixtureへ縮約し、複数modeを同時変更して原因を隠さない。
reportでは数値 / 配置 / 要求単位機能の合否、性能効果の達成 / 未達 / 未判定、長文到達長・品質範囲、skip / 未実施backendを分ける。
Huihuiの確認は今回変更した共通部分のassets / default / mask / dynamic binding、影響した入口の短いsmokeと通常model切替に限る。
未実施1Mを通常利用不可の条件へ昇格せず、成功とも記載しない。v1.12r1策定時点では検証実行なし。以後の限定検証scopeは§4を参照する。

## 12. 全工程の検証・通常入口・完了条件

以下は該当scopeに適用する証拠であり、M-NUM / M-CACHE / M-NORMAL / 個別M-QUALはsection 4の依存集合で判定する。基本入口、cache-only、両演算modeのscopeを分け、M-ALLは指定cacheとexpert-assist / layer-splitの両実装・必要な組合せを含む証拠で判定する。補助N→Q全品質 / 公式最大・全候補は別評価とし、未判定をPASSにせず必須完了を止めない。部分報告はM-ALL完了を待たない。

- 初期fixtureで実型decode、範囲・alignment、partial read、cache key / layout、1/2/4/8tokenを確認する。
- 強制GPU hot / RAM hit / SSD missで同一profileの数値、route / mask / stateを比較する。
- stage / slotのpressure、queue満杯、prefetch取消、Engram公平性、cancel / disconnectを試す。
- secondary_device P2P / host bounce / RAM / SSDの配置同値、visibility / device-role binding、graph / event ownerを確認する。
- secondary_device pressure / 他consumer変動、D2H失敗・drain不能dst隔離、late completion、跨device cancel / fault、fallback後の次requestを検証する。
- DeepSeek専用のvisibility変更で現Huihui V2 / global mask / plain登録・所有管理 / 通常入口が変わらないことを確認する。
- read / allocation / DMA / kernel error、世代越えcompletion、drain失敗、次request健全性を確認する。
- startup / 定常 / prefill / DSpark別にphysical / commit / WDDM / GPU / queueのledgerと実測を照合する。
- SSD read、RAM→stage、stage→GPU、kernel、overlapを分け、cold / warm、TTFT / TPOT / p95 / p99を測る。
- source全SHA確認はcold測定条件と分ける。初回検証、通常起動、必要時scrubを混同してcacheを暖めない。
- 通常CLIは同設定再利用、明示切替、status / health / models一致、失敗後の再選択・中止を確認する。
- binary / source / profile / artifact / tokenizer / model / context / effective flagsをreceiptで結ぶ。
- Pi / DSHへQwen tokenizer / MTPを誤接続せず、既存clientのprovider / retry / compact等を試験都合で縮小しない。
- official readiness / retry等は既存経路を維持。保護不一致から停止許可や自動再起動を推定しない。
- 各実装・GPU検証開始時に現在のstatus / client / ownerを確認し、依頼範囲の操作だけ行う。
- Huihuiのbinary / profile / artifactを維持し、共通変更に影響する通常入口の短いsmokeと通常model選択による切替を確認する。Huihui全面の品質・性能再測定は追加しない。
- 短文生成は長文・1M全文・速度の証明としない。未実施は明記する。
- 最新版の独立レビューで未解決重要指摘0、必須scopeに適用するbuild / offline / 実GPU / 通常入口 / 安全cleanup・再確認の証拠を揃えて完了とする。指定cache-onlyと両演算mode、採用DSpark / graph等flagsの必要組合せは影響scopeを再検証し、基本構成だけのPASSを代用しない。mode選択・実効status・履歴継続と安全停止の通常入口証拠も含める。

## 13. 変更範囲・次の作業

実装候補は、section 3のproject-owned control / native / model / client / tests層、少数の版付き上流hook / CMake差分と、
Strata-dataのcatalog / CLI / runtime manager / model別profile・receipt、および実装結果に対応する説明書。
Pi / Harness / WebUI / chatは段階6で確認した実依存箇所に限定し、別modelの資産・保護を変更しない。StrataModは対象外。
上記folder構成はv1.12r1策定時の配置案。2026-10-21のユーザー実装依頼で実装を開始し、現在は§4の隔離worktree・有界raw fixture・試験bundleと本計画/owned READMEを変更対象にしている。通常CLI/client等は依存順の後続scopeで扱う。
v1.12r1策定時は本fileだけの文書作業だったが、その制約は現在の承認済み実装を未着手に戻すものではない。原HTML、会話txt、AGENTS、memoryは保護し、無関係な変更・既live管理/現Huihui資産を維持する。
進捗とscope別の実装/未実施は同じ計画へ更新し、各waveの計画/実装と変更後最新版を既存手順で独立reviewする。commit・push・PRは個別承認を維持する。

## 14. 固定参照と改訂履歴

- [local基準Strata](https://github.com/Niko1221/Strata/tree/477ac13cbe8e582c20484871ce459d20d82df09d)
- [Strata FileExpertSource](https://github.com/Niko1221/Strata/blob/477ac13cbe8e582c20484871ce459d20d82df09d/src/core/expert_source.cpp)
- [Strata DirectFile](https://github.com/Niko1221/Strata/blob/477ac13cbe8e582c20484871ce459d20d82df09d/src/platform/direct_file.cpp)
- [Strata RemotePrefillSource](https://github.com/Niko1221/Strata/blob/477ac13cbe8e582c20484871ce459d20d82df09d/include/strata/core/remote_experts.hpp)
- [Strata remote copy](https://github.com/Niko1221/Strata/blob/477ac13cbe8e582c20484871ce459d20d82df09d/src/core/remote_experts.cpp)
- [Strata peer検査](https://github.com/Niko1221/Strata/blob/477ac13cbe8e582c20484871ce459d20d82df09d/src/core/peer_experts.cpp)
- [AMD HIP P2P API 7.0.1](https://rocm.docs.amd.com/projects/HIP/en/docs-7.0.1/doxygen/html/group___peer_to_peer.html)
- [AMD HIP multi-device公式説明](https://rocm.docs.amd.com/projects/HIP/en/latest/how-to/hip_runtime_api/multi_device.html)
- [mmnga DeepSeek](https://github.com/mmnga/Strata/tree/d4c07dde710cd009c47f36a8d002ff938b0eef67/src/deepseek41)
- [Maya model / flow](https://github.com/mw00/project-maya/blob/8d9a9b5d705049a87da853717cdc59440252de30/src/ds4/ds4_model.cu)
- [Maya Engram I/O](https://github.com/mw00/project-maya/blob/8d9a9b5d705049a87da853717cdc59440252de30/src/ds4/ds4_engram_io.hpp)
- [Maya native GGUF](https://github.com/mw00/project-maya/blob/8d9a9b5d705049a87da853717cdc59440252de30/src/ds4/ds4_gguf.cu)
- [Maya metadata pack](https://github.com/mw00/project-maya/blob/8d9a9b5d705049a87da853717cdc59440252de30/tools/ds4/pack_gguf.py)
- [LuceBox DS41 source-map](https://github.com/Luce-Org/lucebox/blob/81940128d118f4d2bc0070e4c772542938c7a5c3/server/docs/DS41.md)
- [Unsloth固定GGUF](https://huggingface.co/unsloth/DeepSeek-V4.1-Flash-1017-GGUF/tree/f924b94f19c1fea02c06a65c8475b0a45e2b88b1)
- [公式固定config](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017/blob/1bae0e1088993b9b82de08f59de5be5a34e42170/config.json)
- [公式演算参照](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017/blob/1bae0e1088993b9b82de08f59de5be5a34e42170/inference/model.py)
- [公式量子化kernel参照](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017/blob/1bae0e1088993b9b82de08f59de5be5a34e42170/inference/kernel.py)
- [Strata test / backend登録](https://github.com/Niko1221/Strata/blob/477ac13cbe8e582c20484871ce459d20d82df09d/CMakeLists.txt)
- [Strata HIP intrinsics test](https://github.com/Niko1221/Strata/blob/477ac13cbe8e582c20484871ce459d20d82df09d/tests/hip/intrinsics.cpp)
- [Strata DMA byte / event test](https://github.com/Niko1221/Strata/blob/477ac13cbe8e582c20484871ce459d20d82df09d/tests/core/dma_batch_parity.cu)
- [mmnga artifact test](https://github.com/mmnga/Strata/blob/d4c07dde710cd009c47f36a8d002ff938b0eef67/tests/core/deepseek41_artifact_test.cpp)
- [mmnga MXFP4 ALU test](https://github.com/mmnga/Strata/blob/d4c07dde710cd009c47f36a8d002ff938b0eef67/tests/deepseek41/mxfp4_alu_test.cu)
- [mmnga CHECK / engine](https://github.com/mmnga/Strata/blob/d4c07dde710cd009c47f36a8d002ff938b0eef67/src/deepseek41/engine.cpp)
- [Maya GGUF test](https://github.com/mw00/project-maya/blob/8d9a9b5d705049a87da853717cdc59440252de30/tests/ds4_gguf_test.cu)
- [Maya Q参照候補](https://github.com/mw00/project-maya/blob/8d9a9b5d705049a87da853717cdc59440252de30/tools/ds4/ref_gguf.py)
- [Maya reference / compare tools](https://github.com/mw00/project-maya/tree/8d9a9b5d705049a87da853717cdc59440252de30/tools/ds4)
- [LuceBox unit tests](https://github.com/Luce-Org/lucebox/tree/81940128d118f4d2bc0070e4c772542938c7a5c3/server/test/unit)

- [Strata公式MCP管理](https://github.com/Niko1221/Strata/blob/477ac13cbe8e582c20484871ce459d20d82df09d/tools/strata_mcp.py)
- [Strata server](https://github.com/Niko1221/Strata/blob/477ac13cbe8e582c20484871ce459d20d82df09d/serve/server.py)
- [Strata frontend / parser](https://github.com/Niko1221/Strata/blob/477ac13cbe8e582c20484871ce459d20d82df09d/serve/frontend.py)
- [公式encoding / tokenizer固定配布root](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017/tree/1bae0e1088993b9b82de08f59de5be5a34e42170)

- [Strata graph契約](https://github.com/Niko1221/Strata/blob/477ac13cbe8e582c20484871ce459d20d82df09d/include/strata/core/graph.hpp)
- [Strata HIP graph / handoff test](https://github.com/Niko1221/Strata/blob/477ac13cbe8e582c20484871ce459d20d82df09d/tests/hip/handoff.cpp)
- [Strata host graph test](https://github.com/Niko1221/Strata/blob/477ac13cbe8e582c20484871ce459d20d82df09d/tests/core/host_graph_launch_test.cu)
- [Strata sampled acceptance参照](https://github.com/Niko1221/Strata/blob/477ac13cbe8e582c20484871ce459d20d82df09d/include/strata/core/spec_prob.hpp)
- [Strata verifier parity test](https://github.com/Niko1221/Strata/blob/477ac13cbe8e582c20484871ce459d20d82df09d/src/kernels/spec_verify_parity.cpp)
- [Strata bench素材](https://github.com/Niko1221/Strata/blob/477ac13cbe8e582c20484871ce459d20d82df09d/tools/strata_bench.py)
- [Strata needle素材](https://github.com/Niko1221/Strata/blob/477ac13cbe8e582c20484871ce459d20d82df09d/tools/needle_bench.py)
- [Strata fake-engine cancel test](https://github.com/Niko1221/Strata/blob/477ac13cbe8e582c20484871ce459d20d82df09d/serve/test_quiet_cancel.py)
- [Maya DS4 Stats](https://github.com/mw00/project-maya/blob/8d9a9b5d705049a87da853717cdc59440252de30/src/ds4/ds4_model.hpp)
- [Maya layer group / 境界・shared rows・tap実装](https://github.com/mw00/project-maya/blob/8d9a9b5d705049a87da853717cdc59440252de30/src/ds4/ds4_model.cu)
- [Luce expert branch / canonical join](https://github.com/Luce-Org/lucebox/blob/81940128d118f4d2bc0070e4c772542938c7a5c3/server/src/common/moe_hybrid_ffn_eval.cpp)
- [Luce V4.1 layer-split拒否範囲](https://github.com/Luce-Org/lucebox/blob/81940128d118f4d2bc0070e4c772542938c7a5c3/server/src/deepseek4/deepseek4_backend.cpp)
- [Luce shared KV跨cut検査](https://github.com/Luce-Org/lucebox/blob/81940128d118f4d2bc0070e4c772542938c7a5c3/server/src/deepseek4/deepseek4_loader.cpp)
- [LuceBox sampled distribution test](https://github.com/Luce-Org/lucebox/blob/81940128d118f4d2bc0070e4c772542938c7a5c3/server/test/unit/test_ds4_spec_sampling.cpp)
- [DeepInfer固定README](https://github.com/deepseek-ai/DeepInfer/blob/774ce244b87cc0eb8d4b94ab9f5de2ab22049f01/README.md)
- [DeepInfer deployment Q&A](https://github.com/deepseek-ai/DeepInfer/blob/774ce244b87cc0eb8d4b94ab9f5de2ab22049f01/doc/inference_deployment_qa.md)
- [DeepInfer V4.1 model構造](https://github.com/deepseek-ai/DeepInfer/tree/774ce244b87cc0eb8d4b94ab9f5de2ab22049f01/deepinfer/model_executor/models/v4_modules)
- [DeepInfer HF loader / layout](https://github.com/deepseek-ai/DeepInfer/tree/774ce244b87cc0eb8d4b94ab9f5de2ab22049f01/deepinfer/hugging_face)
- [DeepInfer DSpark schedule](https://github.com/deepseek-ai/DeepInfer/blob/774ce244b87cc0eb8d4b94ab9f5de2ab22049f01/csrc/engine/mtp_varlen.hpp)
- [DeepInfer sampler](https://github.com/deepseek-ai/DeepInfer/blob/774ce244b87cc0eb8d4b94ab9f5de2ab22049f01/deepinfer/model_executor/layers/sampler.py)
- [DeepInfer tests](https://github.com/deepseek-ai/DeepInfer/tree/774ce244b87cc0eb8d4b94ab9f5de2ab22049f01/tests)
- [deepseek-recipe固定README](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/README.md)
- [Recipe Windows wheel build資料](https://github.com/deepseek-ai/deepseek-recipe/blob/935817c66f5d6e64838f419692545f06787e485f/docs/build-python-wheel.md)
localの段階6確認対象はC:\Develop\AI配下のStrata-data管理codeとPi / Harness連携code（section 10のsource表）。
2026-10-20の現V2確認はREADME.md、Strata-data/model_catalog.py、official_runtime.pyのnative / require_registration、およびprofiles/huihui-ud-q4_k_xl_v2-262144.jsonのread-only読取による。runtime状態・GPU成功は照会していない。
上流参照は固定revisionに束縛し、移植採用componentとlicense / encoding版をmanifestへ引き継ぐ。
| 版 | 変更 / 決定 |
|---|---|
| v1.1 | Model保存先を確定。Q4専用loader案を共通reader / 実型dispatch / DeepSeek adapterへ修正 |
| v1.2 | Strata基盤、mmnga CUDA、Maya第一移植候補、LuceBox参照という再利用境界を合意 |
| v1.3 | 段階4の供給・寿命・queue・公平性・容量・性能仮定を具体化 |
| v1.3r1 | fallback維持、現inventory、独立算定、Maya CPU decode境界、有限slot prefill、位相別budgetを反映 |
| v1.4r2 | ユーザー指定のsecondary_device容量cache、storage-only provider、device binding、P2P / host bounce会計、drain不能dst隔離を追加 |
| v1.5r2 | 段階5の参照独立性・数値契約・誤PASS防止・境界fixtureを追補 |
| v1.6r2 | 全段階共通layer / folder案、通常CLI・全client、family codec / epoch、owner / 二層lock / switch、candidate隔離・固定profile / bundleを追補。段階4 / 5本文を保持 |
| v1.6r3 | lock内で確認済み旧identity / epochと固定target bundle / profile snapshotを再照合し、確認後・lock前の変更時はprocessを変えず再確認へ戻る契約とrace受入条件を明記 |
| v1.7r1 | 段階7の順序・実token測定・比較判定・長文state・DSpark / graph・要求単位の資源 / faultを追補。ユーザー指定の対象外運用を全体から削除し、Huihui確認を共通変更の既存動作へ限定 |
| v1.7r2 | ユーザー指定に合わせ段階7の試験範囲を要求単位の資源 / pressure / faultへ限定。性能A/B・長文入力・DSpark / graph・各要求のdrain / 上限 / 次要求を維持し、全章の試験条件と履歴を整合 |
| v1.8r1 | DeepInfer / Recipe固定調査を追補。公式仕様・fixture優先、表現 / 精度差と近似の隔離、DSpark因果・test coverage、元生成token IDsのcodec境界を明記。実装本線・既数値契約を維持 |
| v1.9r1 | 全体を43taskの成果物・完了依存・DoDと未着手状態へ整理。数値検証から通常統合へ直接接続し、固定試験bundle→検証→資格の順とscope別milestoneを明記 |
| v1.10r1 | deviceを役割名へ整理。基本通常入口・native数値と選択secondary cache資格の不要依存を除去し、指定cache納品証拠は維持。既管理の最小拡張、動的cache path、補助N→Q品質 / 最大候補と必須完了の区別を明記 |
| v1.11r1 | ユーザー指定でexpert-assist / layer-split両演算方式と通常mode切替を必須追加。single / cache-onlyを維持し、実sourceの精度 / 共有row・tap境界、46task / 資格 / 会話継続・両方式比較へ整合 |
| v1.11r2 | Expertの一度だけの保証を論理route結果の採用 / commit / combineへ限定。安全な再計算時の旧試行結果・遅延完了の二重採用防止と整合 |
| v1.12r1 | 全体再監査で現Huihui V2 plain経路へ現在地を更新。T44の両GPU全40層TF、T45 trunk / 最小tap ABIとT47実draft結合、T46基本mode CLIとT47既最適化・consumer結合へ責務を整合。47taskは旧scopeの分解のみ |

### T24着手・現在地（2026-10-21、impl27）

- 承認pre r1＋import/default/gone補足の5files: OWN/control/{owner_adapter.py,bootstrap_binding.py}、OWN/tests/control/{test_owner_adapter.py,owned_child.py,verify_owner.py}。生成先はworktree/build-deepseek-t24。既manager/CLI/helperはread-only参照し、fixture専用子process内だけROOT/STATE/PORT/CLI ROOTを差替え、check_port_availableには明示ephemeral portを渡す。official mutator/現Huihui/18080/登録を変更しない。
- TDD missing-file RED後、固定manifestを検証前に保存して実owned child/ephemeral listenerの12tests成功。PID/create/exe、cohort未知child、foreign listener、二層lock競合、snapshot/argv/creator、profile変更、half JSON、cleanup_pending、retained Popen、停止後port再利用を検証。bootstrapは実creator直接identityを照合し、寿命の異なる全祖先列挙を要求しない。fixture handshakeはJSON/socket所有確認で、公式HTTP/model READYや生成資格ではない。
- manifest SHA b7a111187506fb8f6c59e34ada467a2aa889166d5520e37868779bcd950a5db7、proof b4d30f2c8c9ea9b34298fd0065d33d6151ad0c459f2d578192838354089336f3、28boundfiles。独立review未了、T24未完了。実official bootstrap/normal CLI/retry/READYはT29/T30/T33に留保。
- T05固定r2/最大2fileを維持。02:49JST committed shard2=26,575,110,144/48,129,640,000B、shard8=13,690,208,256/202,758,032,592Bは途中bytesでLFS未確定。master89094のみglobal receipt writer、worker91964はshard8単独。全9receipt未了。
- T17はpre v2重要0・Main GOで環境担当がhost-only実装着手。T10の完了依存T05は維持し、Mainの開始gateのみ見直し: T24後は固定T03全9header/1043tensorとT08 APIでoffline adapter/正負fixtureを並行準備可。T05全9SHA/full receiptまでT10完了/全source資格を判定せず、synthetic receiptを実全source証拠へ数えず、real検査をoptional/bypass化しない。

### T24 r2修正検証（impl28）

- r1の独立重要3件は、helper単体検査とadapter mutation経路の結合不足。r2はstop_confirmedにsnapshotを渡し、同state lock内でconfirmed identity/current binary・profile/snapshot/attemptとlistener・cohortを停止前再照合する。handshake入口もsnapshot integrity/current targetを確認。変更profileとforeign listenerはadapter実呼出で旧root/foreign双方の生存を検査した。
- 最小start_fixture transactionは既CLI外側lock＋manager state lockを使い、既active/unknown ownerを保護、intent→Popen直後birth/観測保存→fixture handshakeの順。READY前crash/cancelとcleanup失敗を実test-owned rootで起こし、旧READYを表示せずfailed/cleanup_pendingへ保持する。既cleanup_spawn_handleのsaved cohort判定が未成立ならcleanup_pendingを維持し、成功停止へ丸めない。新owner authority/official start/retry loopを作らない。
- 14tests/28boundfiles、manifest bundle-r2/manifest.json SHA f4aa5d10ada9ace97067362092ca6c1b052e261f47acfdc7cea901a7406194c4、verification-r2.json ce3b0e53d6dfdc1bb868aa3d5278f6106eb5dc9250bafe28b843ca67dec4b749。r1証拠は旧版として保存。r2独立再review未了、T24未完了。

### T24 r3/T17完了・T10着手（impl29）

- T24 r2独立reviewの残重要1: root independently gone＋保存verified childの既cleanupを、追加listener guardが拒否していた。r3はlive rootを既guard、unknown拒否を維持し、independently goneだけ保存birth cohortを再照合してlistener外部所有を拒否後、既stop_ownedへ渡す。実root gone/child生存cleanup正例＋foreign/inspection unknownの無停止負例を追加し15tests成功。28boundfiles、bundle-r3/manifest SHA70082a1d48a97dfc2cece99eb03c624789a3f89953bd9ab4567f445c6848a889、verification-r3 SHA896d75b52076cfa8e29f8fbe8ac58cb7c8581167d2a29ca86983d7351db90e00。独立再review未了、T24未完了。
- T17 r2はWindows host span-provider scopeで完了、独立review重要0/Main受理。6files=native/io/{CMakeLists.txt,span_provider.hpp,span_provider.cpp}、tests/io/{span_fixture.cpp,provider-contract.json,build_verify.py}。standalone MSVC C++17 /MT、177assertions/9rawoutputs byte一致/54bindings前後一致を独立再実行。manifest a52f284f6cba7f8d84ec6912f7ff8691342809ce26ef5d0423ba34777e092620、exe2ca2fddfda6d9054fbffdce31a75a8c68d56f143921a9023ea4f167b96980f92、proof14f26fc86348a2c444bea7e31093f58f19e5ab2a8a6bf26b795ec9616d84aba4。
- T17はDirect/Buffered/boundedMap×Unicode synthetic/T03小窓、23span cursor、T16 opaque hostlease2cycles、issued cancel/drain/late epoch抑止と次要求、wake/control/unknown/short/error/quarantineを検証。r1の合法credit4096<maxchunk8192で未発行になる重要1をRED保持し、free creditのaligned floorへ発行分割してoffset0/13の8KiBが有限進行・exactへ是正。構成拒否や通常gate追加で回避しない。9binding/output負例成功。
- T17実error後fallback強制/GPU/model供給/T11atomicset/T18は未実施。fixture buffers8192B/peak8192B、mappedwindow40960B等は通常context/output/cache上限ではない。allocator/DirectFile内部/OS physical-cacheはunknown。生成5,464,897B/105filesはr1/失敗/独立証拠を含む実保持量、free542,112,948,224BはT05並行時点値で再減算しない。
- T10承認6filesのoffline code/fixture準備を着手し、未実装sourceでCMake REDをbuild-deepseek-t10/tdd-red.logへ保存。固定config3311B/SHA8be45ce0476004a3f529fd896115a4a2e800a129ad2d3ec05b16050f52e21879をreference-config.jsonへ保存。T05全量依存は未充足、T10未完了。T27は環境担当がread-only pre調査中。

### T24限定完了・最新現在地（impl30）

- T24 r3独立review重要0・Main受理。独立--verify-onlyの15tests/28boundfiles一致、manifest70082a1d.../proof896d75b5...前後不変、重要R1–4解消を確認した。固定source5: owner_adapter.py EF9A8A8DCAE1D00BA3AC84568A2D984A41E2CF3F8B10C0BD1C89E2A605B36D11、bootstrap_binding.py 356F508F7399E385419FF6F5671A9209E10924183E21201A4CFDCCD32E8A1075、test_owner_adapter.py 0C86D6D9DEEECA1483BD6C748709352946C520D933C611C0E578A6FCDE23AD3D、owned_child.py 48098A10479932CA1F0D2408C0967FA406F9A7D1CE45057CED01FC45EEDFC64D、verify_owner.py A3F5A8C791E54C918E06B3B298825704ACB219DBF1AA7E871FFF4C0377D73028。完了はhost fixture/純粋binding/既owner helper委譲まで。実official DeepSeek/start retry/HTTP READY/通常CLI/native producer/fullmodel/GPUは未資格、T29/T30/T33等で統合する。
- T17は上記r2限定完了、T27はread-only pre調査中。T10はoffline code/fixture準備中・T05完了依存未充足。03:00JST前後のT05 committed shard2=34,091,302,912B、shard8=21,474,836,480Bはpartialで全LFS未確定。2session/固定sourceを維持し、全9full receipt未了。

### T10 offline固定版・T27着手（impl31）

- T10承認6files: OWN/models/deepseek41/{artifact.hpp,artifact.cpp,reference-config.json}、OWN/tests/model_artifact/{CMakeLists.txt,artifact_fixture.cpp,build_verify.py}。native metadata/25×40+compress11+index24+Engram4+top4=1043の実name/shape/native type/rowbytes/spanを固定configと照合。TensorSpan原rank/原file絶対offsetを保ち、Sliceに別のexpert/head物理範囲を返す。T08のstrict SHA-bound prefix caller条件を再確認し、全source取得済みとは扱わない。
- offline r1は実MSVC C++17 /MTの3compile+link成功（build.log保存）。407assertions、全1043索引のT03一致、独立Python式の240expert端点（0/383）と96Engram head端点、4binding負例/45boundfiles/前後compiled bindingを確認。未知family/Qwen PLE/shape/layout67・117/集合欠落・重複/範囲/overflow/tokenizer差を拒否する。joyai-llm/pad1と公式/Engram pad2は別metadataで、tokenizer互換はnull/未資格。DSpark共有・独立draft/vision対応は未資格で恒久欠如にしない。
- fixed6hash: artifact.hpp a5a108d8d4daa44376df6a8842e39d08ca9b9e012bf0a663e7e1aca01f427ab0、artifact.cpp47002a20800423415fa604d541831d15de5ab9e6fd40d399de2229e07ce2bc74、config8be45ce0476004a3f529fd896115a4a2e800a129ad2d3ec05b16050f52e21879、CMakefcb86ebd2c8539f4f70383a5b9b18cd9c3e53d44a662dc2d6fde565d828b081f、fixturec521e27d7a7a86d13312a1c42eaeb924eab49127b96152b2d7984086998a4fa0、runner8b2d19c92df52b0962c814c2e1bfe47bfa0de28579f2e789ff8317ec4b1dd601。build-deepseek-t10/bundle-offline-r5 manifest18d68332b59ae1e724daac877b9c54f056d0e06bdee72ae433768a200543dc97/exe15de85f369f5450d9d140c1eadd3dcfb0c6344721f3d07f5ac5a23e042b91548/proof851d82723516273ab3721206d37cc346380f19549f5845a0ca68c18c12ce797b。独立review中・T10未完了。
- 明示full qualification経路はT05実receipt検査→実全9原file索引/同TSV→receipt再検査が必須で、現在receipt欠落による拒否を確認した。offline proofはfull_source_qualified=false。全LFS/実fullsource/T10完了の代用にせず、通常start全hash gateも追加しない。固定公式HF configの同revision LICENSE1084B/SHAf2c6c602815669d292889e5be8c802f2ed950653b77999b1584e8e6aed25d040を生成bundleへ保存し、compiled Strata/ggml noticeも保持。
- T27はpre v1＋追補重要0/Main GOで環境担当がtests/codec3files＋task-local buildを着手。公式固定Recipe0.2.0 Pythonbinding無改変Windowswheelの全API維持、通常機能削減0。実build/API/独立review未了、server/inference資格別。Main03:02時点のT05残430,601,024,080B＋metadata差引余裕104,247,152,048B、T27 envelope20GiB込み82,772,315,568Bは工程見積（通常headroomではない）。

### T10 offline r2独立review済み（impl32、task未完了）

- offline r1の独立重要2件を是正: R1は原source path/sizeをnative索引へ保持しておらず、SourceSet9files＋SourceTensor{source,span}を追加。固定shard/path/計画size/revision/LFS identityとspan上限を一度照合し、expert/Engram Sliceが同sourceへ戻る。offlineでは候補path/expected sizeで未資格、T05実receipt/原file照合後に実source qualificationとする。wrong source size/revision/LFS/path/shard/missing6負例、同source2正例、source上限負例を追加した。R2はdisk manifestの固定前後SHAとproof内manifest/aggregate/exe hash、生成copy manifest改変拒否を追加。
- r2（bundle-offline-r7）の独立--verify-onlyで416assertions/全1043source spans/240expert・96head端点/5binding負例/47boundfiles成功、未解決重要指摘0。manifest0fc437f4a842a57104edc3b1211cf6e3f1ea9075b0cb248ad7de9130306c54db、exeeb86680cf39c7c31416f9ef93a6c77f34bfcf535ec5571360aee4c9cd8500b2b、proof3cc0131caa7bfa4b230f537e33429270bb8c00f4f4d0d3cdc31a6884800ffaaa、aggregatea247fb76e2f5e9abfca000e6b4ff7a03c0e1b1329509578e079e4c571b8ecb42。
- fixed6hash: artifact.hpp5487d4ca211a8ca707c95aa3af18244a89bdbd92fb5112748b1ca7578da6562d、artifact.cppc64609d7e520dc237645a5d526a00d6e9f4e3d40ec82cee0da73c2efb9a38f77、reference-config8be45ce0...不変、CMakefcb86ebd...不変、fixture97f40e7db6a58de63b095a343ffd3ff6c871848f4fcff39ef899731bcbff8851、runnerdf97cc4e5f3723e4b8f920a53899b188bd0aeab36d524904d2449c31d8b1517b。旧r1は当時版証拠で、現在のoffline重要0はr2。
- 独立--qualify-fullも実T05receipt欠落を拒否し、full_source_qualified=false。全9LFS/fullreceipt後の原source実行/最新版reviewを残し、T10 task未完了。T11はMain指示のread-only pre調査中（追加raw取得/抽出/コード0）、完了依存は維持。

### T11 offline着手/T05・T27現在地（impl33）

- T11 pre r1＋A discovery/B holdoutの計2BF16入力、text/vlの計4route補足が独立重要0/Main GO。承認9files=OWN/models/deepseek41/{ffn.hpp,ffn.hip}、OWN/tests/ffn/{CMakeLists.txt,ffn_fixture.cpp,reference.py,contract.json,acquire_fixtures.py,fixture-receipts.json,build_verify.py}。追加rawはDATA/records/deepseek-v41/t11-20261021/weights、生成build-deepseek-t11。通常設定/新registry/既固定source変更0。T05→T10full→T11完了依存は維持する。
- 独立Q helper TDD5件NameError RED→6CPUtests GREEN。BF16/FP8 tie・zero scale105・shape/nonfinite・unbiased bias・localreceipt変造拒否の限定scope。公式固定model.py e5decd76.../kernel.py1236c350...の式/cast/丸めと独立Decimal100小Ntraceをcontractへ先行記録。全stage期待manifestは準備中でG前に固定し、Gコード/実行/全数値/atomicset検証はまだ未了。
- finalized shard9からrouter/b/b_vl/shared45,468,672Bをlocal抽出し、Q learnedrouteはA [103,99,229,249,146,347]、B [54,129,177,227,38,92]（VLで順序変化）。本当のunion12 expertをfinalized shard2から抽出し、合計271,076,352B/42fixtures、receipt SHA3c41beee0d550b53249edda773674898c1a99a57b5066252931e6f8047054076。最大496,684,032Bは見積、実取得量と分ける。source currentfileID/stat/header/取得時全LFS checkpoint/rangesと原tensor span・slot・rawSHAをbindし、part/HTTP/新worker/全量copy0。全9source qualificationはfalse。fixtureの12/24expertやraw512MiBを通常model制限へ昇格しない。
- T05 master89094はshard2を03:17:26JST全48,129,640,000B commit後、固定LFS一致時のみrenameする経路でshard3へ進行。final2のfileID7318349395372031/mtime1792520246691901900、fullprefixSHA17df217d8fc26a39f21ea40805dc6ab788c7ce8623a59a95c431051df7eafc94/180ranges/part・lock無し、固定source9a08c847...一致を確認しMain受理。追加48GB再hashは要求/実行せず、取得時running SHA＋制御経路/currentidentityの証拠（最終T05receipt既検査は維持）。個別final1/2/9、active3/8、全9未完了。
- 03:18:12 fresh free507,750,727,680B/既model保持93,101,825,773B/残407,605,750,800B/T11dev2GiB＋raw512MiB＋metadata差引余裕97,443,845,104B。既T27増分はfreeへ算入済で二重控除しない。将来全容量保証/通常headroomではない。
- T27 OpenCV501compile/installは成功、既AMDlibclang24＋locked opencv0.93.7 binding109errorsでPythonbinding compile失敗。Mainがtask-local公式LLVM補完を承認。18.1.8は固定MSVC14.44 STLがclang<19をSTL1000拒否するsource根拠により未使用0B候補として撤回（unused partialは所有確認後cleanup済）。現在19.1.7 tar845,236,708Bの必要component限定取得/展開へ是正、既20GiB工程envelope内。19適合原因/修正は実build成功まで仮説、T27未完了。Recipe/Python/OpenCV/Cargo.lock/STLguard/共有設定/通常APIは変更0。

### T11 offline固定r1・T27/T05現在地（impl34）

- T11の全stage独立Q期待manifest SHA c5bc2d246e1a76fb45ecf2dadc942267f849421198db49491f875be1d183ad2eをG前に固定。2BF16入力族A/B（B holdout）×text/vl、batch1/2/4/8の10jobs。nativeは固定T09 packed projectionへHIP router/cast/act-QDQ/SwiGLU/route/combineを追加し、stage code/ID/最終BF16はexact、scores/Siluだけ事前固定2ULP。公式全N→Q品質/T42とは別scope。T11 APIは任意positive batchをprimitive8/4/2/1へ分割し、fixture値を通常capへ昇格しない。
- 両arch compile/link成功後、初回identityのmissing rocm_kpack.dllをtask-local closureへ補完（失敗証拠保存、数値期待不変）。bundle-r2 manifest31c58e95a90fe4616a125f2896b1b6da28b4c174e33308033e024824c8a44da2、EXEdfad04fa483db1ac74d7304f0e7df2b2b6174f67328ae04bcd82b689d686132f。Main GO/直前CLI停止確認後のprimary PCI0000:07:00.0 gfx1201実試験は10jobs/13,805,888 stage値一致、stderr空、前後binding一致。元GPU proof9fcba1b292471e98bc42001f86dd84a73972fe9febf49510044c79390522da21。secondary/実engine stream lifetime/全model/全source qualification未実施。
- 保存済binary/入力/出力を変更せず、wrapperだけCPU再検証を追加。元capture runner c0d6b251...と現revalidator055299a9528c875b42ae11be078e4ac5d0926c27c79a0da3d757d36b80f2876fを分離し、primary-revalidation-manifest SHA967856b435346abe504eb659e84d630a30f0d6e66e25b49725e1437445e6023bへ現wrapper/元manifest/元proof/全savedoutputを試験前固定。CPU --verify-onlyで同10jobs/全値再比較、N→Q小literal4、output負例5、observed型・unknown・source span/bytes・manifest改変10負例、route-after-cast/double-route/skip-down-QDQの実fixture露見を確認。再検証proof f92c5ff977b82c2d522f5094cef17a3863751b1472c9a91c4a6573dca8143de2、GPU再実行0。独立review中でT11未完了。
- T34会計: T09 primitiveのraw/input/output成功割当最大12,771,328Bと、T11 helperの同時scratch実測491,520Bを区別。helperは同期copy後returnのRAIIで全scratch解放し、その後projectionが開始、projectionもreturn前にbuffer解放するためdeviceの両scopeは非重複でexplicit peakはmax。audit trace/他live host vectorsを含まないhost matrix scopeは部分下限で、full host peak/allocator/context/driver physicalはunknown（0ではない）。source→role/expert→原絶対span→primitive→T34 bytesを各atomic.tsvで固定receiptと再照合。
- fixed9source SHA: ffn.hpp FCC94A93A5788C77DCDDFC13523CFA0AFE4983B88FC86CC82C13DB1D356B16B9、ffn.hip AB4D05863B4E0EEFC4085FDF40B7C0775606FAF2CE1BA85F741BF63E89F9D50F、CMake08FED10B1DC4C7D483DF04B86BA996751C9D2AEA212322C3731A0E1A1204AC95、fixture1EAEEA5A795830ACD570AC1458B907DBD747BA4F0DE99A2BB027631591CDD49E、referenceF2D848E5F5DBF8785FD7310328E5063ABC3934625A85C2886E5C1678F919F205、contract49A98970A2AE6F726D6F6EF371C0E9D16432A6C088A14B909A5FFD0A757AB5A9、acquire2EE15FF6903ABC3F1B823BDDD808BA9E24EE81AA40DD6F734D013AA44CEDBF79、receipt3C41BEEE0D550B53249EDDA773674898C1A99A57B5066252931E6F8047054076、runner055299A9528C875B42AE11BE078E4AC5D0926C27C79A0DA3D757D36B80F2876F。
- T27はLLVM19でもClang Drop 0xc0000005が再現し、独立pre v2重要0/Main承認のupstream501fb53 generator.rs build-only backport1（20追加2削除）をtask-local依存へ適用。CRLF適用失敗→未適用build失敗も保存、適用順序是正後Rust compile成功。OpenCV同版WITH_OPENCL ONで公開APIの未定義symbolを補完し、公式Recipe/Python/lock/STL guard/通常APIは変更0。Windows repaired wheel11,739,737B/SHA6f1fd01f3296c7b1c86074e160d6992f593b9328773be1b8a8ec218723286ae6、fresh import/owned35/公式48/5binding負例が成功した固定r1を独立review中。CPU子processだけPYTHONUTF8=1/OPENCV_OPENCL_RUNTIME=disabled、通常設定へ反映0。実推論/tokenizer native結合/画像推論は未資格、T27未完了。
- T05固定source/最大2fileを維持。03:43:51JST master89094 shard3 committed19,327,352,832/48,129,640,000B、03:44:17 worker91964 shard8 committed55,834,574,848/202,758,032,592B、両running/エラー出力0。これらpartialは全LFS未確定、個別final1/2/9のみ。全9receipt→T10実source資格→T11完了依存は維持し、synthetic/offline結果を実全source証拠へ昇格しない。

### T27限定完了・T12 read-only pre（impl35）

- T27 r1は独立review重要0/Main受理でWindows公式CPUcodec scope完了。最小Windows PATH（build PATH除外）のfresh childでowned35assertions＋公式48tests（skipped0）独立成功、1772bindings/installed OpenCV3DLL SHA前後一致、Recipe114Gitblob/Cargo332archive/承認build-only patch1/Clang19/OpenCL exports/CRT MDを独立確認。manifest d8f4ccdc0f1379b8e7648f224f7483fc970d348eac8f2c970a46bc09baf93450、proof9a185fd2c05ea6b8c0cb08668c066b8bdc3ff1d3a7748fd747827dea2e1a5980、negative035b19477d141dde67a7ee7edb0f216a07e53f7638fc002c7b189bfbeec81ae4。生成4,963,111,952Bはreview前時点実保持量でfreeへ既算入済。旧失敗とpatch1は保存、pristine buildとは呼ばない。
- 全127741merges/vocab129280とnative元IDの小fixtureを比較、GGUF deepseek_imageとRecipe imageのID129264差/公式notice、48special flag差を区別し、実decoder参照membership1283IDsはtype3/4集合と一致。DSML literal/content、toolcall制御、ThinkingEnd/日本語UTF8split/stopを検証したが、joyai-llmのnative解釈/EOS1消費/全model tokenizer結合/画像推論/T28実producer接続は未資格。公式API/paramsを縮小せず、UTF8/CL disabledはCPUfixture子processのみ。T28入口はtask-local bundle/venv/Scripts/python.exeの公式deepseek_recipe既APIで、元IDを再tokenizeせず渡す。
- T12は公式固定model/kernelを再取得SHA照合し、単一flatten RMS・投影後rsqrt・HC4/Sinkhorn20・staggeredのoffline pre r1を独立計画reviewへ提出。final9由来norm/fn/base/scale計8raw3,973,336Bだけを候補とし、コード/追加raw0。T05全9receipt→T10実source資格→T12完了依存を残す。T11固定r1は独立review中、task未完了。

### T11 r2境界補完/T12着手（impl36）

- T11 r1独立CPU再validationは成功したが、実learned入力はscale114以上/logits[-5.50,4.85]/非tieで、承認済みzero/min-amax/20/tie境界のG検証不足が重要1。r2は同じHIP bf/qdq/router/swiglu kernelへcontrolled runtime入力を通し、G前の独立boundary期待manifest8cfa8a9cd713dd7b48bfbc9e8d570f14b1908e7cbba910061af0701b5a9952daを固定。zero/signedzero/tiny scale105、FP8 midpoint RNE/scale126–127境界、BF16 tie/subnormal、20±ULP/21/80/100/-100、rounded tie/near-tie biasとclampを実G検査した。synthetic境界は実weight資格へ数えない。
- 新bundle-r3 manifest e55290f627eba73bf875a319d92e7086ca89b5ec397b7b77b53f06cd4ed738ee、EXEc38927aba9f5a904a841771bad7ebfc65682d517fc229e6c5ffd58012a829d0a。実行直前CLI停止exit0を再確認しprimary境界11,913値/12stages＋learned10jobs/13,805,888値が事前契約へ一致、stderr空、前後binding成功。primary-r3-verification fa455ecd2eb848bc420aad04f20be29f8c4d6ecfb965d49d21c6627b12d81824、CPU replay revalidationmanifest10278b8ecd9daa615c0551fb6b79a62585270ab869e475149648ee6940bcedf4も成功。元learnedQmanifest c5bc2d24.../reference/contract/raw不変、r1証拠は当時版保存。追加fixture compile typoのREDはboundary-compile-red.logへ保存後訂正。T11独立再review中・task未完了。
- 変更4hash: ffn.hpp4F438C0718DACC4D609CD354840343722E160B49B802F9D032692731FA63153A、ffn.hip374440D1695697DD566DD1870316A0778BEDE31D0B486AC6C0D92303695D428B、fixtureF49266CF3FE7A40261FD71D64E0649360D9CEA89F435C23526DA62235AFE1B1E、runnerD3C1FB8D6C8D445233859E56DA98C7F65FEA750E10C37561231460CFE643E201。他5hashはimpl34から不変。
- T12 pre r1＋precision補足は独立計画review重要0/Main承認。T11修正固定後、承認9files/既final9 bounded8rawのみでoffline準備実装を開始（検証/独立実装review未了）。N/Q期待/各stage閾値/holdoutをG前に固定し、T04 H5120定振幅exactをHC20480一般還元へ流用しない。subblock injectはstaggered境界だけ、実attention/FFN統合はT20。T05→T10full→T12完了依存維持。
- T13 hash/history/gatherとT20 Engram fullforward/T25独立資格の責任を既task記述へ明確化。各layer1/14のKV167,116,800B Q8＋gate81,920B F32とnorm/cast/residualをT20/T25で会計し、T11 primitive12.77MBを流用しない。T20-owned bounded helperをT25 Engram検証前に実装/実G実行する順序で、新task/stage/全T20完了依存は追加しない。T12とT13のsource範囲は別で、既T10/T09だけread-only共通。T12 normをEngramへ無条件流用しない。
- T27最終占有は独立logs/outputを含む36,782files/4,991,089,986B、free457,069,277,184B（T05並行時点snapshot）。proof当時4,963,111,952B/free465,788,047,360Bとは別時点で、既保持をfreshfreeへ二重控除しない。固定source/manifest/proof不変、完了scopeはimpl35のまま。

### T11 r2独立review済・T12/T13着手現在地（impl37）

- T11 r2の未解決重要指摘0。独立CPU --verify-onlyで境界11,913値/12stages＋learned10jobs/13,805,888値を再比較、metadata10/output5負例・3semantic fault露見・2534bound recordsの前後一致に成功。保存runtime入力から独立Qで境界12stageを再導出して全byte一致、FP8 scale/code・tie IDs・BF16 RNE literalも照合した。G境界不足R1解消、独立GPU/build再実行0。impl36時点docsもexact重要0。T11はoffline準備scopeで独立review済み、T05全9receipt→T10実source資格→T11 fullsource reviewまでtask未完了。
- T12はhelper5testsのNameError RED→GREEN、承認final9のみ8raw3,973,336Bをlocal抽出（receipt9f8e62570021845d2c26f4bdb54b6557ec594423241e2866477600ba8cfed5fb）。独立Decimal Nのuniform/asymmetric20roundとRMSzero/tiny/oneのliteralを新Qと再照合後、実H5120/HC4/10jobs＋controlled3casesの全stage期待manifest198c3baa71eb2c10c5960b4322fa4a83891f44835cec443d2914cd620efbfb00をGコード/実行前に固定した。large sigmoidでNumPy exp overflow警告が出たが結果は規定finite0/1（警告履歴保持）、候補Gは期待生成に使用0。native実装/G/実会計/独立実装reviewは未了。fixtureの2blockは学習済blk0係数を再使用する明示staggered境界で実層1資格ではない。
- T13 pre v1＋追補重要0/Main GOで環境担当が9filesのoffline hash/history/gather準備を着手。全tokenmap/prime/hash N→Q一致・96tuple再導出後に96×264B=25,344Bのstrict小HTTP fixtureを取得する承認scope。T10/T27/T03/T12不変更、prefix専用metadata adapter、全T05/T10full完了依存/Engram fullforwardのT20 helper→T25実G責任は維持。T12/T13 GPUの短windowは担当間でready順に調整し、新registry/通常gate/追加承認stageを作らない。
- 03:57:20JST T05 master3 committed29,527,900,160/48,129,640,000B、worker8 committed65,766,686,720/202,758,032,592B、両running/エラー出力0。partialの全LFS未確定、個別final1/2/9・全9receipt未了の状態を維持。

### T12 offline固定r1（impl38、task未完了）

- T12承認9filesの実装と両arch compile/host CPU検証が成功。G前Qmanifest198c3baa71eb2c10c5960b4322fa4a83891f44835cec443d2914cd620efbfb00は不変。HC4/H5120/B1,2,4,8×A/Bholdout、zero/tinyの10jobs（2blockは同blk0学習係数を明示再利用）とcontrolled uniform/asymmetric/large3casesで全20roundのrow/colを記録し、単一HC20480RMS/投影後rsqrt/pre/post/comb[i,j]/epsilon/cast/staggeredを比較する。subblockは事前固定runtime BF16 injection、headもsynthetic collapseで、実attention/FFN/学習済headの資格ではない。
- 環境担当GPU使用0を確認して短windowを調整、直前CLI owned model停止exit0/free429,752,156,160Bを確認後primary gfx1201実13jobs/5,506,648stage値が固定契約へ一致、stderr空/前後binding成功。bundle-r2 manifest2358b4500d93c97c4108abae20a32d6b75525cef0b2373ef5a769ca1b33a4f19、EXEbcb64f9c049c49fe470ffab06da4e733adfa7b4b65c499df287a6a3c3481d612、primary-r2-verification e8ae451150d075bdbe0d25f7c0003ee33c2158b2d912bba00048e7bb7c9de01e。CPU --verify-onlyで全保存stage/2487bound recordsを再比較、observed11/output5負例、10vs20/transpose/staggeredずれ露見を確認。独立実装review中、独立GPU/build未実行、T12 task未完了。
- N/Q小literalのuniform/asymmetric各20roundの係数/全row/colは独立Decimal100＋明示FP32丸めから再構成一致。別N-rms-verification.json probeではRMSzero/tiny/oneのN→Q inv bits一致、zero/tinyの保存G tapもN bits一致（oneはCPU Qのみ、追加GPU0）。一般公式GPU reduction topology同一とは呼ばない。T04 H5120定振幅exactの単純流用0。局所rsqrt事前2ULP、他canonical stage/cast/終端BF16 exactの比較契約をG後変更していない。
- source9hash: mhc.hpp1FD3E184A8848F13A2C0E2568A042193EB82996EF2C72F66298BFD1CE09447C1、mhc.hipCFCECCAAAF92D6E1FD5EE4070FA555EECE899EBA27E91026CD66E8A3318F858C、CMakeBFF9CCC5DFCC6F380FF166829E5F39F93F8EC06C93318EE429CB417639A6D3B6、fixture10CB6F9142383B08A70E46AE50D27490D3715E920A16DB4CC927F6AB47181021、reference7BE934D5E7DDC5BA1ED24CC3E5E7F9C85C0D5D18B14BFF1BFFB34011526F08AB、contract798FF5B10D0696E9A288D47CB7380283133E99C9DB4F55EBB1BAC7D94AD70AE4、acquire40061D4D4DFE2457F73F1FB3110DB8BD6B6C24A47D2D3227CDC3DE9FE9A08552、receipt9F8E62570021845D2C26F4BDB54B6557EC594423241E2866477600BA8CFED5FB、runner830D7D86E767AEDBE7D37F5BC2CBAC57B5B2F584B64E51B01A27B5714AA12C70。
- T34 fn projectionは原SourceTensor/name/path/span/batch→packed/input/outputをatomic.tsvへ保持し固定receipt再導出で照合。B8のdevice primitive2,622,208B、helper scratch1,475,200Bは同期helper return/RAII解放とT09 project return/freeで非重複、explicit peakはmax。host vectors/audit trace/driver/context/allocator peakはunknown。生成4,742files/335,091,402Bはraw3,973,336Bとは別保持、工程generated512MiB内で通常capではない。T09/T10/T11/T13/source/共有ENV変更0。
- T18/T20へのhandoff: 現T09/T11/T12はhost vector同期alloc/upload/readback API、private既kernelのresident device入力/stream公開接点はまだない。後段preで既DeviceArena/ExpertCache/PinnedRing/owner-eventを再利用する最小resident view/stream接点・fill→consumer→last-use/slot-generation・hit時のH2D/read delta等を検証し、host raw cache再呼出しだけをdevice cache資格へ数えない。凍結済sourceは今変更しない。万能executor/複製実装を前提にしない。
- 04:09:45JST T05 master3 committed38,654,705,664/48,129,640,000B、worker8 committed75,698,798,592/202,758,032,592B、両running/エラー出力0。個別final1/2/9だけ、active3/8は全LFS未確定、全9receipt→T10full→T11/T12等完了依存を維持する。

### T12 r1独立review済・現在地（impl39）

- T12 offline r1は独立review重要0・Main受理。独立CPU replayで13jobs/5,506,648値、observed11/output5、2487bindings前後一致。保存runtime入力から独立Q全2308stages再導出して期待全byte一致、Decimal N再構成/RMS3case Q＋保存G zero/tiny2case一致、実receipt validatorへのspan/type/shape/layout等6変造拒否を確認。単一HC20480 RMS→投影後rsqrt/eps区別/Sinkhorn20/comb[i,j]/staggeredと同期scratch寿命もsource照合。独立GPU/build再実行0、impl38固定source/Q/manifest/proof不変。
- T12 task全体はT05全9receipt→T10full→T12fullsource review待ちで未完了。注入2block/合成head/hostwrapperを実attentionFFN/実層1/学習済head/resident engine供給資格にしない。T14はMain指示のread-only offline pre調査へ進むが、code/raw0、実装は独立pre重要0/Main承認後。
- T13は環境担当のNQ全map/定数一致・96raw/両archbuildまで進み、base GgufFileのarray sample64を検出。base/T10を変更せずowned prefix metadata adapter内で既Cursorを用いtokenmap全129280を保持する補完中、実G/独立実装review未了。T18/T20 resident view/既stream API拡張はpre未承認で、凍結済sourceを変更しない。

### T13 r2独立受理・T14着手/T05個別final3（impl40）

- T13 r2のoffline準備scopeは独立review重要0/Main受理、task全体はT05/fullT10依存待ちで未完了。NQ全129280tokenmap/99092count/8multiplier/48prime-offsetと2976hash値、426hostassertions、96distinct実hashedrow25,344B strict HTTP取得とT17 Direct/Buffered/Map三経路全byte一致、17負例を確認。各GPU154requests×256=39424 FP32/BF16値・特殊class＋OOB拒否後次256値が一致、独立GPU/build再実行0。T13 r1のsharedSDK rocm_kpack実load/binding漏れ重要1は、同版181248Bをownedcopyし最小PATH/actual loaded HIP/comgr/kpack3DLL SHAで是正した。kernel/Q/rawと他8source不変、226bindings前後一致。
- 固定manifest7668f669dfd387f4800cce5674ef758f6e3f6a12f1cfce5e3994a92ab32d9872、EXE3db24bad334669894719f6696ff5bddf7f4fc553fa9ed41821e53843b6d93c21、proof8e5eff3296f7c22dff47bf8088ece7a6086fd80c1dff69474a82f63ceb1f28c3。生成251,018,041B/free410,542,985,216BはT05並行snapshot（proof記載251,017,801B/free410,767,384,576Bと時点別）。通常cap/共有設定/driver変更0。全Engram gate/KV/norm/cast/residual forwardはT20-owned boundedhelper先行→T25独立G前NQ/実G、T19cache/T18供給/画像推論も未実施。T11 primitive12.77MBの会計をEngramへ転用しない。
- T14 pre r1＋WindowView/activationFP4精度補足は独立重要0/Main承認、9files=OWN/models/deepseek41/{kv.hpp,kv.hip}・OWN/tests/kv/{CMakeLists.txt,kv_fixture.cpp,reference.py,contract.json,acquire_fixtures.py,fixture-receipts.json,build_verify.py}のoffline準備着手。既final9から13raw22,292,480BをDATA/records/deepseek-v41/t14-20261021/weightsへlocal bounded抽出する承認範囲、新HTTP/part/全量copy0。raw32MiB/generated1GiBは工程見積で通常capではない。全stage期待/holdout/精度をG前固定、prefill129全querychunkとdecode128ring/可視floorを分離、activationE2M1 signedzeroとnative39+0を別契約。T05→T10full→T14完了依存維持、G/独立実装review未了。
- TileLang cast一次来歴: 固定HF inference/requirements.txt98B SHAbe82bcd5775ccf8361ddd22cac53ef7b3b83434697fc3c61c75870450fb9437eはtilelang==0.1.12、inference/config.json1982B SHA2e84f45cf1dac8c7fcbb200e96667d4b913275690668ed496f24c7747207a809はdtype=fp8等を明示。TileLang2d63708c8ad57196051c4636a1167c5453c73a48のcuda_fp8.h/common.h→CUTEalias→CUTLASS submoduleb2dd65dc864e09688245b316ac46c4a6cd07e15c/include/cutlass/float8.h:421（SHA6963b577695eecfb9c0ad1d56fed071b268c16cc247c08a356a7292f3d5ef268）のcvt.rn.satfinite.e4m3x2.f32へ対応。E4M3 scale RNE/finite448飽和をTorch tensor.toのoverflowNaNと混同しない。source閲覧/数値契約の根拠でコード流用0。OCP E2M1 element規則とblock16/E4M3形式全体も区別する。
- T05 master89094は04:22:32JST shard3全48,129,640,000B commit→04:22:55 shard4へ進行。final3はfileID6755399442243727/mtime1792524152758300500、取得checkpoint全LFS0c8065f620a049cb437024c54ff12c314c94603a1cc683f5191be4689d6d6d3b/180ranges/sourceETag一致、part/lock無し/stat前後一致、固定code9a08c847...をread-only確認。追加48GB再hash0、個別final1/2/3/9・active4/8・全9receipt未了。04:23:17fresh free406,317,510,656B/既model192,213,230,893B/残308,494,345,680B/metadata後余裕97,806,387,760B、T14raw32MiB＋gen1GiB後96,699,091,504B見積。既T12/T13保持はfreeへ算入済で再減算せず、通常headroom/全将来保証ではない。取得source/最大2session固定、第三worker0。


### T14 native診断・T18着手/T05取得継続（impl41）

- T14は13raw22,292,480Bをfinal9からlocal抽出し、数値Q manifest4212aef63428a4b29f09875c939304df0ddd6ef75bf63ab31c8e169af0b599e8・append/state期待78ebf8bee2c6abd9278d1eda31b265002469353bbded40949aa4db2926a8a846をG前固定。両archcompile/link、最小PATHでnative state737assertions成功。初回GはWindows0xc0000005で数値資格0、trial1–4/診断EXE r5を保存して原因切分け中。artifact/13raw読込、device count/selectを通過、初回bfGPU buffer確保付近まで局在。memInfoは呼出しが戻っただけでstatus成功は未証明。owned6DLLはSDKとSHA一致、faultはownedamdhip64_7.dll RVA450120。期待/許容差変更0、通常保護迂回0。T05→T10full→T14完了依存維持、独立read-only診断は最終実装reviewの代替ではない。
- T18はpre v2独立重要0/Main承認後、環境担当がquant2/lease2/primary_supply2/tests5の11files＋build-t18のみ実装。borrowed同device/stream/input-output容量/世代/完了lease、既kernel resident接点とexpert38の原file>4GiB経路を対象とする。raw追加0/generated2GiBは工程見積。quant2固定628a10851cbc51effe02b020c6ee37fa2c9396570d62bcce1a8f4dbec4e3f16f/b46db27e41309a6f56b9098fcd7a93ec1b90f99d04881a0bee1a6c47a8583f78をT14でも使用、過去T09/T11/T12等proofの使用版とは区別し、新T18 bundleで影響回帰予定。T17 nonowning span集合へtemporaryを渡したfixture寿命問題を保持へ是正しhost167成功、実Gはdirect12jobs後の別fixture例外/未drain終了を診断・修正中、最終PASS未成立。全T05/fullT10待ち・task未完了。
- T05固定2session継続、04:55:23JST shard4 committed26,038,239,232/48,129,640,000B、04:55:10 shard8 committed110,058,536,960/202,758,032,592B、双方running/error出力0。個別final1/2/3/9・active4/8、全9receipt未成立。04:48:20fresh free367,307,399,168B/既model230,725,330,221B/残269,982,246,352B/metadata16,777,216B後97,308,375,600Bは時点別工程算定で、既保持の再減算/通常headroom化なし。


### T14 offline固定r1・独立review提出（impl42）

- impl41のAV診断中は当時履歴。r5同EXE/同PCI07(currentordinal1)/同DLL/envで、元TMP/TEMPではArtifact前後ともmemInfo status1→firstmalloc AV。TMP/TEMPだけtask-owned build-t14/tmpへ変更すると前後ともmemInfo0・2×163840B malloc/free成功。独立read-onlyで4A/Blog/COMGR blit compile失敗→transfer-manager初期化失敗を照合済み。一般userTMPの根本理由は未確定、child限定TMP/TEMP補完のみで共有環境/通常起動設定変更0（通常bootstrapへの必要性は後段T30で照合）。数値期待/閾値のG後調整0。
- 新G前Qmanifest4212aef63428a4b29f09875c939304df0ddd6ef75bf63ab31c8e169af0b599e8を維持。state期待v1を保持し、実append decode128slot indicesをprefill全query索引とは別に直接検証するv2をG前固定: d500dc7d4d7e5cacdd7ea77f3317640ed0c7a172877fcbe1c4a3b37e4658b40b。native更新/再linkで実EXE SHAも変わるので旧診断EXE byte不変とは呼ばない。
- bundle-r7 manifest a84d61d83bd423766d3baa05e81430a46361498fb6c3545e4756087519815090、EXE2d7933d2446d3a733b436671fa363d5a38dc53fc061dbb018b5c4c64a9418a6b、primary-verification-r1.json 1e670e2f454d23c3e8cb8e5dd61d630875fc765c07af16ed6c34d6f02442c20c、compiled aggregate932b91f6ee2cd381b3fd04d24e6960203feb92a3ffe410c92533d7bb46ea5b6c。primary48jobs/14,497,896値を固定bits/局所2ULPと照合し成功、stderr空。CPU replay同48、native737state assertions/observed8負例/2338bound records前後一致、比較wrapperの欠落/短縮/余分byte/NaN/有限誤値5負例も別CPU記録で拒否。まだ独立実装review中、Mainによるoffline受理前。
- 実shape projection B1/2/4/8×2入力族、period8のactual G projectionを用いるtemporal長1/2/3/127/128/129・複数context、6append replay、16controlled（FP4 scale/RNE/signedzero、FP8 zero/tiny/midpoint、pool tie/large、RMS zero/tiny、RoPE/inverse）を同HIP経路で検証。period8再使用を129個別projection資格とは呼ばず、共有writer/可視floor/partial/group先頭位置とpacked ring/decoded viewを区別。hostwrapper/同期append fixtureまでで実attention/T15index、resident supply/engine stream-lifetime/fullsource/全model未資格。T05→T10full→T14 task完了依存維持。
- 実device primitive peak2,965,504B（packed Q8 matrix2,785,280＋B8 input163,840＋output16,384）、別scratch実peak655,360Bは同期lifetime非重複でmax、単純加算しない。full host allocator/driver/context内部peakはunknown。memInfo前後status0/free34,050,342,912→34,036,973,568/total34,208,743,424Bは別観測。actual loadedHIP/comgr/kpackはbundle-r7の3ownedDLL/SHA一致、最小PATH/childTMP、選択6非secret env keyのみ記録。生成4,831files/1,066,128,407B（旧失敗/診断bundle保存込み、raw22,292,480B別）は1GiB工程見積内。通常context/output/cache capへ昇格0。
- T18は環境担当のprimary1,313,280bits/secondary145,920bits/forcedPAGEABLE primary1,313,280bits機能試験まで到達、最終delta/capacity/実reservation拒否補完とaffected compat回帰中で未受理。共有quant2は受領固定SHA維持、過去task proof版と新T18実bundleを混同しない。T15はT14固定版review中にread-only pre調査へ、code/raw0。
- T05最新05:05:48JST shard4 committed33,285,996,544/48,129,640,000B、05:05:47 shard8 committed117,306,294,272/202,758,032,592B、双方running/error出力0、個別final1/2/3/9・active4/8/全9receipt未成立。

T14 r1固定source SHA（当該review対象版）:
- Strata-extensions\models\deepseek41\kv.hpp: `bca5964d5de6fa13eb0da03c496e9a2f93a5826c2e2dbed188554e8dac6a51b1`
- Strata-extensions\models\deepseek41\kv.hip: `52b9baa083c1572aab416385652777b4ef89e5df66e57c70a99bff1ad17e82f8`
- Strata-extensions\tests\kv\kv_fixture.cpp: `4946f97d3fca16d61a161b4ab3104da43b4e96c30f5cd6074291cf73937fefe0`
- Strata-extensions\tests\kv\CMakeLists.txt: `7d818b06349b348411c257de06c9572a221ed054bb024bb3d24ae21046d48679`
- Strata-extensions\tests\kv\reference.py: `6b7e6cb4ed1994b00fe71336457447be7c522ef36d0f8e6fb8693c8515d31f9a`
- Strata-extensions\tests\kv\contract.json: `4bd5b293bf9a10008ca5f7d8da55ff1fdf9c55d6746fd4cd0bf1fb84b076006f`
- Strata-extensions\tests\kv\acquire_fixtures.py: `47c2945c9613908b8ecbe3e8e1792bb1c03aac725f7c72cacf843b168f0e21c9`
- Strata-extensions\tests\kv\fixture-receipts.json: `5e4b9cd823b9d763aa1096dddd4caebfaa2d51345e976919b9d5d24a1f962864`
- Strata-extensions\tests\kv\build_verify.py: `e009dcae8053874fbf907fd0b1e7143d82b37439418f0356c779cd275018eb85`


### T14 wrapper-only r2独立重要0/Main受理（impl43）

- impl42のreview中は当時履歴。r1独立レビューで全48jobのprimitive/scratchを0へ変造してもvalidatorが受理する実bytes falsePASSを検出。bufferのfixed shape/batch/lengthと同期lifetimeから全peakを再導出し、0/過少/過大/bool/他batchの負例を追加するwrapper-only r2で解消。native/EXE/Q/DLL/input/保存outputs/Gproofは変更せず、追加GPU/build0。full host allocator/driver/context内部peakunknownを0化しない。
- 新validator SHA E03AE0B0B002E60FC52C795F6F11408C4E16D0E8181690D523ADEA36C0B8074C、primary-cpu-validation-r2.json SHA8F99ACDA7A5FB55B5217450570D2B0E7FA77C5401BAA6F9DAB26E960778400B8。原capture-runner-r1.py e009dcae8053874fbf907fd0b1e7143d82b37439418f0356c779cd275018eb85は原manifestのrecipeと全byte一致するsnapshotで別保持し、原EXEを新validatorでbuildしたとは扱わない。原bundle-r7 a84d61d8…/EXE2d7933d2…/Gproof1e670e2f…を新CPUproofがSHAでbindし、原runner行以外の全bound fileも前後照合する。
- 独立CPU replay48jobs/14,497,896値/observed17負例成功、元all48peak0変造の拒否と追加4kind×scratch0/bool/負値12probe拒否を確認。独立原source審査とQ全2126stage再導出・Decimal N/receipt6変造拒否・比較5負例・native737stateも成功、独立GPU/build0。未解決重要指摘0、Mainの現5hash照合後offline準備scope受理。T05→T10full→T14 task完了依存は未充足のまま、実attention/index/resident/fullsource未資格。
- T14初回TMP条件差は後段既T30の実効env検証へ引継ぎ、通常CLI/公式bootstrapの既logs/tmp/childTEMP継承と、HIP初期化より前に実child TMP/TEMPが反映された事実を確認する。今回fixture専用pathを通常固定path/新起動条件へ昇格せず、一般userTemp根本原因未確定は維持。新task/手順は増やさない。


### T15 offline準備着手・T05取得継続（impl44）

- T15 pre r1＋indexer4096側wq_b FP8activationQDQ・圧縮層共通YaRN補足は独立重要0/Main GO。9files=OWN/models/deepseek41/{attention.hpp,attention.hip}とOWN/tests/attention/{CMakeLists.txt,attention_fixture.cpp,reference.py,contract.json,acquire_fixtures.py,fixture-receipts.json,build_verify.py}、生成build-t15、既個別SHA確定final9だけから28raw293,415,424BをDATA/records/deepseek-v41/t15-20261021/weightsへlocal抽出済。receipt b33a46c02c41fd03e19dc5b8b5d6cd7bce3bd0a54341dfea5984d1293c26a147。HTTP/part/全量copy0、T14 fixed source/原raw不変更。
- rawはlayer2/20 fullattention各8weights、indexer2/20各4weights・indexer24のproj/q_bとlayer24 q_a/norm。short learned実shapeと別controlledlong visible16383/16384/16385を分離、index32×128とattention64×512/group8、source20 ratio1/candidate2048blocks×8/top512位置順、online64 probBF16/sink分母、FP4indexblock32 UE8M0とcompressedblock16 E4M3を区別する。layer2/20/24のquery/SWA/inverseには圧縮層共通theta160000/YaRNを使い、pureSWA layer0のT14 ratio0を流用しない。全N/Q/精度/holdout/実lifetime peak期待は新G前固定、通常候補/context/output cap変更0、T05→T10full→T15完了依存維持。
- 現在は8test RED→CPUhelper8 GREEN（candidate最新partialblock/visibility、strict roundedtie selection、FP4minscale/signzero、online sink/all-1、indexcast/norm）のみ。candidate maskは最新visible末尾を含むblock全体をkeepし、causal visibilityは別適用する。全stage期待manifest/native/G/実会計は未了、CPUhelperを実operator/task完了へ昇格しない。
- 05:18:30fresh free320,561,938,432B/残model224,935,421,392B/metadata16,777,216B、T18将来残268,435,456BとT15新raw293,415,424B＋生成2GiBを単回控除後92,900,405,296B見積。既T18/T14等保持はfreshfreeへ算入済で再減算0、raw384MiB/gen2GiBは工程見積で通常上限/全将来保証ではない。T05最新05:20:05 shard4 committed44,560,285,696B、05:20:24 shard8 committed128,580,583,424B、両running/error出力0・全9receipt未成立。


### 現在地の短更新（impl45）

- T15はpre重要0/MainGOの既9file範囲。raw28/293,415,424Bのreceipt不変、CPUhelperは当時8から独立Decimal Nのindex cast/online2block照合を加えて現在10tests成功。actual28weightの独立Q projectionとshort L1の98stage/484,112値をCPU上で生成する開発検査まで到達。全stage期待manifest/精度・holdout・実lifetimepeakのG前固定、native/build/実G/独立実装reviewは未了。helper/部分Qの成功をtask完了へ繰上げない。
- T18は既serial G機能証拠の後、空slotよりvalidslotを先evictし得る不具合/2slot distinct保持hit検査不足と、別weight fill/DMAがconsumerから未分離のpre未達を検出。同11file内で空slot優先・distinct2units交互hit・fill状態とsingleconsumer input/output/lastuseの最小分離を修正中。既stream/event/lease/providerを再利用、1slot defer有限進行/newbroker無し。quant2は受領版不変更、既serial証拠を通常asyncpipeline資格へ繰上げず未受理/taskpendingを維持。過去の1,313,280/145,920等はFP32値のbit一致比較件数。
- T05 master89094はfinal4後shard5へ進行（05:27:40JST committed2,684,354,560B）、worker8は05:27:31 committed133,949,292,544B、両running/error出力0。final4現size48,129,640,000B/fileID5348024558690483/mtime1792527878377749300、checkpoint全LFS3bd8b2ebf8f51d8708a73ae0895f8d4acc7e4c983ba4e89d038492b203cc89ac/180ranges/ETag5e34a594…、part/lock無し/stat前後一致・code9a08…不変。固定SHA一致→samevolume rename→return→master5という既code経路と現在観測をMain受理、追加全量再hash0。個別final1/2/3/4/9・active5/8/full9receipt未成立、最多2session/source固定を維持。


### T15初回nativeと修正中の現在地（impl46）

- T15 numerical-QはG前に55jobs/7,515stagesを固定（manifest a4087bd5cd683a5d6f552bd84220bb3ef8489382363e1602abdaa085f3b86cfe）。Decimal Nの4小trace、actualweightのprojection/shortと27controlled・6longを区別し、masked −inf/all-invalid denominator +infの期待位置を固定。期待本体660,585,716B、入力259,489,152B。実allocation/lifetime期待もG前固定し会計68/出力12負例を拒否、CPU helper10成功。
- 初回bundle-r1 da0fdefa…/EXE2a4e444c…は両arch compile、host9、native55jobs exit0/stderr空まで実行したが、CPU比較でsource2の候補maskをsource20 pruningと共用した不一致を検出し資格FAIL。原source snapshot/manifest/EXE/全出力/診断を保持、Q/閾値変更0。初回全保存の他184,303,992値・実会計は一致した観測であり、全job合格には数えない。
- key_writer policyを2/8/14=no pruning・20=pruning・未知拒否とする最小引数で是正し、source20 consumerは同owner policyを継承。mask表示だけでなくnative選択母集団に反映。host14へ拡張し、weight scale1/64もnative cast kernel内で演算する。新bundle-r2 manifest90e0f4a668d67bed6ed6247747a97fbf3e572811d33973eb85ee7c4e5ad54f54/EXEab0595dff04a0c5c869d81ed66e359155cedf01d6305d6422501945aeabb112eは両arch/host14成功、再G待ち。実allocation期待/数値Q不変、未review/未受理・task未完了。
- 初回T15/T18の開始通知が交差し短時間重複した。global free/elapsedは他fixture重複の観測で性能資格なし、自前explicit allocationと区別（initial-attempt-context.json）。外部からの破壊的停止/通常consumer/driver/shared変更0。次回は当該windowの譲渡ACK後に開始する既担当調整を維持。
- T18はr3の空slot/別slot並行是正後、独立reviewでReady→launch間のselectedweight lease不足R1を検出し、r4 demandReady borrow→launch移管/Ready cancel解放と実fixtureを修正・再検証中。未受理、quant2/lease2/Qは受領固定版不変。最新保持1,944,244,408Bはfreshfreeへ算入済、将来残64MiBは工程見積で通常上限ではない。
- T05最新05:55:15JSTはmaster5 committed24,427,626,496B、worker8 committed154,887,258,112B、両running/error0。個別final1/2/3/4/9・active5/8・全9receipt未成立。05:51:58fresh free265,898,725,376B、残model172,831,678,352B＋metadata控除後93,050,269,808B（既保持二重減算0、全将来保証ではない）。


### T15 offline固定実装r1（impl47、独立review中）

- 初回mask不一致をkey_writer契約（2/8/14非prune・20prune、consumer24はowner20継承）と選択母集団で是正。数値Q a4087bd5…/全allocation期待/閾値は不変。初回失敗bundle/source snapshot/全出力を保持し、r2は未G候補、r3は独立replay入口とDeepSeek/AMD等license束を含む実build recipeで再固定。native演算sourceはr2/r3同じでも再link EXE byteは別とする。
- bundle-r3 manifest017c5dfcbefedeef5990cb0adf557e13bfd2668d9608764c8490acbc3b843b0d、EXE52bb1e3a2dc931cb2295ca263ff43a042ca73ff59999bd8d534775bc0e579ae3、primary-verification-r3.json237902259d4cb2b7ee9a147cab1bc3f1da647a60967c962009f802a5690d6e50。primary PCI0000:07:00.0/ordinal1/gfx1201で55jobs/184,304,150stage値が全比較成功、exit0/stderr空。当回T18譲渡ACK後、直前CLI停止済みを確認して実行し重複なし。actual3owned HIP/comgr/kpack DLL path/SHA、選択6runtime env key、manifest前後一致・compiled identityをbind。
- realweight projection B1/2/4/8×2族、short L1/2/3/8と複数context（period8の再使用を明示）、27controlled、long16383/16384/16385×2合成族。source2/20のactualattention/index、consumer24のown query/weights＋source20候補/keys、FP8/FP4/RMS/RoPE/cast/tie/mask、online64/sink/all-invalid/inverse/groupA/outBまでの同期host-wrapper準備資格。longのdecodedpayload/controlled queryは合成で、学習長文全経路/全layer/実engine/resident/非同期供給/全N→Q品質を合格にしない。
- CPU --verify-onlyを保存出力から再実行し同55jobs/184,304,150値成功（GPU再実行0）。host14assertions、会計68拒否＋出力12拒否。explicit primitive最大45,654,016B・scratch最大35,896,320Bは同期非重複lifetimeのmaxで、各jobの事前純粋式と全observedを比較。full host/driver/context peakunknownを0へ丸めない。compiled3/dependency24/recipe6/input7759/tool8/bundle12/DLLsource6のbinding群。実装9fileの固定SHAはbuild-t15/fixed-review-handoff.json、独立review未了・Main受理前。
- 全T05→T10full→T15完了依存を維持しtask未完了。通常context/output/retry/candidate cap変更0、新registry/起動gate0。T14 frozen source不変更、T18 quant2受領固定SHAを使用し過去task proof版と区別。生成保持は下記snapshotの通りで初期gen2GiBは工程見積、失敗証拠を削除してcapへ合わせない。
- build-t15現在保持2,842,771,238B/22,958files（初回失敗/未G候補/現r3/比較記録を含む、freshfreeへ算入済）。05:56:12時点はfree258,724,610,048B−残model/metadata166,511,910,800B−T15将来768MiB−T18将来64MiB=91,340,284,016Bの工程見積。T18その後の将来残は32MiBへ更新、既保持二重控除0・全将来保証ではない。
- T18 r4はReady→launch lease修正後primary/PAGEABLE各1,336,320値・secondary145,920値exact、8pipeline/96cycles、CPU109checks=108拒否＋1正常captureまでで独立再review/Main受理待ち。保持1,986,044,618Bと将来32MiBは時点工程記録、task全体はT05/fullT10待ち。T05最新05:59:03 master5 committed27,380,416,512B、05:59:16 worker8 committed157,840,048,128B、両running/error0・個別final1/2/3/4/9と全9receipt未了を維持。

### T15 R1修正版とT18受理の現在地（impl48）

- T15 r1独立reviewは元55jobs/184,304,150値・N4trace/CPU10/28rawと6変造拒否等を確認した一方、SWA prefill length129/query128が先頭0..127を誤選択するR1を指摘。共通prefill helperをqueryごとのmax(r−127,0)から生成する形へ是正し、通常length cap追加0。新G前boundary-Q1fa760ffb9c3f157491987a013af11403d010ed31f67afa92e5bde53b05cc7f9で127/128/129の全query indices/causal maskと最終query actualonlineを固定。行0=.125/行128=1.5等の非周期KVで誤窓が数値にも露見し、元8周期で隠さない。元Q55jobs a4087bd5…/全数値期待/閾値/reference.py/contractは不変、旧r3 sourceはattempt-r3-source/mapping.jsonで保存。
- 新native bundle-r4 manifest014225eb6de04935140a8a4f112e940dd1f619cc47770d8f692f4f7c5ca96a0f / EXE8790bea83cd9d265e29c521238701769bc09043bff8b5262cbf949c391bf598fでprimary58jobs/184,772,313値・全indices/mask/最終onlineが比較成功、native exit0/stderr空。直前CLI停止済み・当回T18譲渡ACK後に実行、重複なし。host14/actual3ownedDLL/選択6env/原input/Q/source束縛を保持。
- r4 wrapperはprefill127のindex countを128と誤記し、期待885,760B対実885,752Bの8B差で全資格判定FAIL。固定形状とMemory lifetimeからI=min(L,128)へ純粋再導出するCPU-only修正を施した。原allocation f38ee5cf…と原capture-runner-r4.py SHA3cd257fba88fa27f14ff9e5a6ccd76859e84a61484616533323793b8a65e3290は原native manifest recipeに一致して保持、新validator c1c0045ba07d18950622893ea1bf43b706da2bbdc645296dfbb76ce2f7bcaa69は別binding（新validatorで旧EXEをbuildしたとは表示しない）。native/source/EXE/input/Q/DLL/保存全出力は不変更、追加GPU/build0。
- 新allocation-expectations-cpu-r5.json2d1247c9e995b62769f56e6ca9d87c322db309e33cb2b26d4b1aca1cbb2872e2とprimary-cpu-validation-r5.json43c62fffa431ddff43d452f686f6ba9cfce35cbcb1008a2a04fa6d4b63286437を固定。CPU --verify-onlyで58jobs/184,772,313値・76会計拒否/12出力拒否・原capture/newvalidator/前後manifest一致を再確認。R1修正版の独立再review待ち、Main受理前、全T05/fullT10依存/task未完了。9file最新版hashはbuild-t15/fixed-review-handoff-r2.json、原Gのsource/recipeと現validatorの役割を区別する。
- T18 r4は独立最終重要0/Main offline受理。manifest546e1848…/EXEf5d2a669…/verificationc7fb777e…、host167/>4GiB6266880B、primary/PAGEABLE各1,336,320・secondary145,920値exact、96cycles/8pipeline、CPU109checks=108拒否＋1正常capture。Readyからresident leaseを保持しlaunchへ移管/Ready cancel解放へ是正、非選択slot prefetchを維持。affectedcompat集約1c591ea6…は別固定証拠。全T18taskはfullT05/T10待ち、T19/20/21実供給結合未資格。旧104checksも103拒否＋1正常であり104負例とはしない。
- T19はpre v2独立重要0/Main GOで環境担当がrow_supply2＋tests5のみoffline実装着手、既T13/16/17/18/T10 source不変更/raw追加0。issue_readsだけ新read可/pollはread0/stable sharedfillとwaiter寿命/Ready lease/有限wave、低層joint公平I/Oまでで、T20 realowner coordinator結合は未了。T20はread-only pre調査のみ、現PrimarySupply.advance()の無条件issueをfairness grantが迂回しないconsumer-only poll/許可予算付きissue接点を後段preで具体化する。新scheduler/authority/通常gateは追加しない。
- 06:11:37fresh free233,234,046,976B/残model142,699,798,416B＋metadata控除後90,517,471,344B。T15現保持3,654,224,767B/30,683filesはfreeへ算入済（原失敗/全再試験を保持し初期gen2GiBは超過、通常hardcapにはしない）。現phase将来残128MiBへ更新、T18残32MiB/T19新256MiB工程見積を各単回計上、追加G修正ならfresh増分を再算定。T05最大2session固定・個別final1/2/3/4/9・active5/8・全9receipt未成立。

### T15 offline固定r2独立再review結果（impl49）

- 独立再reviewの未解決重要指摘0、R1解消。native014225eb…/EXE8790bea8…/CPUproof43c62fff…/validatorc1c0045b…のexact一致と、保存58jobs/184,772,313値、76会計拒否/12出力拒否を独立CPU replayで確認。独立GPU/build再実行0。
- 新boundary3件/全54stageを独立Qで再導出し全byte一致、127/128/129全queryの正しい窓/causal maskと最終actualonlineを照合。旧129誤窓は32,768出力値が異なり、周期列による偽一致でないことを確認。I=min(L,128)のscratchは127=885,752B/128=887,808B/129=889,856Bで実Memory式と一致。原capture/歴史allocationと現validator/新allocationの別binding、元Q55/閾値不変を確認。
- 成果はoffline準備scopeの独立review重要0まで。fullT05→T10full→T15完了依存は未充足でtask全体未完了、resident/fullcore/全layer/長文品質資格は後段のまま。impl48の再review待ちは当該版時点履歴。T18 offline受理/T19実装着手/T20 read-only preとT05全9receipt未成立の区別を維持。


### T20 preと取得の現在地（impl50）

- T15 offline固定r2はMainが原native manifest/EXEと新CPUproof/validatorの現物hash・独立重要0を確認し受理。全T05→T10full→T15完了依存未充足/task未完了、通常cap/機能縮小0は維持。impl49のMain受理前は当該版履歴。
- T20 pre r2はbuild-deepseek-t20/pre-r2.md SHA9fd3fe263ac16038c9b5f00834c707c0f100318a4743e68260929ef3ceea1ceeで独立review中。25filesの薄いdevice接点/旧host wrapper維持、full-K昇順rowtile、auditoffの任意trace write/D2H分離、collapse→学習済output_norm→head、全40state/activation/scratch/weighttile同時寿命のT34会計を具体化。T19は現在host RowResultのみでdevice-output借用はT20-owned追加、責任/last-use寿命の一点を同pre内で調整中。code/既API変更GOなし、新event registry/通常gateなし。実shared source書込windowはT19担当と直接調整し、T19 fixed build/G/sealのbindingを動かさない。
- T19はpre v2重要0/Main GOの7newfilesで実装中。G前Q manifest cbb1aa1747ed3eca177afea8862528106bba80cc3ef9140a36611f3e7cefb661（96rows/原tuple/SHA/FP32-BF16/手書きcountertrace）を固定しhost/jointIO校正中、実G/独立review未了。単なる期待固定を成功資格に数えない。
- T05 shard5は06:25:01JSTに48,129,640,000B/full LFS929054a6bbf3701765779b58c37988b6c6284a3b8413901858b59c0e95f37cc3/180ranges→samevolume rename→return→master6へ進行を確認しMain受理。final fileID4222124651891482/mtime1792531501056784300はstat前後一致、part/lock無し、固定source不変、追加48GB再hash0。master6最新06:32:24 committed5,905,580,032B、worker8最新06:33:15 committed183,341,416,448B、両running/error0。個別final1/2/3/4/5/9・active6/8・全9receipt未成立、最大2file/source固定を維持。8完了後のworker先はmaster現在位置とfresh snapshotをMainへ渡して判断し、勝手に増設しない。

### T20実装着手・T19受理・T21着手（impl51）

- T20 pre-r4.md SHA0abd2e4f47c9d3a8966067ccbf4dbde1503ab0367985676654afe969d17c5c1eは独立重要0/Main現物確認で25files＋docs/生成6GiB工程見積のoffline準備実装GO。最終output_norm/optional auditwrite、1row borrowed output→Core stream last-use event→完了後cursor進行と、任意newrowのshard-level fullfile lazy resolverを固定。旧14sharedのbefore snapshots/source-map.json0715f6c1…を保存、T19作者の当回shared write譲渡ACK後にAPI接続へ進む。歴史proofを変更後sourceの資格へ流用しない。
- 新owned device_ops/core/engram_forwardとtests/coreから着手。原rank2/3/path/spanを保つfull-K output-row tile、B>1 stride/ragged、全40stateを含む同時lifetime会計、独立Decimal outputnorm/Engram小literalの7CPU testsをRED→GREEN。key振幅不変の追加試験で先行helperのkey RMS欠落がREDとなり、公式model.py e5decd76…359の rstd=rsqrt(mean(h²)+eps)×rsqrt(mean(key²)+eps)へ是正してGREEN。h/key両方はHC別width5120/eps1e-20で、joint20480 RMSと混ぜない。G前N/Q/実traceには両normstageを明示する。同scopeの数学補足を独立reviewerも公式式整合として確認、G後期待修正ではない。
- 初回native dev buildは新Core geometry/Engram helperと旧quantを両arch compile/linkし、GPU未使用のhost28assertions成功。これは初期metadata/compile資格のみ、全stage N/Q/lifetime最終固定・実resident core/全40state接続・影響互換G/実実装reviewは未了。全T05→T10full→T20完了依存を維持しtask全体未完了。通常CLI/出力/context/candidate cap変更0。
- T19 r2は独立最終重要0/Main offline受理。原capture manifest279eeb05…/EXEabdb7de1…/Q8eb4ef63…不変、新validator481a58a7…とCPU proof8b291489…を別bindし、総proof0dd5b4b5cd4ef660f93ab62b77fb9fd74ddf2ba0c0764b06b58105ef01b09788。host878/3path×25344B、primary/secondary/PAGEABLE各62976 FP32/BF16値exact、CPU301拒否＋正常captureとfailed-query unknown。pinned subset R1は実4stage属性から再導出して是正、追加GPU0。96physical fixture rowsと低層jointExpert/Row公平I/Oまでで、actualfullfile8/任意row lazy resolver/Core借用/T20 realowner全結合/Engram fullforwardは未資格。全taskはT05/fullT10待ち。T20へ当回write譲渡済、旧32consumed sourcesはimmutable-source/map7bd95543…にexact保存。
- T21 pre-v1.md SHA f92784536d4f6649c1a8ef09c9acb7d72794bde08aa2033c75a820134dd36f32は独立重要0/Main GOで環境担当7newfiles実装着手。device role/directional transfer fixtureの限定scope、fixtureだけの全byte監査D2Hを通常CopyTaskへ昇格しない。T20 sourceとの競合変更0、実G/独立実装review未了。
- T05最新06:48:29JST master6 committed17,716,740,096B／06:48:25 worker8 committed195,957,882,880B、両running/error0。個別final1/2/3/4/5/9・active6/8・全9receipt未成立、最大2file/fixedcode維持。8確定後はsnapshotとmaster位置をMainへ渡し次worker先判断を待つ。T19実保持150815739Bはfree算入済、将来残32MiBという工程値で通常capではない。

### T20 pre-r5実装・T21受理/T05現在地（impl52）

- T20 pre-r5 SHA52c5714e834f97069abd6c41e22dc58240b066216a9ece64597d0c89c382afa3 は独立重要0/Main GO。lease_queue.hpp/.cpp追加で27files、工程6GiB見積を維持。旧lease2をbefore/lease-source-map.json（SHA9f5a95b2d682fd3b7a5d1d7aa66614615c9e39a794bf1fa5ea399ae40747e0e7）へ保存し、同size/alignのDemandOrderへ順序だけ抽出。成功reserve/正の実readだけturn更新、0候補から次へ・Prefetch後回し・既FIFO/all-or-none/owner責任は維持。新Core coordinatorは実owner outstanding gaugeと累積issued deltaを区別。両arch build/host61はgeometry/順序の開発検証であり、実4KiB credit trace・全40state/activation/scratch同時寿命・実core/G・影響回帰は未了。
- Engram helperのh/key両RMSに加え、sum_h/sum_key/weighted_dotのoptional FP32監査tapを追加（normal audit nullはwrite/D2Hなし）。T25は公式q/k融合根拠と独立N/QをG前に固定して当該helper実Gを資格する。T20開発captureの自動流用やmockを層接続資格にしない。現Coreは薄いdevice接点/rowtile/coordinator段階で、実block/step graph未実装。
- T21 r2は独立重要0/Main offline受理。manifest5663ac9e…/EXE94643a1e…/proof b3e32cbfc7e19326eda539604ec199dc6453ce50c3e91d739d9c6d136a2a2f48。72regular/1,255,770B＋各role control792B、host16/metadata344/661CPU拒否。Ready cancel last-use/event drain、実overlap拒否/隣接合法、未試行statusを是正。peerは両方向canAccess0でenable/copy未試行、local/hostbounce/PAGEABLEのみ資格。通常監査D2H/モデル結合/T22/T44/T45資格へ昇格しない。
- T05 worker8 exit0、202,758,032,592B/LFS12df293355efbd104b088a77e13ee22410fb1ec3f7ab3863947f09896e64bec7・756ranges・同file rename/固定source/stable identity・part/lock無しをMain受理（追加全hash0）。条件付き承認どおり空いた1枠をworker7 session57571へ移し、master89094と最大2/globalreceipt writer1を維持。個別final1/2/3/4/5/8/9、07:22正本pollでactive6 committed42,949,672,960B・7 committed20,132,659,200B、両running/error0。全9SHA/fullreceipt未成立。masterが7lockで安全exitした場合、worker7完了後に既main resumeする。

### T05/T10限定完了・T20実装現在地（impl53）

- T05 worker7は07:46:15に48,129,640,000B/full LFSf18feae5878dd680f1ea87ecd1d84f4fb098480298b25a3162dcbdab8dc2ca5b・180ranges・同file rename・current fileID4503599628672363/mtime1792536375071152200一致でexit0、part/lock無し。元masterは7lockで想定した安全exit、worker7完了後に固定main resume90946を実行しexit0。新worker/追加全量copy/通常startup hash gateは0。
- 全9原本500,707,576,573B/9LFSのreceipt `Strata-extensions/tests/artifact/full-model-receipt.json` SHA34adf6366f6c744eb48fa86b08801891b0278c48de6e7a7adfa2e40fca425b30 を07:51:03生成。固定source9a08c847…/testafc132d3…不変、9header/1043tensor/40trunk/原本6spanを照合。既validatorのstat/header/span読戻し成功。独立側は全9current ID/size/mtime/LFS checkpoint・1873range履歴・part/lock無し/合計bytes、同validator＋7変造拒否を確認し重要0、MainがT05完了を受理。resume既final再資格は既承認mainの処理で、readback/独立reviewに追加2回目payloadhashは無い。
- T10既承認 `--verify-only --qualify-full` を原r7 bundleで実行成功。`build-deepseek-t10/bundle-offline-r7/full-source-verification.json` SHAdb41734a163bf15b30b8051b7c13d2d7602c30412b9cff993354d0ed97395bf8、manifest0fc437f4…/EXEeb86680c…/aggregatea247fb76…不変。別reviewdirでfull=Trueを独立再実行し1043 original source index/416assertions/240expert/96head/5binding拒否、保存proof全field一致で重要0/Main構造scope完了受理。native DTO自体はauthorityを持たず、full資格はcaller wrapper記録。数値/生成/DSpark/vision/通常runtimeは未資格。
- T05/T10成立だけで他offline taskを自動完了にしない。旧固定版とT20変更後sourceを区別し、各残条件・影響回帰・最新独立reviewで判定する。07:52:19 free90,017,832,960B、原本既保持500,707,576,573B/残model増分0、metadata16MiB後90,001,055,744B。既保持はfree算入済み、T20等の将来工程分だけ単回計上する。
- T20は全40層 `CoreSequence::step/prefill` と共通 `run_layers` を使う明示fixture `audit_layers([first,end),raw token,pos,BF16 residual20480,FP32 pre4)` を組立て、両arch build/host68・CPU独立helper8tests、変更DemandOrderを使う既T16 host135assertions/1472Bの影響回帰まで成功。normal prefillの中間logits/trace payload D2Hは行わず、要求した最終又はfull_logitsだけ返す。これらは開発検証でG/全40数値/有限prefill・union実進行・working set/影響GPU回帰・独立実装reviewは未了。4KiB手書きQ traceは原offset5051106880の5000Bに対し(2496,4096),(2504,4096)で固定、実owner照合は未実施。
- T25 pre-v2 SHAe5f0e1df4282840fd7cd64c64454136d2e27ac8cde29e2ed350486108bd66e46は重要0/Main GO。公式q/k計163840Bを含むraw429056B、全40960 gate F32bit bridge一致。helper7tap版を含むimmutable181sourceを短copy windowで固定しT20 live編集と分離。r1 N全式/SourceFiletuple不足を補完したr2事前NQ後、両GPU25jobs各6572448値一致・独立最終review待ち。実[0,2)/[20,25) bounded layer/state NQと実Gは未了、Core全完成を新gateにせず当該ABI/実sourceを同waveで追補する。

### 個別component完了と残条件（impl54）

- T05/T10の完了後、既offline資格を一括昇格せず個別照合した。`build-deepseek-t20/full-source-followup.json` SHA4224968cabadca3e30f7f98a1e1c18a21ed917314e771c1fb67bc290c26b08eb はT11/T12/T14/T15の91span/590757592Bをqualified current9source/T10 indexから再導出し、原shape/type/rowbytes/offset/upperbound・bounded原本SHA・元proof対応を独立確認重要0、Mainが元component scope完了を受理。T13もown3source不変、qualified final8から96row/25344Bのoffset/SHA再照合が独立重要0/Main完了受理。追加全payloadhash/GPU/buildは0。
- T11 atomic12771328Bと別scratch491520Bの同期非重複資格は元componentの証拠であり、T20全40state/activation/weight/row/scratch同時full-core peakではない。変更後live kernels/device APIはT20 affected資格待ち。T18/T19は変更ownerのactual hit/read/H2D0・permit/noissue poll/取消次要求、Row fullfile8高offset・借用返却の必要subset待ち。T21固有roles2とResidentSlot関連関数は旧版同一だが、変更DemandOrderの必要subsetとT18依存は未了。一括完了にしない。
- T25先行Engram helper r2は最終独立重要0/Main限定受理。manifest ace61bfa…/Q8cb75c…/EXE94d9…/proofd8a1c81a…、両GPU各25jobs/6572448値・362outputs/24412032B exact、独立Decimal N全式/realFP64gate16/69拒否・peak5493516B。actual連続層state/S5-2/fullT25/T20は未了。旧immutable consumed helper資格と変更中live Coreを分ける。
- T20はimpl53の両arch/host68・CPU8・影響lease host135以降、実G未実施。finite prefill/layer union/all40stateの数値・実同時working set・影響検証・独立実装reviewを進める。全9取得は完了しdownload sessionは終了、globalreceiptも成立済み。以前のT05/fullT10待ち表現は当時の履歴であり、現在の残条件は本節とtask表による。

### T20新owner subset検証・hot是正（impl55）

- T20の実owner subsetは `build-deepseek-t20/owner-attempt-4/verification.json` SHAb57dfa3fab76d55fcb5588829904f2655d593820a5541461b83afb5313b6874a へ固定。20projection（expert38 gate/up/down・routerF32・attnKVQ8、B3/19×2族）、final8の未登録last-head24rows cold/devicehot/RAMhit、取消後の次要求で492033値exact。4KiB実credit/両outstanding<=1,4096・実E→R→E、noissuepoll3/未発行取消/実発行取消drain→次projection、不正borrow cursor拒否/取消中再利用拒否/lastuse event返却→次rowを確認。実同時device5083904B=Core880640+Primary4194816+Row8448、driver/context/OS physical peakはunknown。3ownedDLL/前後binding・immutable consumedsource/native/Qを保存。独立側は全20Qと原本24row/EOFを再導出、source/outputs/credit/取消を確認したがhot値未保存R1を指摘し、その時点のhot counter成功だけを数値資格にしなかった。
- R1補完はcold20全suite反復0。`owner-hot-attempt-1/verification.json` SHA2be04e24d672cebfd81356c0e44e25e111b8ba2d062f6b790f9c35c765f4ec8b / EXE986ccd75…/G前hotQ8a77ba2eee09004630480f81c2d109b4f287b967325241ac930f3e2b182da5f8。最終tile/activewaveだけwarm→targetをNaN poison→実hot launch→strided compact保存し22040値全bits/bytes一致、hot read/H2D0。CPU replayfc7fb1d4…、short/bitflip/全poison/counter/duplicateの5変造拒否成功、独立再review重要0/R1解消。旧attempt4とのsource差分はfixture/runnerだけでmath/owner APIは同一、統合 `owner-subset-final.json` SHA15acac40875f44d55b105a4905c5c0e355ede592f6d4e3c52c29b899866bd78e。旧capture runnerと新CPUvalidator/旧Gとhot補完を別bindした。
- 08:21:43JST T20生成保持593273585B/458files、freshfree89392857088B、モデル残増分0。既保持はfree算入済み、今後T20 6GiBは保守工程reserveで通常capではない。全40層/有限prefill/layer union/whole simultaneous working-set・全影響資格は未了で、owner subsetを全core合格にしない。T25 actualは独立Q graphと同run_layers用fixtureの実装中、G0。snapshot9153df18…の181sourceと変更後live版は別記録、全core完成をT25開始条件へ追加しない。
- 本版最終判断: 独立側はcold492033値の原本Q/row再導出に加え、hot22040値を別sliceで再構成・poison実書込・6counter0・5拒否/52source/外部deps/DLL/outputを照合し重要0。live Primary/Row/lease/quant/Core10fileもhot snapshot同SHA。MainはT18/T19/T21を元component範囲で完了受理。T21はpeer未試行のlocal/bounce/PAGEABLEのみ。全40Core/有限prefill/全state同時working-set/wholeT25を成功へ拡張しない。impl54の残条件待ちは当時履歴、本版tableが現在地。

### 全40独立Q・実capacity grantと後続現在地（impl56）

- T20は承認済みwave1基準のnormal prefill2＋append1を実証する。layer-major batching/速度を新必須条件にせず、実各token/層top6 union・再読/weight bytes、finite rowtile、全40state＋全activation/scratch/constants/weight/row同時peakと寿命を固定し比較する。現step loopのcompileだけをprefill実証にしない。raw IDs[3,37,1024]・implicit BOSなし・fixture context storage3/full_logitsを別固定し、通常context/総batch/出力を制限しない。
- 独立T25 ActualOracle f3bc0e942ee9d523e20b4269d70cf3bc7a553b8089d738d1f19227d16d1b69bcと固定T04/09/11–15 CPU参照を別immutable rootへcopyし、T20 own semantic adapter（原token embedding Q8→BF16/HC4、全40、collapse→学習output_norm→head noQDQ）から事前Q生成中。first token40framesまで進行、全3token seal/実Gは未了。限定T25資格やcandidate Gから期待/閾値を生成せず、後続T26が利用可能な入力/source/bundle/出力来歴を保存するが自動完了にしない。
- CoreSequenceの常時4KiB grantを、PrimarySupplyが実保持read bufferから返すcapacity由来へ是正（現64KiB/1outstanding、明示issue-only/actual requested消費）。4KiBは既資格の最小credit fixtureに閉じ、新ユーザー設定/無制限issue/管理層は追加しない。math/期待不変。新capacity-ownerのwarm requested量/operationsをG前Q66b29244…で純粋導出、CPU7変造拒否/両archhost68まで、影響小Gは未了。CoreRuntimeStatsはstatic F32 source logicalbytes・実storage transfer/ownedと固定40×384bit union/各層dispatch token数を記録する。既router CPU IDsを使い、追加activation payload D2H/全履歴trace保持は0。全40同時会計は未資格。
- T25 actualは独立事前Q18call/54framesとfresh replay9callを含む27call/81layerの実G進行中。181source snapshot9153df18…の旧Core/4KiB経路を維持し、live T20 capacity是正版へ旧proofを流用しない。helper r2の限定完了とは分け、actual連続state/S5-2/wholeT25は未資格。
- T28 pre-v2（build-deepseek-t28/pre-v2.md SHAba20f1e2…）はEOS後push/DTO終端R1解消の独立重要0/Main GOで環境担当7newfilesに着手。controlled元ID frame→実公式Recipe codec限定、実sampling/生成producer/通常server結合は未実施で、mockを実生成資格にしない。T25 actualの修正を優先する。通常CLI/機能/出力枠の変更0。


### 全40事前Q固定・capacity影響検証（impl57）

- 全40独立CPU Qはtokens[3,37,1024]・120frames/source228963 readsを生成完了。`build-deepseek-t20/full-q/sealed-manifest.json` SHAafef342a7a9410fb5202f9c86bcf4e95ba0b5f8f7d9965ac5d6017879039bb0c を実G前固定。wave1 normalprefill2＋append1・全logits3×129280、実route union bitset/全40state・compressed/key rowsと源tupleを保持。純粋寿命式は初期CoreStorage13126901B＋F32 constants2261440B＋Primary4194816B＋Row8448B＝explicit同時device19591605B、driver/context/allocator/OS physical/fullhost peakはunknown。weight logical38899787712B・source union19251904448B・再読19647883264Bは事前期待で、実counter照合はまだ未判定。会計/state controlled変造201件拒否はCPU validator試験であり実fullG合格ではない。
- 実retained I/O capacity由来64KiB grantの必要影響だけ `owner-capacity-attempt-1/verification.json` SHA6e8b9ae1f3e94144f45fd302adbc01c403811ad6ceed14c7e5920967470279dd / CPUreplay614f43ad… / Q66b29244…へ固定。20finaltile warmのlogical/requested/H2D/operationsを原offset・rowbytes・64KiB物理窓から独立再導出、hot22040値exact・7拒否＋positive・実getter呼出を独立確認重要0/Main限定受理。旧4KiB最小credit資格/数学期待は保持、全40資格へ拡張しない。
- 08:51 fresh CLI停止済み/free88323502080B、担当間の当回共有GPU ACKで `full-core-attempt-1` / session82357 を開始。初期CoreStorage実13126901Bへ到達、全40数値/有限prefill/実union再読/同時working-setは実行中・未判定。T25 old immutable9153 actualrunとの明示overlapであり、source/TMP/outputを分離、free/elapsed/physicalpeakを隔離性能証拠にしない。小capacity Gも同条件をshared-window.jsonへ記録。通常consumer停止/reset/global設定/通常cap追加0。T25 actualとT28 controlledcodecの未資格区分はimpl56のまま。


### T20全40実G・cache会計補正と後続（impl58）

- `full-core-attempt-1` のnormal wave1 prefill2＋append1はnative exit0/stderr空、G前Q afef342a…に対し全387840 F32logitsが全bit/byte一致。全40state positions3、compressed/key rows[1,1,1,3]、各層3token route union、実requested output D2H1551360B・中間activation payload D2H0、明示同時device19591605Bも純粋寿命式と一致。初回validatorは全projectionをcold加算したsource会計だけで停止したので、その時点をPASSにしなかった。数学/入力/保存出力/native EXE7a182b9a…は不変。
- 独立Qの事前source列を既Primary実2device/2RAM slots・empty first→first eligible valid規則でCPU再生し、blk.0.hc_attn_fn.weight F32[20480,24]1966080Bが初回slot1へ残り、後2tokenのresident2hit/RAMhit0で3932160Bを読まないことを再導出。projection要求logical38899787712B、miss由来実source logical38895855552B、unique source union19251904448B、実再読19643951104Bを区別した。旧全cold期待/runner/failedattemptは保持、新cache-accounting-r2.jsonを別生成し、新CPUvalidator84eae602…/cpu-validation-r2.json SHA4b7970df98f26ac9f11a3e7c3d06a703ca8d07f203ff1ddfefe61b39793b8665で照合成功。追加GPU/build0。
- 原native-capture-receipt.json SHA479ba3918ed8bf8af342207158edd20b8acf19df5569d3714db37de2ecc7b424 は原EXE/Q/compiled consumed source・外部deps/tools/bitcode/DLL・9原本currentidentityの前後を確認し、immutable sourceと原recipeを保持。今回CPUvalidatorが旧EXEをbuildしたとは扱わない。201会計/state拒否・controlled output4拒否、全T20実装は独立review提出中/Main最終未受理。T26全40TF最終資格へ自動昇格しない。driver/context/allocator/OS physical/fullhost peakはunknown。shared-window.json dd183f29…でT25旧actualとの明示overlap/性能非隔離を記録、通常consumer/reset/global変更0。
- T25 actualは旧snapshot9153の27calls/81layersがnative exit0/stderr空、11549556値/1626filesの事前Q一致まで終了。全cold会計をcache規則でCPU再導出して厳密化/別validator bindingを補完中、最終独立review/実層state判断待ち。T20新sourceの証拠へ旧snapshotを流用しない。
- T28 controlled native T23 frames→既DTO→公式Recipe codec r1はpre-v3のEOS実RED是正を含み独立重要0/Main限定受理。manifest971c2673…/EXEf0c341c8…/proofd11065df…/codec56307d20…、160assertions＋2unit/1023bindings・追加DSML失敗終端5probe。EOS前numeric prefixと全raw IDs/count/hash/EOS indexを分け、finished後push0/DTO valid finishまでterminal保留。全vocab等の通常API/capsは縮小しない。実sampler/生成producer/normalserver hookは未実装・同task追補pre調査中、T28全体を完了にしない。


### T20 scope完了・T25具体残とT26準備（impl59）

- T20最終独立R1はdefaultlast/同入力audit対/失敗freshの実coverage不足であり、元fulltrue3token387840logits/120frameQ/全40state/route/19591605Bの一致を保持した。fixture/runnerだけを補完した `branch-core-attempt-1/verification.json` SHA63af4027f4040999c8c444131bf85565ea7b9d5bca3f9adfe4fe057160040e19 / EXE58c2d92e… / 事前Q294b91d6… / CPU35756513…で、defaultfalse prefill2のrow1/position2/129280logits exact・D2H517120B・中間head無し/source25222267520B（1residenthit）を確認。invalidtoken→旧sequence再利用2拒否/破棄→fresh2sequenceの実[0,1)同入力/state audit off/on残差/pre40968値exact、監査mirror20484値/81936B exact、off audit call/D2H0、通常必須capture81936Bとaudit trafficを分けた。新Core API/数学/Q緩和0、元fulltrue3tokenの再suite0。
- 独立側は原Qから全default/audit期待を別再導出、source/tool/deps/bitcode/native/DLL前後binding、default read/cache/owned式・追加16拒否＋positiveを照合し重要0/R1解消。Mainは元T20有限wave1 primary text Core scope完了を受理。統合 `build-deepseek-t20/verification-final.json` SHA77e5f5c9f80fbc5e03f5cb85fb057e2a96ce680b3a5eb34bb959828c6b09029f。原G recipeと新CPUvalidator84eae602…はexact historical snapshotを分け、全T26/他mode/性能/longcontext/自由生成/通常serverへ完了を広げない。通常cap/CLI/共有環境変更0。T20生成保持3019files/1503096963B、freshfree88000073728B、将来review/doc増分見積64MiBへ（旧6GiBは工程見積で通常capでない）。既保持はfree算入済み、再控除しない。
- T25 actual最終proof07ae343776d93ff6c072553409bfc0e10d3c0c7b5007c4e65b6167472169e108は独立最終重要0/Main bounded3range＋freshA限定受理。27calls/81layers、11549556値/1626files、54native拒否/85CPU拒否・source/cache厳密化、peak17847085B。当該proofの未資格項目すべてを新gateにはせず、元DoD照合でsmallstateの実保存→復元→継続が具体残1件と判明。source2ratio2 CompressionState pending/publishedのdeep保存復元小fixtureを同8tests/旧snapshotでpre追補中。Core公開restore/全40G追加は求めず、helper/actual既数値証拠を保持し、wholeT25完了だけを保留。
- T26 pre-r1 SHA4516d9023a2bd9c7997af544462a7c98839e2f80ac4b72bc51fb5df722557c9fは独立重要0/Main GO。新 `tests/numerics/t26/{contract.json,qualify.py,test_qualify.py}` のCPUreceipt adapterを実装、missing module RED→4CPUtests GREEN。既全40rawIDs/positions/implicitBOSfalse/全9assets/flags/寿命/原captureと新CPU別bindingを再利用し追加全40G0。固定14入力refsまで準備、T25_restore最終適用receiptが未確定でdependencies_final=false/receipt未発行、T26最終実装review未了。teacher targets[37,1024,null]・未知3rdNLL/未取得全40中間driftを0へ丸めず、全N→Q品質T42・自由生成/serverは別。

### T25元scope完了・T26最終CPU資格記録（impl60）

- T25/S5-2はsmallstate source2ratio2のdeep保存→別枝→復元→同suffix継続を補完。r2 final `build-deepseek-t25/state-restore/verification-final.json` SHA9029ca46ca679e7fa79ab2b5193d7b82f4825ad61006530f26fe0c3e2fe3ece4、15360値/61440B exact・68native descriptor/snapshot拒否＋45CPU拒否、explicitdevice2146440B。旧helper/actualの受理証拠と統合し、coverage-map-v3.md SHA66ceeea5f6169cd0c965539bef6a3dec22cf56c7021fe4cf4117d746e2ea3cbd / coverage-evidence-v3.json SHAd09726fb0c220b4419df239a293f53a30459cf3420d93009a5a796e3ccf8eb53 の全20anchorを独立exact確認重要0、Mainは元component scope完了受理。Core公開restore/全40復元/自由生成/T42品質は本資格に含めない。coverage正本はimmutable impl59 snapshotへbindし、将来の本計画更新で歴史来歴を変えない。
- T26は承認3newfilesだけでCPU adapterを固定。contract b4c8dcc892770c426355555f672cc0d0c4440ac98553499f48eb38048d77d6c6 / qualify.py 2e297bc078163ee4db94c6b8b729f3077696a027368be5c74bf4b29b3822f61f / tests1b962482dad58b3930c4d4b590e66732f44b22719e4c817286fed09884bd5cba、7CPUtests GREEN。T20/T25受理済み15固定refs・最新20anchor・全9原本currentidentity/header/span・原実flags/sourceID/DLL/immutable recipeと全387840logitsを再照合し、`build-deepseek-t26/verification.json` SHAde015333af9e9334bb979aeb77972484059f630fbcfbf9aa17dc8c8be4cc570f を発行。独立実装reviewへ提出中でT26最終完了は未受理。原G/Q/native/input/output不変更・追加GPU/build0、旧captureと新CPU adapterを別bindする。
- TF rawIDs[3,37,1024]/positions[0,1,2]/implicitBOS=false、targets[37,1024,null]。3rdNLLと未取得全40中間driftはunknown、全9構造assets/1043tensorと実text1003tensorの資格を区別。N→Qモデル品質・自由生成・normalserver/secondaryへ拡張しない。
- T29はread-only field調整のみ。T28残normalproducer pre-v2 SHA280b4699963b030a7ad466f44a050d930a93512a70dd2fdad6a942a0a17e5c88は独立review中/code0。actual9native paths/fixedrevision/layout・公式Recipe tokenizer・context/primaryPCI/既owner環境を用い、fixture TSV/prefixを通常必須にしない。通常総cache予算とactive tile/wave/context3/2slotsの試験設定を分け、既SupplyConfig/RowConfig容量へ明示変換する案を調査。Huihui/default256K/既profile bytesを変更しない。T35等はread-only候補整理に留める。
- 09:40容量観測: free87684763648B、T25保持1111999524Bは既にfreeへ算入済み/将来残32MiB、T20将来64MiB、T28 normal工程見積2GiBは旧64MiBと置換。工程reserveは通常hardcapではなく、既保持を再控除しない。

### T26元TF scope完了・T29 pure provider計画（impl61）

- T26 fixed primary text全40TF receiptde015333af9e9334bb979aeb77972484059f630fbcfbf9aa17dc8c8be4cc570fは独立最終重要0。作者固定Python3.12.10/NumPy2.5.3で独立7testsと別dirqualifyを実行し、全field/同SHAを確認。別NumPy2.3.4でも数値/適用15refs/全20anchor/9currentidentity/1043構造/387840logits/actual flags・寿命は同一でruntime表示だけが差。Mainは元TF scope完了受理。NLL[13.00108519055275,9.984940638415583,null]、exact KL/NRMSE0、未取得全40中間drift nullを保持し、N→Q品質T42/自由生成/server/他modeへ拡張しない。追加GPU/build/fullpayloadhash0。impl60のreview中記録はその時点履歴。
- T29 pure family assets/profile/catalog計画は `build-deepseek-t29/pre-r1.md` SHA0c34c0ace6ada8b14a71861dc514a4ead36e95df9187e5f63e80050750f39afa。OWN provider2/tests3＋DATA model_catalog1の6files候補、独立事前review提出・code0。Huihuiの行/順/既profile bytes/default256Kを維持。catalog/readinessはpure family dispatch、通常CLI/manager起動・登録write/lock/preflightは元T30責任。未実装接点を明示し、未評価だけを禁止理由にするgateを新設しない。T28依存は維持、実normalbinary/profilefield・新profilepath確定は同pre内追補してreviewする。
- T28 normalproducer pre-v3はhidden64 config/settings/GEN伝播の同scope是正をreview中/code0。通常budgetはcaller意図/単位とowned factory resolved bytesを分ける。既DeepSeek normalauto算定関数は存在せず、正本試算の16/60/2GiB等を既定値としない。既SupplyConfig/RowConfigへ実mandatoryallocation後の残量とcaller予算を渡す最小factory設計をT28同preへ具体化し、fresh availableから既使用RAMを再控除しない。全free使切り/fixture2slots/context3の通常固定化/新起動gateは追加しない。T35はこの通常予算接点のread-only設計整理から後続へ、T44/45大scopeは現時点未着手。

### T29 pure実装r1と後続read-only（impl62）

- T29 pre-r2 SHA9d99cdea7000554253d23953bb2751a7dded07967669d7bb2d6728012102345bは独立重要0/Main6files GO。OWN/control/providers2・tests/providers3＋DATA/model_catalog.pyだけを変更。missingprovider RED→10CPUtests GREEN、実9qualified原本/currentidentity/header・1043原spanのtype/shape/rowbytes/boundsと公式Recipe tokenizer identityを確認し、`build-deepseek-t29/verification.json` SHA8a2decdfb08656d716c32e29eb40eeb82baf17e1d160533be512b08d0a173257へ固定。provider985c4b8e…/catalog01a501b9…/runner97e817d3…、全6source/input/runtime前後SHA一致をbind。旧catalog raw保存・Huihui行/既context/availability/layout対照、既全profile bytes前後一致。独立実装review中、T29全task未受理。
- family providerはpure originalasset/layout/profile宣言、実normalmetadata/native owner資格はcaller/T28/T30責任。新entryは固定Q4variant名だが汎用type/role契約を狭めない。context1..1048576と提示presetを区別し既default256K/モデル選択順を保持。現ownerのmandatory RAM/device slots非0を説明し、seed0/top_k0/optionalrole0を一律拒否しない。normalproviderは将来installed OWN pathだけを読み、開発checkoutへ自動linkしない。
- 生成profileはB29隔離内のみ。未完成T28 normalbinaryの代わりにhistorical T20 EXEを明示fixtureとしてpath検証し、normalproducer資格/通常profile配備としない。実profilefield/path保存・登録write/通常CLI/manager起動0。T28依存と同wave実profile追補reviewは残る。normalbudgetはdevice_cache_payload_bytes/ram_cache_payload_bytesのauto又はpositive宣言とfactory resolved bytesを分離、auto fractionsはT28同preの未確定変更可能default提案として扱う。producer-pre-v4はCoreprefill cancel/progress最小接点も同review中、product変更GO前でCore編集0。
- T37は依存成立によりread-only調査開始。固定公式configのnum_nextn_predict_layers3/target layers37,38,39/dspark_block_size5/noise128799を確認しただけで、5を層数/通常limitとせず、draft weights/confidence/encoding/sampling/RNG/因果/不足artifactの実対応は調査中。新原本取得/巨大copy/Core/通常設定変更0。T29/T28主経路と指摘修正を優先し、両大実装は同時着手しない。

### T29 pure限定受理・T28通常実装とT37計画（impl63）

- T29 pure r1独立指摘R1は有効524288-only profileを暗黙262144要求で見落す利用不具合、R2は明示placementを無検証保持する不具合。元6file内のr2でcontext未指定asset callerが既存有効family profileをdefault優先で選び、明示contextも伝達しdefaultfile自動生成0。既control/contracts.validate_placementの4modeを再利用しprimary_pci/secondaryと整合、placement未指定を必須化しない。最新auto fractions finite[0,1]（0=extraなし/必須active保持）を宣言として保持し、payloadbytespositiveと分離。
- `build-deepseek-t29/verification.json` SHAfd6c87f24526a7418d0ad58ed726d367f5a4b713baae25367a43eaa7ff3d6edc / provider e4dea65329cd840e9e21c37cc24b3447a8e7c6e0c4c899b979eb3ae119cf8619 / DATAcatalog798d848a902b93fea068ec1ad4648a5f7735ce9e5e7654b86a94f44ed7531c9c。独立別BUILDで12tests/17bindings/現9source1043spans/公式tokenizer/旧Huihui4profilebytes前後を確認、generatedpath以外全意味field一致・重要0/R1R2解消、Mainはpure準備scope限定受理。旧r1source/proofはr1-historyへ保持。T28依存/auto実resolve/normalprofile出版・登録/通常CLI起動は未了、wholeT29完了にしない。
- T28 normalproducer pre-v5 SHAbda2d6b34ea8953ce09302fa954fa7382c895541c5d252f84a0c268817def33aは独立最終重要0/Main実装GO。14new＋既存6（Core2最小prefill controlを含む）をenvironment作者が単独write。Core hpp49c99eea…/hipde2f8aab…はcallback前後token境界/全ID事前検証/取消invalid+drain・旧head/last-only条件維持の初回固定版で、まだ新normalbundleの必要影響G資格をしていない。既T20/T26 accepted math/source/captureは歴史保持、normalproducerへ旧proofだけを流用しない。通常予算は新変更可能auto fraction .5/1/64とexplicitpayloadbytes、実mandatory/既availableと既使用を二重控除せず解決する案を同scope実装中。fixture2slots/context3を通常capへ転用しない。
- T37 read-only pre-r3 SHA7500cac5e8e695e590879597e7c27aeaff8db40e65f83da515965adc5959592dを独立review中。公開native第一候補Luce固定HF ba58445f…/7965746848B/LFS02468aa7…、sidecar由来converter5ada…が既固定Luce819…と全byte同一ff001938…を確認。Q2K/Q4K候補4923041440Bは追加型/品質差、公式3source案7933129808Bと比較し最小候補を明示。今はmetadata/sourceだけでartifact本体/rawweights取得0、actualnativeheaderは既PythonT08parserで確認中、Core/通常設定変更0。
- 公式mtp.0/1/2は801/798/802=2401tensor、44–46のstrict206 JSONheaderだけ計255152B＋各8B長を取得し、confidence BF16[1,5376]・Markov各[129280,256]等の実型/shape/offsetを確認。target37–39 attention入力HCmean concatは独立mtpweightsと別。confidenceはnorm前collapsed5120+priorIDMarkov256のconcat rawdot、DeepInfer温度/clamp/sigmoid率と別、nativeF16保存差をlosslessとしない。採否effective targetp/actual proposalqは全sampling変換後で、T28表示LPをqへ転用しない。default5はstage数/通常hardlimitではない。T37コード/8GB取得はpre最終review/Main判断前、T38実採否/分布Gは別。


### T37固定artifact取得・host実装の固定版（impl64）

- T37 pre-r4 SHA9e1a1991c647d065254ec5bec52bf633e554707fe6aaa64e27e54d44a41a0a06は独立最終重要0/Main GO。metadata調査は既T08 Python parserによる65536B prefixへ是正し、header7296Bと未資格weight payload58240Bを別計上、先行body0表記は当該prefix全体について撤回した。全79tensor（F32 36/F16 9/Q8 25/MXFP4 9）、公式原1221weight＋1177scale対応・VLbias3未使用、synthetic confidencebias0生成を区別。C++既reader.inspect_prefixのsinglefile/type1未対応はT38接点へ残し、T37は共有reader変更0のPython metadata＋新host F16契約とする。
- 固定Luce repo/rev ba58445f0818edfc69e680390bc9b4873af8a621のnative draft1fileだけをModel専用variantへ取得。session10368は30ranges/7965746848Bのrunning fullSHA02468aa72b7233d50696682817b66ea661ebf387a0b6beecf6954febd8680b1e一致→same-file rename/exit0。ETag05558ef2…はLFSと別、current fileID1688849861586580/mtime1792546350109170800・partbody/lock無し、checkpointだけ保持。artifact-receipt.json SHAe93c30d232f95df0c7700c0e31bea23b4c453d5c8ea6aa18c20dedfb1f3b5365。既T05 helperはprivate importのmodule-local transport引数だけを分離し、受理T05source/target9変更0。追加8GB再hash/全target再copy無し。
- 承認9newfilesのみでhost DTO/原SourceSpan/target37–39対capture36–38/owner epoch/originalIDs、F16 widening、HC mean、norm前5120＋priorMarkov256 confidence rawdot、effective p/qと表示LP分離・採否/残差/確定prefix/EOS/取消/RNG namespace契約を実装。missingmodule REDを保存し10Python tests GREEN。独立Decimal N/bit Q・124原本first/last-row spans（3stage/最終expert127/Markov先末/全native型）をcandidate前seal c11dedbfd02628753d4d7d60ff29b0a2bca0baeb59817eb7e560cbc6d8a92a12。host-r3 MSVC /fp:strict /MT実行は654051実decode値全byte一致、755native拒否、6output変造拒否＋8metadata変造拒否成功。raw合計1130756B。公式confidence10752B strict206と実native5376要素はBF16→F16 cast全bit一致、このtensorの実値差0でありHCfn等全変換のlossless主張ではない。
- build-deepseek-t37/verification.json SHA31d033aadc20d4ffa414976d99fc6426f51ba5b7b82b70480daaf14faa567fd8、source-map-r1.json SHA8350700f500043926347d5c285a590ac818245a27de84472924793e668de0018の203consumed source/noticeをimmutable保存。初回host-r1 CMake Windows backslash解釈失敗は保存し、recipeをas_posixへ是正、旧Q/attemptを保持。最終host-r3はconfidence境界/metadata負例と工具/PE disk依存bindingを補完して新Q先seal、CPUverify-only再実行で同proofSHA。独立実装review/Main完了判断は未了。実loaded DLL path/再帰closureは本host資格で未観測、GPU0、T38 draft3層/targettap/実採否/通常DSpark/性能へ拡張しない。
- 取得開始freshfree88239497216Bから既保持二重控除0で将来増分見積を単回控除。最終工程snapshotはgenerated42542743B/1415files、Model7965746848Bはfreshfree79212814336Bへ既算入済み、model残取得0/将来generated保守512MiB工程reserve（通常capでない）。T28には残取得0と同reserveを通知。
- T28 normalpre-v5 GOのCore2はenvironment作者が単独変更・両archcompile済、新normalG資格未了。constructor途中throwのrawhandle cleanup不足は同pre constructor delta-v2独立重要0/Main GOでPrimary/Row2hipsだけを補完中、通常成功path/math/header/capacityを変更しない。旧T20/T26/owner成功資格はimmutable歴史版のまま、新failure→fresh/normalauto再選択の資格へ自動流用しない。T29pure限定受理/whole依存待ちを維持、Huihui/default/profile/通常設定変更0。


### T37元scope完了・T35 eager測定のread-only計画（impl65）

- T37 r1独立reviewは実writer basename検査の具体R1を指摘。旧wrapperはfilename+'.lock'を見ていたが、再利用exclusive_writerはfilename+'.part.lock'を作る。現物に正しいlockが無い観測とvalidator一般条件を分け、helper.file_pathsのpart由来へ修正、隔離fake rootで旧predicateがactual part.lockを通すREDを再現→新CPUvalidatorがpart.lock/partbody2拒否・空root正常を確認した。
- 固定wrapper-only r2: tests/dspark/build_verify.py SHA1fee33c0dacb3209c17928c9e52fd4ed39f4d8607d766a1fa072294a6e5dafcf、host-r3/cpu-validation-r2.json SHA803b0c816b81c4358e4eca88ff4b950d218f40137f04468872c4ee6e393f1a10、verification-r2.json SHA2a9b4596cfae7c4ae89c97453652bd2fc1ecde0ebc70bd3f5301b55f8c98f202。原capture runner/proof31d033aa…/Q c11dedbf…/EXEb9afeacb…/manifest5c3b7c96…/203immutable source/138outputsは不変で、現CPUvalidatorが旧EXEをbuildしたとは扱わない。数値fixture再実行/新build/GPU/全8GBhash追加0（native identity queryのみ）。
- 独立側は別dirで固定EXEの755拒否/127正例/654051decode値/138outputs全byte・10Python tests、qualified final原本から全124spanのscalar期待を再導出し、5376confidence BF16→F16 bridgeをこのtensor限定で確認。30ranges/LFS/ETag/currentidentity/正しいpart.lock無し、492binding前後とr2 CPU負例・旧capture別bindingを照合、最終重要0/R1解消。Mainは元T37 artifact/host契約/bounded fixture scope完了を受理（全体28/47完了）。T38 type1 GPU projection/独立128expert top3 draft演算/実tap/採否/確定state/分布/通常DSparkへJSON契約やtarget既Gを流用しない。
- 最終fixture raw1130756Bはhost-r3の論理fixture合計、開発host-r1/r2/r3を含む保持raw実3392268B（8MiB枠内）と分ける。Model残取得0、8GB finalはfreshfree算入済み、追加全量copy/hash無し。将来generated512MiBは保守工程reserveで通常capでない。
- T35は依存T20/T26/T34成立後のread-only pre-r1 SHA1bf35665fa0fc7fd833335bf527f68f86e96565dc464369025e769140e54e265を独立計画reviewへ。候補newtests4＋existingproducer.cppのINFO既scalar export1のみ、code/G0。T28 usualauto(.5,1/64)宣言とactual resolved slots/payloadを分け、fixture2slots/context3/旧工程reserveを通常budgetにしない。coldはnewprocess/empty appcache、warmはsameprocessの保持weight/row owners＋fresh Core（KVprefix reuseでない）、OSphysicalcoldはunknown/globalpurgeや他consumer停止無し。原T23 IDs/rollinghash/finish/DONE実countとmonotonic最初のraw model tokenのTTFT/aggregate TPOTを結合、Service可視first_token/HTTP/SSEと別。N不足/未測定time/physical peak等を0へ丸めず、RAMhit未通過も性能PASSとしない。pilot後の事前固定paired AB短case案、不要baseline全suite/新SLO/長時間総当りを追加しない。通常T28binary/API/実生成/normalauto実値は同pre waveの未確定に残し、wholeT28完了を新DAGgateにしない。
- T28 latestはnormalQ86c7e28d…を公式4promptIDsから独立先sealしargmax4482/LP/top3を固定、G0。sampler124assertions/adapter13tests再GREEN、終端chunk内content/LP保持を含む最小修正後に両arch再build中。constructor10局所fault→freshとactual prefillcontrol/normalHTTPはこれからであり、compile/CPUをnewnormalG成功にしない。T35 INFO scalar追加は既主経路へ割り込まず別承認差分/当回write窓で調整する。


### T35 CPU先行実装・T28 focused Gと未資格auto（impl66）

- T35 pre-r4 SHAd4215b6cbfdc6e6e704bf526d1a185b9169680b6bf22f03c8bc8d80ca0d97125は独立最終重要0/Main GO。承認newtests4 `tests/backend/{eager_contract.json,eager_bench.py,test_eager_bench.py,build_verify.py}` を実装、missingmodule RED保存→20CPUtests GREEN。T23 DTOを再利用して元ID/hash/sequence/finish/DONE count、EOS1を含むN、0とmissing、clock逆行/分解能0/同frame又は同stampのTPOTnull、累積owner delta対fresh Core currentrequest絶対値、device合計alias/pinned unknown/null、cold supply false0拒否、paired CIと不足標本を検証。host pipeのfake Python childと起動失敗時の自child回収もCPU検査であり実モデル性能証拠ではない。
- 固定CPU `build-deepseek-t35/cpu-verification.json` SHA7a9fa9be7f4d008f00f292debf47c1d8c128dbde2373a196ec7cae0e9e99df51、`cpu-subset-r1/source-map.json` SHAc9432a6f7fbb1a800743db23cf4c469720ba2e52df51c5193fe674cdebd71daeにnew4＋既DTOをexact保存。同実装reviewの先行subsetへ提出中、追加承認stageや実pilotの代用にしない。actual_GPU_runs=0/actual_performance_qualified=false。
- 公式RecipeのChatCompletionRequest.convert→DeepseekV41Encoding.encodeでsky promptを実13IDs `[0,128803,19905,418,1234,3107,15174,943,270,12709,16,128804,128822]` に確定、context4096/max3はbenchmark選択値で通常default/limitへ昇格しない。先頭ID0は公式template由来で、追加implicitBOS=false。prompt-encoding.json SHAc0c4ed016b9d97acbb84d9876ec1ad57482999d66f6eea72f5051c41a61b180b。pending-pilot-input.json SHA7c5bd1f5…はT20/T26/T34 acceptedrefsを結び、normal_manifest/binary/receipt/resolvedbudgetはnull/not_executable=trueのまま。T28の4IDs/C16/max1観測とは別workload、actualnormal source/flags/通常budgetを受領し同pre waveのpilot契約をG前sealしてから実行する。
- producer.cppの既stats INFO scalar不足はMain承認5file範囲内で現environment singlewriterへmappingを手渡し。Primary receivedには実counterが無いのでnull、pinned unknownはsubset=null/known bool、Core constant_source/storage_uploadはcurrentrequest絶対値、actual_device_ownedはCoreStorage+Primary+Rowの既合計で再加算しない。hostaliasはPrimary.host_owned+Row.host_payload+owner_metadata。helper/control traffic未観測を0へしない。新normalbundleへ別bindし、当方sharedsource並行書込0・Core/owner/math変更0。
- T28 focused Gはconstructor10局所fault→fresh owner close（proofc44d016a…）、prefillcontrol13assertions/取消1token/D2H0→fresh2token129280logits exact（proof278d207c…）、旧explicit working-min budgetで実normalEngine→既HTTP handlerの4IDs→4482『您』/LPtop3局所2ULP/length count1/hash一致（proof1fbd6889…）まで観測、いずれも独立最終review前。旧model label fallbackはCPU最小修正、strict STOP14host case/INFO readonly追加版をnormal-next2別bundleへ固定し、過去captureのsource/出力を上書きしない。
- 同新default-auto-attempt-1はtypedcancel後の次HTTPで503となり未資格終了/GPU0。原因未確定でerrorbody/rawframes/partial startupINFOの診断を補完中、観測していない中間成功をproofに足さない。Q/fractions/math不変、blind再G/新cache上限/通常disable/driverreset/他consumer停止は無し。T35はこの結果を成功normalbudget/性能baselineに使わずpendingを維持し、T28必要修正/再Gを優先して当回windowを調整する。wholeT28/T29/T35は未完了、全体28/47完了のまま。


### 通常配置依存とT35 CPU準備の限定受理（impl67）

- T35 CPU subset r1 proof7a9fa9be7f4d008f00f292debf47c1d8c128dbde2373a196ec7cae0e9e99df51は独立20tests/重要0/Main限定受理。実pilot/性能/normalauto結果は未資格、pending inputのnull/not_executableを維持。pipe fileobject明示closeの非blocking改善は次通常差分で扱い、新完了gateにしない。
- T28 auto503は保存診断からnative1token内PP0のまま300秒超→既engine_silence_s300終了と具体化。元失敗attemptを保持し、env担当の実layer境界進捗delta-v1 ca8a92a8…は独立重要0/Main GO。数学/期待/Q/通常context/既期限を変えず必要新bundle/実Gへ、当方Core/producer書込0。旧explicit正常Gや実auto値観測を新normal全体資格へ先取りしない。T35は新normalbundle/実fieldsの引渡しまでpilotpending。
- T29 profile/path追補r1 efd4c49a…は現候補方針重要0。r2 SHA c2b9e54a6fdef96c32d3ec27b616cca01578e5809d932a0d907ba5924ac60c6bを同reviewへ。installedOWNとupstream_root/modelrootを分離、固定bundle/baseに必要serve/tools/Web/template/LICENSEを保持する候補を具体化。静的import-facts-r2.json af6b3ad5…の33files959424Bはsource inventoryのみ、runtime import閉包/venv移設/配置成功ではない。可変元checkoutや開発worktreeへの暗黙依存を避け、selected packageだけの隔離CPU entry/module.__file__確認を予定。全repo複製/新registry/全起動hashsuite無し。
- 最終package/venv保存先/field互換/filelistは未確定。newpublicprofile保存・配備・登録・起動0、既Huihui4profile/default保護とT30実spawn/lock/再選択責任を維持。T29pure限定受理とwhole未完了を分ける。28/47、T37元scope完了/T38実draft留保は不変。


### T29隔離Python/base閉包のCPU固定版（impl68）

- T29 profile-addendum-r5 d9784cc4731120ba7202542d0b71914deec851907e464dddbca82f3294916ff7は独立重要0/Main GO。METADATAの改行正規化text SHAと実file raw SHAをruntime-distributions-r2.json39faae1f…で分離、旧facts/r4を保持した。
- 旧6source＋新runtime_stage/test2の8source scopeでB29隔離stageを実装。missingmodule RED→新12+既provider12=24CPU GREEN。固定5wheel7792811BだけSHA取得、Recipe既修復wheel11739737Bを再用。既basePython3.12.10から新venvを-E -sで生成し外部PYTHONPATH/PYTHONHOMEをpoison、actualentry --help・固定base/必要tools/Web/template/Recipe/codec・module/native DLL pathを確認。sky13原IDsとDTO[4482,EOS1]→Recipe1ID、hash変造拒否、context16/4096/524288とalias/settingsをCPU照合。既T27/vision環境は不変更、native/listener/GPU0。
- runtime-stage-r3/verification.json SHA23490e823a2237c76598ad3222f99a8d319f793151769b31cdb920b6b8018229、統合runtime-stage-verification.json SHAf2febf890a4f854b86183b2cb6bf4876bdd3e7343ae90a6f26341497c1eb5418を独立実装reviewへ。原pure r2/7consumed sourceはaccepted-before-runtime-stage/map eb43a7b3…に歴史保存し、新8source/captureを別bind。初回pip quotedpath拒否は保持→fileURI是正、取得済wheel再利用。全3attempt保持180755951Bはfree算入済み、工程256MiBは通常capではない。
- 新ownedPython候補は既通常Strata版Jinja/MarkupSafe/psutil/Pillow/regex。旧T28fixtureのvision版とpsutil未installed unknownとは環境差分があり、CPU閉包を正常model/HTTP生成資格へ流用しない。jsonschemaは現上流optional/未installedのfallbackを保持。公開profile保存/installed配備/登録/通常起動は0、T28依存/T30実spawn/最終保存先は残りwholeT29未完了。
- T28progress64の新source Gはenvがfresh129280logits一致/取消例外回復成功を観測し独立最終review中、同4IDs/C16/max1 autoattempt3は進行中でwhole未資格。旧503失敗を保持し通常300秒設定/数学を変えない。T35実pilotは新normalbundle/actualfield引渡しまでpending、T44は次read-only候補のみ。28/47を維持。


### T29最終通常package/provider/profileの公開後CPU固定版（impl69）

- T29隔離CPU閉包f2febf89…/capture23490e82…は独立最終重要0/Main限定受理。配置pre-r3 860e88027d0f2f07855b988759fc18ab978a979525967dc8f0b55d9ce2af1e57/inputs-r4 1fef3455…は独立重要0、Tokenizer README/LICENSEの別notice R1解消。55copy169106520B、native1204f586…/EXE194b3eab…とpolicy4cee70c8…（68CPU/14拒否、OOM実発生/新数値Gなし）を旧成功数学pathと別bind。実装candidate1fdf20dd…は36CPU/8source独立重要0/Main必要scope受理。
- 承認scopeでC:/Develop/AI/Strata-extensions/runtime/deepseek41/09a17ee51c2bcf41296f84685673f2a1edf5a73e8db3dcb9dd3faeba84a70b1dへ最終venvを新生成し、固定base/entry4/55file/wheels/noticesを配置。-E -s/外部PYTHONPATHとPYTHONHOME poisonでactualentry --help/Recipe-codec/template-Web/203module/実OpenCV3+PYD/CRT pathsをCPU確認後、globalprovider/contracts3とDeepSeek専用6presetprofilesを保存。Model原本/既T27環境のコピーや変更0、Huihui4profile/default/catalogbytes不変。runtime実保持234545426Bはfree算入済み。
- 初回公開はpackage CPUと9file保存まで成功した後、検証wrapperのDATA sibling import不足でcatalog readback失敗。failure.json/旧candidate36testpublisher sourceを保持、wrapper-only catalog_moduleのsys.path scope補正をRED→GREENし37CPUへ。newCPUvalidator source-map889dac06…を旧publisherと別bind、package再生成/新modelGなし。deployment-publication-r1/verification-final.json SHA617003af653dc63940593441c165eb42f5fb0c1b7dae74a39e1108d7eb9d1665、package-manifest aab2c4ef…/final-location probe7300e9d1…で公開9file全candidatebyte一致・installedprovider/全6context/defaultavailabilityを再読。最新版は独立最終review中。
- 保存宣言のruntime_epoch省略、nativebundle/packageidentity/選択Python/upstreambase/entry/modelrootを分離。T30の既manager/bootstrap/LowTMP/実epoch/owner/CLI接続は未実装で通常CLI起動/HTTPモデル実Gはこの配置scopeでは0。旧T28vision環境と新owned環境のmodel資格を混同せず、必要実証は後続T30/33実入口caseで同bundleへbindし重複4IDsGを増やさない。T29whole完了依存T28は未了で、T30未実装を新たなT29DAG依存にはしない。
- T28progress64/1204policyの最終重要0/Main必要scope受理、sampler124/STOP14/adapter独立12・作者13も重要0。auto3はtest-only urllib900秒TimeoutErrorで実PP継続中に未完となったもので製品silence503再発ではない。元attemptを保持し、期限を除いたtestharnessで欠落finalHTTPだけauto4を実行中（同公式4IDs/C16/max1）。wholeT28/実normalauto未判定、T35実pilot/性能はpending。environmentはT44 read-onlypre、primary作者はT29→T30を優先、28/47維持。

### T28/T29元scope完了・T30通常入口CPU実装（impl70）

- T28 final-integration-r1/verification.json SHA80c7fa0fe4f72ecc92ff6278201140b8a97be8c94699e47f61f143e35e8679b4、37anchor64df225a…は独立最終重要0/Main元primary-text producer/公式Recipe/既HTTP scope完了。actualauto4は4promptIDs/C16/max1から4482「您」/LPtop3/length1/165実PPへ到達。provider旧e4→T29新96のprovenance変化で元wrapper失敗した事実は保持し、実runtime非消費を強制禁止import probe・旧新providerから固定cfg全dict一致で独立確認、新CPU別bindingで閉じた。前後trueへ改変せず、追加同4ID Gなし。旧vision fixture環境の資格をinstalled新Python/通常CLIへ広げない。
- T29元componentもMain完了受理。completion-dependency-r1.json SHA2d9b011d61ad57dea2320c68eeba564198033809b1a95f210abd6d609a2e01a0は受理T28/全37anchorと既公開final617003af…/package aab2c4ef…/probe7300e9d1…/public9＋Huihui4現物を対応。独立最終重要0、機能/配備/G/37tests再実行0。T29古いpending/失敗proofは履歴で保持、T30を追加依存化しない。現在30/47元task scope完了。
- T30 pre-r3 SHA6be2c727b40f98acfacda7a2a03ba861004f06a6fcf16a326dd1f3cc719992e4は独立重要0/Main承認。13sourceをCPU/TDD実装、development3/verification.json SHA48750606eef06aee453c829d364a769ca31f643218227d14e11d9071a33e5fb4は新17＋既28=45GREEN/current HuihuiV2 4profile/layout/default・保護10profile/guard原SHA不変を確認し独立実装review中。既旧IQ4名を必須にするtestmoduleはbaseline KeyError/旧mirror不在であり、削除済modelを再登録して通したり全suite成功と扱わない。
- 新helper2は通常installed OWN/control/deepseek_launch.pyとdeepseek_bootstrap.pyを読む計画、現まだ配置0。通常09a17package/provider3/6profilesは不変更。実CPUでvenv直接spawnはroot/actual子PIDが分かれるため、従来BASE_PYTHON13argv＋child-only __PYVENV_LAUNCHER__=selectedvenvを保持しroot=writerPID/実prefixを確認。Lowhelperは別のredirector/actualbase二重identity検査を維持する。READY/reuseのINFO実在context/予算/容量をstrict照合し、INFO未提供bundle/epoch/PCIはnull、freshowned exactargv由来と別bind。optional psutil/integrity診断失敗は旧同等catch/nullで返却processを失わない。実selected Lowhelper/Stage/MCP/CLI/stop/新環境modelはまだ未資格、同wave固定review→必要実入口へ続行。
- T35は既T28capture CPU観測のみ追加。sameattempt startup0→finalのprimary requested37947244544B/602261logicalread（平均63007.97B）、SSDmiss60533/GPUhit13253/RAMhit1842。send→firsttoken2108.782秒/生成1IDでTPOTnull、physical帯域/原因はunknown。normal生成recipeはRelease/-O3/元nonFMA等を確認したが性能原因を断定しない。sky13/C4096/max3のpending pilotへこの機能caseを転用せず、長G前に必要最小計測条件を再確認する。envはT44承認実装、Core/producer同fileはprimary作者変更0。通常制限/新SLO/他consumer停止0。

### T30実Low/Stage・通常CLI READYとT35小host診断（impl71）

- T28/T29元scope完了、30/47は維持。T30 pre-r4 fc805b61…の13source内でR1実INFO/argv対応、R2optional診断例外、R3親processのfamily import状態漏れを修正。親/Low検査だけscoped importをfinally復元し、実server子のselected環境を維持。development7/verification.json SHA086698b7955820b1235c791a8cb628ed86b786bdbbffc60fab7b415cfdea6afdは新21＋既28=49CPU、source13/snapshot13/protected17一致、独立最終重要0/Main限定受理。
- installed helper2はknown旧SHA→新exactへ更新し、publication-r3 7aefe478…に保存。low-stage-attempt-1.json SHA44485694103b7e53bf5b831381e445a401d4983a9699c6a48f826c03ea6a5d66は実Low RID4096/redirector＋実base両出生・退出、同parent BASE13argv/root=StageWriter PID/birth、forgedparent birth実child exit1の2case。独立replay重要0/Main限定受理。legacy TEMP pin/hip_env_guard/ACL/期限は不変更、selected manifestの唯一preparedserver row path/SHAを照合する同13source補完でありguard追加・弱化なし。
- 18080は別管理StrataMod/HuihuiV2の稼働中で、attempt2はforeign保護で拒否しDATA所有へ昇格しなかった。その後ユーザーが本件のStrataMod停止と検証継続を明示承認。fresh root11872/birth・listener9004親子・health一致後に専用StrataMod.cmd stopを1回実行、対象4出生gone/survivors[]/portfree/status runningfalseをauthorized-stratamod-stop-1/verification.json SHA7c476cfd7789c3dea20a0862014f9890d75e75ce848d7d12ab3e3d92bff3eccfへ保存/Main確認。一般の他consumer停止許可ではなく、手動forcekill/別port迂回0。旧履歴の他consumer停止0は当時の記録として保持する。
- attempt3は通常MCP→BASE/Stage→selected新owned Python/tokenizer/Low/native→loaded/APIに到達後、作者managerがbusy-only /statusからINFOを誤読してREADY照合失敗、既cleanup完了/生成0。原attempt/state/logを保持し、実Service.metricsのengine.infoを返すJSON /metricsへ最小是正した。guard緩和・新native/package/数学変更なし。
- normal-cli-attempt-4/startup-verification.json SHAe9ce2c3d2948565b14b4d4cd3d15381cb4530ec8466327e171c5d758ec26ef0dで通常CLI C4096/defaultauto READYを観測。freshowned native exactargv/positive epoch/INFO context・予算・容量を照合、INFO未提供identityはnullとargv由来を分離。同processの通常HTTP4入力ID/max1は進行中で最終出力・stop/次操作・最終review未了。controllerの事前encodingでcanonical modelをRecipeへ直渡ししたCPU失敗は保存し、実Serviceと同じmodel=strata正規化後4ID一致、HTTP要求はcanonical名を維持。native送信前のwrapper補正で製品source変更0。C4096/max1は本試験条件で通常上限ではない。native raw IDの直接captureは本外部HTTP caseでは行わず、旧T28の原4482/DTOと不変binary/codecを別参照する。
- T35 host-io-pre-r2の同wave小fixtureを実装。missing validator RED→21CPU GREEN（原20＋host literal1、6意味変造拒否とfallback非clean）。build.json SHA4ce1da9d9293b78cd3ae414dcc16f002d06628ee5e19fde4b29128bd25701ade、host-io/attempt-1/verification.json SHAb818d3d9087519346f36ea7bea54d80b842748c65d3f83341b75812a8bbf128e。既T17 SpanProvider/依存を別snapshotからcompileし、通常Core/Primary/Row/lease/normal CMake変更0。原file1先頭2MiB（header/payload混在）を独立事前RAM期待/SHA→stdin→ABBA各全byte一致→事後原本readで照合、useful8MiB＋事前事後4MiB/logical計12MiB、原本currentidentity不変・raw保存/GPU0。A32direct/B1direct、各requested/received2MiB・errors0/outstanding1/try_close、explicit RAM期待2MiB＋出力2MiB＋buffer＋provider metadata最大6292437B。これは全heap/OS/内部allocation/physical peakではない。
- ABBA host lifecycle秒はA0.0091893/B0.0013659/B0.0014103/A0.0079991。chunkとprovider lifecycle回数の両差があるため、今回のhost overhead切分け材料に留め、maxchunk単独因果・物理SSD帯域・全model遅延主因/改善倍率を断定しない。独立21CPU/捕捉値再生・意味負例/source/EXE/元identity照合で重要0/Main限定受理、追加read/G0。元T35 sky13/C4096/max3/paired通常性能は未了、T30の4ID/1出力を性能PASSに転用しない。
- T44はenvironment担当単独でlive Core2/CMake/worker等を実装・CPU/fixture固定中、実新mode G資格未了。T30のinstalled09a17/native1204は不変で当該live編集へ依存しない。通常機能/選択/default/guardの縮小、SLO・新gate追加0。T31/T32のread-only接点整理は実行中T30 source/package/configに触れず先行可能だが、完了依存は維持する。

### T44元scope完了・T31/T32承認CPUとT30通常request継続（impl72）

- Main完了受理は31/47。T44 final-r2/verification.json SHA5c5c6de45ba14ee70cee80a45f359e41a7a61417048ccb3256849a447aae4ca8は19anchor独立最終重要0。5micro465920値＋全40/120frame16057056値が事前Qexact、355S365P/720adopted/1065copy、両bounce leg14542220B、lease141pipelinepairs/取消error/shutdown→freshとrequested device26342453Bのalias会計を確認。peer直送/physical同時性・T46通常mode切替/速度・T47draftgraphを成功へ広げない。
- T44 full40実capture477a3e0f…の319.11秒はT30との明示shared・異workload/SSD/free/物理非隔離の観測のみ。T30 installed09a17/native1204とT44新liveCoreは別source/output/TMPで、当回T44 GPUwindow終了を別receiptへ保存。T45pre-v2は独立重要0/Main13source GOでenvironment単独実装開始、まだ実layer-split/実tap/draft成功ではない。T44保持1430329012Bはfreshfree算入済み、将来旧1GiBを32MiBへ置換し再控除しない。
- T30 attempt4は通常CLI C4096/defaultauto READY→新owned環境4prompt/max1 HTTP200「您」/LPtop3局所2ULP/count1へ到達（330e1b0b…）。同PID/birth再利用→通常stop→status/modelsで選択操作へ戻り、owned出生全gone/18080listener空（6dde6e29…）。2289.218秒は機能caseの観測でTPOTnull/性能false、外部HTTPから実PP/rawIDを直接観測したとはしない。source13/helper2/package/profile/保護17不変、統合normal-cli-final-r1/verification.json SHA06b73b232b164f5bf46502dd1d39eaa6322b89eec1db0c809d3dfd53a7872687を独立最終reviewへ。Main全T30受理は未了。今回ユーザー承認のStrataMod正規停止1回を一般の他consumer停止許可へ広げず、試験context4096/max1を通常capにしない。
- T31pre-r2 227717d7…/T32pre-r1 826e0adb…は独立計画重要0/Main承認、稼働T30 source/profileを侵さない新OWN CPUだけ先行。T31 parser6source component f0b827b9…は7Python＋Node literal独立重要0/Main限定受理。derived chat最小patch/通常選択を保持し、制御HTTPの成功2turnとEOF失敗後の履歴非commitを実derived mainで追加、component3 b8a5141c…は11Python＋Node GREENで独立review中。実通常chat/WebUI/provider/新immutablepackage/公開6profile更新・wholeT31/T32は未了。
- T35 key-hoist-pre-r1 f9b3c3f8…を独立計画reviewへ。Primary SupplyMatrix::key()を各device/RAM slotで再生成する現物と通常7745/15262slots対旧2slot fixtureの差を仮説として記録。immutable lookup内keyをloop外1回へhoistする5source案、原本read/G0のmetadata小ABでkeybytes/先頭index/hitmiss/比較count同値を検証する。Primaryはenv単独writerで現実編集0、新map/registry/通常cache予算縮小なし。主因/モデル改善倍率はunknown、旧遅いcapture/1204を保持し、sky実pilot/paired性能は未了。

### T30元通常入口完了・T31 CPU修正受理とPrimary最小hoist build（impl73）

- MainはT30 normal-cli-final-r1/verification.json SHA06b73b232b164f5bf46502dd1d39eaa6322b89eec1db0c809d3dfd53a7872687を独立最終重要0/94path・49CPU/元DoD対応で完了受理、T44と合わせ全体32/47。通常CLI→既MCP/LowRID4096/同root Stage→newownedPython/09a17/native1204/C4096 defaultauto READY→HTTP200「您」/length/count1/LPtop3局所2ULP→同PID/birth再利用→通常stop後cohort3出生gone/portfree/status/models復帰を実証。元失敗・限定承認StrataMod stop1を保持。2289.218秒はT44とshared非隔離の今回機能case観測、TPOTnull/性能未資格、他context/mode/画像/全clientT33へ広げない。
- T31 component4のR1は共通parser受理と旧1data行表示parserの分岐によりmulti-dataの本文を落とす不具合、R2は途中parser例外後の当該reader解放不足。旧4/5とREDを保持し、feedから検証済みassembled eventを返して既表示/MCP/usageへ結び、当該AbortController＋reader cancel/releaseをfinallyへ追加。component6/verification.json SHAba81690faa305b30fc930c8862f6b84e628aa4efe1b5494f2f823e07c9b3b651は10source/55refs・独立11Python＋Node literal/actualsend6case重要0、R1/R2解消/Main CPU限定受理。multi-data/CRLF/coalesced/content+finishとreasoning/本文を次promptへexact、malformed未読tail→当該解放→次request正常を確認。実browser/provider SSE/新package/6profile公開・wholeT31は未了、T32実SDKは未実施。T30依存成立は新成功の代用ではない。
- T35 key-metadata-ab-3/verification-CPU.json SHAabb3126f7cf2770c3b1b6d852ba907f65bb7713e4b3f5d579e6c64391a38d06fは独立22CPU/8意味変造拒否・120ABBAarm/30case/314keybytes重要0/Main subset受理。元actual key定義全byte/9field変異/Unicode path・device2/7745/RAM2/8768/15262で検索結果/hitmiss/比較count不変。7745miss A9.80/9.91ms対B.0123/.0120ms、RAM15262miss A19.85/19.12ms対B.0434/.0257msはhost metadata診断だけで、モデル主因/改善倍率はunknown。原本read/G0、ab1 includeclosure失敗/ab2 fixture余分stringcopy発見→ab3 directconst比較是正を保持。
- environment単独writerのPrimary before8bcc3e2c…→after809ec404…はhit/start_fill入口key各1回/二loop比較のみ、RAM予約/Fill mutation前生成、数学/lease/cachecapacity/Row不変更。key-normal-native-1/verification-build.json SHA3cdc40e45b229f006b969f38b11e5c77c6431b1d1f00b3d6f7cb5eaf05bcd825/manifest b3d7d280…はaccepted normal1204 immutable58＋旧CMakefaa3b20b…＋Primary1deltaだけで両archbuild/identity成功、declared39差1行・572unique参照/T45 live0を独立重要0。newEXE142c4dac…はまだ新owner/modelG未資格で、旧1204のG/性能成果を新IDへ流用しない。
- T31承認liveSSE4IDs/Q86c7を新candidatepackage/newnativeへG前bindし、実cold/hot/転送counter/loadedDLL/前後sourceを同captureで必要実証する方針。独立reviewはこの範囲に別owner小Gを機械追加するgap無し、未観測tierや全request H2D0を要求しないと確認。公開6profile更新前に必要scopeを閉じ、T35whole性能をT31新DAGへ追加しない。prospective input候補は60copy169143884B/15cb03c0…で未公開、helper/最終filelist/code固定後の最新版IDと通常pathを同wave reviewへ渡す。
- T45は独立pre重要0/Main13source GO、environment単独で6CPU/初回Core API両archcompile/link。早期valid R1はinvalid後target採用/downloadをvalid predicateへ是正、retire/drain borrow保持は不変。controller stub/実copy-lastuse-cancel-fresh/Q会計seal/Gは未了で、元T44/1204資格から分離する。T31/T35新native以外の通常cache予算・model/context/guard/性能SLOを縮小せず、commit/push/PR0。

### T31候補package・実SSE保存とbrowser後日確認（impl74）

- Main受理は32/47を維持。T30通常CLI/manager、元T44 expert-assistを含む既完了scopeは不変更。T31 component9 b6d74399…は旧09a17で旧chat argvを保ち、新client_extension宣言だけselected entryを使う互換修正を独立13Python＋Node6/19runtime CPU重要0/Main受理。未知packageや新宣言のmissing/tamper entryを開発ROOTへfallbackしない。
- package-candidate-r1/verification.json SHA0ca6da0c86760314872a5a356aa732ebddb463184204e2a14176be51ed630f36は独立最終重要0/Main候補CPU scope受理。60copy169143884B、親55の53同SHA/EXE・app2置換/clients5追加を明示し、新15cb03c0…へfinalpath新venv/固定base/Recipeを組立。manifest740file、実234854318B、poison環境の-E/-s/-B/空cwdでentry/help/chat/pip/probeを確認。公開6profileは旧09a17のまま、既Huihui/default不変、候補CPUをmodel数値へ昇格させない。
- ブラウザ小fixtureはroot/child可視ページに対するautomation routeが露出せず、ユーザー依頼retry後もgeneric CUA一覧[]/iab unavailable。明示Browser pluginの公開setupBrowserRuntimeも正規MCP Node REPLで初期化成功後、child browser一覧[]/rootはMCPApps tabs0のみ、iab unavailable。r5 verification-unavailable.json SHAa6660a038bdb87f2fc280cabfc1f7bb6af48159a44084c4b30b2e5902a8783f5に実結果/正規fixture終了を保存。根本登録理由未確定、設定変更/認証回避/CDP/native迂回0。
- ユーザーが『ブラウザ検証はスキップする・あとでまとめて動作確認する／ほかを進めて』と明示。今回browser実操作は後日まとめ確認へ延期し、未実施をPASSにしない。元T31 DoDは実provider SSE/EOF/cancel/遅延commit/旧履歴/通常選択で、実browserは同preで選んだ方法だったため、browser-method-addendum-r1 cbac054b…を元DoD不変の検証方法差分として独立重要0/Main受理。component11 da380901…は採用store.get/set→strata.chat保存/reload・旧untagged/new incompleteと次prompt除外、実stop handler→当該controller/reader回収、render/updateへ渡るpartial/stopped/error payloadを13Python＋Node6で独立確認。可視描画/実クリック/browser固有storage/ReadableStream/DOMは未確認のまま。
- 新nativeはaccepted1204 immutable58＋旧CMake＋Primary1hoistのみのb3d7d280…/EXE142c4dac…で、T45 liveCore/CMakeに依存しない。actual-sse-attempt-1 manifest SHA3b4e342fa25bd924a9b308feecb433d77e6bf2155b1dfd7fc76e6dae20aa0ab8をG前固定し、runtime740/Model9 currentidentity/Q86c7/actualconfigをbind。freshCLI停止/native0・environment当回window ACK後、selected新owned Python→実preparedserver/hooks/実native/既Service/HTTP SSEを1回実行。C4096/defaultauto/4原IDs/max1はこの試験条件で通常capではない。他consumer停止追加0。
- 原token_batch ID4482/LPtop3局所2ULP/length/finish hash/count1/DONE・実SSEを保存。harness生成時の非ASCII期待literal文字化けでtext assert失敗し、その後のfinally記録は既close後proc=Noneの.poll呼出で失敗した。原run/manifest/failure/SSEは保持し、走行source書換・同4ID再G0。Unicodeescape固定の新CPU revalidation-r1/verification.json SHA4140ce111b893ed35e6c707b2f7194c52dcaa3b52004e61b85229c52d1f68f28で原SSE7byte分割→採用parser、您/usage4+1/原ID/LP/hash/DONE/actual DLL/runtime/Model9 metadataを作者再照合し独立review中。保存出生のgoneと隔離endpoint接続拒否を実観測、native returncodeは未取得null。final INFO前assert失敗のため最終read/hitcounterは未観測nullで旧/期待値を埋めない。
- startup実autoはdevice7745/RAM14671・row976543/1849842、device owned16539616982B/host owner subset31350313008B。requestclock→原first tokenは302.906秒、1出力のためTPOTnull。今回機能case固有の観測であり、正式paired性能/旧非隔離caseとの速度比・全T35完了を主張しない。actual-client-replay-r1 97f8de4e…は保存した実SSEをselected ChatStreamとderived実send/apiMessagesへCPU再生し作者GREEN、独立review中。実browser成功の代用表記にはしない。
- 公開関数は承認同waveのknownold6profileだけを対象に実装中。component12指摘R1はnumeric config row実size/SHA未照合、R2はstagedtempのfsync失敗時回収不足。component14 f03e44c7…でconfig一意/rawSHA/欠落重複改変拒否、open成功直後ownedtemp登録/foreign temp非削除/失敗後次正常を16Python＋Node6で独立重要0。まだ公開0。実SSE必要scopeの最終review後にknownold6→新packageへ明示更新し、通常chat/WebUI HTTP/quit/status-stopの元必要接点へ進める。通常起動ごとの新receipt gateは追加しない。
- T45はenvironment単独writerでcontroller/full/small transport/APIcancel/tap fixture初稿両archcompile・synthetic2244stage/15boundary/16057056値positive＋136拒否まで。正式source/Q固定reviewと実Gは未了。T32は承認計画の実装未了、T33全client/他mode/画像/性能・DSpark実draftは未資格。commit/push/PR0。

### T31元接点完了33/47・T32 pure CPU着手（impl75）

- MainはT31 final-integration-r1/verification.json SHA8c0af05941a6e66a32ef66366081db33f514221de66d2a262844cf8cc7080272を独立最終重要0/895refs859unique・15anchor/740runtime/source12＋snapshot/公開6/normal31filesと元preDoD対応により完了受理。全体33/47。actual SSE4140ce11…/client replay97f8de4e…/publication394a59c6…とusual9edae3d9…を別bindingで統合し、元harness failureを新成功へ書換えない。
- 新15cb03c0…/nativeb3d7d280…の通常CLI C4096/defaultauto READY→selected chat /quit exit0→実HTTP index/appが採用package全byte/ContentType一致→正規stop/status/models/cohort3出生gone/portfreeを実証。usual web dispatchは元owner guardを通し、ユーザーのbrowser skipに従いopen callbackだけ制御して実表示/クリックは実施していない。今回通常入口の追加model request0は保存metrics requests0/output0/corepos0/read0で確認。実モデルSSEと両実parser/履歴への再生は既1回を利用し、同4ID再G0。
- 公開6profileはknownold→新exactへ更新、旧09a17 package/旧T29/T30 proofを保持。Huihui4/default/catalog/provider3/installedT30helper2は不変更。ブラウザはユーザー明示skip/後日まとめ動作確認、可視描画/実クリック/browser固有storage/DOM成功を主張しない。T33の全client reasoning/tool実往復、T35正式paired性能・final request counter/旧SSE native exitcode未知は別scopeのまま。
- T32 pre-r1 826e0adb…の18source承認範囲でnew clients/runtime_binding.py・family_policy.mjsとtest4の6sourceからTDD着手。missing helper RED→3Python＋Node pureGREENをpure-component-1/verification.json SHA247088a3bfd16541271d9c3c8571c2b2bcc2a8af15d04fa87e73b3421977effdへ固定し独立早期review中。任意合法context/preset分離、canonical＋宣言alias、SDK7level正wire mapとserver ultra保持、呼出側のfresh manager observationを渡した場合のepoch/config/native birth正規化とINFO identity nullを扱う。既DATA/Pi/Harness12sourceは前後SHA不変、installed helper/settings/session/credentials/vendor/node_modules/G変更0。実fresh authority/tool execute hook/SDK transportの接続は未実施で、helper純CPUを全T32へ昇格しない。
- T45はenvironment単独でfixed-r2正式G前reviewへ提出（manifestca1409f5…/2848bindings・両arch/host68/synthetic full179＋small72拒否/各正例）、実G0。T35 newPrimary purehoistの必要数値はT31実SSEの独立重要0/Main受理で成立した範囲のみ。旧602k logical read/64KiB lifecycle hostAB/PP165広域分布を原因断定に使わず、次の性能は元sky長Gを盲追加せず最短のcold/warm・N>=2 actual TPOT pilot条件を同preで具体化してレビューする。通常予算/context/出力/思考/retry/compact/guard/公式既定の縮小0、commit/push/PR0。

## 現在の追加状況（計画impl76）

- MainはT45元layer-split component final-r1/verification.json SHA0beee42a63e646c2905b1d82e799d20780f0e503494e9db68b56401393caefa6を独立最終90b09bea9f3da1016dd0cc5e33f4cb473bfe12af4827d895eb47df16ca9fdb41重要0と現物読戻しにより完了受理。全体34/47。全120frame16057056値/境界65298値、small transport auto/bounce各17924値/API20484値/cancel-prefix fresh20484値が事前Qexact。P14550069B/S11837045Bのowned/会計・15copy253512B・state寿命を適用scopeへ結び、通常CLI modeT46/実draftTapT47/性能/peer/physical同時性は未資格。
- T32 integration-component-2/verification.json SHA325e5148901d7e2e976c5b143e4f8d9a792e1fb05b65b2c8645a5886ca7307bdは18source/旧12before/installed2/保護profileの現物対応、独立8Python＋Node実Pi policy/nativeargs/subagent/audit/tool callback・Harness tools/execute制御tests重要0/Main CPU限定受理。pure1のobservation epoch/n_ctxがTrue/1.0を整数と等値受理するR1はtype intを境界で要求して解消。旧247088a3…を修正版成功へ書換えない。通常任意合法context/SDK7levelとserver ultra/既Huihui/default/retry/compact/権限委譲を保持。
- actual-sdk-addendum-r1 SHA5129e5746b23967b14a5e58fa7ed5f4db7b05defca4489b05e2f96314999e3a3とsdk-input-r2 bf97904d…は独立plan/inputCPU重要0。実pinned SDKのfetchCaptureはネット接続0のCPU調査で、両bodyをselected15cb03 Service.prepareへ通し原4IDs/thinkingfalse/temp0/top_p1/max1一致。実provider成功ではない。DSH既定300000msはsemantic chunk待ちでstart非yield/PPコメント非pulseとsource確認、既T31単発302.906sから今回のtimeout失敗を断定せず、通常300s/vendor設定を変更しない。
- env当回soleGPU ACK後、actual-sdk-attempt-1/manifest.json SHAbd17ea206810a3d40175a35e9e634a7bac7b369f65c79f063cbc6c997ba49003を固定し、通常CLI C4096/defaultauto READY/実Pi launch --check成功→Pi実SDK requestを実行中。runtime740/18source/installed2/SDK entry・locks/Model9 metadataを固定し、T45 liveCore/CMake非消費。keepalive受信は本文/終端成功と区別、現在はPi本文未取得/DSH未実行/最終cleanup未了。C4096/max1/offは有限試験内だけ、通常limit/公式既定へ昇格しない。
- 走行harness先読R1はfinallyのoptional after-owner INFO観測例外がusualstop/後続記録を飛ばす一般条件。走行bd17/sourceは不変更・中断0。別cleanup-recovery-r1/verification.json SHA9445fc0fd50fb894ef310a19b17f059197905277bf5e5c097e47a4b2d84e15efを4CPU正負で固定しreview中。samePID/birth＋通常ownership成立時だけ正規stopを独立試行、foreign/unknown owner停止0、原SDK例外保持、後続source/cohort不明をnull/unknownで別保存。実cleanup済みと仮定せず、同4ID再Gをこのwrapper条件のために追加しない。
- T22は元責任内でproduction packedcache接点＋CoreProjection/normalproducer cache-only実route/profileRoleの最小実装/実証も必要と明記。T21 copy primitive/T44 secondary計算はstorage-only providerの代用ではなく、environmentがread-only pre作成中。新task/gate/registryは追加しない。
- T35はpurehoist/新native必要数値の受理範囲と正式paired性能を分離し、既counter/PP/hostABだけから原因・速度倍率を断定しない。次pilotは最短公式入力でcold/warm＋N>=2 actual TPOTの必要最小条件を同pre追補してから実施、元sky13長Gの盲追加0。ブラウザはユーザー明示skip/後日まとめ確認のまま、追加browser調査0/未実施PASS0。T33全client reasoning/tool、T46/T47、性能は未了。commit/push/PR0。

## 現在の追加状況（計画impl77）

- MainはT32 final-integration-r2/verification.json SHA3bf061ab73a23071fc244041792862a64dff00b1d1c8a5e82347f1760ed20409を独立最終重要0/867unique・8Python＋Node/元DoD対応で完了受理。全体35/47。actual-sdk-attempt-1/verification.json SHAa478e6a780c73f9c77444cb118822d36e8fd442c12d78a048f130b7a4d2ec46eのPi/DSH実pinnedSDK各1要求は両HTTP200/本文您/length（DSH max-tokens）/usage4+1/DONEと通常check/正規stop/status/models/cohort3出生gone/listeners[]を保存。SDKに未提供の原生成ID/LPはnullで、期待4482を本文から逆算した観測にしない。rawSDK firstcontentは280.1566693秒/215.6443751秒の当機能case観測のみ、TPOTnull/性能未資格。DSH既定300000ms・通常server300sは不変更で実完了した。
- 最終レビューR2はPython epoch1792568209599735400がJS Numberを通る際に丸められ、公開assertSameAuthorityもsafeInteger条件で同authorityを拒否する不具合。epoch-lossless-r1/verification.json SHAa02cc20803ab94d6fe273f5a742eb94da57f4e3304bd4f1e9331b472c68562bcでnewhelper2/tests2＋installed2だけを変更し、Python側strict positive intのmanager/observationとfresh native argv decimal一致からcanonical decimal stringをfamilyAuthorityへ渡す。JSもstrict string/argv対応・隣接epoch/unsafe number拒否を確認。元4bindingのPython fingerprintをsaved exactint＋freshnativeargvから独立再導出し原保存値と全一致、新decimal authority/newfingerprintも別CPUで一致。丸めた値をstring化して成功にせず、旧raw/capture/旧finaldbea…は履歴保持。同SDKモデル要求の再G0。通常epoch/native/API契約は変更しない。
- actual runの一般cleanup R1は今回の成功経路では発生0。旧走行runを後付修正版にせず、別cleanup9445fc0f…の4CPU正負/独立重要0/Main限定受理を併記。optional観測失敗が正規stopを飛ばさず、foreign/unknown ownershipは停止0、原SDK例外/後続unknownを別保存する。T33の実model reasoning/tool・全agent/通常activationはこの空入力SDK成功へ拡張しない。
- T35 minimal-pilot-addendum-r1 SHAda503fe947a44fbf0c6e1064230ea58314e369d482a9f136128852867e4b9dfeは独立計画重要0/Main承認。元sky13/max3を最短公式4IDs/max2のapp-empty A→同owner/freshCore warm Bの計2要求へ替え、通常budget/context/output等は不変更。23CPU RED→GREENでshort contractとstdout/stderr pipe closeを確認。input生成のmissing model/tuple比較/buildoriginコピーpath対応失敗はCPU履歴に保持し、normalnative/Modelへの変更0。
- 実行前review R1はnative/6DLL/Model9 currentidentityの事後検査とINFO実loaded path照合不足。minimal-pilot-CPU-2/verification.json SHA0d5037159e4a18e0e4289ac64b4736a5ff417a0d89b07d9de74dfac614552e53でwrapper内にnative bindings/Model9 stat前後と実INFO3ownedDLL path/SHA・未観測nullを追加、24CPU RED→GREEN。旧seal3d6614ad…とsnapshotをexact履歴保管しhistory-map67c473a5…で元pathとの対応を明示、新pilot-seal.json SHA1b0cfabde82044d37fe333383efeb307d231aaf3d624396c620d0d678ff5b2d1は独立再review中で実G未開始。新nativeを作らずinstalled15cb03/b3d7とimmutable originを使用、T22/T45 live変更は非消費。
- T22はproduction packedcache＋CoreProjection/normalproducer cache-only route/role実証を元task内で閉じるpre25f33c41…が独立0/Main18source実装GO、environment単独writerで初段CPU/descriptor準備中。現livePrimary/Core等はT22未資格差分を含むので既accepted normal/runtimeと混同しない。cache-onlyはT33から分離、両compute方式の通常資格T46/最適化結合T47の責任を維持。
- T35 formal paired性能はpilot観測後の同wave事前契約まで未了、T33最小計画はこれから。browserはユーザー明示skip/後日まとめ確認で追加調査0/未実施PASS0。通常retry/compact/tool権限/default/Huihui/原本を保持、commit/push/PR0。


## 現在の追加状況（計画impl78）

- Main受理済み35/47を維持。T32 latest3bf061ab…は元SDK transport/authority component完了、実model reasoning/toolと全client activationはT33に残る。T33 pre-r2 SHA5f7e6a1a68144fcaad7be80aaace5a8c76e81bbf7024412df201dcab081cfa93は独立重要0/Main14source実装GO。Pi public message_end replacementがSDK保存/tool実行より前に適用される既公開接点で、応答中epoch変更/観測不能のpartialをabortedとして保持し次contextへ混入させない案を含む。通常retry/compact/既完成履歴と旧untaggedを保持。actual body/原prompt token数/生成上限/semantic初出とMCP coverageは同wave実施前固定が残り、制御CPUを実model reasoning/tool成功へ昇格しない。
- T35 pilot-run/verification.json SHAfa82382067954d579620fb69c57c739dc5522003dd974b5f60e633af7c4ff2b8は独立重要0/Main pilot限定受理。旧通常RAMauto .5/row1/64条件の1pairで、A/B原IDs各[4482,55753]/count2/length/DONE一致、同owner PID28480、pipe TTFT286.9379155/224.6427218秒・TPOT71.0798401/64.3814342秒。元DTO・617native bindings/Model9stat/INFO実3DLL/counters/actual budgetsを前後照合し、QUIT/exit0/native[]を保存。正式CIやhoist因果/倍率/物理I/O成功ではない。
- ユーザー直接指定『測定・検証ではDRAMメモリ使用量を残りメモリ量を８ｇｂになるまで消費して測定しておいて』を今回以後の試験条件へ反映。measurement-contract-pre-r2.md SHAcb153db293cdba8b8c35b7004bdab953fcdb915181bf787c6318194b4b1c92e7はMain読戻し/独立計画重要0。同model RAM cacheの試験explicit payloadだけを増やし、target8589934592B・観測評価帯8..9GiB・配分aim8.5GiBで実availableを判定する。通常profile/default/device auto/生成枠は変更0。旧pilot/旧proofを8GiB条件へ遡及変更しない。
- noGEN minimum owner較正もHIP/巨大DRAMを使うためT22と既資源窓で排他、帯内minimumは採用可能、初候補＋最大2回のchecked再選択だけ。GEN中追従alloc/filler/追加他consumer停止0。explicit RAMは既countsでweight/row同slot floorとなり、旧auto row配分との差をreportへ記録する。zero-init cache capacityとvalid model payload/hitを分け、payload/commit割当だけでresident/actual available達成としない。構築後/GEN前後/10秒monitorの全必須観測点で帯内の場合だけ『観測点で達成』、missingはunknown・帯外は条件未達、連続保証0。
- 同4sourceで3AB/6要求・pilot除外/df2 paired-log t95/precision式を実装中。formal-CPU-1/verification.json SHAb5bf5ca81115cf021b4b32aa83a0a6a83d4f59a164a53dfcf9025c18e6c0960cに初期RED→33CPU GREENとbefore/snapshotを固定し独立実装reviewへ。Win32 GlobalMemoryStatusEx availableとEX2 WorkingSet/PrivateWorkingSet/PrivateUsageを別採取、API失敗null/birth不一致・有限較正/monitor cleanupをCPU確認。自身の小Python processのみでEX2成功を確認し、巨大RAM owner/新native起動/正式Gは未実施。formal input/seal・資源窓・各pair実観測・最終reviewは未了。要求DRAM条件未達pairを除いてCIを作らず全CI未判定にする。
- T22はenvironment単独でproduction cache-only route/fixtureを実装・compile中、DRAM同条件の追補を同wave固定済み。livePrimary/Core等のT22差分はT35/T33 installed15cb03/nativeb3d7へ混入させない。ブラウザ可視操作はユーザー明示skip/後日まとめ確認のまま、追加調査/未実施PASS0。T35正式性能/T33実reasoning-tool/T46/T47は未完、commit/push/PR0。


## 現在の追加状況（計画impl79）

- Main受理35/47を維持。T33 pure-component-1 ccada694…は3Python＋Node/旧履歴とlossless tagの純CPU限定受理。Pi message_end接点はpi-commit-CPU-2/verification.json SHA0a31087de9dd9ce0ac3049332d96289906267db835e9778395ad494276fc2013で実ExtensionRunner→AgentSession in-place/listener/SessionManager保存とrunAgentLoopの制御responseを確認し独立重要0/Main CPU限定受理。same tool1・stale/unknown tool0、partial aborted保存/次context除外、legacy/user不変更。production差分はPi guardのfamily assistant限定hook、SDK/vendor/settings/G0。実model reasoning/tool成功とは呼ばない。旧035347…の実policy/session-manager body閉包不足は2body追加のproof-only補完で、元版は保持した。
- T33 service-CPU-1 c5b84aff…はnew runtime_identity.pyからstrict launch int→canonical decimal HTTP tagを作り、Service.metrics/openai_chunksへ薄metadataを付けるunitを追加。6Python GREENだがfake Service/generatorでの元field/引数/None/unknown INFO/legacy保持の範囲で、実preparedserver・新package・各consumer commit/activationは未接続、独立review中。actual SDKの最短system/tool body/原token数/最初semantic時点/終了条件/MCP coverageも実施前固定が残る。
- T35 formalCPU3/verification.json SHAa60e6371f5cda92ee5e6f11d023684d6e72f1d278b91f9e44d2e692c179efb75は38CPU/旧pilot replay・独立重要0/Main準備subset受理。R1 physical global status/null/PIDbirth/点順序、R2 derived precision∞、R3 worker例外点省略、R4 selectedowner/command/budget/context/workload/raw/closed joinを修正。exact measurement-seal SHA202d82378aca84249a75fa7d3d729edf032f07c50caaa1fff2b2a30a39c5798cの重要0後、当回env sole資源窓/freshCLI停止/native[]で旧strict pair0を実行した。
- 旧pair0はminimum→RAMtarget56988769384B/実payload56986792720B・weight=row27170へ1回選択し、constructed available9396719616BでA開始。Aは原IDs[4482,55753]/count2/length/DONE、pipe TTFT243.5804608/TPOT51.1501438秒。保存monitorで帯外となりB-before14311936000Bの既strict guardがB GEN送信前に拒否、harness exit1・native正規QUIT exit0/CIM[]/usualstatus停止。engine crash/メモリ目標達成とは扱わない。postclose-CPU-1/verification.json SHAd6fffa471bb11796a6743dd2461e599a94edefaca030731501848cee64ed9d3fは原失敗/source不変更・archived DTO/clock・617binding/Model9stat/実3DLL・33memory点・終了を独立重要0/Main限定受理。A数値と条件false/B0/不完全pair/CI0を区別する。
- ユーザー最新明示指示『厳密にしなくても良い 続けて』により、DRAM残8GiBは目安/運用上の目標へ緩和する。新measurement-contract-pre-r4.md SHAdfb804f41895d978a4ad145792e8845327b099bbe82f444256f9178afae169c7はMain全文読戻し・独立review中。fresh availableから試験model RAMcache候補を1回選び、実available/privateworking/commit/変動をreportする。8..9GiBの参考帯外だけでGEN拒否/中断/metric・CI無効化はしない。正数/overflow/owner/閉包と数値・clock保護を保持し、通常profile/default/device auto/生成枠は不変更。固定30秒settle案r3は未実装の草案として保持し、原因特定/settle保証/全点帯内を完了gateにしない。無目的filler/追加他consumer停止0。
- 旧pilotは旧通常auto .5、旧strict pair0は当時の未達/B0記録として保持し、新条件の成立pair/CIに混ぜない。新approx-8g-r1有限dirへ正式3AB/6要求を事前固定し、帯診断とpaired-log df2 CIを分離する最小4source修正を同wave review後に進める。現在正式完了pair0/CI0、資源窓はenvへ返却/native0・大RAM解放。T22は同緩和へ同期し、liveCore/Primary等の未資格差分をinstalled15cb03/nativeb3d7へ混入しない。ブラウザはユーザー明示延期/後日まとめ確認、未実施PASS0。T33全体/T35正式性能/T46/T47は未了、commit/push/PR0。


## 現在の追加状況（計画impl80・当時のcheckpoint）

- Main受理35/47を維持。T33 client-stream-CPU-2/verification.json SHA334fad06d9f6784de455b75ecc2ee8a9f3ad77a68791f42a2771c90b38ab7264はoptional HTTP runtime identity/stream終端/commit直前照合と旧default parserを独立8Python＋Nodeで確認し重要0。旧15Python/actualsend6の実body2をproof-onlyで追加、T22変更により旧candidate入力のlive sourceが変わった1caseは明示除外し旧失敗を保持した。chat-identity-CPU-3/verification.json SHAb711dd3f2bc9337e7dff25aedc23c98aee0e8204c853421eae6f9cbfb4738b97は独立12Python＋Node重要0。新extension明示時だけ送信前metrics→各SSE tag→commit前fresh metricsを照合し、未知metricsは既OSError再確認経路へ戻す。実derived chat main＋制御HTTPの正常first→途中epoch変更second拒否→third再確認/旧完成first保持/失敗second次prompt混入0を確認。実Service/package/Web identity接続、通常provider reasoning/toolとactivationは未了で、制御HTTPを実モデル成功とは呼ばない。
- T33 sdk-input-draft-1/input-observations.json SHA7c953c4506e3fee2c960edff9022e35d94d365d5816d1333e4cf004fd97752afは公開AgentSession/DSH AgentRegistry＋AgentLoopのfetchCaptureだけで最短bodyをCPU固定。system『Call f.』/user『f』/空parameterのtool fで、Pi公式Recipe原prompt276tokens・wire max64、DSH271tokens・C32768/wire max64。DSH C4096では公式pi-aiのcontext safety4096によりwire max1となる旧draftも保持し、SDK/vendor安全余白は変更しない。実first semantic時刻は未観測、network/model0。DSH semanticidle300000msは不変更で、native PPを本文/reasoningへ偽装しない。長toolpromptを盲Gせず、公開progress接点と供給の既観測を根拠に必要最小の改善/計測案を同wave整理する。
- T35 measurement-contract-pre-r4 dfb804f4…/formal-report-only-CPU-1 dfc1110d…は独立重要0/Main同scopeGO。新approx-8g-r1/measurement-seal.json SHAfc7dea4fc2442155cbb414c1d2599abeb329c9c81525e4d306f63e7fc07c7a54を独立exact重要0で固定。ユーザー『厳密にしなくても良い 続けて』に従い残8GiBは目安/report-onlyで、帯外/unknownだけではGEN拒否・metric/CI無効化をしない。fresh availableからmodel RAMcache候補1回、実working/privateworking/commit/availableを保存し、通常profile/default/device auto/数学は変更0。旧auto pilot/旧strict Aのみ失敗は別条件として不変。
- 正式approx pair0/verification.json SHAa0ec2bf6726554eef22719b6d987977d3c5f1e6c8e64bf1349d64a4e923c0d39は独立重要0/Main subset受理。A/B原IDs各[4482,55753]/count2/length/DONE、pipe TTFT400.309999/128.0241254秒・TPOT53.5285248/51.6419636秒。RAM実payload62075123936B・primary/row各29596slots、同pair固定。67保存点available7027769344..9143050240Bは参考帯外診断を含む実観測で、連続保証0。closed PID54336/birth134370487721113724/exit0、runtime617/Model9stat/実INFO3DLL/数値・clockを照合した。
- 正式approx pair1/verification.json SHA17031752ffbc62af1d8c0ec89f27038fa79fa0da6d3e119e426725bd23706d68も独立重要0/Main subset受理。A/B原2IDs/終端一致、pipe TTFT242.0100644/129.2418297秒・TPOT51.3703913/50.8744373秒。RAM61112409992B・各29137slots、fresh算定によるpair0との差を隠さず併記しpair内は同一。51点available8745472000..9378082816B、closed PID48044/birth134370498188681065/exit0で別fresh ownerを確認。2pair回収/残pair2未実施・正式CI未生成であり、原因/hoist倍率/物理cold/whole性能は未資格。source/sealを固定したまま残1pairへ進める。
- T22はfixed-r2独立G前重要0/Main small GO、host68/recovery26/normal分類83成功。19:01 JSTに最初auto cap1 smallのnoGEN minimum→approx候補を開始し、4smallの当回sole native/GPU/巨大RAM窓をT35pair1終了後に譲渡した。T35pair2は返却後に直接調整する。noGENも同資源排他で、約60GB級ownerの二重起動0。T22 liveCore/Primary/CMakeの未資格差分はinstalled15cb03/nativeb3d7へ非混入。ブラウザ可視操作はユーザー明示延期/後日まとめ、未実施PASS0。新通常制限/他consumer停止/commit/push/PR0。

## 現在の追加状況（計画impl81）

- Main受理36/47。T35 approx-8g-r1/measurement-run/verification.json SHA f25baa25a3b608131ac97089d0bbb968fff5ffc138777b0b3981d2d13870effb は正式3ABの独立最終重要0/Main元測定scope完了。pair2 9ce6852e…を加え、原IDs各[4482,55753]/count2/length/DONE・617runtime/Model9 stat/実3DLL・pair内同予算/跨pair fresh出生・正規exit0を照合。TTFTのcold/warm比G2.2263720955、95%CI[1.0721187505,4.6233056791]は広くprecision1.07661、TPOT G1.0207373014/CI[.9866693996,1.0559815059]は跨1で効果未判定。hoist因果/physicalcold/一般性能PASSへ広げない。RAM各pair62.075/61.112/61.171GBは実cache payloadで、残8GiBはユーザー最新指示の目安/report-only。帯外診断で数値/CIを無効にせず、旧auto pilot/strict Aのみ失敗を正式3pairへ混ぜない。新completion台帳/再Gは追加しない。
- T33 package-builder-CPU-1 df1c92a9…は独立16Python/Node bound4+default6重要0/Main受理。latest input e68c63d8…の62copy169162058Bで新5df2e15e…を組立、identity-candidate-r1/verification.json SHA6a98e6aee122eefcaa27c92ec43b223896cc21422b732be4d39610f62aa9ffad/manifest70ee79c2…/probe23bddeb5…/742manifestfiles/実234886661Bは独立847refs・新venv poisoned CPU再実行重要0。実selectedService metrics/openai_chunks controlledprobeとRecipe/codec/context/entry/help/pip成功、native b3d7不変・公開6profile0・新native/listener/G0。validatorはidentitybranchだけ既installedprovider96fbc…をfile-specで束縛しmutable T22sourceを消費しない。既15cb03/旧schema/Huihui/default保持。実通常metadata入口/モデルreasoning-tool/activationは残件で、候補CPUを実モデルtool成功とは呼ばない。
- T22 first r2はfixture logicalB3直渡しのshape/batch失敗で数値0、通常Coreの既batch_wavesをfixtureへ再利用し2+1へ是正（数学/原Q不変更）。r3の4small1392値は独立最終重要0/Main subset受理。normal-r4実cache-onlyはtypedcancel count0→fresh HTTP「您」/raw4482/LPtop3/length/usage4+1・正規closeへ作者到達し、normal-r4 proof24d49a49…を最終reviewへ。actual P16.535GB/S12.367GB/RAM59.170GB/available約8.856GB、Shit0のnormalroute実証とsmall warm証拠を分離する。全T22はMain未受理のまま。現在native/大RAM解放、T33公開対象との競合は当run回収済みで解消した。
- Xolotl固定HEAD比較を本計画の改善順序節へ反映した。既承認C32→持続file/worker→route限定read集約/重畳、既数値意味を保つHIP/tile、layer-major prefill、会話RAM/prefixの順。任意routing biasはユーザー追加指定により計画対象、既定0/基礎最適化後/品質・速度未実証で、固定baselineへ混入しない。T38/T39/T47へDSpark/graph等を重複統合し、比較v2重要0を移植承認にしない。本節の新計画部分は独立reviewへ。C32 production変更0、T46薄dispatchはread-only計画準備、ブラウザはユーザー明示延期/後日まとめ確認のまま。通常profile/default/思考/retry/compact/samplerを試験都合で縮小せず、commit/push/PR0。

## 現在の追加状況（計画impl82）

- Main受理37/47（元v1.12r1）。T22 final-r1/verification.json SHAb990d74d6503f8069e3b926391fb67ed00b66acf01e4b5b1f27474b2d74903bf/coverage e2a2317134684ad9904451ae7afe1082f8027d3b2c5b48cf195cf0ced0e6d7b5は独立最終重要0/Main完了受理。production packedcache/CoreProjection/normal cache-onlyを小4case1392値＋normal実Q/alias/役割/会計/正規closeで実証。typedcancel cookie1-1→実HTTP2-2が正しく、以前1-2とした速報は訂正。normal Shit0/fills65646でありwarm効果はsmallの別証拠、速度未実証。normal最終Powned16.5376GB/Sowned12.367GB/RAM約59.170GBは一度ずつ会計し、将来残は旧2GiBを32MiBへ置換。通常profileのT22native反映は未実施で、現5df2/b3d7へ黙って混ぜない。
- T33 identity-publication-CPU-1 4c7018e2…は18CPU独立0。候補parent15と同native/EXEbytes・元SSE4140の数値scopeをjoinし、knownold6だけnew5df2へ公開したprofile-publication-r1/verification.json SHAba87e0bc5e3c5cb7ca97b32a8fc51a25198f26c5ab9d4eb8a681d11e9700ca80は独立重要0/Main公開subset受理。六context/静的epoch無し・Huihui4/catalog/default/installedprovider保持。新metadataの数値G成功と偽装せず旧native同bytesの証拠を再利用する。
- 通常identity入口attempt2 verification SHA7fb58e831cb5a27dcae11d42c8bae97425c98de18336e582f79f7f98b4df5d4f/evidence00046831…は856refs独立重要0/Main限定受理。actual5df2/b3d7/C4096 config整数epoch1792580245916745000とHTTP lossless decimal tag一致、selectedchat /quit、実HTTP index/app bytesとContentType、owner保持webdispatch（browser openだけユーザー延期）、usualstop/status/models・cohort3出生gone/listener空を確認。GEN/requests/corepos/read/H2D/D2H0、742runtime/profiles/source不変。試験RAMのみfreshavailableから約8GiB残を狙うexplicit60.36GB、ready実available7.706GB/report-only。保存autoは不変更。attempt1はharness cmd.exe表記のsyntax失敗でnative0、元記録を保持しWindows実path表記だけ是正した。全T33 actualreasoning-tool/activationは未了。
- C32承認4testsourceはimplementation作者のCPU初段（owned synthetic/42tests/原本read0）後environmentへ所有権移譲。fixed-r2 seal独立0/43CPU後のactual b7195a55…は同64KiB/4workers/outstanding1・32direct/各2MiB/全bytes SHA/closeを作者確認、A32provider10.36/9.86ms対C1provider32窓4.90/5.19ms。noGEN modelcache RAM59.309GB/available8.87..8.92GB・GEN0・正常解放、原本最大12MiBを保持。actual独立最終結果待ちで、モデル倍率/production速度へ広げない。次の持続I/O production最小差分はenvironmentが別exact計画を作り既レビュー流れへ。こちらは4testsource編集0。
- T46 thin dispatch pre-r1 SHA384034b4fc40a846819c3e9b7ac2d4999b4c4f9345245e22f906da6b7fd163d5を独立計画reviewへ。11sourceの既CLIoverlay→mode→ExpertAssist/LayerSplit接点、既STOP/owner/予算保護とT33identity保持、mode別最短試験と比較を整理。RAM全role配分式は未確定の候補でnative実装前の同wave差分reviewへ、未合意defaultや通常capにしない。native solewriterはenvironment、C32productionと共有file順序を直接調整する。

## 現在の追加状況（計画impl83）

- 原v1.12r1のMain完了受理は37/47を維持する。T35 baselineの正式3pair/広いTTFT CI・TPOT跨1は元scope完了のまま保持し、今回追加のXolotl最適化/任意biasを完了数へ含めない。T33実model reasoning/tool/activation、T46通常mode・比較、T47結合等は未了。ブラウザ可視操作はユーザー指示どおり後日確認で、未実施をPASSにしない。
- C32 host診断 b7195a55…は独立最終0/Main受理。続く持続provider追加componentはprovider-persistent-fixed-r4/verification.json SHAd7144de048f99a18221ce673b6c25d9aa5d43436a0e705c31e2516645061802b、normal-applicability.json SHAb35cf89cd97ceca4e16710e123124424b2b542a5f5c524bda8862bd597f629a3、追補e03534a1041a3a90aab896a59e8c3a4c6b48a126d9c36d4affb3f6d372194b12を独立最終0/Main追加component受理。20output/2880値、26trace/10control/22nativecheck、実close/freshと47production source中Primary1差分を確認。同ownerで直接観測した範囲と、未観測の新binary別tile/Identity・genuine最終normalbundle適用を区別する。新normal実G/公開/モデル速度は未資格で、既T46の必要captureへ共通化する。
- quant block32 scale hoistはMain承認4sourceの単独writerをimplementationへ移し、envはC32/T46用の旧quant29d9bf0a…をimmutable親へ保存。newquant63b67bc76111db2d3c7e33c00e22077fb2c217166e90696db282bcf5ed775ff3はvalue/decode/checked API/headerを保ち、K昇順FP32/+0/product→acc/noFMAと型8/39/43の元算術を維持した。quant-block-scale/final-r1/verification.json SHA9935b7d36ef067c62f7f2d934610a366409010e2d6fbcaea7acce376c2cbcf6bは独立最終0/Main両GPU小component受理。各39job、計78job/4,345,448値の旧new全bitと独立Qが一致、fullK5120/2304/B1,2,4,8/rows256・padding・全scale/特殊値を確認した。
- quant PCI07の元runはnativeexit0/39job全bit一致後、6負HIPeventを後処理が拒否してcontrollerexit1。原raw/source/失敗を保持し、post-CPU acd72a003500f009913913a039919747772031195f8c20e6c5d479470213c7f5でraw負値を保存、event時間をnull/invalidへ分離した。first owner finalINFOは欠落nullのまま。PCI07数値の再Gは0、残PCI03だけ実行しe9375105dc806d541d5c9a7f48035c05ffbdaa48f2df11c326ebd192c9bc0baeでnative/controller0・負event0・正常closeを確認。Record/ElapsedTime順序に具体誤りは未確認で原因不明、F32 controlの観測差も含めscale単独速度因果/倍率/CIを主張しない。newnormal適用は未資格、既T46 genuine閉包へquant1差分を明示handoffした。
- 既tile_rows knobの試験計画tile-geometry-pre-r1.md SHA34b3d0676042f89f8da829b862d0cb02acb0582fe394b42cdec17e1ac6c0d409はMain全文/独立計画0でnewtest3実装GO。2MiB/旧256に対する試験1713はgate/upでbyte上限771、down1713となる静的geometryで、通常defaultを変更しない。全型metadata/末端/overflowの作者4CPUとmetadata-CPU-1.json 3bd42958…を準備した段階、実Core body実行/旧quant小Q/代表A/Bは未実施。通常allocator/数学を変更せず、速度効果とslot容量を同一視しない。
- T46 pre-r2 0a17eba00e2408e5b0bb9ab78bab59f879539b9b4d0cf270c24aa3c64d74359bと入口追補r2 83ec962885de77d271369d48aed3188ad96d96b982a77ff0dac83bc096c7b4aeは独立重要0/Main11source GO。CPU-component-5/verification.json SHA335b68b3f45226c2e614ff32831f7ace0913e4b68b8750e633b11de87b33a001は14CPU/実P5 immutablehook比較で独立0/Main限定受理。新manifestのexecution ABIと唯一hookbodyに対応するmodeargvを生成し、旧capability無しsingleは旧argvを保持する。mode-onlyは既placement→保存推奨pair/odd192/cut24→明示overrideで解決、推奨をwhitelistや最適性保証にしない。emptyassignmentはRAM式CPU境界のみで公開nonempty placement契約を維持する。
- T46 package-entry-addendum-r1.md SHAb27d4640e5b08cdf84e918147d327d4559a1ea686290d491771c0b81fc2ed4c8は独立計画0、Main読戻しへ提出した。現5df2親62copyからEXE/hook2置換＋control/contracts.py追加の原則63copy、残60とT33identity/client bytes保持、newvenv/latestprovider CPU→globalhelper/provider knownold2→6profile→通常mode/INFO/STOP/復帰を具体化。最終native/ID/filelist、新manifest/defaults保存/配布、実効表示/通常mode数値/比較は未了。envはproducer2fileを実装中で、持続Primaryと受理quant1deltaを同一最終閉包へ明示し、未合意丸め/通常制限を混ぜない。
- 今回の追加wave実検証はmodel RAMcacheで残DRAM概ね8GiBを目指し、実available/working/privateworking/commitをreport-onlyで保存した。noGEN較正も約60GB ownerを使うため当回sole GPU/大RAM窓へ含め、今回quant両ownerは原handleexit0/対象CIM[]/RAM解放を確認しenvへ返却済み。原model weight payload追加read0というquant表現は合成fixtureの範囲であり、noGEN ownerのheader/metadata読取とは区別する。通常profile/default・Huihui・思考/context/retry/compact/samplerとユーザー権限を保持し、新gate/他consumer停止/commit/push/PRは追加しない。
- 追加2資料の指定SHA現物を照合し、canonical改善順序に候補重複と任意bias詳細境界を統合した。λ0は追加tier補正0で元learnedbias/bias_vl保持、従来kernel直分岐。tile coverage/要求snapshot/target verify/bonus/prefix数学由来を区別し、未確定の係数/品質/標本/APIを既決定にしない。原37/47と追加Xolotl/bias未了を別に報告する。ブラウザ後日まとめ確認・通常context/思考/retry/compact/sampler保持・commit/push/PR0。


## 現在の追加状況（計画impl84）

- 元v1.12r1のMain受理37/47とT35 baseline完了を保持。追加Xolotl/bias、T33実reasoning/tool/activation、T46実mode・比較等は未了。ブラウザ可視操作は後日確認、通常default/context/思考/retry/compact/sampler不変更。残DRAM概ね8GiBは引続report-only目標で、帯外をGEN拒否や時計無効へ戻さない。
- geometry fixed-r1/verification.json SHA64d68329ad4516cee7412b459e54d74ce8b3aca155f72951ae9d56fbc2678b0eは独立最終重要0/Main小component受理。実Core source_tile/row_tiles/tiled_projectionと旧quant同EXEを使い、両PCI各7424/計14848値で旧256対試験1713の全bit/独立Q/padding一致、gate/up呼出9→3/down20→3を確認。actualCore1188metadata/5invalid、全16event非負、699refs/owner617/Model9stat/実DLLを照合し、owner24812原handleclose0/CIM[]/大RAM解放。RAM59375749544B/available約8.84〜8.88GBは実観測。合成resident projection envelopeであり通常モデル速度ではない。旧normal同EXEの代表1ABは承認済みだが未実施、通常tile/default変更0。
- T46 native union-r3のstartup cleanup R1是正をsource/CPU独立0で確認後、Compute INFOのdeclared_device_cache_payload_bytes欠落を既ready契約との実不整合としてr4で1scalar補完。native-union-build-r4/build.json SHA2c12eedaa97e137ed7125935ce74f1cf9eb8a8e9807e46bd44b50cf8e817afdc、EXE92e9174e8f31523f376b5eea94c1a391bd6839117d7d063bec631b53c4e30134は両arch/83+38+23CPUと独立source重要0/Main限定受理。qualified persistent Primary/newquantを明示unionし、後着T36 live Coreを消費しない。実owner/newnormal数値/性能はまだ未資格。
- T46 CPU6 78688bd8…/package-input-r1 2df0311e…は63copy/親60same/EXE+hook2置換/contracts1追加をRED→15mode/package+旧stage19CPUで固定し独立0/Main受理。旧r3候補f5fe6c68…/60a16fc5…は新venv/実Service identity/Recipe/codec/context/poison/entry/chathelp/pipcheckのCPU成功として保持。r4input a07f1fb3…は新ID3a32258855fb127de928202df4c9ebfd03300e0e90eaa862a3dae367a89026c5/63copy169474526Bへ明示更新。package-candidate-3a32258855fb/verification.json SHA48d5f30c922d1a077bc609e6feefea1651f41c6e23bb92ef58e1ac21935988dfは743files/実235237902B、新venvと同prepared Service probeを独立0/Main CPU受理。親client/identity extensionsとLF client bytesを保持しexecution ABIのみ追加、globalhelper/provider/公開10profile/Huihui/catalogは不変更。旧候補成功を新nativeの実機成功へ偽装しない。
- CPU7 27676c88329afdf85dac1e9e9808c78b372b4c524bdb2ea1166fcdcf7fb9662eはmode-aware ready/実観測表示の18CPU独立0/Main限定受理。cut境界でRow無しslot0を正しく区別し、実mode/PCI/assignment/cut/headと全roleRAM/minimum/unused/devicealiasを検査。旧runtime21は20成功＋1既隔離fixture問題（helper/bootstrap2copyが既contracts依存を欠落）、before同失敗を保持し全21PASSとしない。実installed contracts bodyは存在しnew63copyにも束縛、無関係旧testは変更0。実mode/INFO表示のusual入口はまだ未実施。
- T46 actual-mode-addendum-r1 SHA9e0fde79707235d3b1db55a69e7432e8f0225da44b2d8180bdb2cb187a7deb27は独立計画重要0/Main承認済み、実G未実施。最短4原IDs/max2の完了生成は各mode1要求/計4、typedcancel controlとは別計数。candidate singleで新native数値を確認してからknownold公開、残3modeは通常CLI mode-only、最後single復帰は生成0とする案。第1token LPは旧Q2ULP、第2token LPは今回single実観測を対照にし旧期待を捏造しない。全role明示totalRAM/実auto容量差/順序/epoch/clockdomain/OScache未知を記録するpilotで、全mode CIや全直積を新gateにしない。genuine capture/配備は未実施。
- T36 pre-v2 SHA969f07f9f4fc40d729e8f71152a7407faf55f4ca4637e210204360493a5a4c6fは独立計画0/Main13source GO、envがT46r4 immutable閉包と別に初期CPU実装へ着手。live数学state continuationとweightcacheを区別し、長文/reuse/append/reset実機や品質を未資格のまま保つ。noGENもsole GPU/約60GB資源窓へ含め、今回geometry窓は正規回収して返却済み。commit/push/PR0。

## 現在の追加状況（計画impl85）

- impl84のcanonical plan SHA0a540d51234df180025768e870bbe92ca3f3fcf7b855a3c6194e81486552eab0とOWN README SHA94e8ec3f0891a5f5b0cdf64f656b8739bb90d56c11c6e5f73bb9878bee1659f7は独立review重要0、統括の本文SHA読戻しで受理済み。本impl85はその後の担当移管/計画状況を記録する文書差分で、独立review前。
- 統括確認により旧integration handoffは凍結、旧作者は安全終了。通常CLI統合はsession 01a15e92-2cb4-75e1-bdae-87e184dafe0f、prefixは01a15e92-d5bc-7050-bf4a-d5bd350003a3、perfは01a15e93-ba56-74a1-8422-999d9df463cf、reviewは01a15e91-6199-72c3-8fbe-56b5856ac95b、監督は01a158c7-0143-7b62-bd87-9f99a9aa4786が担当する。DSpark/T38は01a15e9a-3ee1-76f2-befb-f0f1f5018775、graph/T39は01a15e9a-d184-7ca2-844b-f6e37b383929が計画調査開始、実装/実G未了。実装4（CLI/prefix/DSpark/graph）＋速度1＋独立review1＋監督の分担とし、共有Core/producer/quant/Primary/CMake編集は統括調整、他担当無断編集0。旧handoffを書き換えず、新sessionの成果物/現在引継ぎで続ける。
- T46 actual r1 SHA9e0fde79707235d3b1db55a69e7432e8f0225da44b2d8180bdb2cb187a7deb27は独立計画重要0/Main承認済み、実G未実施。observer追加のactual-mode-addendum-r2-draft.md SHA0a103ad3d055c490df920b89efe969d4b19f80300a1015ae0292c80c95b966caとt46-observer-plan-handoff.md SHAd9f8ad18afdc0c692afa748f0201849fa29d6ffe660626f654d5db46d6328aa8は独立review待ち。通常env未指定で追加I/O0、対象外prompt記録0を計画し、試験env限定begin後cancel fixtureを含む。未実装、新package未作成で、r1承認をr2へ流用しない。
- T36はR1未解消。指摘内容/解消/実長文資格を推定しない。native r4 immutableとT36 live閉包を分ける。原37/47、T35 baseline完了、公開旧5df2、旧runtime CPU20成功＋1既fixture依存不足と既未了を維持。通常機能/context/思考/output/retry/compact/sampler/timeoutの縮小0、残8GiBは目安/report-only。今回文書更新で製品コード編集/G/CPU試験/公開/commit/push/PRは0。

## 現在の追加状況（計画impl86）

- impl85 plan ed70c2971233523ec9d26a6a41ec423da88ded2ac683c77e78fc6b56e4dfb06a/OWN README c050b7aeb412ec766068119cbc2917dd5152ebc427bbb9533843f8f0d1aba2aeは独立重要0、統括の本文SHA/差分読戻し受理済み。observer r2 0a103ad3…と配備準備CPU7 proof d7f5b5d2…も独立重要0/統括受理、r2実装GO。本impl86文書差分と下記新実装を、その受理へ遡及包含しない。
- observer製品変更はhook1file SHA0a5c240f279a641148e57ddacdad7154e9acfbe5c1dc884622c4b43593ec6e98＋新test1file SHA802eefd53e710807e8e467540c995f54426fd6674ef9f0c1de05ac2f7c58d2ecで作者freeze。15新CPU、disabled before/after4trace一致、mock境界を含むenv経路/actual bootstrap無害child、DTOcapture9mutant拒否、自然contracts依存row/helper ABI計4件が成功。通常env追加I/O0/対象外prompt記録0、試験env限定cancelと失敗時cleanupを確認した作者CPU成果で、最終source/CPUは独立review待ち・未受理。詳細はbuild-deepseek-t46/t46-observer-implementation-handoff.md SHA6bb0f17a4b06d2f6b13630cebe96d9064b626618d74063dff4d0d9bf24c3dede。
- final input-r4 SHA0d2f84a0ccf4bb516ef900ee92b9dcf601781b6a46826c5348cc720a3f153683/新IDe32f159e984ec22450b7d378d59a2dfdadb95a62cdeca22c8bf4c8e5c825a0a6、candidate proof e86e9e6e06fbe57740a0741a62fa3c2a4a4b95a381af303378592742b63a92b9、prepared-Service probe 3cde7f6e8f96223a62d4a5427fed2f99434f42dc016a57eaee03efb906c533a6、CPU seal 10e4236520b5cb904f954cca959c8b2d21bb1352bd0482d9c46a2c648a3679ecを束縛。native r4 immutable、親T33 client/identity/ABIと他62selectedを保持。r3 ID280d1f31…はlogger error後parse/cancel停止の作者是正前CPU履歴で、最終成功へ流用しない。
- final probeは合成producerを使う実prepared Service raw4/DTO/Recipe/SSE/usageのCPU確認である。生成IDs[4482,55753]、第2LP合成-1.25、Core位置5を実model数値/2ULP資格と呼ばない。実G/normal数値/公開0。actual4mode orchestrator、実launch owner/全role較正/数値proof join/通常cleanup等の実G前sealは未完成、G-ready0。統括指示で別Sol medium作者が新試験fileだけのactual runner作成を並行開始、完成/受理/実G成功ではない。CPU sealを実G前seal完了へ広げず、ready後にT36小実機とT46の当回窓を統括と調整する。
- 統括からperf正常1ABの較正/選定/A/B全owner原handle exit0・CIM消滅・公開停止と資源窓返却の報告を受領。CPU replayはcreated時刻再現性を診断中、追加GEN不要との連絡。これは本sessionのfresh runtime照会や最終独立受理ではなく、速度値/性能成功を推定しない。旧actual/source/失敗を保持する。
- DSpark plan-v3 091cd48d…はR2計画上解消・独立計画重要0、統括のnew13module GO。T39 module-only r1 4b4a5882…はsource/host/object-compile subset独立重要0/統括限定受入れ。sharedAPI計画reviewは並行、共有Core/producer/quant/Primary/CMake編集は統括調整、他担当無断編集0。実DSpark/通常graph利用/数値/性能の受理へ広げない。
- T36 R1 fixed source/CPU/build subsetには独立重要0の記録があるが、実owner/adoption/Q/retained safe-fresh/HTTP等は未資格で、R1の実機解消/T36全体完了とは区別する。producer/state-capture等の別指摘を解消済みと推定しない。原37/47/T35 baseline/公開旧5df2/旧runtime20成功＋1既fixture不足/他未了を維持。約8GiB残はreport-only、通常context/思考/output/retry/compact/sampler/timeout縮小0。今回文書作者の製品編集/GPU/大RAM/公開/commit/push/PRは0。本impl86は独立文書review待ち。

## 現在の追加状況（計画impl87）

- impl86 plan362bc01d…/OWN README6aa7ade6…/handoff c8795a7d…は独立重要0・統括の全文差分/SHA受入れ済み。本impl87はobserver返却重要2修正版/newcandidate、actualrunner CPU、publication scope是正を同checkpointにまとめる文書差分で、独立review待ち。旧見出し/履歴は保持する。
- observerに返却された重要2点はcancel_fixture event保存失敗でもcancel副作用が残ることと、capture因果順序検査の不足。fix-r2はevent write/flush成功時だけcancel.set、GEN send→begin→fixture→typed STOP→finish→DONEの因果検査を追加。hook SHAd73dffd348ee35f771eefa7c665e92958374e8d7df5cf6809a29d41ac3df121e/test9559b48994169cca44298208565e339e6c479afb12c97c42898e1329c86b2e5a/capture315c2ee7710c14e9cd9ff12b002a1dd405edd769b7f8a8c5fc691a6ca66bfde0で作者freeze。16CPU/因果8＋旧9mutant拒否/旧validator受理4再現が作者成功、独立再review待ち・重要2解消判断0。
- 正本build-deepseek-t46/t46-observer-implementation-handoff-r2.md SHA62dbf0637cfccb00bb8310ab43177fb5e9e4316166cbe6090cd86640b8735d28、source-map1e838f75e229f4791d6d3cb2a311c792d2f6bd855cefa551f854029050ed25fb、fixCPUproof4d5b8c1169d122486b9da1a1dbdcac4051cb32fda7bd80adfae9fce8d9ce2a86を参照。input-r5 SHA6f85c5cce5234aa611f0135e0bbd1c5c5d50f39574030f9374b3d89666909439/ID86cce0ea59294dae23dc3b0ccb9cac04cf1c26ecc50c769d824d7eb38295e0e6/candidateproof fb88469154c4cbed4f54c0d5de3d7b40b59fe6dd460c9bea2c84c4b221e58a4d/Serviceprobe f71a35538131a93528d51c70bcb2f2dc9bfbb92a790900bda70a4791dbb6edceへ必要scopeを再結合。旧e32/input-r4/proofは歴史保持。probeのID/LP/Core位置は合成producer値で、実model資格0。通常env off/対象外要求・通常設定/immutable native r4/親client identityは維持。
- actualrunner別作者からCPU12成功を受領したが、最終seal/handoffは固定待ち。固定版/独立review/実G前seal完了を先取りせず未G-ready。新candidateへの結合と数値/owner/Model9/DLL/cleanup/全role予算/通常CLI等の必要scopeが残る。実G/normal数値/公開0、窓を自動開始しない。
- publication-join-plan-r2.md SHAc3c3e456b3219466e4bd4da7c4245e530c229ab00e371daad72e2a360ba9ee58/handoff db3f7397877407bfd486b52b17fdee14fd4d68a70e32e650ebe2dd315ea4c689は独立計画重要0/統括受入れ・2関数実装GO（公開GOではない）。別Sol medium作者がruntime_stage2関数＋隔離CPUを並行開始、実装受理/実公開0。旧stageはimmutable captured assembly履歴、新publisherは別closed source-mapへ束縛する。ユーザーのrollback除外指定に従い、旧未承認9fbc案の独立回収2API/後日saved-old復帰/専用receiptとそのCPUを削除。数値joinとknown-old8target publishの2関数だけで、partial状態/元例外/未実施を記録→配備停止、既batch temp清掃/その場失敗処理/foreign保護を再用する。既CPU7回収caseは歴史primitive成功だけで新機能許可にしない。
- 共通receipt.source_mapはpublication operation source-map、numeric.source_mapはactualsingle pre-G/runner source-mapでaccepted_numeric.reviewed_source_mapとexact一致させる。両source-mapを同hash必須としない。numeric-review/numeric-verification recordで接合し、新registry/人間GO/通常起動gateを追加しない。
- 統括の最新直接連絡ではgeometry posthoc既1AB subsetはMain受入れ、pipeTTFT単発246.257936秒/162.7740111秒（一般倍率未資格）。T36 producer-r4 source/CPU0、Engram visitor header/host0、capture plan-r2 GO、旧owner fixture重要1はrow-tile修正中。T38 APIv5計画0/sampling2 writer移管/isolated tap準備GO。T39 shared-r2計画0/Primary2実装review中/tiny AV失敗診断。いずれも受入れscopeを超える実T36/T38/T39/T46完了や実G成功を推定しない。code harness小temp残置のautomatic approval blockedは実G/owner残とは別で、詳細はobserver修正handoff参照。原37/47/公開旧5df2/旧runtime20成功＋1既fixture不足/他未了、約8GiB report-onlyと通常機能を維持。今回文書作者の製品編集/GPU/大RAM/公開/commit/push/PR0。

## 現在の追加状況（計画impl88）

- impl87 plan1531be23…/OWN READMEbd69db82…は独立文書重要0・統括の全文差分/SHA読戻し受入れ済み。observer修正62db…/candidate86c/probeは既source・CPU・候補組立/合成probe subset受入れ。さらにpublisher-r2 handoff67a5ecfa393614c44bb02f5f5ab1e422d5fe0ac023a1bd399bcb5d81649cddafとrunner-r3 handoff accb34e85ab85f50543acdee2f2e8358f58195036a219c9e921a5f3d1c039506は統括が全文と各独立0を読戻し、source/必要CPU/接点/preseal subsetを受入れた。Publish-R1・Runner-R1/R2は当該実source上で解消、過去freeze時点のreview待ち記述は履歴として保持する。本impl88差分は独立文書review待ち。
- 最終stage d899063daab649c404908f3da093b4e556ec185d900ee1bdaf0b9de5049f446c、runner606e4aba653ead96a2f3228855704ea0730773c5e369891565aff7aa4bceb5f5/live78faa887daf48b036b94576ed24a2b500cbab34e74d4a540e62ac17adcc51b27、必要CPUproof ac4dc779bb6270f12d6efb1499295bf4f163a6237dcba43ae483bcfadaf89dba/preseal c7db6018c9c0dc51255ea1c924d961a768603d3a13e9de8c380f0b88119ba70fを保持。runnerはprevious保存verification/hash/本文と受理single raw_complete/configからLP・totalRAM基準を結び、出生/cohort観測失敗でも保持元Popenへの正規closeへ進む。必要4CPU（5早期失敗条件含む）が成功、旧15へ足して全19実行とはしない。publisherはtemp観測の二次失敗をunknown/errorへ分離し元例外とreceipt保存causeを保持、局所1test2subcaseと新runner接点1testが成功。旧37関数/join不変と旧stage immutable assembly履歴・新publication別closedmapを区別し、旧無変更suiteを反復成功と数えない。
- runner作者はsingle-preparation、immutable proofと既review exact envelopeの結合、実行引数placeholder解消をCPUで準備中。publisher作者はentry-diff-preparationを整理中で新実装/実公開0。準備中sourceを本checkpointの新freezeへ含めず、accepted final sourceと区別する。stage準備readyを実G成功・現owner停止確認へ広げない。実GPU/noGEN/新single数値受理/8target公開/cache-expert-split各1完了/publicsingle GEN0復帰は未了、candidate86c/native r4/公開旧5df2と原37/47を保持する。
- 共通AVについて統括の直接連絡はgraph markerでsetDevice後の最初のmalloc512でAV、旧geometry同SDK成功例があり根因未確定。runtime DLL比較build-deepseek-t46/runtime-DLL-comparison-CPU.md SHA9cfa9b8493d286e2d5af57b3135c6c99463bee37f4e51a56e4de89d2ce21222a/JSONd2106114730bd3d4f6f5788283f659d7a528dbfa320476cde34c490700abb77cでは、candidate86c/r4/T36/T39 AV bundleのruntime3（HIP/comgr/kpack）が同size/SHA。T39保存WERの3pathとT36 faulting HIP pathという実ロード証拠の範囲を分け、実T46ロード成功・同根因・安全性は未判定。Rootの次最小env/API比較待ちで当回T46大RAMを盲試行しない。これは当回試験順の調整であり新通常起動gateや公式利用禁止を追加しない。
- 根拠はcurrent handoff/review-20261021.mdの当該独立再review節と統括の最新直接連絡。実G所要時間/現ownerstatusを推定せず、他taskの新受入れも本checkpointで拡大しない。通常機能/context/思考/output/retry/compact/sampler/timeoutと約8GiB report-only、ユーザーのrollback除外・2関数publisher/部分失敗記録→停止/既batch temp清掃/foreign保護を維持。今回文書作者のsource/DLL/profile/前freeze/handoff/計画編集、G/CLI/API/status/公開/commit/push/PRは0。

## 現在の追加状況（計画impl89、2026-10-22 JST）

- impl88 plan d3c707e7…/OWN README afc6710d…/handoff77f6da4b…は独立文書重要0・Main正式文書scope受入れ済み。今回は現在task表T33/T36/T38/T39/T46も更新し、各source/CPU/compile受理scopeと実G未了を分ける。過去見出しと当時の未確定記述は履歴として保持。本impl89文書差分は独立review待ち。
- actual-single-01のexact commandは1回exit1、内部status-beforeのsyntax errorでservice/native/noGEN構築前に保護停止。noGEN/native/GPU/GEN要求0、原artifact保持・retry0、担当の保存post-status/models成功・cohort消滅/native/listener0・窓返却記録を参照する。本作者が現在statusを照会したわけではない。finalactual-handoff.md SHA cbf4617eed4518fab59b40696f21caae599688627504f567aea659a6680045a5。これはHIP AV再現やモデル数値失敗ではなく、T46 HIP資格は未実証。
- status-adapter-diagnosis/report.md SHA437d52ae28e8a470a37829b43289d09a2f85cd4d0c3852123f71fe83a23bf4dfは、無害batchと明示許可された現物read-only status2callでcmd.exe argv[0]のforward slash→native Windows表記だけexit1→0を確認。歴史env全体は未保存、単一OS一般則や広いquoting/ENV移植へ一般化しない。既停止確認・exit0必須・通常入口/選択肢を保持する。
- statusfix-r4 handoff db8ca77f228b070021df8890c5ebb6adf06b1f5dda7f0f801059e840b29930a7はMain全文/差分/CPU読戻し後のreview-ready固定版で、独立review待ち・Main受入れ未。live ee252ad9…のcmd.exe path1expressionとtest31e0b9f8…の局所回帰1件だけ、空白batch path/通常argv・env/cwd pass-through・exit0/7拒否をRED→GREENで確認。複合空白argumentの別quoting境界は既存挙動として原error保存・一般対応未変更、通常利用制限へ昇格0。runner606eは不変。CPUproof73d00351…/新preseal-final-r4 seal266a7272…/map5ffe4dc7…は882/882unique照合。旧r3/旧失敗/preparation/受理publisher sourceは歴史保持。新command-draft-r4は--review placeholder/review_envelope:nullで実行用ではなく、actual-single-02未作成。独立review/既review envelope準備と別窓後の新attemptは未実施、当回再G0・numericproof未存在。
- T33 remaining-preparation-20261022.md（build-deepseek-t33、SHA a5944ab23fe6c81b953dafe7bfdc729a7ac7b1b6db43144853d820e4e754e5bb/JSON43ead7a6…）は既計画由来の入口・固定入力・合格条件だけのread-only整理。旧Pi276/DSH271 raw token準備を実reasoning/tool/activation結果としない。Pi保存context4096に対し予定32768再prepare未、DSH32768/defaultidle300000維持、max64は試験内。旧公開5df2のCPU成果とcandidate86cの新native single数値前提、T33責任とT46mode/T47scopeを区別し、新依存/consumer停止/通常gateを追加しない。
- T36はcapture-r2 single-Core pipelineの独立0/統括準備subset受入れ、環境A再観測計画210e8933…独立0とlauncher/実行未了を区別。paired作者CPU/compile報告・tap統合計画r2の固定は未reviewの別範囲。T38 attention-fix-r2-report/author-report.md SHA4c5cd9f7…は中央独立0で修正source/CPU/compile-link subsetのAttention-R1解消。旧tail-r1重要1には遡及せず最新tail/live aggregate再freeze/reviewは別途。leaf Q/期待bytesの限定受入れ、leaf実装GO、TargetSupply作者固定も実network/actor/GPU資格ではない。T39はclosed Primary/CMake source/CPU/build受理と環境A同tiny単回実観測を区別、normal-integration-plan-r1は独立計画review待ち。詳細exact版は中央review-20261021.mdと各handoffを参照。
- 根拠時点は今回UTF8読戻しのcurrent handoff/中央review及び統括直接連絡、作者chatの最新固定報告を区別する。環境Aは条件束の単回観測で分子機序/共通AV根因は未確定、runtime3同bytes比較9cfa9b…は安全性/同根因/実T46ロード成功を証明しない。原37/47・optional T42別・残9と既未了を維持、推定完了0。通常context/思考/output/retry/compact/timeout/SDKと8GiB report-only、rollback除外を維持。source/DLL/profile/前freeze/各計画/旧handoff編集、G/CLI/API/status/process/公開/commit/push/PR0。新台帳・新手順・通常利用gate0。
