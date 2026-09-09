#include "node_darwin_frameworks.h"

#ifdef __APPLE__
#include "util-inl.h"

#include <dlfcn.h>

#include <cstring>

namespace node {
namespace darwin {
namespace {

template <typename T>
T LoadFunction(void* handle, const char* name) {
  void* symbol = dlsym(handle, name);
  CHECK_NOT_NULL(symbol);
  static_assert(sizeof(T) == sizeof(symbol));
  T result;
  std::memcpy(&result, &symbol, sizeof(result));
  return result;
}

template <typename T>
T LoadData(void* handle, const char* name) {
  void* symbol = dlsym(handle, name);
  CHECK_NOT_NULL(symbol);
  return *reinterpret_cast<const T*>(symbol);
}

template <typename T>
const T* LoadStruct(void* handle, const char* name) {
  void* symbol = dlsym(handle, name);
  CHECK_NOT_NULL(symbol);
  return static_cast<const T*>(symbol);
}

#if TARGET_OS_OSX
constexpr char kCoreFoundationPath[] =
    "/System/Library/Frameworks/CoreFoundation.framework/Versions/A/"
    "CoreFoundation";
constexpr char kSecurityPath[] =
    "/System/Library/Frameworks/Security.framework/Versions/A/Security";
#else
constexpr char kCoreFoundationPath[] =
    "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation";
constexpr char kSecurityPath[] =
    "/System/Library/Frameworks/Security.framework/Security";
#endif

void* OpenFramework(const char* path) {
  void* handle = dlopen(path, RTLD_LAZY | RTLD_LOCAL);
  CHECK_NOT_NULL(handle);
  return handle;
}

CFStringRef CreateTrustSettingsKey(const char* key) {
  const CoreFoundationApi& cf = CoreFoundationApi::Get();
  CFStringRef result = cf.CFStringCreateWithCString(
      cf.kCFAllocatorDefault, key, kCFStringEncodingUTF8);
  CHECK_NOT_NULL(result);
  return result;
}

}  // namespace

const CoreFoundationApi& CoreFoundationApi::Get() {
  static const CoreFoundationApi api;
  return api;
}

CoreFoundationApi::CoreFoundationApi()
    : handle_(OpenFramework(kCoreFoundationPath)),
      CFArrayCreateMutable(LoadFunction<decltype(CFArrayCreateMutable)>(
          handle_, "CFArrayCreateMutable")),
      CFArrayGetCount(
          LoadFunction<decltype(CFArrayGetCount)>(handle_, "CFArrayGetCount")),
      CFArrayGetValueAtIndex(LoadFunction<decltype(CFArrayGetValueAtIndex)>(
          handle_, "CFArrayGetValueAtIndex")),
      CFArraySetValueAtIndex(LoadFunction<decltype(CFArraySetValueAtIndex)>(
          handle_, "CFArraySetValueAtIndex")),
      CFDataGetBytePtr(LoadFunction<decltype(CFDataGetBytePtr)>(
          handle_, "CFDataGetBytePtr")),
      CFDataGetLength(
          LoadFunction<decltype(CFDataGetLength)>(handle_, "CFDataGetLength")),
      CFDictionaryContainsKey(LoadFunction<decltype(CFDictionaryContainsKey)>(
          handle_, "CFDictionaryContainsKey")),
      CFDictionaryCreate(LoadFunction<decltype(CFDictionaryCreate)>(
          handle_, "CFDictionaryCreate")),
      CFDictionaryGetValue(LoadFunction<decltype(CFDictionaryGetValue)>(
          handle_, "CFDictionaryGetValue")),
      CFEqual(LoadFunction<decltype(CFEqual)>(handle_, "CFEqual")),
      CFNumberGetValue(LoadFunction<decltype(CFNumberGetValue)>(
          handle_, "CFNumberGetValue")),
      CFRelease(LoadFunction<decltype(CFRelease)>(handle_, "CFRelease")),
      CFStringCreateWithCString(
          LoadFunction<decltype(CFStringCreateWithCString)>(
              handle_, "CFStringCreateWithCString")),
      kCFAllocatorDefault(
          LoadData<CFAllocatorRef>(handle_, "kCFAllocatorDefault")),
      kCFBooleanTrue(LoadData<CFBooleanRef>(handle_, "kCFBooleanTrue")),
      kCFTypeArrayCallBacks(
          LoadStruct<CFArrayCallBacks>(handle_, "kCFTypeArrayCallBacks")),
      kCFTypeDictionaryKeyCallBacks(LoadStruct<CFDictionaryKeyCallBacks>(
          handle_, "kCFTypeDictionaryKeyCallBacks")),
      kCFTypeDictionaryValueCallBacks(LoadStruct<CFDictionaryValueCallBacks>(
          handle_, "kCFTypeDictionaryValueCallBacks")) {}

const SecurityApi& SecurityApi::Get() {
  static const SecurityApi api;
  return api;
}

SecurityApi::SecurityApi()
    : handle_(OpenFramework(kSecurityPath)),
      SecCertificateCopyData(LoadFunction<decltype(SecCertificateCopyData)>(
          handle_, "SecCertificateCopyData")),
      SecItemCopyMatching(LoadFunction<decltype(SecItemCopyMatching)>(
          handle_, "SecItemCopyMatching")),
      SecPolicyCopyProperties(LoadFunction<decltype(SecPolicyCopyProperties)>(
          handle_, "SecPolicyCopyProperties")),
      SecPolicyCreateSSL(LoadFunction<decltype(SecPolicyCreateSSL)>(
          handle_, "SecPolicyCreateSSL")),
      SecTrustCreateWithCertificates(
          LoadFunction<decltype(SecTrustCreateWithCertificates)>(
              handle_, "SecTrustCreateWithCertificates")),
      SecTrustEvaluateWithError(
          LoadFunction<decltype(SecTrustEvaluateWithError)>(
              handle_, "SecTrustEvaluateWithError")),
      SecTrustSettingsCopyTrustSettings(
          LoadFunction<decltype(SecTrustSettingsCopyTrustSettings)>(
              handle_, "SecTrustSettingsCopyTrustSettings")),
      kSecClass(LoadData<CFStringRef>(handle_, "kSecClass")),
      kSecClassCertificate(
          LoadData<CFStringRef>(handle_, "kSecClassCertificate")),
      kSecMatchLimit(LoadData<CFStringRef>(handle_, "kSecMatchLimit")),
      kSecMatchLimitAll(LoadData<CFStringRef>(handle_, "kSecMatchLimitAll")),
      kSecPolicyAppleSSL(LoadData<CFStringRef>(handle_, "kSecPolicyAppleSSL")),
      kSecPolicyOid(LoadData<CFStringRef>(handle_, "kSecPolicyOid")),
      kSecReturnRef(LoadData<CFStringRef>(handle_, "kSecReturnRef")),
      trust_settings_application(
          CreateTrustSettingsKey("kSecTrustSettingsApplication")),
      trust_settings_policy(CreateTrustSettingsKey("kSecTrustSettingsPolicy")),
      trust_settings_policy_string(
          CreateTrustSettingsKey("kSecTrustSettingsPolicyString")),
      trust_settings_result(CreateTrustSettingsKey("kSecTrustSettingsResult")) {
}

}  // namespace darwin
}  // namespace node
#endif  // __APPLE__
