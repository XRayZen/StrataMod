# Isolated seed caller input contract v1

専用construction test mainのみ、exact argvは `--t38-seed-input <absolute manifest.tsv> --t38-seed-output <absolute nonexisting-directory>` のargc5。normal main/CLIへ追加しない。UTF-8（BOMなし）、LF又はCRLF、各行TAB分割、空行/コメント/重複/未知tag・field/余分列/NULは拒否。manifestは有限metadata <=65536B（本testだけのschema上限）。値中TAB/CR/LFは禁止。

```
schema<TAB>T38-seed-input-v1
producer<TAB>artifact_root<TAB><absolute directory>
producer<TAB>primary_pci<TAB>0000:07:00.0
producer<TAB>bundle_id<TAB><sealed bundle string>
producer<TAB>runtime_epoch<TAB><positive u64 decimal>
producer<TAB>context<TAB><u64 >=3>
producer<TAB>tile_bytes<TAB><positive u64>
producer<TAB>tile_rows<TAB><positive u64>
producer<TAB>active_batch<TAB><positive u64>
producer<TAB>device_cache_payload_bytes<TAB><positive u64>
producer<TAB>ram_cache_payload_bytes<TAB><positive u64>
producer<TAB>mode<TAB>single
producer<TAB>source1..source9<TAB><absolute original native source path>
caller<TAB>request_id<TAB><nonempty sealed string>
caller<TAB>draft_path<TAB><absolute original draft asset path>
caller<TAB>draft_prefix_path<TAB><absolute saved T37 prefix path>
caller<TAB>draft_credit<TAB><positive u64>
caller<TAB>target_credit<TAB><positive u64>
caller<TAB>owner<TAB><explicit nonzero u64 cookie>
caller<TAB>epoch<TAB><positive u64>
caller<TAB>bundle<TAB><sealed bundle string>
caller<TAB>device_ordinal<TAB>0
identity<TAB>fixture_sha256<TAB><producer.bundle_id>
identity<TAB>asset_sha256<TAB><producer.bundle_id>
identity<TAB>bundle_sha256<TAB><producer.bundle_id>
identity<TAB>request_id<TAB><caller.request_id>
identity<TAB>epoch<TAB><caller.epoch>
identity<TAB>phase<TAB>prefill
prompt<TAB>3<TAB>37<TAB>1024
receipt<TAB>target<TAB><absolute target authority receipt path><TAB><64 lowercase SHA256>
receipt<TAB>draft<TAB><absolute T37 draft authority receipt path><TAB><64 lowercase SHA256>
receipt<TAB>draft_prefix<TAB><same caller.draft_prefix_path><TAB><64 lowercase SHA256>
receipt<TAB>input_lineage<TAB><absolute independent input seal path><TAB><64 lowercase SHA256>
```

source1..source9 は9本それぞれ1行、他の全行も必須。source/assetのbody再hashを要求しない。receiptは保存済小authority metadata/prefixのみで、target original modelや8GB draft bodyをreceiptとして渡さない。input_lineageのexpected適格性はnumeric/Mainが決め、parser成功はQ/G readinessではない。mode/PCI/P3/device等の固定値は本finite fixture入力だけ、通常option/settingsへ制限を追加しない。

producer.runtime_epoch=caller.epoch=identity.epoch、producer.bundle_id=caller.bundle=identityのfixture/asset/bundle3文字列、caller.request_id=identity.request_idを照合する。これは既producer identity(config,id)の6fieldに合わせたexplicit bindingで、暗黙owner生成なし。pathsはabsolute、数字は符号/空白なしのdecimal、overflow検査、creditsはpositiveであってnormal上限なし。outputは未存在を検査してcreate-only。PREFIXは同mapからProducerConfig/owned strings/Asset(prefix検査)/RequestBinding/Identityを構成する。leaf factoryも同schemaをparseし、Body実引数binding/metadataと照合する。

PREFIXとfactoryはそれぞれmanifestをGENERIC_READ/FILE_SHARE_READで開き、同一handleのbefore/after volume/fileID/size/lastwriteを検査し、読んだ**全metadata bytes**をSHA256する。PREFIXはfactory呼出し前後にも同fileを読み直し、initial/leaf factory snapshot/finalが同SHA/length/fileidentityであることを保証する。factoryはoutputへ `input-manifest.tsv` と `input-binding.json` をcreate-only保存するため、PREFIXはfactory後そのbindingのmanifest SHA/length/fileidentityをinitialと照合できる。path文字列一致だけで同入力としない。leaf Body stateはparse結果/rawbytes/paths/destinationをshared-ownedで保持しstack参照をcaptureしない。manifest/receipt不明時はconstructor前に拒否し、async開始後例外はwhole-group retention契約へ返す。

producer.hpp/cppはPREFIX owner、leaf3fileはleaf owner、modelsCMakeはgraph owner。Body4argsとfactory二string署名は承認計画どおり。今回input配線の実装詳細であり、新framework/API/通常flagは追加しない。
