# プロジェクト配置

製作・起動の入口は[README](../README.md)、詳しい手順は[BUILD_AND_RUN.md](BUILD_AND_RUN.md)です。Picoの実装、Pi5配信、ケース、試験、調査記録を分けています。

```text
PicoW_Youtube_Player/
├── README.md / LICENSE / THIRD_PARTY_NOTICES.md
├── CMakeLists.txt                    # Pico本番・ボタン診断のビルド
├── config.h                         # Wi-Fi等の実設定、Git除外
├── web-config.json                  # Pi5 Web/TCPの実設定、Git除外
├── pico/
│   ├── pico_player.c                # Wi-Fi/TCP、フレーム受信、表示
│   ├── lcd_display.h                # SPI0、LCD窓、採用ガンマ
│   ├── lcd_gamma_lgfx.h
│   ├── rgb565_transform.h           # 色補正・180度回転
│   ├── jpeg_decode.c / jpeg_decode.h
│   ├── config.example.h / lwipopts.h
│   └── third_party/                 # TJpgDec/LovyanGFXの元ライセンス
├── server/
│   ├── web.py / static/             # ダークWeb UI/API
│   ├── media.py / library.py        # 取得・変換・履歴・容量管理
│   ├── frame_cache.py / playback.py # JPEG1枚ずつ展開、PWF2 TCP配信
│   ├── streamer.py                  # 既存JPEG連番のCLI比較
│   └── requirements.txt
├── hardware/case/
│   ├── README.md                    # 採用v3・印刷と組立
│   └── slim-v3/
│       ├── blender/                 # .blend、生成ソース、設計画像、原資料
│       ├── stl/                     # 4部品＋一括配置、原資料と検査
│       └── SOURCE_MANIFEST.json
├── deploy/                          # user/system unitの見本
├── tests/                           # 49件のホスト試験
├── diagnostics/
│   ├── server/                      # LCDパターン、ガンマ比較
│   ├── pico/                        # ボタン診断、隔離CYW43計装
│   ├── results/                     # 測定JSON・限定pcap
│   └── artifacts/                   # 設定入りUF2/ELF保全、Git除外
├── docs/
│   ├── BUILD_AND_RUN.md / WEB_PLAYER.md
│   ├── images/ / verification/
│   ├── diagnostics/                 # 通信・LCD・ボタンの調査記録
│   └── history/                     # 従来READMEと配置整理時点の記録
└── data/                            # 元動画/JPEG/SQLite、一時処理、Git除外
```

ルートの `server.py`、`diagnostic.py`、`requirements.txt` は既存CLI用の互換入口です。通常Webは `python3 -m server.web --config web-config.json`、既存JPEG連番だけの試験は `python3 -m server --frames …` を使います。

本番にはボタン操作をまだ組み込んでいません。別ターゲット `pico_w_button_test` でGP12〜15を確認します。本番の通信診断は `PLAYER_CYW43_DIAG=ON` の場合だけ隔離driverを使い、共有SDKは編集しません。LCDガンマと180度回転は通常ビルド既定ONです。

過去の配置整理・19件試験・移動前後の比較は[当時の配置記録](history/PROJECT_LAYOUT_20261007.md)へ移しました。開発途中の通信計測と配線案は[開発記録](history/DEVELOPMENT_LOG.md)に保持しています。現在の実装や採用配線は最新READMEを参照してください。
