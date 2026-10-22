// Host-only fixture: OS file spans and system SHA256, without GGUF/model semantics.
#include "strata_ext/provenance.hpp"
#include <windows.h>
#include <bcrypt.h>
#include <array>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
std::uint64_t decimal(const wchar_t* text) {
    if (!*text) throw std::invalid_argument("empty integer");
    std::uint64_t value = 0;
    for (; *text; ++text) {
        if (*text < L'0' || *text > L'9') throw std::invalid_argument("invalid integer");
        const auto digit = static_cast<std::uint64_t>(*text - L'0');
        if (value > (std::numeric_limits<std::uint64_t>::max() - digit) / 10)
            throw std::invalid_argument("integer overflow");
        value = value * 10 + digit;
    }
    return value;
}

void checked(NTSTATUS status) {
    if (status < 0) throw std::runtime_error("BCrypt operation failed");
}

struct Hash {
    BCRYPT_ALG_HANDLE algorithm = nullptr;
    BCRYPT_HASH_HANDLE handle = nullptr;
    std::vector<unsigned char> object;
    ~Hash() {
        if (handle) BCryptDestroyHash(handle);
        if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
    }
    void initialize() {
        checked(BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0));
        DWORD bytes = 0, count = 0;
        checked(BCryptGetProperty(algorithm, BCRYPT_OBJECT_LENGTH,
                                 reinterpret_cast<PUCHAR>(&bytes), sizeof(bytes), &count, 0));
        if (count != sizeof(bytes)) throw std::runtime_error("invalid BCrypt property");
        object.resize(bytes);
        checked(BCryptCreateHash(algorithm, &handle, object.data(), bytes, nullptr, 0, 0));
    }
};

void span_hash(const std::filesystem::path& path, std::uint64_t offset, std::uint64_t length) {
    const auto size = std::filesystem::file_size(path);
    // Subtraction avoids overflow at offset+length, including UINT64_MAX input.
    if (offset > size || length > size - offset ||
        offset > static_cast<std::uint64_t>(std::numeric_limits<std::streamoff>::max()))
        throw std::invalid_argument("span outside file");
    std::ifstream stream(path, std::ios::binary);
    if (!stream) throw std::runtime_error("file open failed");
    stream.seekg(static_cast<std::streamoff>(offset));
    if (!stream) throw std::runtime_error("file seek failed");
    Hash hash;
    hash.initialize();
    std::array<unsigned char, 65536> buffer{};
    while (length) {
        const auto count = static_cast<ULONG>((length < buffer.size()) ? length : buffer.size());
        stream.read(reinterpret_cast<char*>(buffer.data()), static_cast<std::streamsize>(count));
        if (stream.gcount() != static_cast<std::streamsize>(count))
            throw std::runtime_error("short read");
        checked(BCryptHashData(hash.handle, buffer.data(), count, 0));
        length -= count;
    }
    std::array<unsigned char, 32> digest{};
    checked(BCryptFinishHash(hash.handle, digest.data(), static_cast<ULONG>(digest.size()), 0));
    for (const auto byte : digest)
        std::cout << std::hex << std::setw(2) << std::setfill('0') << static_cast<unsigned>(byte);
    std::cout << '\n';
}
}  // namespace

int wmain(int argc, wchar_t** argv) {
    try {
        if (argc == 2 && std::wstring(argv[1]) == L"--identity") {
            std::cout << "{\"upstream_reference_base\":\"" << strata_ext::upstream_reference_base()
                      << "\",\"compiled_owned_sha256\":\"" << strata_ext::compiled_owned_sha256()
                      << "\"}\n";
            return 0;
        }
        if (argc != 5 || std::wstring(argv[1]) != L"--sha256")
            throw std::invalid_argument("usage: --identity | --sha256 file offset length");
        span_hash(std::filesystem::path(argv[2]), decimal(argv[3]), decimal(argv[4]));
        return 0;
    } catch (const std::invalid_argument& error) {
        std::cerr << error.what() << '\n';
        return 2;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 3;
    }
}
