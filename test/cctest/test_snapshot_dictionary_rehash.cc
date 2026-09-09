#include "src/handles/handles.h"
#include "src/heap/factory.h"
#include "src/objects/dictionary-inl.h"
#include "src/objects/hash-table-inl.h"
#include "src/objects/property-details.h"
#include "src/roots/roots-inl.h"

#include <cstdio>
#include <vector>

#include "gtest/gtest.h"
#include "v8_private_startup_test_fixture.h"

namespace i = v8::internal;

class SnapshotDictionaryRehashTest : public V8PrivateStartupTestFixture {};

namespace {

constexpr uint32_t kCapacities[] = {16, 32, 64, 128, 256, 512, 2048, 4096};

template <typename Table, int kEntrySize>
void ScrambleWholeEntries(i::Tagged<Table> table) {
  std::vector<i::Tagged<i::Object>> entries(table->Capacity() * kEntrySize);
  i::DisallowGarbageCollection no_gc;
  for (uint32_t entry = 0; entry < table->Capacity(); ++entry) {
    const int index = Table::EntryToIndex(i::InternalIndex(entry));
    for (int field = 0; field < kEntrySize; ++field) {
      entries[entry * kEntrySize + field] = table->get(index + field);
    }
  }
  for (uint32_t entry = 0; entry < table->Capacity(); ++entry) {
    const uint32_t source = (entry + 1) % table->Capacity();
    const int index = Table::EntryToIndex(i::InternalIndex(entry));
    for (int field = 0; field < kEntrySize; ++field) {
      table->set(index + field, entries[source * kEntrySize + field]);
    }
  }
}

template <typename Table, int kEntrySize>
void ExpectEmptyEntriesCleared(i::Isolate* isolate, i::Tagged<Table> table) {
  i::ReadOnlyRoots roots(isolate);
  for (uint32_t entry = 0; entry < table->Capacity(); ++entry) {
    const i::InternalIndex index(entry);
    if (Table::IsKey(roots, table->KeyAt(index))) continue;
    for (int field = 1; field < kEntrySize; ++field) {
      EXPECT_EQ(roots.undefined_value(),
                table->get(Table::EntryToIndex(index) + field));
    }
  }
}

struct NameDictionaryEntry {
  i::DirectHandle<i::Name> key;
  i::DirectHandle<i::Object> value;
  i::Tagged<i::Smi> details;
};

void TestNameDictionary(i::Isolate* isolate, uint32_t capacity) {
  i::HandleScope scope(isolate);
  auto table = i::NameDictionary::New(
      isolate, capacity, i::AllocationType::kOld,
      i::USE_CUSTOM_MINIMUM_CAPACITY);
  ASSERT_EQ(capacity, table->Capacity());
  std::vector<NameDictionaryEntry> entries;
  for (uint32_t entry = 0; entry < capacity / 2; ++entry) {
    char name[64];
    std::snprintf(name, sizeof(name), "snapshot-name-%u-%u", capacity, entry);
    i::DirectHandle<i::Name> key =
        isolate->factory()->InternalizeUtf8String(name);
    i::DirectHandle<i::Object> value =
        isolate->factory()->NewFixedArray(static_cast<int>(entry + 1));
    table = i::NameDictionary::Add(isolate, table, key, value,
                                   i::PropertyDetails::Empty())
                .ToHandleChecked();
    const i::InternalIndex found = table->FindEntry(isolate, key);
    ASSERT_TRUE(found.is_found());
    entries.push_back({key, value, table->DetailsAt(found).AsSmi()});
  }

  const i::InternalIndex deleted = table->FindEntry(isolate, entries.back().key);
  ASSERT_TRUE(deleted.is_found());
  table = i::NameDictionary::DeleteEntry(isolate, table, deleted);
  entries.pop_back();
  const int hash = table->Hash();
  const int next_enumeration_index = table->next_enumeration_index();
  const int flags = i::Smi::ToInt(table->get(i::NameDictionary::kFlagsIndex));

  ScrambleWholeEntries<i::NameDictionary, i::NameDictionaryShape::kEntrySize>(
      *table);
  table->RehashForSnapshotWithBoundedScratch(isolate);
  EXPECT_EQ(capacity, table->Capacity());
  EXPECT_EQ(entries.size(), table->NumberOfElements());
  EXPECT_EQ(0u, table->NumberOfDeletedElements());
  EXPECT_EQ(hash, table->Hash());
  EXPECT_EQ(next_enumeration_index, table->next_enumeration_index());
  EXPECT_EQ(flags, i::Smi::ToInt(table->get(i::NameDictionary::kFlagsIndex)));
  for (const NameDictionaryEntry& expected : entries) {
    const i::InternalIndex found = table->FindEntry(isolate, expected.key);
    ASSERT_TRUE(found.is_found());
    EXPECT_EQ(*expected.value, table->ValueAt(found));
    EXPECT_EQ(expected.details, table->DetailsAt(found).AsSmi());
  }
  if (capacity >= 32 && capacity <= 2048) {
    ExpectEmptyEntriesCleared<i::NameDictionary,
                              i::NameDictionaryShape::kEntrySize>(isolate,
                                                                   *table);
  }
}

void TestNameToIndexHashTable(i::Isolate* isolate, uint32_t capacity) {
  i::HandleScope scope(isolate);
  auto table = i::NameToIndexHashTable::New(
      isolate, capacity, i::AllocationType::kOld,
      i::USE_CUSTOM_MINIMUM_CAPACITY);
  ASSERT_EQ(capacity, table->Capacity());
  std::vector<i::DirectHandle<i::Name>> keys;
  for (uint32_t entry = 0; entry < capacity / 2; ++entry) {
    char name[64];
    std::snprintf(name, sizeof(name), "snapshot-index-%u-%u", capacity, entry);
    i::DirectHandle<i::Name> key =
        isolate->factory()->InternalizeUtf8String(name);
    table = i::NameToIndexHashTable::Add(isolate, table, key, entry + 100);
    keys.push_back(key);
  }
  ScrambleWholeEntries<i::NameToIndexHashTable,
                       i::NameToIndexShape::kEntrySize>(*table);
  table->RehashForSnapshotWithBoundedScratch(isolate);
  EXPECT_EQ(capacity, table->Capacity());
  EXPECT_EQ(keys.size(), table->NumberOfElements());
  EXPECT_EQ(0u, table->NumberOfDeletedElements());
  for (uint32_t entry = 0; entry < keys.size(); ++entry) {
    const i::InternalIndex found = table->FindEntry(isolate, *keys[entry]);
    ASSERT_TRUE(found.is_found());
    EXPECT_EQ(static_cast<int>(entry + 100), table->IndexAt(found));
  }
  if (capacity >= 32 && capacity <= 2048) {
    ExpectEmptyEntriesCleared<i::NameToIndexHashTable,
                              i::NameToIndexShape::kEntrySize>(isolate,
                                                                *table);
  }
}

}  // namespace

TEST_F(SnapshotDictionaryRehashTest, RehashForSnapshotPreservesEntries) {
  v8::Isolate* public_isolate = NewTestIsolate();
  v8::Isolate::Scope isolate_scope(public_isolate);
  v8::HandleScope handle_scope(public_isolate);
  i::Isolate* isolate = reinterpret_cast<i::Isolate*>(public_isolate);
  for (uint32_t capacity : kCapacities) {
    TestNameDictionary(isolate, capacity);
    TestNameToIndexHashTable(isolate, capacity);
  }
}

void NodeStartupDictionaryRehashTestsAnchor() {}
