# 製作・起動手順

ここでは新しい環境で、採用済みSPI0配線とSLIM v3ケースを再現します。既に動いている実機では、実設定を見本で上書きせず、同じポートへ二重起動しないでください。

## 1. Pi5の依存を用意する

必要なのはPython 3/Pillow、yt-dlp、HTTPS対応ffmpeg/ffprobe、Node.jsです。PicoビルドにはPico SDK、CMake、ARM GCC、makeまたはNinjaを使います。通常配信にROSや追加Webフレームワークは使いません。

Pythonは専用venvへ依存を入れられます。以下はPi5で実行する例です。

```bash
cd /home/tane/dev/PicoW/PicoW_Youtube_Player
python3 -m venv "$HOME/.venvs/picow-player"
. "$HOME/.venvs/picow-player/bin/activate"
python3 -m pip install -r server/requirements.txt
```

yt-dlpとNode、ffmpeg/ffprobeはその環境で使用するものを用意し、Web設定へ絶対パスを記入します。各ツールの実パスと機能を確認できます。

```bash
command -v yt-dlp ffmpeg ffprobe node cmake arm-none-eabi-gcc picotool
ffmpeg -protocols
ffprobe -protocols
python3 -c 'from PIL import Image; print(Image.__version__)'
```

ffmpeg/ffprobeの一覧にHTTPSが必要です。使用環境ではユーザーがffmpeg/ffprobe 9.0.2をOpenSSL対応で構築済みです。他の環境では版名だけで判断せず、機能を確認してください。[当時の再ビルド記録](FFMPEG_HTTPS_REBUILD.md)を残しています。ChromeやChromeのCookieは取得に使いません。

## 2. LANとWeb設定

Pi5とPico Wが通信できるLANを用意します。Pico WのWi-Fiは2.4GHzです。Pi5のLANアドレス、ネットマスク、GW/DNSと、Picoへ割り当てる静的IPを確認してください。

新規設定だけ作成する例：

```bash
test -e web-config.json || install -m 600 web-config.example.json web-config.json
```

[設定例](../web-config.example.json)の各項目を自分の環境へ編集します。

| 項目 | 内容 |
|---|---|
| data_dir | 保存先の絶対パス。書込み可能な場所 |
| web_host / web_port | ブラウザー用のbind先。試作は192.168.0.120 / 16152 |
| tcp_host / tcp_port | Pico向けのbind先。試作は192.168.0.120 / 16151 |
| yt_dlp | yt-dlpの絶対パス |
| ffmpeg / ffprobe | HTTPS対応の対応する実行ファイル |
| node | Nodeの絶対パス。特にsystemdではシェルのnvm設定を読まない |

見本の `/home/tane/…` やIPは使用環境の例です。別ユーザーではそのまま使わず、実パスへ合わせます。LANから使う場合はPi5のIPで待ち受けます。`127.0.0.1` は同じPi5からのWeb確認だけに適し、Picoから接続できません。ポート16150/8080はアプリで予約扱いです。

## 3. Picoの設定とビルド

新規設定だけ作成します。入力した秘密値や生成UF2/ELFを公開しないでください。

```bash
test -e config.h || install -m 600 pico/config.example.h config.h
```

`config.h` をローカルのエディターで開き、WIFI_SSID/WIFI_PASSWORDとSERVER_IP/SERVER_PORTを入力します。SERVER_IPはPico自身ではなく、配信するPi5のIPです。設定例の192.0.2.1は見本で、実Pi5へ接続しません。

使用個体の液晶は次の設定で色と全画面表示を確認しました。

| 項目 | 値 |
|---|---|
| DISPLAY_PROFILE | 0（SPI0 GP17〜21） |
| LCD_SPI_BAUD | 20000000 |
| LCD_MADCTL | 0x60 |
| LCD_X_OFFSET / LCD_Y_OFFSET | 0 / 24 |
| LCD_INVERT | 1 |
| PLAYER_LCD_GAMMA_LGFX | ON |
| PLAYER_ROTATE_180 | ON |

Pi5側の反転＋R/B交換補正と合わせた値です。別モジュールの位置や色は固定診断で確認します。採用済み配線にボタンがあるので、古いSPI1案へ切り替えないでください。

SDKは既にインストールしたPico SDKのパスを指定します。試作環境はSDK 2.1.1、SHA `9a4113fbbae65ee82d8cd6537963bc3d3b14bcca` です。共有SDKを編集せず、標準ビルドでは隔離通信診断をOFFにします。

