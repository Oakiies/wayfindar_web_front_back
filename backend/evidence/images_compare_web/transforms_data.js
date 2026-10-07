const TDATA = {
  "floor_id": "floor5",
  "map_K": {
    "f": 1400.0,
    "cx": 960.0,
    "cy": 540.0
  },
  "wide_K": {
    "f": 686.4651700376153,
    "cx": 960.0,
    "cy": 540.0
  },
  "shots": [
    {
      "point": "1",
      "shot": 0,
      "lenses": {
        "normal": {
          "base_img": "../images_compare/1/normal/image_001.jpg",
          "base_w": 1920,
          "base_h": 1080,
          "baseline": {
            "success": true,
            "xy": [
              207.852258765592,
              100.25411312113928
            ],
            "num_inliers": 85
          },
          "modes": {
            "crop": [
              {
                "label": "90% (1728x972)",
                "frac": 0.9,
                "img": "transforms/crop/1_0_normal_90.jpg",
                "w": 1728,
                "h": 972,
                "result": {
                  "success": true,
                  "xy": [
                    207.84786841392855,
                    105.2251600390131
                  ],
                  "num_inliers": 46
                },
                "drift_px": 4.971048856618746
              },
              {
                "label": "75% (1440x810)",
                "frac": 0.75,
                "img": "transforms/crop/1_0_normal_75.jpg",
                "w": 1440,
                "h": 810,
                "result": {
                  "success": true,
                  "xy": [
                    206.3897575957096,
                    112.01338622482123
                  ],
                  "num_inliers": 27
                },
                "drift_px": 11.849869771389269
              },
              {
                "label": "60% (1152x648)",
                "frac": 0.6,
                "img": "transforms/crop/1_0_normal_60.jpg",
                "w": 1152,
                "h": 648,
                "result": {
                  "success": true,
                  "xy": [
                    208.14953064998494,
                    118.452405723675
                  ],
                  "num_inliers": 19
                },
                "drift_px": 18.200720431366356
              },
              {
                "label": "50% (960x540)",
                "frac": 0.5,
                "img": "transforms/crop/1_0_normal_50.jpg",
                "w": 960,
                "h": 540,
                "result": {
                  "success": true,
                  "xy": [
                    208.22090590545045,
                    123.07881330686955
                  ],
                  "num_inliers": 19
                },
                "drift_px": 22.82767704524928
              },
              {
                "label": "40% (768x432)",
                "frac": 0.4,
                "img": "transforms/crop/1_0_normal_40.jpg",
                "w": 768,
                "h": 432,
                "result": {
                  "success": true,
                  "xy": [
                    208.80110932186594,
                    127.62025078523055
                  ],
                  "num_inliers": 16
                },
                "drift_px": 27.382582201613786
              },
              {
                "label": "30% (576x324)",
                "frac": 0.3,
                "img": "transforms/crop/1_0_normal_30.jpg",
                "w": 576,
                "h": 324,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              }
            ],
            "resize": [
              {
                "label": "75% (1440x810)",
                "frac": 0.75,
                "img": "transforms/resize/1_0_normal_75.jpg",
                "w": 1440,
                "h": 810,
                "result": {
                  "success": true,
                  "xy": [
                    207.93602535440368,
                    100.25046183123163
                  ],
                  "num_inliers": 75
                },
                "drift_px": 0.08384612882616088
              },
              {
                "label": "50% (960x540)",
                "frac": 0.5,
                "img": "transforms/resize/1_0_normal_50.jpg",
                "w": 960,
                "h": 540,
                "result": {
                  "success": true,
                  "xy": [
                    207.9333666612606,
                    100.19923191555044
                  ],
                  "num_inliers": 75
                },
                "drift_px": 0.09793077895469007
              },
              {
                "label": "35% (672x378)",
                "frac": 0.35,
                "img": "transforms/resize/1_0_normal_35.jpg",
                "w": 672,
                "h": 378,
                "result": {
                  "success": true,
                  "xy": [
                    207.89708469519047,
                    100.22539926792075
                  ],
                  "num_inliers": 86
                },
                "drift_px": 0.05323391147587773
              },
              {
                "label": "25% (480x270)",
                "frac": 0.25,
                "img": "transforms/resize/1_0_normal_25.jpg",
                "w": 480,
                "h": 270,
                "result": {
                  "success": true,
                  "xy": [
                    207.98741511298263,
                    100.19821980011737
                  ],
                  "num_inliers": 78
                },
                "drift_px": 0.1462576547563662
              },
              {
                "label": "15% (288x162)",
                "frac": 0.15,
                "img": "transforms/resize/1_0_normal_15.jpg",
                "w": 288,
                "h": 162,
                "result": {
                  "success": true,
                  "xy": [
                    207.7564354223269,
                    100.45555468547082
                  ],
                  "num_inliers": 83
                },
                "drift_px": 0.2230713270567072
              }
            ],
            "zoom": [
              {
                "label": "1.25x zoom (1920x1080)",
                "frac": 1.25,
                "img": "transforms/zoom/1_0_normal_125x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": true,
                  "xy": [
                    206.9300999087145,
                    109.63195998535643
                  ],
                  "num_inliers": 32
                },
                "drift_px": 9.423077457286713
              },
              {
                "label": "1.5x zoom (1920x1080)",
                "frac": 1.5,
                "img": "transforms/zoom/1_0_normal_15x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": true,
                  "xy": [
                    208.2873656572897,
                    115.49442545877461
                  ],
                  "num_inliers": 18
                },
                "drift_px": 15.246522165919759
              },
              {
                "label": "2x zoom (1920x1080)",
                "frac": 2.0,
                "img": "transforms/zoom/1_0_normal_20x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": true,
                  "xy": [
                    208.11539819670472,
                    123.19629294426508
                  ],
                  "num_inliers": 18
                },
                "drift_px": 22.943688835861742
              },
              {
                "label": "3x zoom (1920x1080)",
                "frac": 3.0,
                "img": "transforms/zoom/1_0_normal_30x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              },
              {
                "label": "4x zoom (1920x1080)",
                "frac": 4.0,
                "img": "transforms/zoom/1_0_normal_40x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              }
            ]
          }
        },
        "wide": {
          "base_img": "../images_compare/1/wide/image_001_wide.jpg",
          "base_w": 4032,
          "base_h": 3024,
          "baseline": {
            "success": true,
            "xy": [
              210.6830056915399,
              93.91765955837283
            ],
            "num_inliers": 34
          },
          "modes": {
            "crop": [
              {
                "label": "90% (3628x2722)",
                "frac": 0.9,
                "img": "transforms/crop/1_0_wide_90.jpg",
                "w": 3628,
                "h": 2722,
                "result": {
                  "success": true,
                  "xy": [
                    210.3363582691949,
                    99.14181571968243
                  ],
                  "num_inliers": 42
                },
                "drift_px": 5.235644376117177
              },
              {
                "label": "75% (3024x2268)",
                "frac": 0.75,
                "img": "transforms/crop/1_0_wide_75.jpg",
                "w": 3024,
                "h": 2268,
                "result": {
                  "success": true,
                  "xy": [
                    208.85432816597964,
                    107.0150519368031
                  ],
                  "num_inliers": 28
                },
                "drift_px": 13.224437553523877
              },
              {
                "label": "60% (2420x1814)",
                "frac": 0.6,
                "img": "transforms/crop/1_0_wide_60.jpg",
                "w": 2420,
                "h": 1814,
                "result": {
                  "success": true,
                  "xy": [
                    207.395770798099,
                    115.62649692051787
                  ],
                  "num_inliers": 23
                },
                "drift_px": 21.956309636656147
              },
              {
                "label": "50% (2016x1512)",
                "frac": 0.5,
                "img": "transforms/crop/1_0_wide_50.jpg",
                "w": 2016,
                "h": 1512,
                "result": {
                  "success": true,
                  "xy": [
                    205.99406882782822,
                    122.58225349733691
                  ],
                  "num_inliers": 21
                },
                "drift_px": 29.045568932241117
              },
              {
                "label": "40% (1612x1210)",
                "frac": 0.4,
                "img": "transforms/crop/1_0_wide_40.jpg",
                "w": 1612,
                "h": 1210,
                "result": {
                  "success": true,
                  "xy": [
                    204.8367655953746,
                    122.47102147137164
                  ],
                  "num_inliers": 20
                },
                "drift_px": 29.145720093981243
              },
              {
                "label": "30% (1210x908)",
                "frac": 0.3,
                "img": "transforms/crop/1_0_wide_30.jpg",
                "w": 1210,
                "h": 908,
                "result": {
                  "success": true,
                  "xy": [
                    207.0469750137473,
                    128.47106154611362
                  ],
                  "num_inliers": 12
                },
                "drift_px": 34.74418380126748
              }
            ],
            "resize": [
              {
                "label": "75% (3024x2268)",
                "frac": 0.75,
                "img": "transforms/resize/1_0_wide_75.jpg",
                "w": 3024,
                "h": 2268,
                "result": {
                  "success": true,
                  "xy": [
                    211.29149354104348,
                    94.95269482095716
                  ],
                  "num_inliers": 31
                },
                "drift_px": 1.200647932487496
              },
              {
                "label": "50% (2016x1512)",
                "frac": 0.5,
                "img": "transforms/resize/1_0_wide_50.jpg",
                "w": 2016,
                "h": 1512,
                "result": {
                  "success": true,
                  "xy": [
                    211.72726444001103,
                    94.06376688056828
                  ],
                  "num_inliers": 33
                },
                "drift_px": 1.0544305019097273
              },
              {
                "label": "35% (1412x1058)",
                "frac": 0.35,
                "img": "transforms/resize/1_0_wide_35.jpg",
                "w": 1412,
                "h": 1058,
                "result": {
                  "success": true,
                  "xy": [
                    210.62632108816493,
                    93.74926438286509
                  ],
                  "num_inliers": 29
                },
                "drift_px": 0.17767971013613487
              },
              {
                "label": "25% (1008x756)",
                "frac": 0.25,
                "img": "transforms/resize/1_0_wide_25.jpg",
                "w": 1008,
                "h": 756,
                "result": {
                  "success": true,
                  "xy": [
                    211.38581633651916,
                    94.8831803637237
                  ],
                  "num_inliers": 28
                },
                "drift_px": 1.1942249487686694
              },
              {
                "label": "15% (604x454)",
                "frac": 0.15,
                "img": "transforms/resize/1_0_wide_15.jpg",
                "w": 604,
                "h": 454,
                "result": {
                  "success": true,
                  "xy": [
                    211.61375858984925,
                    94.77879275355915
                  ],
                  "num_inliers": 25
                },
                "drift_px": 1.2680107797503315
              }
            ],
            "zoom": [
              {
                "label": "1.25x zoom (4032x3024)",
                "frac": 1.25,
                "img": "transforms/zoom/1_0_wide_125x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    208.98687276940095,
                    102.52674776312062
                  ],
                  "num_inliers": 35
                },
                "drift_px": 8.774580708312575
              },
              {
                "label": "1.5x zoom (4032x3024)",
                "frac": 1.5,
                "img": "transforms/zoom/1_0_wide_15x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    207.97480959049,
                    112.34153141332358
                  ],
                  "num_inliers": 24
                },
                "drift_px": 18.621852223916616
              },
              {
                "label": "2x zoom (4032x3024)",
                "frac": 2.0,
                "img": "transforms/zoom/1_0_wide_20x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    205.94141200981588,
                    122.63176358645835
                  ],
                  "num_inliers": 20
                },
                "drift_px": 29.102963436363005
              },
              {
                "label": "3x zoom (4032x3024)",
                "frac": 3.0,
                "img": "transforms/zoom/1_0_wide_30x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    202.18548068162556,
                    129.27971218793328
                  ],
                  "num_inliers": 15
                },
                "drift_px": 36.368704918788666
              },
              {
                "label": "4x zoom (4032x3024)",
                "frac": 4.0,
                "img": "transforms/zoom/1_0_wide_40x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              }
            ]
          }
        }
      }
    },
    {
      "point": "1",
      "shot": 1,
      "lenses": {
        "normal": {
          "base_img": "../images_compare/1/normal/image_002.jpg",
          "base_w": 1920,
          "base_h": 1080,
          "baseline": {
            "success": true,
            "xy": [
              206.64803923709553,
              88.8218317418053
            ],
            "num_inliers": 72
          },
          "modes": {
            "crop": [
              {
                "label": "90% (1728x972)",
                "frac": 0.9,
                "img": "transforms/crop/1_1_normal_90.jpg",
                "w": 1728,
                "h": 972,
                "result": {
                  "success": true,
                  "xy": [
                    207.2198726358946,
                    85.22943532173642
                  ],
                  "num_inliers": 41
                },
                "drift_px": 3.637623602698031
              },
              {
                "label": "75% (1440x810)",
                "frac": 0.75,
                "img": "transforms/crop/1_1_normal_75.jpg",
                "w": 1440,
                "h": 810,
                "result": {
                  "success": true,
                  "xy": [
                    206.90373623529626,
                    76.52028521243962
                  ],
                  "num_inliers": 20
                },
                "drift_px": 12.304203670658158
              },
              {
                "label": "60% (1152x648)",
                "frac": 0.6,
                "img": "transforms/crop/1_1_normal_60.jpg",
                "w": 1152,
                "h": 648,
                "result": {
                  "success": true,
                  "xy": [
                    208.98913301216143,
                    78.79900459976108
                  ],
                  "num_inliers": 13
                },
                "drift_px": 10.29260822060913
              },
              {
                "label": "50% (960x540)",
                "frac": 0.5,
                "img": "transforms/crop/1_1_normal_50.jpg",
                "w": 960,
                "h": 540,
                "result": {
                  "success": true,
                  "xy": [
                    206.89021297385588,
                    64.8295557444793
                  ],
                  "num_inliers": 11
                },
                "drift_px": 23.993498195357883
              },
              {
                "label": "40% (768x432)",
                "frac": 0.4,
                "img": "transforms/crop/1_1_normal_40.jpg",
                "w": 768,
                "h": 432,
                "result": {
                  "success": true,
                  "xy": [
                    204.7438931634615,
                    59.685591428232975
                  ],
                  "num_inliers": 14
                },
                "drift_px": 29.198395022329102
              },
              {
                "label": "30% (576x324)",
                "frac": 0.3,
                "img": "transforms/crop/1_1_normal_30.jpg",
                "w": 576,
                "h": 324,
                "result": {
                  "success": true,
                  "xy": [
                    201.97130411233266,
                    53.75956981327644
                  ],
                  "num_inliers": 11
                },
                "drift_px": 35.37278703992597
              }
            ],
            "resize": [
              {
                "label": "75% (1440x810)",
                "frac": 0.75,
                "img": "transforms/resize/1_1_normal_75.jpg",
                "w": 1440,
                "h": 810,
                "result": {
                  "success": true,
                  "xy": [
                    206.6393288286063,
                    88.81010526850561
                  ],
                  "num_inliers": 70
                },
                "drift_px": 0.014607579953492152
              },
              {
                "label": "50% (960x540)",
                "frac": 0.5,
                "img": "transforms/resize/1_1_normal_50.jpg",
                "w": 960,
                "h": 540,
                "result": {
                  "success": true,
                  "xy": [
                    206.64341166399402,
                    88.81657876856686
                  ],
                  "num_inliers": 72
                },
                "drift_px": 0.007000582879564657
              },
              {
                "label": "35% (672x378)",
                "frac": 0.35,
                "img": "transforms/resize/1_1_normal_35.jpg",
                "w": 672,
                "h": 378,
                "result": {
                  "success": true,
                  "xy": [
                    206.64870950918413,
                    88.81513343466004
                  ],
                  "num_inliers": 75
                },
                "drift_px": 0.006731759300877684
              },
              {
                "label": "25% (480x270)",
                "frac": 0.25,
                "img": "transforms/resize/1_1_normal_25.jpg",
                "w": 480,
                "h": 270,
                "result": {
                  "success": true,
                  "xy": [
                    206.62905060693964,
                    88.843106253835
                  ],
                  "num_inliers": 67
                },
                "drift_px": 0.028516187285456247
              },
              {
                "label": "15% (288x162)",
                "frac": 0.15,
                "img": "transforms/resize/1_1_normal_15.jpg",
                "w": 288,
                "h": 162,
                "result": {
                  "success": true,
                  "xy": [
                    206.53633685255852,
                    88.89473456838847
                  ],
                  "num_inliers": 66
                },
                "drift_px": 0.1333875737655901
              }
            ],
            "zoom": [
              {
                "label": "1.25x zoom (1920x1080)",
                "frac": 1.25,
                "img": "transforms/zoom/1_1_normal_125x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": true,
                  "xy": [
                    206.63726296489466,
                    78.2598212038124
                  ],
                  "num_inliers": 26
                },
                "drift_px": 10.56201603543167
              },
              {
                "label": "1.5x zoom (1920x1080)",
                "frac": 1.5,
                "img": "transforms/zoom/1_1_normal_15x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": true,
                  "xy": [
                    208.65703340105705,
                    72.32782072857378
                  ],
                  "num_inliers": 11
                },
                "drift_px": 16.6159097510619
              },
              {
                "label": "2x zoom (1920x1080)",
                "frac": 2.0,
                "img": "transforms/zoom/1_1_normal_20x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": true,
                  "xy": [
                    202.55826131356636,
                    56.2222040612013
                  ],
                  "num_inliers": 14
                },
                "drift_px": 32.855167148833516
              },
              {
                "label": "3x zoom (1920x1080)",
                "frac": 3.0,
                "img": "transforms/zoom/1_1_normal_30x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": true,
                  "xy": [
                    201.55578427291928,
                    55.10707956485563
                  ],
                  "num_inliers": 12
                },
                "drift_px": 34.09714907398139
              },
              {
                "label": "4x zoom (1920x1080)",
                "frac": 4.0,
                "img": "transforms/zoom/1_1_normal_40x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              }
            ]
          }
        },
        "wide": {
          "base_img": "../images_compare/1/wide/image_002_wide.jpg",
          "base_w": 4032,
          "base_h": 3024,
          "baseline": {
            "success": true,
            "xy": [
              201.4521129192908,
              94.43952260815244
            ],
            "num_inliers": 40
          },
          "modes": {
            "crop": [
              {
                "label": "90% (3628x2722)",
                "frac": 0.9,
                "img": "transforms/crop/1_1_wide_90.jpg",
                "w": 3628,
                "h": 2722,
                "result": {
                  "success": true,
                  "xy": [
                    202.670112644329,
                    90.52047454891299
                  ],
                  "num_inliers": 54
                },
                "drift_px": 4.10395675182155
              },
              {
                "label": "75% (3024x2268)",
                "frac": 0.75,
                "img": "transforms/crop/1_1_wide_75.jpg",
                "w": 3024,
                "h": 2268,
                "result": {
                  "success": true,
                  "xy": [
                    204.80648926575105,
                    85.84548052712134
                  ],
                  "num_inliers": 36
                },
                "drift_px": 9.225475595557414
              },
              {
                "label": "60% (2420x1814)",
                "frac": 0.6,
                "img": "transforms/crop/1_1_wide_60.jpg",
                "w": 2420,
                "h": 1814,
                "result": {
                  "success": true,
                  "xy": [
                    206.22440688787705,
                    80.81491660186018
                  ],
                  "num_inliers": 24
                },
                "drift_px": 14.43622798896235
              },
              {
                "label": "50% (2016x1512)",
                "frac": 0.5,
                "img": "transforms/crop/1_1_wide_50.jpg",
                "w": 2016,
                "h": 1512,
                "result": {
                  "success": true,
                  "xy": [
                    207.65332820595242,
                    81.21754074146358
                  ],
                  "num_inliers": 20
                },
                "drift_px": 14.603967800381332
              },
              {
                "label": "40% (1612x1210)",
                "frac": 0.4,
                "img": "transforms/crop/1_1_wide_40.jpg",
                "w": 1612,
                "h": 1210,
                "result": {
                  "success": true,
                  "xy": [
                    208.5618579165295,
                    76.31582616086571
                  ],
                  "num_inliers": 16
                },
                "drift_px": 19.468355011123933
              },
              {
                "label": "30% (1210x908)",
                "frac": 0.3,
                "img": "transforms/crop/1_1_wide_30.jpg",
                "w": 1210,
                "h": 908,
                "result": {
                  "success": true,
                  "xy": [
                    207.1351587581856,
                    62.19837919021007
                  ],
                  "num_inliers": 12
                },
                "drift_px": 32.73817861310107
              }
            ],
            "resize": [
              {
                "label": "75% (3024x2268)",
                "frac": 0.75,
                "img": "transforms/resize/1_1_wide_75.jpg",
                "w": 3024,
                "h": 2268,
                "result": {
                  "success": true,
                  "xy": [
                    201.45170177772877,
                    94.35386732868878
                  ],
                  "num_inliers": 40
                },
                "drift_px": 0.08565626618866064
              },
              {
                "label": "50% (2016x1512)",
                "frac": 0.5,
                "img": "transforms/resize/1_1_wide_50.jpg",
                "w": 2016,
                "h": 1512,
                "result": {
                  "success": true,
                  "xy": [
                    201.26257765442728,
                    94.5815219457622
                  ],
                  "num_inliers": 39
                },
                "drift_px": 0.23682784572026538
              },
              {
                "label": "35% (1412x1058)",
                "frac": 0.35,
                "img": "transforms/resize/1_1_wide_35.jpg",
                "w": 1412,
                "h": 1058,
                "result": {
                  "success": true,
                  "xy": [
                    200.61326646245172,
                    93.80121647927928
                  ],
                  "num_inliers": 38
                },
                "drift_px": 1.0540863780110954
              },
              {
                "label": "25% (1008x756)",
                "frac": 0.25,
                "img": "transforms/resize/1_1_wide_25.jpg",
                "w": 1008,
                "h": 756,
                "result": {
                  "success": true,
                  "xy": [
                    200.5669472796796,
                    94.1698293319564
                  ],
                  "num_inliers": 23
                },
                "drift_px": 0.9253392203801225
              },
              {
                "label": "15% (604x454)",
                "frac": 0.15,
                "img": "transforms/resize/1_1_wide_15.jpg",
                "w": 604,
                "h": 454,
                "result": {
                  "success": true,
                  "xy": [
                    200.8670986681362,
                    92.87519801283794
                  ],
                  "num_inliers": 19
                },
                "drift_px": 1.6701356572326287
              }
            ],
            "zoom": [
              {
                "label": "1.25x zoom (4032x3024)",
                "frac": 1.25,
                "img": "transforms/zoom/1_1_wide_125x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    203.3665568353444,
                    87.19555963416704
                  ],
                  "num_inliers": 43
                },
                "drift_px": 7.492669422588057
              },
              {
                "label": "1.5x zoom (4032x3024)",
                "frac": 1.5,
                "img": "transforms/zoom/1_1_wide_15x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    205.66219148376803,
                    82.55421120775864
                  ],
                  "num_inliers": 32
                },
                "drift_px": 12.608940820045172
              },
              {
                "label": "2x zoom (4032x3024)",
                "frac": 2.0,
                "img": "transforms/zoom/1_1_wide_20x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    206.33899592057656,
                    78.69771609172705
                  ],
                  "num_inliers": 21
                },
                "drift_px": 16.482903199037143
              },
              {
                "label": "3x zoom (4032x3024)",
                "frac": 3.0,
                "img": "transforms/zoom/1_1_wide_30x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    209.7850370597234,
                    74.90898347727062
                  ],
                  "num_inliers": 12
                },
                "drift_px": 21.233925295929396
              },
              {
                "label": "4x zoom (4032x3024)",
                "frac": 4.0,
                "img": "transforms/zoom/1_1_wide_40x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    207.16926008601502,
                    61.86581644032275
                  ],
                  "num_inliers": 10
                },
                "drift_px": 33.07162084377009
              }
            ]
          }
        }
      }
    },
    {
      "point": "2",
      "shot": 0,
      "lenses": {
        "normal": {
          "base_img": "../images_compare/2/normal/image_004.jpg",
          "base_w": 1920,
          "base_h": 1080,
          "baseline": {
            "success": true,
            "xy": [
              206.7397812817286,
              132.09139006742637
            ],
            "num_inliers": 70
          },
          "modes": {
            "crop": [
              {
                "label": "90% (1728x972)",
                "frac": 0.9,
                "img": "transforms/crop/2_0_normal_90.jpg",
                "w": 1728,
                "h": 972,
                "result": {
                  "success": true,
                  "xy": [
                    206.9302885020627,
                    127.39865038046676
                  ],
                  "num_inliers": 44
                },
                "drift_px": 4.696605026033723
              },
              {
                "label": "75% (1440x810)",
                "frac": 0.75,
                "img": "transforms/crop/2_0_normal_75.jpg",
                "w": 1440,
                "h": 810,
                "result": {
                  "success": true,
                  "xy": [
                    205.10424392771387,
                    122.05096592622152
                  ],
                  "num_inliers": 19
                },
                "drift_px": 10.172762622398436
              },
              {
                "label": "60% (1152x648)",
                "frac": 0.6,
                "img": "transforms/crop/2_0_normal_60.jpg",
                "w": 1152,
                "h": 648,
                "result": {
                  "success": true,
                  "xy": [
                    209.22530614578645,
                    111.39222704241851
                  ],
                  "num_inliers": 13
                },
                "drift_px": 20.84785801433093
              },
              {
                "label": "50% (960x540)",
                "frac": 0.5,
                "img": "transforms/crop/2_0_normal_50.jpg",
                "w": 960,
                "h": 540,
                "result": {
                  "success": true,
                  "xy": [
                    209.84021892848895,
                    108.47416787595122
                  ],
                  "num_inliers": 11
                },
                "drift_px": 23.819863510166364
              },
              {
                "label": "40% (768x432)",
                "frac": 0.4,
                "img": "transforms/crop/2_0_normal_40.jpg",
                "w": 768,
                "h": 432,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              },
              {
                "label": "30% (576x324)",
                "frac": 0.3,
                "img": "transforms/crop/2_0_normal_30.jpg",
                "w": 576,
                "h": 324,
                "result": {
                  "success": true,
                  "xy": [
                    212.86908113350307,
                    95.95551472745622
                  ],
                  "num_inliers": 10
                },
                "drift_px": 36.652009539162044
              }
            ],
            "resize": [
              {
                "label": "75% (1440x810)",
                "frac": 0.75,
                "img": "transforms/resize/2_0_normal_75.jpg",
                "w": 1440,
                "h": 810,
                "result": {
                  "success": true,
                  "xy": [
                    206.71492118395085,
                    132.11932404567494
                  ],
                  "num_inliers": 64
                },
                "drift_px": 0.03739427231957706
              },
              {
                "label": "50% (960x540)",
                "frac": 0.5,
                "img": "transforms/resize/2_0_normal_50.jpg",
                "w": 960,
                "h": 540,
                "result": {
                  "success": true,
                  "xy": [
                    206.7522986257495,
                    132.10058213971115
                  ],
                  "num_inliers": 66
                },
                "drift_px": 0.015529909665736055
              },
              {
                "label": "35% (672x378)",
                "frac": 0.35,
                "img": "transforms/resize/2_0_normal_35.jpg",
                "w": 672,
                "h": 378,
                "result": {
                  "success": true,
                  "xy": [
                    206.766823087278,
                    132.14182200783287
                  ],
                  "num_inliers": 70
                },
                "drift_px": 0.05722446907168431
              },
              {
                "label": "25% (480x270)",
                "frac": 0.25,
                "img": "transforms/resize/2_0_normal_25.jpg",
                "w": 480,
                "h": 270,
                "result": {
                  "success": true,
                  "xy": [
                    206.68028623375776,
                    132.05930609580744
                  ],
                  "num_inliers": 68
                },
                "drift_px": 0.0675946889030279
              },
              {
                "label": "15% (288x162)",
                "frac": 0.15,
                "img": "transforms/resize/2_0_normal_15.jpg",
                "w": 288,
                "h": 162,
                "result": {
                  "success": true,
                  "xy": [
                    206.7223515584888,
                    132.19696127548502
                  ],
                  "num_inliers": 67
                },
                "drift_px": 0.1070003515096005
              }
            ],
            "zoom": [
              {
                "label": "1.25x zoom (1920x1080)",
                "frac": 1.25,
                "img": "transforms/zoom/2_0_normal_125x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": true,
                  "xy": [
                    207.6696120351773,
                    122.80232798864195
                  ],
                  "num_inliers": 22
                },
                "drift_px": 9.335483893916255
              },
              {
                "label": "1.5x zoom (1920x1080)",
                "frac": 1.5,
                "img": "transforms/zoom/2_0_normal_15x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": true,
                  "xy": [
                    207.7240161896129,
                    119.81395313135708
                  ],
                  "num_inliers": 11
                },
                "drift_px": 12.316824918503007
              },
              {
                "label": "2x zoom (1920x1080)",
                "frac": 2.0,
                "img": "transforms/zoom/2_0_normal_20x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": true,
                  "xy": [
                    208.87622134425888,
                    108.44525571052067
                  ],
                  "num_inliers": 11
                },
                "drift_px": 23.742452404198282
              },
              {
                "label": "3x zoom (1920x1080)",
                "frac": 3.0,
                "img": "transforms/zoom/2_0_normal_30x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              },
              {
                "label": "4x zoom (1920x1080)",
                "frac": 4.0,
                "img": "transforms/zoom/2_0_normal_40x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              }
            ]
          }
        },
        "wide": {
          "base_img": "../images_compare/2/wide/image_4_wide.jpg",
          "base_w": 4032,
          "base_h": 3024,
          "baseline": {
            "success": true,
            "xy": [
              204.73799664918167,
              134.9326005400172
            ],
            "num_inliers": 32
          },
          "modes": {
            "crop": [
              {
                "label": "90% (3628x2722)",
                "frac": 0.9,
                "img": "transforms/crop/2_0_wide_90.jpg",
                "w": 3628,
                "h": 2722,
                "result": {
                  "success": true,
                  "xy": [
                    202.6071804952772,
                    134.99405394723513
                  ],
                  "num_inliers": 36
                },
                "drift_px": 2.131702137494579
              },
              {
                "label": "75% (3024x2268)",
                "frac": 0.75,
                "img": "transforms/crop/2_0_wide_75.jpg",
                "w": 3024,
                "h": 2268,
                "result": {
                  "success": true,
                  "xy": [
                    205.0362772312954,
                    126.62669610542656
                  ],
                  "num_inliers": 39
                },
                "drift_px": 8.311258616011093
              },
              {
                "label": "60% (2420x1814)",
                "frac": 0.6,
                "img": "transforms/crop/2_0_wide_60.jpg",
                "w": 2420,
                "h": 1814,
                "result": {
                  "success": true,
                  "xy": [
                    205.20440589077208,
                    123.16135320193523
                  ],
                  "num_inliers": 29
                },
                "drift_px": 11.780483923631618
              },
              {
                "label": "50% (2016x1512)",
                "frac": 0.5,
                "img": "transforms/crop/2_0_wide_50.jpg",
                "w": 2016,
                "h": 1512,
                "result": {
                  "success": true,
                  "xy": [
                    207.29013567510876,
                    115.2052745154915
                  ],
                  "num_inliers": 28
                },
                "drift_px": 19.89172706643617
              },
              {
                "label": "40% (1612x1210)",
                "frac": 0.4,
                "img": "transforms/crop/2_0_wide_40.jpg",
                "w": 1612,
                "h": 1210,
                "result": {
                  "success": true,
                  "xy": [
                    210.24930532855677,
                    110.83151953665529
                  ],
                  "num_inliers": 19
                },
                "drift_px": 24.72320021538409
              },
              {
                "label": "30% (1210x908)",
                "frac": 0.3,
                "img": "transforms/crop/2_0_wide_30.jpg",
                "w": 1210,
                "h": 908,
                "result": {
                  "success": true,
                  "xy": [
                    210.90915552027357,
                    107.47252617087668
                  ],
                  "num_inliers": 13
                },
                "drift_px": 28.144962003367226
              }
            ],
            "resize": [
              {
                "label": "75% (3024x2268)",
                "frac": 0.75,
                "img": "transforms/resize/2_0_wide_75.jpg",
                "w": 3024,
                "h": 2268,
                "result": {
                  "success": true,
                  "xy": [
                    202.2174130189808,
                    141.09807708861166
                  ],
                  "num_inliers": 26
                },
                "drift_px": 6.660813982397703
              },
              {
                "label": "50% (2016x1512)",
                "frac": 0.5,
                "img": "transforms/resize/2_0_wide_50.jpg",
                "w": 2016,
                "h": 1512,
                "result": {
                  "success": true,
                  "xy": [
                    204.89958486392146,
                    134.35280998746273
                  ],
                  "num_inliers": 32
                },
                "drift_px": 0.6018868963303755
              },
              {
                "label": "35% (1412x1058)",
                "frac": 0.35,
                "img": "transforms/resize/2_0_wide_35.jpg",
                "w": 1412,
                "h": 1058,
                "result": {
                  "success": true,
                  "xy": [
                    205.1000720653033,
                    134.21800743944928
                  ],
                  "num_inliers": 28
                },
                "drift_px": 0.8010879516875341
              },
              {
                "label": "25% (1008x756)",
                "frac": 0.25,
                "img": "transforms/resize/2_0_wide_25.jpg",
                "w": 1008,
                "h": 756,
                "result": {
                  "success": true,
                  "xy": [
                    201.63429591554697,
                    142.3017839071757
                  ],
                  "num_inliers": 21
                },
                "drift_px": 7.996112914583549
              },
              {
                "label": "15% (604x454)",
                "frac": 0.15,
                "img": "transforms/resize/2_0_wide_15.jpg",
                "w": 604,
                "h": 454,
                "result": {
                  "success": true,
                  "xy": [
                    201.95954507904364,
                    138.93999602679256
                  ],
                  "num_inliers": 23
                },
                "drift_px": 4.876372803122209
              }
            ],
            "zoom": [
              {
                "label": "1.25x zoom (4032x3024)",
                "frac": 1.25,
                "img": "transforms/zoom/2_0_wide_125x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    203.87368929005177,
                    130.41027827733916
                  ],
                  "num_inliers": 40
                },
                "drift_px": 4.604174829278269
              },
              {
                "label": "1.5x zoom (4032x3024)",
                "frac": 1.5,
                "img": "transforms/zoom/2_0_wide_15x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    205.42720182379253,
                    123.32268460429032
                  ],
                  "num_inliers": 32
                },
                "drift_px": 11.630354758448066
              },
              {
                "label": "2x zoom (4032x3024)",
                "frac": 2.0,
                "img": "transforms/zoom/2_0_wide_20x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    206.49765923105477,
                    117.19685927384221
                  ],
                  "num_inliers": 26
                },
                "drift_px": 17.82282050245547
              },
              {
                "label": "3x zoom (4032x3024)",
                "frac": 3.0,
                "img": "transforms/zoom/2_0_wide_30x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    210.89749533952053,
                    107.89962783156805
                  ],
                  "num_inliers": 16
                },
                "drift_px": 27.725818970267458
              },
              {
                "label": "4x zoom (4032x3024)",
                "frac": 4.0,
                "img": "transforms/zoom/2_0_wide_40x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              }
            ]
          }
        }
      }
    },
    {
      "point": "2",
      "shot": 1,
      "lenses": {
        "normal": {
          "base_img": "../images_compare/2/normal/image_005.jpg",
          "base_w": 1920,
          "base_h": 1080,
          "baseline": {
            "success": true,
            "xy": [
              208.0770298351506,
              224.18085302942845
            ],
            "num_inliers": 32
          },
          "modes": {
            "crop": [
              {
                "label": "90% (1728x972)",
                "frac": 0.9,
                "img": "transforms/crop/2_1_normal_90.jpg",
                "w": 1728,
                "h": 972,
                "result": {
                  "success": true,
                  "xy": [
                    207.7753179642717,
                    226.7562386334482
                  ],
                  "num_inliers": 19
                },
                "drift_px": 2.5929984694213353
              },
              {
                "label": "75% (1440x810)",
                "frac": 0.75,
                "img": "transforms/crop/2_1_normal_75.jpg",
                "w": 1440,
                "h": 810,
                "result": {
                  "success": true,
                  "xy": [
                    206.8262852407665,
                    230.44708915524072
                  ],
                  "num_inliers": 10
                },
                "drift_px": 6.3898417214212575
              },
              {
                "label": "60% (1152x648)",
                "frac": 0.6,
                "img": "transforms/crop/2_1_normal_60.jpg",
                "w": 1152,
                "h": 648,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              },
              {
                "label": "50% (960x540)",
                "frac": 0.5,
                "img": "transforms/crop/2_1_normal_50.jpg",
                "w": 960,
                "h": 540,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              },
              {
                "label": "40% (768x432)",
                "frac": 0.4,
                "img": "transforms/crop/2_1_normal_40.jpg",
                "w": 768,
                "h": 432,
                "result": {
                  "success": true,
                  "xy": [
                    219.72339957866987,
                    293.2723879158676
                  ],
                  "num_inliers": 11
                },
                "drift_px": 70.0662409521647
              },
              {
                "label": "30% (576x324)",
                "frac": 0.3,
                "img": "transforms/crop/2_1_normal_30.jpg",
                "w": 576,
                "h": 324,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              }
            ],
            "resize": [
              {
                "label": "75% (1440x810)",
                "frac": 0.75,
                "img": "transforms/resize/2_1_normal_75.jpg",
                "w": 1440,
                "h": 810,
                "result": {
                  "success": true,
                  "xy": [
                    208.23470075782694,
                    223.9062947866844
                  ],
                  "num_inliers": 33
                },
                "drift_px": 0.3166107207854825
              },
              {
                "label": "50% (960x540)",
                "frac": 0.5,
                "img": "transforms/resize/2_1_normal_50.jpg",
                "w": 960,
                "h": 540,
                "result": {
                  "success": true,
                  "xy": [
                    208.18441602575095,
                    223.95593984069146
                  ],
                  "num_inliers": 34
                },
                "drift_px": 0.24923430020664586
              },
              {
                "label": "35% (672x378)",
                "frac": 0.35,
                "img": "transforms/resize/2_1_normal_35.jpg",
                "w": 672,
                "h": 378,
                "result": {
                  "success": true,
                  "xy": [
                    208.20243547655986,
                    223.95946771530052
                  ],
                  "num_inliers": 33
                },
                "drift_px": 0.25443669587696915
              },
              {
                "label": "25% (480x270)",
                "frac": 0.25,
                "img": "transforms/resize/2_1_normal_25.jpg",
                "w": 480,
                "h": 270,
                "result": {
                  "success": true,
                  "xy": [
                    208.36455033918466,
                    224.05215974325097
                  ],
                  "num_inliers": 32
                },
                "drift_px": 0.31500793981606323
              },
              {
                "label": "15% (288x162)",
                "frac": 0.15,
                "img": "transforms/resize/2_1_normal_15.jpg",
                "w": 288,
                "h": 162,
                "result": {
                  "success": true,
                  "xy": [
                    208.0721657533595,
                    224.154430347347
                  ],
                  "num_inliers": 28
                },
                "drift_px": 0.02686666000916852
              }
            ],
            "zoom": [
              {
                "label": "1.25x zoom (1920x1080)",
                "frac": 1.25,
                "img": "transforms/zoom/2_1_normal_125x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": true,
                  "xy": [
                    205.91702665992466,
                    228.84256532233198
                  ],
                  "num_inliers": 13
                },
                "drift_px": 5.137818137964211
              },
              {
                "label": "1.5x zoom (1920x1080)",
                "frac": 1.5,
                "img": "transforms/zoom/2_1_normal_15x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              },
              {
                "label": "2x zoom (1920x1080)",
                "frac": 2.0,
                "img": "transforms/zoom/2_1_normal_20x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              },
              {
                "label": "3x zoom (1920x1080)",
                "frac": 3.0,
                "img": "transforms/zoom/2_1_normal_30x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              },
              {
                "label": "4x zoom (1920x1080)",
                "frac": 4.0,
                "img": "transforms/zoom/2_1_normal_40x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              }
            ]
          }
        },
        "wide": {
          "base_img": "../images_compare/2/wide/image_5_wide.jpg",
          "base_w": 4032,
          "base_h": 3024,
          "baseline": {
            "success": true,
            "xy": [
              214.70106232630854,
              221.36803673776393
            ],
            "num_inliers": 20
          },
          "modes": {
            "crop": [
              {
                "label": "90% (3628x2722)",
                "frac": 0.9,
                "img": "transforms/crop/2_1_wide_90.jpg",
                "w": 3628,
                "h": 2722,
                "result": {
                  "success": true,
                  "xy": [
                    211.70431040294582,
                    223.27300925933216
                  ],
                  "num_inliers": 24
                },
                "drift_px": 3.5509776679258604
              },
              {
                "label": "75% (3024x2268)",
                "frac": 0.75,
                "img": "transforms/crop/2_1_wide_75.jpg",
                "w": 3024,
                "h": 2268,
                "result": {
                  "success": true,
                  "xy": [
                    210.351808509651,
                    227.41638399203703
                  ],
                  "num_inliers": 18
                },
                "drift_px": 7.449732429422092
              },
              {
                "label": "60% (2420x1814)",
                "frac": 0.6,
                "img": "transforms/crop/2_1_wide_60.jpg",
                "w": 2420,
                "h": 1814,
                "result": {
                  "success": true,
                  "xy": [
                    206.19583853140017,
                    230.24926055160282
                  ],
                  "num_inliers": 12
                },
                "drift_px": 12.296949549907675
              },
              {
                "label": "50% (2016x1512)",
                "frac": 0.5,
                "img": "transforms/crop/2_1_wide_50.jpg",
                "w": 2016,
                "h": 1512,
                "result": {
                  "success": true,
                  "xy": [
                    206.67156330009058,
                    232.9766760785656
                  ],
                  "num_inliers": 12
                },
                "drift_px": 14.115004851463679
              },
              {
                "label": "40% (1612x1210)",
                "frac": 0.4,
                "img": "transforms/crop/2_1_wide_40.jpg",
                "w": 1612,
                "h": 1210,
                "result": {
                  "success": true,
                  "xy": [
                    205.4354295163316,
                    234.92276934935407
                  ],
                  "num_inliers": 10
                },
                "drift_px": 16.418974619050562
              },
              {
                "label": "30% (1210x908)",
                "frac": 0.3,
                "img": "transforms/crop/2_1_wide_30.jpg",
                "w": 1210,
                "h": 908,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              }
            ],
            "resize": [
              {
                "label": "75% (3024x2268)",
                "frac": 0.75,
                "img": "transforms/resize/2_1_wide_75.jpg",
                "w": 3024,
                "h": 2268,
                "result": {
                  "success": true,
                  "xy": [
                    214.15229536880645,
                    221.70541466004252
                  ],
                  "num_inliers": 20
                },
                "drift_px": 0.6441809032307045
              },
              {
                "label": "50% (2016x1512)",
                "frac": 0.5,
                "img": "transforms/resize/2_1_wide_50.jpg",
                "w": 2016,
                "h": 1512,
                "result": {
                  "success": true,
                  "xy": [
                    213.85260192756786,
                    221.91043318339175
                  ],
                  "num_inliers": 19
                },
                "drift_px": 1.0070148720157457
              },
              {
                "label": "35% (1412x1058)",
                "frac": 0.35,
                "img": "transforms/resize/2_1_wide_35.jpg",
                "w": 1412,
                "h": 1058,
                "result": {
                  "success": true,
                  "xy": [
                    214.3828632500354,
                    221.31868463706638
                  ],
                  "num_inliers": 20
                },
                "drift_px": 0.32200354343445375
              },
              {
                "label": "25% (1008x756)",
                "frac": 0.25,
                "img": "transforms/resize/2_1_wide_25.jpg",
                "w": 1008,
                "h": 756,
                "result": {
                  "success": true,
                  "xy": [
                    212.90559832333614,
                    221.5721600212176
                  ],
                  "num_inliers": 17
                },
                "drift_px": 1.8070299667735488
              },
              {
                "label": "15% (604x454)",
                "frac": 0.15,
                "img": "transforms/resize/2_1_wide_15.jpg",
                "w": 604,
                "h": 454,
                "result": {
                  "success": true,
                  "xy": [
                    214.49096600176398,
                    221.38394132876084
                  ],
                  "num_inliers": 19
                },
                "drift_px": 0.21069746463095948
              }
            ],
            "zoom": [
              {
                "label": "1.25x zoom (4032x3024)",
                "frac": 1.25,
                "img": "transforms/zoom/2_1_wide_125x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    210.50066644626793,
                    225.58445081303336
                  ],
                  "num_inliers": 26
                },
                "drift_px": 5.951594173260835
              },
              {
                "label": "1.5x zoom (4032x3024)",
                "frac": 1.5,
                "img": "transforms/zoom/2_1_wide_15x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    208.70928934148216,
                    228.98010083215055
                  ],
                  "num_inliers": 14
                },
                "drift_px": 9.687355845572378
              },
              {
                "label": "2x zoom (4032x3024)",
                "frac": 2.0,
                "img": "transforms/zoom/2_1_wide_20x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    206.58030354729033,
                    233.003522983176
                  ],
                  "num_inliers": 12
                },
                "drift_px": 14.189124825519539
              },
              {
                "label": "3x zoom (4032x3024)",
                "frac": 3.0,
                "img": "transforms/zoom/2_1_wide_30x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              },
              {
                "label": "4x zoom (4032x3024)",
                "frac": 4.0,
                "img": "transforms/zoom/2_1_wide_40x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              }
            ]
          }
        }
      }
    },
    {
      "point": "4",
      "shot": 0,
      "lenses": {
        "normal": {
          "base_img": "../images_compare/4/normal/image_003.jpg",
          "base_w": 1920,
          "base_h": 1080,
          "baseline": {
            "success": true,
            "xy": [
              207.49772827224686,
              152.59034126924604
            ],
            "num_inliers": 62
          },
          "modes": {
            "crop": [
              {
                "label": "90% (1728x972)",
                "frac": 0.9,
                "img": "transforms/crop/4_0_normal_90.jpg",
                "w": 1728,
                "h": 972,
                "result": {
                  "success": true,
                  "xy": [
                    207.56565763218964,
                    155.1228866137489
                  ],
                  "num_inliers": 27
                },
                "drift_px": 2.5334562005105528
              },
              {
                "label": "75% (1440x810)",
                "frac": 0.75,
                "img": "transforms/crop/4_0_normal_75.jpg",
                "w": 1440,
                "h": 810,
                "result": {
                  "success": true,
                  "xy": [
                    209.01272778833118,
                    157.42564531474085
                  ],
                  "num_inliers": 16
                },
                "drift_px": 5.067088784116001
              },
              {
                "label": "60% (1152x648)",
                "frac": 0.6,
                "img": "transforms/crop/4_0_normal_60.jpg",
                "w": 1152,
                "h": 648,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              },
              {
                "label": "50% (960x540)",
                "frac": 0.5,
                "img": "transforms/crop/4_0_normal_50.jpg",
                "w": 960,
                "h": 540,
                "result": {
                  "success": true,
                  "xy": [
                    211.1454814380736,
                    161.84149159378177
                  ],
                  "num_inliers": 11
                },
                "drift_px": 9.944339369005693
              },
              {
                "label": "40% (768x432)",
                "frac": 0.4,
                "img": "transforms/crop/4_0_normal_40.jpg",
                "w": 768,
                "h": 432,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              },
              {
                "label": "30% (576x324)",
                "frac": 0.3,
                "img": "transforms/crop/4_0_normal_30.jpg",
                "w": 576,
                "h": 324,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              }
            ],
            "resize": [
              {
                "label": "75% (1440x810)",
                "frac": 0.75,
                "img": "transforms/resize/4_0_normal_75.jpg",
                "w": 1440,
                "h": 810,
                "result": {
                  "success": true,
                  "xy": [
                    207.54246334741055,
                    152.5923716172941
                  ],
                  "num_inliers": 59
                },
                "drift_px": 0.04478112619281626
              },
              {
                "label": "50% (960x540)",
                "frac": 0.5,
                "img": "transforms/resize/4_0_normal_50.jpg",
                "w": 960,
                "h": 540,
                "result": {
                  "success": true,
                  "xy": [
                    207.55663182780796,
                    152.60178472641437
                  ],
                  "num_inliers": 61
                },
                "drift_px": 0.06000484621847754
              },
              {
                "label": "35% (672x378)",
                "frac": 0.35,
                "img": "transforms/resize/4_0_normal_35.jpg",
                "w": 672,
                "h": 378,
                "result": {
                  "success": true,
                  "xy": [
                    207.49163314358216,
                    152.5627106778255
                  ],
                  "num_inliers": 68
                },
                "drift_px": 0.028294878965784455
              },
              {
                "label": "25% (480x270)",
                "frac": 0.25,
                "img": "transforms/resize/4_0_normal_25.jpg",
                "w": 480,
                "h": 270,
                "result": {
                  "success": true,
                  "xy": [
                    207.50014708154876,
                    152.5162343413028
                  ],
                  "num_inliers": 67
                },
                "drift_px": 0.07414639173704012
              },
              {
                "label": "15% (288x162)",
                "frac": 0.15,
                "img": "transforms/resize/4_0_normal_15.jpg",
                "w": 288,
                "h": 162,
                "result": {
                  "success": true,
                  "xy": [
                    207.4497372085997,
                    152.41666854146666
                  ],
                  "num_inliers": 58
                },
                "drift_px": 0.18018146010152217
              }
            ],
            "zoom": [
              {
                "label": "1.25x zoom (1920x1080)",
                "frac": 1.25,
                "img": "transforms/zoom/4_0_normal_125x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": true,
                  "xy": [
                    206.69797047853217,
                    157.00466205332594
                  ],
                  "num_inliers": 15
                },
                "drift_px": 4.486183290210869
              },
              {
                "label": "1.5x zoom (1920x1080)",
                "frac": 1.5,
                "img": "transforms/zoom/4_0_normal_15x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              },
              {
                "label": "2x zoom (1920x1080)",
                "frac": 2.0,
                "img": "transforms/zoom/4_0_normal_20x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": true,
                  "xy": [
                    211.14548143807357,
                    161.8414915937818
                  ],
                  "num_inliers": 11
                },
                "drift_px": 9.944339369005709
              },
              {
                "label": "3x zoom (1920x1080)",
                "frac": 3.0,
                "img": "transforms/zoom/4_0_normal_30x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              },
              {
                "label": "4x zoom (1920x1080)",
                "frac": 4.0,
                "img": "transforms/zoom/4_0_normal_40x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              }
            ]
          }
        },
        "wide": {
          "base_img": "../images_compare/4/wide/image_003_wide.jpg",
          "base_w": 4032,
          "base_h": 3024,
          "baseline": {
            "success": true,
            "xy": [
              208.62245150574142,
              150.9842568265974
            ],
            "num_inliers": 23
          },
          "modes": {
            "crop": [
              {
                "label": "90% (3628x2722)",
                "frac": 0.9,
                "img": "transforms/crop/4_0_wide_90.jpg",
                "w": 3628,
                "h": 2722,
                "result": {
                  "success": true,
                  "xy": [
                    210.8657977856747,
                    150.73928311101668
                  ],
                  "num_inliers": 36
                },
                "drift_px": 2.2566822224265066
              },
              {
                "label": "75% (3024x2268)",
                "frac": 0.75,
                "img": "transforms/crop/4_0_wide_75.jpg",
                "w": 3024,
                "h": 2268,
                "result": {
                  "success": true,
                  "xy": [
                    206.56382478706684,
                    154.99023553261443
                  ],
                  "num_inliers": 16
                },
                "drift_px": 4.503977060321556
              },
              {
                "label": "60% (2420x1814)",
                "frac": 0.6,
                "img": "transforms/crop/4_0_wide_60.jpg",
                "w": 2420,
                "h": 1814,
                "result": {
                  "success": true,
                  "xy": [
                    207.38701164291464,
                    158.11722364771896
                  ],
                  "num_inliers": 15
                },
                "drift_px": 7.239166203775295
              },
              {
                "label": "50% (2016x1512)",
                "frac": 0.5,
                "img": "transforms/crop/4_0_wide_50.jpg",
                "w": 2016,
                "h": 1512,
                "result": {
                  "success": true,
                  "xy": [
                    208.66237819154657,
                    172.33975745638645
                  ],
                  "num_inliers": 13
                },
                "drift_px": 21.35553795363535
              },
              {
                "label": "40% (1612x1210)",
                "frac": 0.4,
                "img": "transforms/crop/4_0_wide_40.jpg",
                "w": 1612,
                "h": 1210,
                "result": {
                  "success": true,
                  "xy": [
                    207.6751704157036,
                    166.742626843038
                  ],
                  "num_inliers": 12
                },
                "drift_px": 15.786816241364109
              },
              {
                "label": "30% (1210x908)",
                "frac": 0.3,
                "img": "transforms/crop/4_0_wide_30.jpg",
                "w": 1210,
                "h": 908,
                "result": {
                  "success": true,
                  "xy": [
                    208.8770815331199,
                    169.0739262421104
                  ],
                  "num_inliers": 13
                },
                "drift_px": 18.091461411765184
              }
            ],
            "resize": [
              {
                "label": "75% (3024x2268)",
                "frac": 0.75,
                "img": "transforms/resize/4_0_wide_75.jpg",
                "w": 3024,
                "h": 2268,
                "result": {
                  "success": true,
                  "xy": [
                    208.80942803363533,
                    150.91965170188587
                  ],
                  "num_inliers": 21
                },
                "drift_px": 0.19782326486602317
              },
              {
                "label": "50% (2016x1512)",
                "frac": 0.5,
                "img": "transforms/resize/4_0_wide_50.jpg",
                "w": 2016,
                "h": 1512,
                "result": {
                  "success": true,
                  "xy": [
                    208.36203345988338,
                    151.88385950930098
                  ],
                  "num_inliers": 20
                },
                "drift_px": 0.9365375301267908
              },
              {
                "label": "35% (1412x1058)",
                "frac": 0.35,
                "img": "transforms/resize/4_0_wide_35.jpg",
                "w": 1412,
                "h": 1058,
                "result": {
                  "success": true,
                  "xy": [
                    208.71823162872886,
                    151.16202964915314
                  ],
                  "num_inliers": 24
                },
                "drift_px": 0.20193317805383576
              },
              {
                "label": "25% (1008x756)",
                "frac": 0.25,
                "img": "transforms/resize/4_0_wide_25.jpg",
                "w": 1008,
                "h": 756,
                "result": {
                  "success": true,
                  "xy": [
                    208.21595671679893,
                    151.95917244818992
                  ],
                  "num_inliers": 17
                },
                "drift_px": 1.0562662934423899
              },
              {
                "label": "15% (604x454)",
                "frac": 0.15,
                "img": "transforms/resize/4_0_wide_15.jpg",
                "w": 604,
                "h": 454,
                "result": {
                  "success": true,
                  "xy": [
                    208.72753920729204,
                    151.11876078679043
                  ],
                  "num_inliers": 20
                },
                "drift_px": 0.17068901641523224
              }
            ],
            "zoom": [
              {
                "label": "1.25x zoom (4032x3024)",
                "frac": 1.25,
                "img": "transforms/zoom/4_0_wide_125x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    210.12751010555334,
                    153.56730983128475
                  ],
                  "num_inliers": 27
                },
                "drift_px": 2.989542475679535
              },
              {
                "label": "1.5x zoom (4032x3024)",
                "frac": 1.5,
                "img": "transforms/zoom/4_0_wide_15x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    207.04427425587,
                    156.5134775521397
                  ],
                  "num_inliers": 15
                },
                "drift_px": 5.750036979340072
              },
              {
                "label": "2x zoom (4032x3024)",
                "frac": 2.0,
                "img": "transforms/zoom/4_0_wide_20x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    208.59802416484752,
                    160.05954454103738
                  ],
                  "num_inliers": 12
                },
                "drift_px": 9.075320589094822
              },
              {
                "label": "3x zoom (4032x3024)",
                "frac": 3.0,
                "img": "transforms/zoom/4_0_wide_30x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    209.50105917057135,
                    163.00020474246546
                  ],
                  "num_inliers": 11
                },
                "drift_px": 12.048027047842801
              },
              {
                "label": "4x zoom (4032x3024)",
                "frac": 4.0,
                "img": "transforms/zoom/4_0_wide_40x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    208.45176046555798,
                    165.90410186829106
                  ],
                  "num_inliers": 10
                },
                "drift_px": 14.92082140833238
              }
            ]
          }
        }
      }
    },
    {
      "point": "5",
      "shot": 0,
      "lenses": {
        "normal": {
          "base_img": "../images_compare/5/normal/image_009.jpg",
          "base_w": 1920,
          "base_h": 1080,
          "baseline": {
            "success": true,
            "xy": [
              203.86645528061575,
              277.6005444388087
            ],
            "num_inliers": 77
          },
          "modes": {
            "crop": [
              {
                "label": "90% (1728x972)",
                "frac": 0.9,
                "img": "transforms/crop/5_0_normal_90.jpg",
                "w": 1728,
                "h": 972,
                "result": {
                  "success": true,
                  "xy": [
                    206.09029225596453,
                    285.36652649880443
                  ],
                  "num_inliers": 51
                },
                "drift_px": 8.078114151774782
              },
              {
                "label": "75% (1440x810)",
                "frac": 0.75,
                "img": "transforms/crop/5_0_normal_75.jpg",
                "w": 1440,
                "h": 810,
                "result": {
                  "success": true,
                  "xy": [
                    210.1692121189239,
                    297.7723694842787
                  ],
                  "num_inliers": 26
                },
                "drift_px": 21.13355789799465
              },
              {
                "label": "60% (1152x648)",
                "frac": 0.6,
                "img": "transforms/crop/5_0_normal_60.jpg",
                "w": 1152,
                "h": 648,
                "result": {
                  "success": true,
                  "xy": [
                    206.449105468828,
                    314.8399801236236
                  ],
                  "num_inliers": 13
                },
                "drift_px": 37.32888495680173
              },
              {
                "label": "50% (960x540)",
                "frac": 0.5,
                "img": "transforms/crop/5_0_normal_50.jpg",
                "w": 960,
                "h": 540,
                "result": {
                  "success": true,
                  "xy": [
                    211.7021831995944,
                    314.97431978255906
                  ],
                  "num_inliers": 10
                },
                "drift_px": 38.186355095313615
              },
              {
                "label": "40% (768x432)",
                "frac": 0.4,
                "img": "transforms/crop/5_0_normal_40.jpg",
                "w": 768,
                "h": 432,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              },
              {
                "label": "30% (576x324)",
                "frac": 0.3,
                "img": "transforms/crop/5_0_normal_30.jpg",
                "w": 576,
                "h": 324,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              }
            ],
            "resize": [
              {
                "label": "75% (1440x810)",
                "frac": 0.75,
                "img": "transforms/resize/5_0_normal_75.jpg",
                "w": 1440,
                "h": 810,
                "result": {
                  "success": true,
                  "xy": [
                    204.04446127306062,
                    277.33140134783287
                  ],
                  "num_inliers": 84
                },
                "drift_px": 0.3226827184190475
              },
              {
                "label": "50% (960x540)",
                "frac": 0.5,
                "img": "transforms/resize/5_0_normal_50.jpg",
                "w": 960,
                "h": 540,
                "result": {
                  "success": true,
                  "xy": [
                    203.97698558570943,
                    277.48146449431744
                  ],
                  "num_inliers": 82
                },
                "drift_px": 0.16247147910985135
              },
              {
                "label": "35% (672x378)",
                "frac": 0.35,
                "img": "transforms/resize/5_0_normal_35.jpg",
                "w": 672,
                "h": 378,
                "result": {
                  "success": true,
                  "xy": [
                    204.03330448995524,
                    277.3267314075123
                  ],
                  "num_inliers": 85
                },
                "drift_px": 0.3206434698616878
              },
              {
                "label": "25% (480x270)",
                "frac": 0.25,
                "img": "transforms/resize/5_0_normal_25.jpg",
                "w": 480,
                "h": 270,
                "result": {
                  "success": true,
                  "xy": [
                    203.97549891081758,
                    277.4666765376513
                  ],
                  "num_inliers": 83
                },
                "drift_px": 0.17265899411230368
              },
              {
                "label": "15% (288x162)",
                "frac": 0.15,
                "img": "transforms/resize/5_0_normal_15.jpg",
                "w": 288,
                "h": 162,
                "result": {
                  "success": true,
                  "xy": [
                    203.92662322069717,
                    277.4905590335121
                  ],
                  "num_inliers": 72
                },
                "drift_px": 0.12536734180756318
              }
            ],
            "zoom": [
              {
                "label": "1.25x zoom (1920x1080)",
                "frac": 1.25,
                "img": "transforms/zoom/5_0_normal_125x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": true,
                  "xy": [
                    207.64802688067493,
                    292.8847304124137
                  ],
                  "num_inliers": 28
                },
                "drift_px": 15.745050798334015
              },
              {
                "label": "1.5x zoom (1920x1080)",
                "frac": 1.5,
                "img": "transforms/zoom/5_0_normal_15x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": true,
                  "xy": [
                    207.24950425624206,
                    307.82798883162394
                  ],
                  "num_inliers": 17
                },
                "drift_px": 30.41617028641548
              },
              {
                "label": "2x zoom (1920x1080)",
                "frac": 2.0,
                "img": "transforms/zoom/5_0_normal_20x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": true,
                  "xy": [
                    201.12868537459858,
                    328.26653402456384
                  ],
                  "num_inliers": 11
                },
                "drift_px": 50.7399042644164
              },
              {
                "label": "3x zoom (1920x1080)",
                "frac": 3.0,
                "img": "transforms/zoom/5_0_normal_30x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              },
              {
                "label": "4x zoom (1920x1080)",
                "frac": 4.0,
                "img": "transforms/zoom/5_0_normal_40x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              }
            ]
          }
        },
        "wide": {
          "base_img": "../images_compare/5/wide/image_009_wide.jpg",
          "base_w": 4032,
          "base_h": 3024,
          "baseline": {
            "success": true,
            "xy": [
              181.26049051027874,
              274.9415823538615
            ],
            "num_inliers": 22
          },
          "modes": {
            "crop": [
              {
                "label": "90% (3628x2722)",
                "frac": 0.9,
                "img": "transforms/crop/5_0_wide_90.jpg",
                "w": 3628,
                "h": 2722,
                "result": {
                  "success": true,
                  "xy": [
                    187.6579656904494,
                    279.3830368299024
                  ],
                  "num_inliers": 28
                },
                "drift_px": 7.788081056566052
              },
              {
                "label": "75% (3024x2268)",
                "frac": 0.75,
                "img": "transforms/crop/5_0_wide_75.jpg",
                "w": 3024,
                "h": 2268,
                "result": {
                  "success": true,
                  "xy": [
                    213.56871859898854,
                    288.729032920614
                  ],
                  "num_inliers": 20
                },
                "drift_px": 35.12713189776158
              },
              {
                "label": "60% (2420x1814)",
                "frac": 0.6,
                "img": "transforms/crop/5_0_wide_60.jpg",
                "w": 2420,
                "h": 1814,
                "result": {
                  "success": true,
                  "xy": [
                    212.48520259497232,
                    294.455557171659
                  ],
                  "num_inliers": 18
                },
                "drift_px": 36.82088888065636
              },
              {
                "label": "50% (2016x1512)",
                "frac": 0.5,
                "img": "transforms/crop/5_0_wide_50.jpg",
                "w": 2016,
                "h": 1512,
                "result": {
                  "success": true,
                  "xy": [
                    218.00868866006388,
                    305.1844861702695
                  ],
                  "num_inliers": 19
                },
                "drift_px": 47.59268114431437
              },
              {
                "label": "40% (1612x1210)",
                "frac": 0.4,
                "img": "transforms/crop/5_0_wide_40.jpg",
                "w": 1612,
                "h": 1210,
                "result": {
                  "success": true,
                  "xy": [
                    217.98729523001117,
                    315.36347292205903
                  ],
                  "num_inliers": 13
                },
                "drift_px": 54.614901098772435
              },
              {
                "label": "30% (1210x908)",
                "frac": 0.3,
                "img": "transforms/crop/5_0_wide_30.jpg",
                "w": 1210,
                "h": 908,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              }
            ],
            "resize": [
              {
                "label": "75% (3024x2268)",
                "frac": 0.75,
                "img": "transforms/resize/5_0_wide_75.jpg",
                "w": 3024,
                "h": 2268,
                "result": {
                  "success": true,
                  "xy": [
                    181.49807490584098,
                    275.10943338156414
                  ],
                  "num_inliers": 23
                },
                "drift_px": 0.29089570728269765
              },
              {
                "label": "50% (2016x1512)",
                "frac": 0.5,
                "img": "transforms/resize/5_0_wide_50.jpg",
                "w": 2016,
                "h": 1512,
                "result": {
                  "success": true,
                  "xy": [
                    181.22437764139386,
                    275.32251865485716
                  ],
                  "num_inliers": 23
                },
                "drift_px": 0.38264422733831993
              },
              {
                "label": "35% (1412x1058)",
                "frac": 0.35,
                "img": "transforms/resize/5_0_wide_35.jpg",
                "w": 1412,
                "h": 1058,
                "result": {
                  "success": true,
                  "xy": [
                    181.68187042032795,
                    275.26758070684235
                  ],
                  "num_inliers": 23
                },
                "drift_px": 0.5327625688233892
              },
              {
                "label": "25% (1008x756)",
                "frac": 0.25,
                "img": "transforms/resize/5_0_wide_25.jpg",
                "w": 1008,
                "h": 756,
                "result": {
                  "success": true,
                  "xy": [
                    181.27668712866367,
                    275.4175805896395
                  ],
                  "num_inliers": 18
                },
                "drift_px": 0.47627371427662835
              },
              {
                "label": "15% (604x454)",
                "frac": 0.15,
                "img": "transforms/resize/5_0_wide_15.jpg",
                "w": 604,
                "h": 454,
                "result": {
                  "success": true,
                  "xy": [
                    183.15544209775024,
                    274.5904311881038
                  ],
                  "num_inliers": 17
                },
                "drift_px": 1.9272126660215096
              }
            ],
            "zoom": [
              {
                "label": "1.25x zoom (4032x3024)",
                "frac": 1.25,
                "img": "transforms/zoom/5_0_wide_125x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    191.81991948680073,
                    282.54536348722746
                  ],
                  "num_inliers": 23
                },
                "drift_px": 13.012264515999666
              },
              {
                "label": "1.5x zoom (4032x3024)",
                "frac": 1.5,
                "img": "transforms/zoom/5_0_wide_15x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    215.964953652965,
                    294.9267977409468
                  ],
                  "num_inliers": 15
                },
                "drift_px": 40.04757915392964
              },
              {
                "label": "2x zoom (4032x3024)",
                "frac": 2.0,
                "img": "transforms/zoom/5_0_wide_20x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    218.12182940691315,
                    305.57039808838044
                  ],
                  "num_inliers": 19
                },
                "drift_px": 47.925803681854376
              },
              {
                "label": "3x zoom (4032x3024)",
                "frac": 3.0,
                "img": "transforms/zoom/5_0_wide_30x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              },
              {
                "label": "4x zoom (4032x3024)",
                "frac": 4.0,
                "img": "transforms/zoom/5_0_wide_40x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              }
            ]
          }
        }
      }
    },
    {
      "point": "5",
      "shot": 1,
      "lenses": {
        "normal": {
          "base_img": "../images_compare/5/normal/image_010.jpg",
          "base_w": 1920,
          "base_h": 1080,
          "baseline": {
            "success": true,
            "xy": [
              207.13566541385637,
              250.5009809915047
            ],
            "num_inliers": 60
          },
          "modes": {
            "crop": [
              {
                "label": "90% (1728x972)",
                "frac": 0.9,
                "img": "transforms/crop/5_1_normal_90.jpg",
                "w": 1728,
                "h": 972,
                "result": {
                  "success": true,
                  "xy": [
                    208.30798967743448,
                    247.7704635627433
                  ],
                  "num_inliers": 27
                },
                "drift_px": 2.9715433040330614
              },
              {
                "label": "75% (1440x810)",
                "frac": 0.75,
                "img": "transforms/crop/5_1_normal_75.jpg",
                "w": 1440,
                "h": 810,
                "result": {
                  "success": true,
                  "xy": [
                    209.26619910781966,
                    235.81934836190726
                  ],
                  "num_inliers": 15
                },
                "drift_px": 14.835414065390045
              },
              {
                "label": "60% (1152x648)",
                "frac": 0.6,
                "img": "transforms/crop/5_1_normal_60.jpg",
                "w": 1152,
                "h": 648,
                "result": {
                  "success": true,
                  "xy": [
                    207.57873273537876,
                    225.07612953422648
                  ],
                  "num_inliers": 11
                },
                "drift_px": 25.428711730562814
              },
              {
                "label": "50% (960x540)",
                "frac": 0.5,
                "img": "transforms/crop/5_1_normal_50.jpg",
                "w": 960,
                "h": 540,
                "result": {
                  "success": true,
                  "xy": [
                    206.6312654798905,
                    218.87514101461565
                  ],
                  "num_inliers": 10
                },
                "drift_px": 31.629862053717176
              },
              {
                "label": "40% (768x432)",
                "frac": 0.4,
                "img": "transforms/crop/5_1_normal_40.jpg",
                "w": 768,
                "h": 432,
                "result": {
                  "success": true,
                  "xy": [
                    206.8523752759831,
                    212.82152282460197
                  ],
                  "num_inliers": 10
                },
                "drift_px": 37.6805230995217
              },
              {
                "label": "30% (576x324)",
                "frac": 0.3,
                "img": "transforms/crop/5_1_normal_30.jpg",
                "w": 576,
                "h": 324,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              }
            ],
            "resize": [
              {
                "label": "75% (1440x810)",
                "frac": 0.75,
                "img": "transforms/resize/5_1_normal_75.jpg",
                "w": 1440,
                "h": 810,
                "result": {
                  "success": true,
                  "xy": [
                    207.06191110842468,
                    250.40344570760877
                  ],
                  "num_inliers": 74
                },
                "drift_px": 0.12228176141342358
              },
              {
                "label": "50% (960x540)",
                "frac": 0.5,
                "img": "transforms/resize/5_1_normal_50.jpg",
                "w": 960,
                "h": 540,
                "result": {
                  "success": true,
                  "xy": [
                    207.11396572075355,
                    250.50383528652426
                  ],
                  "num_inliers": 68
                },
                "drift_px": 0.02188660962358586
              },
              {
                "label": "35% (672x378)",
                "frac": 0.35,
                "img": "transforms/resize/5_1_normal_35.jpg",
                "w": 672,
                "h": 378,
                "result": {
                  "success": true,
                  "xy": [
                    207.04719438775422,
                    250.41214544875064
                  ],
                  "num_inliers": 68
                },
                "drift_px": 0.125374942137477
              },
              {
                "label": "25% (480x270)",
                "frac": 0.25,
                "img": "transforms/resize/5_1_normal_25.jpg",
                "w": 480,
                "h": 270,
                "result": {
                  "success": true,
                  "xy": [
                    207.08746529236114,
                    250.48469311874808
                  ],
                  "num_inliers": 73
                },
                "drift_px": 0.05087776047636256
              },
              {
                "label": "15% (288x162)",
                "frac": 0.15,
                "img": "transforms/resize/5_1_normal_15.jpg",
                "w": 288,
                "h": 162,
                "result": {
                  "success": true,
                  "xy": [
                    207.13780940147072,
                    250.5065592829566
                  ],
                  "num_inliers": 65
                },
                "drift_px": 0.005976120682594748
              }
            ],
            "zoom": [
              {
                "label": "1.25x zoom (1920x1080)",
                "frac": 1.25,
                "img": "transforms/zoom/5_1_normal_125x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": true,
                  "xy": [
                    208.94607155413215,
                    238.59307901813068
                  ],
                  "num_inliers": 15
                },
                "drift_px": 12.044737431767986
              },
              {
                "label": "1.5x zoom (1920x1080)",
                "frac": 1.5,
                "img": "transforms/zoom/5_1_normal_15x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": true,
                  "xy": [
                    208.40484841787276,
                    234.48140031225068
                  ],
                  "num_inliers": 13
                },
                "drift_px": 16.069778798627326
              },
              {
                "label": "2x zoom (1920x1080)",
                "frac": 2.0,
                "img": "transforms/zoom/5_1_normal_20x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": true,
                  "xy": [
                    209.13946478728644,
                    226.3479554840847
                  ],
                  "num_inliers": 11
                },
                "drift_px": 24.23600324086129
              },
              {
                "label": "3x zoom (1920x1080)",
                "frac": 3.0,
                "img": "transforms/zoom/5_1_normal_30x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              },
              {
                "label": "4x zoom (1920x1080)",
                "frac": 4.0,
                "img": "transforms/zoom/5_1_normal_40x.jpg",
                "w": 1920,
                "h": 1080,
                "result": {
                  "success": false,
                  "xy": null,
                  "num_inliers": 0
                },
                "drift_px": null
              }
            ]
          }
        },
        "wide": {
          "base_img": "../images_compare/5/wide/imag_010_wide.jpg",
          "base_w": 4032,
          "base_h": 3024,
          "baseline": {
            "success": true,
            "xy": [
              207.03597292949354,
              247.1935135562675
            ],
            "num_inliers": 18
          },
          "modes": {
            "crop": [
              {
                "label": "90% (3628x2722)",
                "frac": 0.9,
                "img": "transforms/crop/5_1_wide_90.jpg",
                "w": 3628,
                "h": 2722,
                "result": {
                  "success": true,
                  "xy": [
                    209.499031851537,
                    251.01440120221915
                  ],
                  "num_inliers": 39
                },
                "drift_px": 4.545969825729582
              },
              {
                "label": "75% (3024x2268)",
                "frac": 0.75,
                "img": "transforms/crop/5_1_wide_75.jpg",
                "w": 3024,
                "h": 2268,
                "result": {
                  "success": true,
                  "xy": [
                    211.64178584521574,
                    244.87874139152015
                  ],
                  "num_inliers": 16
                },
                "drift_px": 5.154772816460736
              },
              {
                "label": "60% (2420x1814)",
                "frac": 0.6,
                "img": "transforms/crop/5_1_wide_60.jpg",
                "w": 2420,
                "h": 1814,
                "result": {
                  "success": true,
                  "xy": [
                    206.28275542036732,
                    241.57334792556586
                  ],
                  "num_inliers": 19
                },
                "drift_px": 5.67041429990564
              },
              {
                "label": "50% (2016x1512)",
                "frac": 0.5,
                "img": "transforms/crop/5_1_wide_50.jpg",
                "w": 2016,
                "h": 1512,
                "result": {
                  "success": true,
                  "xy": [
                    205.96498759254715,
                    238.55704204378208
                  ],
                  "num_inliers": 14
                },
                "drift_px": 8.702623154999102
              },
              {
                "label": "40% (1612x1210)",
                "frac": 0.4,
                "img": "transforms/crop/5_1_wide_40.jpg",
                "w": 1612,
                "h": 1210,
                "result": {
                  "success": true,
                  "xy": [
                    205.93223211475896,
                    235.56012517689987
                  ],
                  "num_inliers": 10
                },
                "drift_px": 11.685630876051013
              },
              {
                "label": "30% (1210x908)",
                "frac": 0.3,
                "img": "transforms/crop/5_1_wide_30.jpg",
                "w": 1210,
                "h": 908,
                "result": {
                  "success": true,
                  "xy": [
                    204.44310314371845,
                    232.51218250679986
                  ],
                  "num_inliers": 15
                },
                "drift_px": 14.908536316823598
              }
            ],
            "resize": [
              {
                "label": "75% (3024x2268)",
                "frac": 0.75,
                "img": "transforms/resize/5_1_wide_75.jpg",
                "w": 3024,
                "h": 2268,
                "result": {
                  "success": true,
                  "xy": [
                    208.66134513937152,
                    248.00597742428087
                  ],
                  "num_inliers": 20
                },
                "drift_px": 1.8171219985105214
              },
              {
                "label": "50% (2016x1512)",
                "frac": 0.5,
                "img": "transforms/resize/5_1_wide_50.jpg",
                "w": 2016,
                "h": 1512,
                "result": {
                  "success": true,
                  "xy": [
                    209.46606291565467,
                    250.5996399315544
                  ],
                  "num_inliers": 25
                },
                "drift_px": 4.18414079892942
              },
              {
                "label": "35% (1412x1058)",
                "frac": 0.35,
                "img": "transforms/resize/5_1_wide_35.jpg",
                "w": 1412,
                "h": 1058,
                "result": {
                  "success": true,
                  "xy": [
                    208.9707509435803,
                    251.18752446434593
                  ],
                  "num_inliers": 25
                },
                "drift_px": 4.437960015327192
              },
              {
                "label": "25% (1008x756)",
                "frac": 0.25,
                "img": "transforms/resize/5_1_wide_25.jpg",
                "w": 1008,
                "h": 756,
                "result": {
                  "success": true,
                  "xy": [
                    207.03543177662638,
                    246.94414901884224
                  ],
                  "num_inliers": 19
                },
                "drift_px": 0.24936512460996238
              },
              {
                "label": "15% (604x454)",
                "frac": 0.15,
                "img": "transforms/resize/5_1_wide_15.jpg",
                "w": 604,
                "h": 454,
                "result": {
                  "success": true,
                  "xy": [
                    207.054375691878,
                    246.9638247344728
                  ],
                  "num_inliers": 19
                },
                "drift_px": 0.23042486090006473
              }
            ],
            "zoom": [
              {
                "label": "1.25x zoom (4032x3024)",
                "frac": 1.25,
                "img": "transforms/zoom/5_1_wide_125x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    208.2321075615349,
                    249.82790890116755
                  ],
                  "num_inliers": 22
                },
                "drift_px": 2.8932294916234538
              },
              {
                "label": "1.5x zoom (4032x3024)",
                "frac": 1.5,
                "img": "transforms/zoom/5_1_wide_15x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    211.27494233327982,
                    241.48843120199464
                  ],
                  "num_inliers": 15
                },
                "drift_px": 7.107518995772844
              },
              {
                "label": "2x zoom (4032x3024)",
                "frac": 2.0,
                "img": "transforms/zoom/5_1_wide_20x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    202.9363793566801,
                    239.39119463508584
                  ],
                  "num_inliers": 14
                },
                "drift_px": 8.813787381715231
              },
              {
                "label": "3x zoom (4032x3024)",
                "frac": 3.0,
                "img": "transforms/zoom/5_1_wide_30x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    205.0483788424849,
                    233.99461512325738
                  ],
                  "num_inliers": 12
                },
                "drift_px": 13.347713291033372
              },
              {
                "label": "4x zoom (4032x3024)",
                "frac": 4.0,
                "img": "transforms/zoom/5_1_wide_40x.jpg",
                "w": 4032,
                "h": 3024,
                "result": {
                  "success": true,
                  "xy": [
                    202.564661393501,
                    229.95386032854137
                  ],
                  "num_inliers": 13
                },
                "drift_px": 17.810060928142498
              }
            ]
          }
        }
      }
    }
  ]
};
