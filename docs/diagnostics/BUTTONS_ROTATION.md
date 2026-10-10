# 4ボタン単体テストと動画180度回転（2026-10-10）

基準コミット70a7d8d、開始時git差分なし。既存LCD設定はSPI0 GP17/18/19/20/21、20MHz、MADCTL60、INVON、X/Y0/24、採用E0/E1ガンマ。Wi-Fi設定値を表示せず、OS/ネットワーク/サービス設定は変更しない。転送時点ではコミットしなかった。その後09:55 JSTに今回のソース・検証・関連文書のローカルコミットだけが承認された。pushは行わない。

## 第1段階: ネットワーク不要のボタン診断

別ターゲット `pico_w_button_test`。ソースは `diagnostics/pico/button_test.c` と `button_test_logic.c/.h`。GPIO12/13/14/15（物理16/17/19/20）を入力、内部プルアップ、共通GND、押下LOWとして読む。LCDは現SPI0配線を共通 `pico/lcd_display.h` で流用する。SPI1案のGP12/13はボタンと衝突するため、この診断はprofile0のみ許可する。

| ボタン | GPIO | 押下表示 |
|---|---|---|
| 1 | GP12 | 赤い丸 |
| 2 | GP13 | 緑の三角 |
| 3 | GP14 | 青い四角 |
| 4 | GP15 | 黄色い十字 |

起動は黒地/灰色のWAITで、番号や特定ボタンの図形を出さない。全ボタンの開放が35ms安定するまで入力を有効にしない。押したまま起動したボタンも、離して35ms待ち、新しく押すまで無視する。各入力マスクが35ms安定してから押下を確定し、長押しの再通知や離した時の別ボタン表示を防ぐ。同時押しは灰色MULTI。単独押下の図形は次の押下まで保持する。

画像はRGB565をPi5側と同じ反転＋R/B入替で補正し、同じLCD設定へ書く。ネットワーク、動画、config.h、USB/UART stdioをリンクしない。秘密設定への依存なしをobject dependencyとmapで確認した。

```sh
cd /home/tane/dev/PicoW/PicoW_Youtube_Player
PICO_SDK_PATH=/home/tane/pico/pico-sdk cmake -S . -B /tmp/picow_buttons_20261010 \
  -DPICO_BOARD=pico_w -DCMAKE_BUILD_TYPE=Release -DPLAYER_CYW43_DIAG=OFF
cmake --build /tmp/picow_buttons_20261010 --target pico_w_button_test -j2
```

UF2: `/tmp/picow_buttons_20261010/pico_w_button_test.uf2`、23,040B。
SHA256: `23dec57bcf9270db4c75e4cca4c3f76178f1a010ea69536a17f3c43804ab16d9`。

ユーザーの09:26 JSTのBOOTSEL/転送連絡後、唯一のBOOTSEL RP2040（bus2/address3、Flash ID `0xE661640843239D21`、従来機と一致）へ09:29:59 JSTに `picotool load -v -x`。Flash Verify100% OK、execute成功。ROM USBの消失を再確認した。stdioを有効にしていないため実行モードのUSB/シリアルログは出ない。その後09:47 JSTにユーザーがはんだ不良の修理とボタンによるパターンテストOKを報告した。第1段階の目視確認は完了。

## 第2段階: 本番動画180度回転（転送・実画面確認済み）

本番側のみ `PLAYER_ROTATE_180=ON`（新規ビルド既定ON）。同じ `lcd_show` のSPI転送直前に、表示側が所有するバッファの12,800画素を画素単位で逆順へ並べる。高位/低位バイト順を維持し、色のビットを変えない。これで(x,y)は(159-x,79-y)へ写る。MADCTL/INVON/ガンマ/表示範囲0..159、24..103は変更しない。フレームサイズ、TCP/FPS/再接続、色補正を保ち、ボタンの本番機能は追加しない。

