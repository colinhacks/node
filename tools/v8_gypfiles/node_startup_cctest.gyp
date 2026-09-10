{
  'includes': [
    'toolchain.gypi',
    'features.gypi',
  ],
  'targets': [
    {
      'target_name': 'v8_private_cctest_cases',
      'type': 'static_library',
      'toolsets': ['target'],
      # Private V8 object layouts are supported only with the bundled static
      # Node/V8 cctest link; external V8 and shared libnode skip these cases.
      'dependencies': [
        'abseil.gyp:abseil',
        'v8.gyp:v8_internal_headers',
        'v8.gyp:v8_maybe_icu',
      ],
      'include_dirs': [
        '<(SHARED_INTERMEDIATE_DIR)',
        '<(SHARED_INTERMEDIATE_DIR)/generate-bytecode-output-root',
        '../../src',
        '../../tools/msvs/genfiles',
        '../../deps/v8/include',
        '../../deps/v8',
        '../../test/cctest',
        '../../deps/uv/include',
      ],
      'sources': [
        '../../test/cctest/test_snapshot_dictionary_rehash.cc',
        '../../test/cctest/test_source_position_collection.cc',
        '../../test/cctest/test_source_positions_advanced.cc',
      ],
      'conditions': [
        [ 'OS!="aix" and OS!="os400"', {
          'defines': [
            'BUILDING_V8_SHARED',
            'BUILDING_V8_PLATFORM_SHARED',
          ],
        }],
        [ 'OS=="mac"', {
          'xcode_settings': {
            'GCC_SYMBOLS_PRIVATE_EXTERN': 'YES',
            'GCC_INLINES_ARE_PRIVATE_EXTERN': 'YES',
          },
        }, '(OS!="aix" and OS!="os400") and (OS!="win" or clang==1)', {
          'cflags': [
            '-fvisibility=hidden',
            '-fvisibility-inlines-hidden',
          ],
        }],
        [ 'node_shared_gtest=="false"', {
          'dependencies': [
            '../../deps/googletest/googletest.gyp:gtest',
          ],
        }],
        [ 'node_use_bundled_v8!="true" or node_shared=="true"', {
          'type': 'none',
          'dependencies!': [
            'v8.gyp:v8_internal_headers',
            'v8.gyp:v8_maybe_icu',
            '../../deps/googletest/googletest.gyp:gtest',
          ],
          'sources!': [
            '../../test/cctest/test_snapshot_dictionary_rehash.cc',
            '../../test/cctest/test_source_position_collection.cc',
            '../../test/cctest/test_source_positions_advanced.cc',
          ],
        }],
      ],
    },
  ],
}