```bash
PICO_SDK_PATH=/home/tane/pico/pico-sdk cmake -S . -B build \
  -DPICO_BOARD=pico_w -DCMAKE_BUILD_TYPE=Release -DDISPLAY_PROFILE=0 \
  -DPLAYER_CYW43_DIAG=OFF -DPLAYER_LCD_GAMMA_LGFX=ON -DPLAYER_ROTATE_180=ON \
  -DPLAYER_STATIC_IP=192.168.0.173 -DPLAYER_GATEWAY=192.168.0.1 \
  -DPLAYER_NETMASK=255.255.255.0 -DPLAYER_DNS=192.168.0.1
cmake --build build --clean-first -j2
```

Pico側IPv4は静的設定です。IP/GW/ネットマスク/DNSは自分のLANへ変更し、DHCP割当や他機器と重ならないIPを選んでください。Pi5側のIPが変わる場合はconfig.hのSERVER_IPも変更します。設定を変更した転送前にはclean-firstを使い、古いUF2を転送しないようにします。

生成物は `build/pico_w_jpeg_player.uf2`。採用ガンマと180度回転は標準ビルド既定ONですが、既存CMakeキャッシュの設定も確認します。診断UF2と通常UF2は区別して保管してください。

## 4. 配線確認とUF2転送

[READMEの配線](../README.md#配線)と[ケース組立](../hardware/case/README.md)を先に確認します。電源を外して配線し、3.3V/GNDとピン番号を照合します。使用個体のBLKは未接続で点灯済みですが、購入した基板の仕様を優先してください。

Pico WのBOOTSELを押しながらPi5のUSBへ接続し、対象機を確認してから転送します。picotoolを使う例：

```bash
picotool info -a
picotool load -v -x build/pico_w_jpeg_player.uf2
```

対象が複数ある場合は、先に転送するPicoだけに絞るか、USB bus/addressで対象を指定します。`-v` は書込み検証、`-x` は書込み後の実行です。自分の対象機のFlash IDを初回から記録して取り違えを防ぎます。

UF2の手動コピーも可能です。その場合は、**実際にマウントされたRPI-RP2ドライブ**へコピーします。過去に `/media/tane/RPI-RP2` が通常ディレクトリとして残っていたため、名前だけでは判断せず、ファイルマネージャーのUSBドライブやマウント情報を確認してください。

本番ファームはUSB/UARTのstdioを有効にしていません。次の書換えも手動BOOTSELを使います。

4ボタンを先に試す場合は、同じbuildで別の `pico_w_button_test` ターゲットを生成できます。この診断にはWi-Fi設定を含めません。詳しくは[ボタン診断](diagnostics/BUTTONS_ROTATION.md)を参照してください。診断後は動画用UF2へ戻します。

## 5. Webから再生する

venvを使う場合は有効にしてから起動します。

```bash
python3 -m server.web --config web-config.json
```

ブラウザーで設定した `http://<Pi5のIP>:<web_port>/` を開き、URL・FPS・範囲を指定します。まず短い動画または区間を6fpsで試してください。取得・変換が終わると自動で切り替わり、繰り返し再生します。Picoの画面で色・向き・余白・動きを確認します。Ctrl+Cで手動サーバーを終了します。

HTTP403などの失敗はUIへ表示します。取得URLの再抽出・HLS代替は1回だけ試しますが、すべての動画の取得成功を保証するものではありません。準備時間には取得・区間再エンコード・JPEG変換が含まれます。ネット取得時間とJPEG変換だけの時間を混同しないでください。

## 6. 常用する場合

[userサービスの例](../deploy/picow-player.user.service.example)を編集し、自分の作成先、config、Pythonの実パスへ合わせます。venvを使う場合はExecStartをそのvenvのPythonにします。動くことを確認してから、自分のuserサービスとして登録できます。

```bash
mkdir -p "$HOME/.config/systemd/user"
cp -i deploy/picow-player.user.service.example "$HOME/.config/systemd/user/picow-player.service"
systemctl --user daemon-reload
systemctl --user enable --now picow-player.service
```

登録済みの環境では例を再コピーせず、既存unitを保持します。手動サーバーとサービスを同時起動しないでください。使用個体ではサービス再起動と保存済み選択の復元を確認済みです。OS再起動と24時間連続動作は未検証です。[Web運用記録](WEB_PLAYER.md)に停止・再起動・ログ確認を記録しています。

## 7. ソフト検証

```bash
python3 -B -m unittest discover -s tests -v
```

TCP試験はlocalhostの空きポートを使い、動画の追加ネット取得や実機への書込みは行いません。ffmpegが利用できる環境で、全49件の成功を確認しました。ハードウェアの発色や無線安定性はこの試験では証明できません。