LCDコードは共通ヘッダーへ移した。ホストで実際の初期化コマンド、GPIO、全25,600BのSPIペイロード、窓設定、色とバイト順、回転を2回した元データ復元を確認した。回転の向き・色・画面の収まりは転送後にユーザーが確認済み。実効高FPS/長期耐久は別途未測定。ネットワークと描画間隔の処理は変えていないが、画素反転の追加CPU時間は実機未測定。

```sh
PICO_SDK_PATH=/home/tane/pico/pico-sdk cmake -S . -B /tmp/picow_video_rotate180_20261010 \
  -DPICO_BOARD=pico_w -DCMAKE_BUILD_TYPE=Release -DDISPLAY_PROFILE=0 \
  -DPLAYER_CYW43_DIAG=ON -DPLAYER_LCD_GAMMA_LGFX=ON -DPLAYER_ROTATE_180=ON
cmake --build /tmp/picow_video_rotate180_20261010 --target pico_w_jpeg_player -j2
```

UF2: `/tmp/picow_video_rotate180_20261010/pico_w_jpeg_player.uf2`、642,048B。
SHA256: `65900f5224c64efdde49e9652d035ad34416fb532212f92740396825b70eaa1c`。
CYW43診断ONは現在のBと同じ。ファームはWi-Fi設定を含むため、保全先 `diagnostics/artifacts/buttons-rotation-20261010/` は非公開/Git除外。元Bの `video-before-rotation.uf2` も保全した（SHA256 `ee4cfe411d542618a188142c5246208e2e36af7d68cae5fe955b951567b6c1fb`）。

第1段階のユーザー確認と第2回のBOOTSEL連絡までは転送しない。第2段階へ戻す際も同じFlash IDを照合する。回転OFF再現は `-DPLAYER_ROTATE_180=OFF`。既存CMakeキャッシュの値は明示フラグで指定する。

49単体テスト成功（初回11.382秒、コミット前再実行11.032秒）、両ビルド警告/エラー0。GPIO実関数、起動時押しっぱなし、チャタリング、長押し、同時押し、時刻のwrap、図形/補正色、LCD実転送を含む。 [証拠](../verification/buttons-rotation-20261010.json)、[テストログ](../verification/buttons-rotation-20261010-tests.log)。


## 第2段階の転送結果（2026-10-10 09:49 JST）

09:47 JSTの「ボタンテストOK、180度動画版を転送、BOOTSEL待機」指示を受領。UF2の上記SHA256一致を再確認し、単一BOOTSEL RP2040 bus2/address4のFlash ID `0xE661640843239D21` が従来機と一致したため、09:49:05 JSTに `picotool load -v -x` で転送。Flash Verify100% OK、実行指示成功、BOOTSEL USB消失を確認。

既存Web/TCPサービスは同じPID78888、active/enabledを維持しており、再起動や設定変更はしていない。PicoのSDK STA MAC `28:cd:c1:09:78:41` で再接続し、転送後の新しい状態値が09:49:17の受信/描画0/0から09:49:31の29/29へ増加、`raw-display`・render=onを確認した。ユーザーが選択した動画 `vEVq_Bx7_KY` /6fpsのまま配信を継続。動画選択は変更しない。

これは転送検証・再接続・LCD書込みのソフト側確認であり、実画面の180度方向・色・四辺の収まりをユーザーが確認し、YouTubeデバイス完成を承認した。短いWi-Fi区間の受信/描画率から安定6fpsを保証しない。転送作業ではOS/ネットワーク/サービス設定、コミット/pushは変更していない。[転送と再生の証拠](../verification/video-rotate180-flash-20261010.json)。


## ユーザー確認とローカル保存

親会話でユーザーが実画面を確認し、4ボタン診断成功に続いて180度回転版の向き・色・収まりを含むYouTubeデバイス完成を承認。09:55 JSTにこのプロジェクトの今回差分だけをローカルコミットする範囲へ「はい」と承認した。秘密設定、動画、UF2/ELF、無関係な変更は含めない。OS・ネットワーク・サービス・実機への追加操作やpushは行わない。この完成承認は高FPS/長期耐久の性能測定を意味しない。
