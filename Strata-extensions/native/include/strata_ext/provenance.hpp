#pragma once

namespace strata_ext {
// The upstream revision is a reference marker; no vendor sources are compiled.
const char* upstream_reference_base() noexcept;
const char* compiled_owned_sha256() noexcept;
}  // namespace strata_ext
