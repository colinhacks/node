{
  'variables': {
    'ada_sources': [ 'ada.cpp' ],
  },
  'targets': [
    {
      'target_name': 'ada',
      'type': 'static_library',
      'include_dirs': [
        '.',
        '<(DEPTH)/deps/v8/third_party/simdutf',
      ],
      'direct_dependent_settings': {
        'include_dirs': ['.'],
      },
      'defines': [
        'ADA_USE_SIMDUTF=1',
      ],
      'dependencies': [
        '../../tools/v8_gypfiles/v8.gyp:simdutf',
      ],
      'sources': [ '<@(ada_sources)' ],
      'conditions': [
        ['OS=="mac" and node_shared=="false"', {
          'xcode_settings': {
            'GCC_SYMBOLS_PRIVATE_EXTERN': 'YES',
            'GCC_INLINES_ARE_PRIVATE_EXTERN': 'YES',
          },
        }],
      ],
    },
  ]
}
