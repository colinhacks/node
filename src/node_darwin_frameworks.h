#ifndef SRC_NODE_DARWIN_FRAMEWORKS_H_
#define SRC_NODE_DARWIN_FRAMEWORKS_H_

#ifdef __APPLE__
#include <CoreFoundation/CoreFoundation.h>
#include <Security/Security.h>
#include <TargetConditionals.h>

namespace node {
namespace darwin {

class CoreFoundationApi {
 private:
  void* handle_;

 public:
  static const CoreFoundationApi& Get();

  decltype(&::CFArrayCreateMutable) CFArrayCreateMutable;
  decltype(&::CFArrayGetCount) CFArrayGetCount;
  decltype(&::CFArrayGetValueAtIndex) CFArrayGetValueAtIndex;
  decltype(&::CFArraySetValueAtIndex) CFArraySetValueAtIndex;
  decltype(&::CFDataGetBytePtr) CFDataGetBytePtr;
  decltype(&::CFDataGetLength) CFDataGetLength;
  decltype(&::CFDictionaryContainsKey) CFDictionaryContainsKey;
  decltype(&::CFDictionaryCreate) CFDictionaryCreate;
  decltype(&::CFDictionaryGetValue) CFDictionaryGetValue;
  decltype(&::CFEqual) CFEqual;
  decltype(&::CFNumberGetValue) CFNumberGetValue;
  decltype(&::CFRelease) CFRelease;
  decltype(&::CFStringCreateWithCString) CFStringCreateWithCString;

  CFAllocatorRef kCFAllocatorDefault;
  CFBooleanRef kCFBooleanTrue;
  const CFArrayCallBacks* kCFTypeArrayCallBacks;
  const CFDictionaryKeyCallBacks* kCFTypeDictionaryKeyCallBacks;
  const CFDictionaryValueCallBacks* kCFTypeDictionaryValueCallBacks;

 private:
  CoreFoundationApi();
};

class SecurityApi {
 private:
  void* handle_;

 public:
  static const SecurityApi& Get();

  decltype(&::SecCertificateCopyData) SecCertificateCopyData;
  decltype(&::SecItemCopyMatching) SecItemCopyMatching;
  decltype(&::SecPolicyCopyProperties) SecPolicyCopyProperties;
  decltype(&::SecPolicyCreateSSL) SecPolicyCreateSSL;
  decltype(&::SecTrustCreateWithCertificates) SecTrustCreateWithCertificates;
  decltype(&::SecTrustEvaluateWithError) SecTrustEvaluateWithError;
  decltype(&::SecTrustSettingsCopyTrustSettings)
      SecTrustSettingsCopyTrustSettings;

  CFStringRef kSecClass;
  CFStringRef kSecClassCertificate;
  CFStringRef kSecMatchLimit;
  CFStringRef kSecMatchLimitAll;
  CFStringRef kSecPolicyAppleSSL;
  CFStringRef kSecPolicyOid;
  CFStringRef kSecReturnRef;
  CFStringRef trust_settings_application;
  CFStringRef trust_settings_policy;
  CFStringRef trust_settings_policy_string;
  CFStringRef trust_settings_result;

 private:
  SecurityApi();
};

}  // namespace darwin
}  // namespace node
#endif  // __APPLE__

#endif  // SRC_NODE_DARWIN_FRAMEWORKS_H_
