# T38 seed input-binding.json v1 exact protocol

This supplements fixed input rows only; it does not change mathematical/read scope.

Factory create-only output `input-binding.json` is one UTF-8 JSON object with exactly:

```
{
 "schema": "T38-seed-input-binding-v1",
 "manifest_path": "<same absolute input argv UTF-8 path>",
 "manifest_bytes_dec": "<unsigned decimal length>",
 "manifest_sha256": "<64 lowercase hex SHA256 of all raw manifest bytes>",
 "volume_serial_dec": "<DWORD volume serial unsigned decimal>",
 "file_id_dec": "<(uint64(nFileIndexHigh)<<32)|nFileIndexLow unsigned decimal>",
 "last_write_FILETIME_dec": "<(uint64(dwHighDateTime)<<32)|dwLowDateTime unsigned decimal>",
 "read_identity_before_after_equal": true
}
```

All integers are JSON **strings**, digits only, parsed as exact uint64 (volume <=UINT32_MAX). No floating-point JSON conversion; values >2^53 retain exact bits. No implicit zero/default on missing fields. `read_identity_before_after_equal` is a Boolean true, not string. Schema and SHA/path are strings. Unknown/duplicate JSON keys or malformed values reject.

Each metadata read uses original CreateFileW GENERIC_READ / FILE_SHARE_READ handle; before/after GetFileInformationByHandle values match volume/fileID/size/last-write. Hash is from bytes read on that handle. Prefix records initial before factory; factory emits this record and `input-manifest.tsv` exact byte copy; prefix after factory rereads the original input and compares its initial/final volume/fileID/size/lastwrite/SHA and factory JSON fields. Also hash/size-check factory saved input-manifest.tsv against the same manifest hash/length. Path equality alone is insufficient; aliases do not substitute for original-handle identity equality. Reject disagreement before any async Owners/Network constructor; if any later throw occurs, existing whole-group guard applies.

Factory source: isolated tests/dspark/t38/fixture.cpp. Prefix source: isolated producer.cpp. Both consume this contract; Network observer does not consume it. This is fixture-only data, no normal JSON/API/registry change.
