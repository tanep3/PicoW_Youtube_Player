# プロジェクト配置

Pico、Pi5配信、ホスト試験、診断/実験、文書を分けた。ルートのCMake起点と秘密設定は保持し、過去のCLI入口を互換ランチャーとして残している。新しいWeb/AI機能は実装していない。

```text
PicoW_Youtube_Player/
├── CMakeLists.txt                 # Pico本番/診断のビルド起点
├── README.md
├── THIRD_PARTY_NOTICES.md
├── config.h                      # 既存秘密設定。場所/権限を保持、Git除外
├── server.py                     # 旧CLIの互換入口
├── diagnostic.py                 # 旧診断CLIの互換入口
├── requirements.txt              # 旧pipコマンドの互換入口
├── pico/
│   ├── pico_player.c
│   ├── jpeg_decode.c / jpeg_decode.h
│   ├── lwipopts.h
│   ├── config.example.h
│   └── third_party/tjpgd/         # ライセンスを保持したTJpgDec
├── server/
│   ├── streamer.py                # Pi5配信本体
│   ├── __init__.py / __main__.py   # 旧import API / python -m server
│   └── requirements.txt
├── tests/                        # 全19ホスト試験
├── diagnostics/
│   ├── server/lcd_pattern.py      # LCD位置/色パターン
│   ├── pico/                     # 計装C、driverコピー、patch、同梱license
│   └── results/                  # 測定JSON・ヘッダー限定pcap
└── docs/
    ├── diagnostics/              # CYW43・有線/FPS検証記録
    ├── VERIFICATION_FIX.md
    ├── YOUTUBE_REQUIREMENTS_INVENTORY.md
    ├── PROJECT_LAYOUT.md
    └── wiring / compact-layout（md・svg）
```

既存のPython bytecodeキャッシュは削除せず、Git除外のまま保持した。Pico本番から診断driverのコードが入るのは`PLAYER_CYW43_DIAG=ON`を明示した場合のみ。旧UF2は元の`/tmp`保存先で保持している。

## 起動と依存

```sh
cd /home/tane/dev/PicoW/PicoW_Youtube_Player
python3 -m pip install -r server/requirements.txt
python3 -m server --host 192.168.0.120 --port 16151 \
  --frames /home/tane/Videos/voltesV_6frame --compensate-colors \
  --fps 6 --mode raw-display --send-timeout 2 --trace-motion
```

LCDパターンは`python3 -m diagnostics.server.lcd_pattern --help`。通常配信と同じポートなので、同時に起動しない。旧`python3 server.py`、`python3 diagnostic.py`、`pip install -r requirements.txt`も利用できる。旧`import server`の公開APIを保持し、新コード/テストは`from server import streamer`を使う。

## Picoビルド

```sh
cmake -S . -B /tmp/picow_build -DPICO_BOARD=pico_w \
  -DCMAKE_BUILD_TYPE=Release -DDISPLAY_PROFILE=0 -DPLAYER_LCD_GAMMA_LGFX=ON -DPLAYER_CYW43_DIAG=OFF
cmake --build /tmp/picow_build --clean-first -j2
```

診断をビルドするときは別buildディレクトリで`PLAYER_CYW43_DIAG=ON`にする。root `config.h`はinclude pathで参照し、なければ`pico/config.example.h`へフォールバックする。設定変更後の転送前はclean-first再ビルドが必要。整理作業ではPicoへの転送を行っていない。

## 検証と保全

- 全ホスト試験: `python3 -B -m unittest discover -s tests -v`、19件成功。TCPループバック試験は空きポートを使い、稼働16151に介入しない。
- 新規本番build `/tmp/picow_layout_build_prod` と診断build `/tmp/picow_layout_build_diag` 成功、compiler warning/errorなし。
- 本番text/data/BSSは317208/0/166068B、診断は320648/0/166636B。
- 診断UF2は移動前の`.120`復元UF2とバイト単位で一致（SHA256 `7be46fb51d43beb4c4cd095c9b309c7c16f5b0e95a4b00d8ab698b7022b81380`）。
- 旧CLIのhelp出力は移動前と完全一致。新モジュールCLIと互換importを確認。
- Gitリポジトリではないため、秘密`config.h`とキャッシュを除外した変更前後snapshotを`git diff --no-index`で比較する。Git初期化・gitlink・remote設定・commitは行わない。
- 変更前snapshot `/tmp/picow_layout_before`（mode700）、移動対応表 `/tmp/picow_layout_moves.json`、manifest `/tmp/picow_layout_manifest_before.json`、差分 `/tmp/picow_layout.diff`。元configをsnapshotへコピーしていない。元パスへ戻す際はこの対応表とsnapshotを使い、ユーザーの後続変更を上書きしない。

稼働中の配信はソースをメモリへ読み込み済みなので移動に再起動は不要。稼働PIDを継続照合し、ファーム再転送やサービス再起動は行わない。次回の通常起動は新CLIまたは互換入口を使用できる。

NASケーブル返却未確認のため、一時有線プロファイルの後片付けは引き続き待機する。

採用したLCDガンマ表は `pico/lcd_gamma_lgfx.h`。通常ビルド既定ON、通信診断オプションとは独立です。既存CMakeキャッシュがOFFの場合はONを明示してください。
