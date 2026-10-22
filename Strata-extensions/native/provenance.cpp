#include "strata_ext/provenance.hpp"

#ifndef STRATA_EXT_REFERENCE_BASE
#error Missing upstream reference marker
#endif
#ifndef STRATA_EXT_SOURCE_ID
#error Missing compiled owned source identity
#endif

namespace strata_ext {
const char* upstream_reference_base() noexcept { return STRATA_EXT_REFERENCE_BASE; }
const char* compiled_owned_sha256() noexcept { return STRATA_EXT_SOURCE_ID; }
}  // namespace strata_ext
