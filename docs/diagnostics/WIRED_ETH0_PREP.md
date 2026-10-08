# 一時有線比較: 準備・実測・復元

状態: **試験をFixし、同じPico Wへ元の`.120`用UF2を転送・Verify 100%成功。`.120:16151`のWi-Fi RAW6fps配信を再開し、受信/描画増加とwlan0双方向通信を確認した。試験専用ruleは撤去しtable16151は空。** 一時eth0プロファイル撤去/旧autoconnect復元だけがNASケーブル返却確認待ち。eth0はNO-CARRIER、IP/経路なし。Wi-Fi IP・既定経路・DNSは不変。ルーター、Firewall、SSH、他サービスは変更していない。SSHコマンドは使っていない。資格情報は表示していない。

## 変更前記録

- Wi-Fi `wlan0`: `192.168.0.120/24`、IPv4既定経路 `via 192.168.0.1 dev wlan0 metric 600`、IPv6既定経路も`wlan0 metric 600`、DNSは`192.168.0.1`と既存リンクローカルアドレス。現実測`wpa_cli signal_poll`では**5280MHz（5GHz、ch56、80MHz幅）**。Pi5 Wi-Fi設定自体は変更しない。
- `eth0`: `NO-CARRIER`、IPv4アドレス/経路/通信なし。NetworkManager管理対象でautoconnect有効。旧有線プロファイルUUID `b33d5ba6-ceab-373c-aa5c-a9d8555c02d4`、名前`Wired connection 1`、`eth0`固定、`connection.autoconnect=yes`、priority -999、IPv4/IPv6 autoで元は既定経路/DNSを無視しない設定。
- 秘密値を含めない前後スナップショット: `/tmp/picow_eth_before.json` と `/tmp/picow_eth_after.json`。Wi-FiのSSID/パスワードを探していない。

## 差込前に実施したeth0のみの変更

1. 一時NetworkManager接続`PicoW-wired-test`、UUID `63a706d9-a9e7-41b5-9974-0e56339792cb`を作成。interface `eth0`かつ物理MAC `2c:cf:67:11:72:f3`に限定。`autoconnect=yes`、priority100、`ipv4.method=auto`、`ipv4.never-default=yes`、`ipv4.ignore-auto-dns=yes`、`ipv4.ignore-auto-routes=yes`、`ipv4.route-metric=2000`、`ipv6.method=disabled`、`ipv6.never-default=yes`、`ipv6.ignore-auto-dns=yes`。
2. 旧有線プロファイルの**`connection.autoconnect`だけ**`yes→no`に変更。差込時に旧設定が既定経路やDNSを追加する競合を避けるため。旧プロファイルは削除せず、他の設定は編集していない。
3. 最初の一般ユーザー`nmcli connection add`はpolkit認証待ちでタイムアウトし、プロファイルは作成されなかった。既存状態を再確認後、`sudo -n nmcli`の正規権限で上記プロファイルを一度だけ追加した。

検証: 一時プロファイル全項目と旧`autoconnect=no`を読戻し、前後スナップショットを機械比較して**Wi-Fi IPv4アドレス、IPv4/IPv6既定経路、Wi-Fi DNS不変**。全体DNSにもeth0からの追加なし。`eth0`は依然IP/経路なし。Pico `192.168.0.173`への現行routeは引き続き`wlan0`、16151配信は稼働中。

## 差込後の確認と動画のみ有線にする案

ユーザーによるケーブル接続後、eth0は`192.168.0.116/24`をDHCP取得、**1000Mb/s Full Duplex**、適用UUIDは一時プロファイル`63a706d9-a9e7-41b5-9974-0e56339792cb`。eth0に増えた経路は`192.168.0.0/24 dev eth0 src 192.168.0.116 metric 2000`だけで、eth0 DNSは空。変更前の記録と比較してWi-Fi `192.168.0.120`、IPv4/IPv6既定経路、DNSはいずれも不変。Pico宛てのWi-Fi送信元`.120`からのrouteは`wlan0`のまま。記録は`/tmp/picow_eth_cable.json`。現行の16151番配信プロセスはこの確認時点で待受なし（前回PIDも終了）であり、今回の差込後調査では停止/再起動していない。

元のPicoファームはサーバーIPをWi-Fi側`.120`に固定している。そのままでは有線比較にならない。route追加前は`ip route get 192.168.0.173 from 192.168.0.116`も**wlan0**だった。ユーザーの具体的承認後、priority5000・table16151が未使用であることを確認して、**有線IPを送信元とし、Pico IPを宛先とする通信だけ**に一致するsource-based policy routeを以下のとおり追加した。

```sh
# 一時適用済み。恒久化していない。
sudo ip route add 192.168.0.173/32 dev eth0 src 192.168.0.116 table 16151
sudo ip rule add pref 5000 from 192.168.0.116/32 to 192.168.0.173/32 table 16151
```

適用後は`ip route get 192.168.0.173 from 192.168.0.116`が**eth0/table16151**、同`.120`が**wlan0**、送信元`.116`でもPico以外のゲートウェイ宛ては**wlan0**であることを確認。Wi-Fiの既定経路/DNSは不変。有線IP送信元のPico pingは5/5応答（初回ARP解決で140ms、以後約4〜8ms）、eth0のPico近隣MACはSDK報告の`28:cd:c1:09:78:41`と一致する。ただしICMP応答だけではTCPの返信経路やARP fluxを証明できない。対象TCPのSYN/データが**双方ともeth0で通ること**を限定captureで照合する。ARPがwlan0へ流れて完全な有線比較にならなければ中止し、Wi-Fi設定を変更して無理に通さない。DHCPの`.116`は一時値であり、試験時に再取得された場合はIPとruleを作り直す。

同じ588枚・RAW表示6fps・色補正・2秒送信期限の**Wi-Fi側ペア基準90秒**を現Pico `.120`で測定済み。Pico状態の約88.104秒端点で表示+468＝**5.312fps**、完成+524＝5.948fps、画面スロット破棄+56、TCP再送バイト少なくとも936,920B、2秒send timeout0回。ログは`/tmp/picow_wifi_paired_baseline.log`と`_tcp.log`。計測用サーバーは正常終了させた。有線用には`config.h`の`SERVER_IP`定義1行のみ`.120→.116`へ一時変更し、元ファイルを権限600の`/tmp/picow_config_pre_wired.h`に保全。SDK/driver/表示/通信設定は不変、`PLAYER_CYW43_DIAG=ON`の同じbuildをclean-first再ビルド。UF2`/tmp/picow_cyw43_wired_116.uf2`（641,536B、SHA256`f03e55d2532c6823d7213ab938f734f9f1aef2f239fc3155659d85458461ca9c`）は**未転送**。Wi-Fi資格情報は表示していない。

上記の有線UF2は手動BOOTSEL後、Flash ID `0xE661640843239D21`を照合して`picotool load -v -x`で転送し、Flash Verify 100%と起動を確認した。同じ引数のサーバーを`.116:16151`へbindし、Pico `.173` / SDK STA MAC `28:cd:c1:09:78:41`の接続と`mode=raw-display`を確認した。

## 有線実測（2026-10-08 JST）

両条件でJPEG588枚、RAW RGB565各25,600B、6fps、色補正、2秒送信期限、同じ診断driver・Pico設定を使用。変えたのはPi5送信元/経路とPicoのSERVER_IPだけ。Wi-Fi基準と有線をそれぞれ90秒採取した。

| 指標 | Pi5 Wi-Fi `.120` | Pi5 eth0 `.116` |
|---|---:|---:|
| Pico状態の端点間隔 | 88.104秒 | 89.000秒 |
| 描画増分 / 実描画fps | 468 / 5.312 | 534 / 6.000 |
| 完成フレームfps | 5.948 | 6.000 |
| 画面スロット破棄 | 56 | 0 |
| 送信タイムアウト / 接続数 | 0 / 1 | 0 / 1 |
| TCP再送バイト増分（ss採取端点） | 936,920B | 3,960B |
| RTO最大 / cwnd=1のサンプル数 | 1,728ms / 16 | 289ms / 0 |
| 500ms以上のsendall停止 | 1回 | 0回 |
| 5秒集計のsendall最大時間 | 1,162ms | 2ms |

`ss`は0.25秒ごとに360件採取。Wi-Fi/有線ともゼロ送信窓のサンプルは0。初回ss時点の再送累計は両条件0なので、表の再送値は採取期間内の増分。有線では動画`sequence=588 frame0001`への周回も確認した。Pico callback最大空白は有線の継続観察で244ms、SPI通常約15.6ms。

許可された限定captureは`host 192.168.0.173 and tcp port 16151`のみ、`-i any -s 54 -c 300`で実施。全300件が**eth0 Out 159件 / eth0 In 141件**、wlan0は0件、kernel drop0。これは双方向eth0の実通過確認で、短いサンプル以外のARP挙動すべてを保証するものではない。`rp_filter=2`、ARP関連sysctlは読取りだけで変更していない。

結論: 今回はPi5のWi-Fi側区間を除くとRAW6fpsを達成し、再送と送信詰まりが大幅に減った。Pico表示/SPI/フレームバッファが6fpsを阻害する必須要因という説明は支持されない。時間差のある単発比較なので、AP、Pi5の無線driver、RF、帯域間転送のどこが損失源かは確定しない。Pico側2.4GHz区間は有線条件でも残る。12fpsは以下の追試で測定した。長時間安定性は未測定。

## 追加のFPS上限試験

ユーザーが有線復元を保留し、理論上限付近の試験を指定した。Picoを再転送せずサーバーの`--fps`だけを変えた。元JPEGは6fps素材なので、高い配信fpsで再生時間が短くなる容量試験であり、新しい動画フレームの生成や補間はしていない。

ローカルSDKの既定`clk_peri=clk_sys=125MHz`、プロジェクトにクロック変更なし、`LCD_SPI_BAUD=20MHz`。SDK `spi_set_baudrate`の分周計算ではprescale=2/postdiv=4、SPI=15.625MHzとなる（実行中getterによる読戻しではなく、ソースとビルド設定からの算出）。表示窓11B＋画素25,600Bを含む純転送上限は約76.261fps。低負荷実測SPI15.6msに毎ループ` sleep_ms(1)`を足すと約60.2fpsの目安だが、Wi-Fi処理とCPUを共用するので負荷時の上限ではない。LCDパネル自身の走査周波数/ティアリングは測っていない。

各条件60秒で、Pico状態端点の差分を集計する。完成fpsは受信に成功した全フレーム（受信スロット満杯による破棄を含む）、実描画fpsは`lcd_show`完了回数。

| 設定fps | 状態端点間隔 | 完成fps | 実描画fps | スロット破棄 | TCP再送 / timeout | SPI処理サンプル中央値 |
|---|---:|---:|---:|---:|---:|---:|
| 76 | 58.844秒 | 69.183 | 8.378 | 3,578 | 1,400B / 0 | 123.675ms |
| 48 | 58.590秒 | 47.892 | 22.017 | 1,517 | 1,400B / 0 | 41.834ms |
| 32 | 58.758秒 | 31.996 | 29.970 | 119 | 0B / 0 | 29.423ms |
| 24 | 58.316秒 | 23.956 | 23.458 | 29 | 2,360B / 0 | 15.652ms |
| 28 | 58.638秒 | 27.866 | 27.150 | 43 | 1,820B / 0 | 28.948ms |
| 12 | 89.000秒 | 12.000 | 11.955 | 4 | 2,260B / 0 | 15.645ms |

76fps時の限定capture300件もeth0 In143/Out157、wlan0は0、kernel drop0。TCP停滞やpbuf枯渇のカウンタ増加なしでも、高い受信負荷でCPUブロッキングのSPI処理が延び、多くの完成フレームが画面スロット満杯で捨てられる。原因の細部は割込み占有率を未測定なので断定しない。SPIサンプルは毎秒の状態報告にある直近フレーム時間のみで、全フレーム分位ではない。

今回の最高実描画は32fps設定の29.970fps。12fpsでは受信完成1,068枚/89秒で12.000fps、描画1,064枚で11.955fps、破棄4枚（約0.37%）。12fpsも完全無欠落とは言わない。いずれの高fps条件も接続1回・送信timeout0、500ms以上のsendall停止0、credit待ち/credit DATA破棄/pbuf割当失敗/TCP memerr/転送バッファ変更/SDPCM不正/driver SPIエラーのカウンタ増加0。高い配信設定ほど高い実描画になるという結果ではない。

試験後は`.116:16151`のRAW6fpsを再開し、元の動画再生速度へ戻した。ログ`/tmp/picow_wired_after_fps.log`、実行セッション42747。終了時にこの本プロジェクトのサーバーだけを停止する。各上限条件は制御したSIGINTで正常終了（exit0）した。実行方法は次のとおり。これは試験用有線UF2・限定routeが残っている間のコマンドであり、通常のWi-Fi向け起動とは異なる。

```sh
python3 -u server.py --host 192.168.0.116 --port 16151 \
  --frames /home/tane/Videos/voltesV_6frame --compensate-colors \
  --trace-motion --fps 32 --send-timeout 2 --mode raw-display
```

再現/集計用スクリプトは`/tmp/picow_run_wired_fps.py`、`/tmp/picow_summarize_run.py`、`/tmp/picow_fps_details.py`。各条件のログ/ss/実時間summary/結果metricsは`/tmp/picow_wired_fps<設定値>*`。秘密値なしの結果JSONは`diagnostics/results/wired-fps<設定値>.json`にも保存した。

ユーザーから有線で画像のカクつきが大きく減ったとの目視報告を受けた。これは6fpsの通信停滞改善を支持する。高fps試験の同じ素材は速送りなので、ネイティブ12/24/30fps動画の滑らかさを証明しない。将来のサーバー有線化は今回恒久化していない。

証拠: `/tmp/picow_wifi_paired_baseline.log`、`/tmp/picow_wifi_paired_baseline_tcp.log`、`/tmp/picow_wifi_paired_baseline_metrics.json`、`/tmp/picow_wired_paired.log`、`/tmp/picow_wired_paired_tcp.log`、`/tmp/picow_wired_paired_metrics.json`、`/tmp/picow_wired_iface.pcap`。秘密値なしの結果JSONはこのディレクトリにも保存する。

復元準備: ローカル`config.h`のSERVER_IPだけ`.116→.120`へ戻し、変更前バックアップとバイト単位の完全一致を確認済み。clean-first再ビルドした`/tmp/picow_cyw43_restore_120.uf2`は641,536B、SHA256 `7be46fb51d43beb4c4cd095c9b309c7c16f5b0e95a4b00d8ab698b7022b81380`で、試験前のUF2と一致する。**まだ復元転送していない**。手動BOOTSELと有線ケーブル取外しが必要。

## 復元状況と残作業

ユーザーが検証フェーズFix・Wi-Fi/6fps復元を決定し、手動BOOTSELを報告した。同じFlash ID `0xE661640843239D21`を照合して`/tmp/picow_cyw43_restore_120.uf2`を転送、Flash Verify100%・アプリ起動を確認した。UF2 SHA256は試験前と一致。`config.h`も秘密値を出力せず変更前保全ファイルとのバイト単位一致を確認済み。

一時有線サーバーだけを正常停止し、pref5000の`.116→.173/table16151`ルールだけを照合して削除した。専用routeはeth0リンク/アドレス撤去時にすでに消えていたため、誤って他のrouteを削除せず空を確認。残りの既存rule/main/defaultは編集していない。

復元後サーバーは`--host 192.168.0.120 --fps 6 --mode raw-display --port 16151 --compensate-colors --trace-motion --send-timeout 2`、ログ`/tmp/picow_wifi_restored_live.log`、実行セッション13374。588枚を読み込み、Pico `.173` / SDK STA MAC一致、受信/描画カウンタの増加を確認した。限定capture200件は**wlan0 In63 / Out137、eth0 0、kernel drop0**。変更前との比較でWi-Fi `.120`、IPv4/IPv6既定経路、DNS不変、eth0アドレス/経路なし。従来Wi-Fi区間の再送/フレーム破棄は残り、復元が性能問題を解消したという意味ではない。

証拠: `diagnostics/results/wifi-restore-result.json`、`diagnostics/results/wifi-restored-headers.pcap`、`/tmp/picow_wifi_restore_flash.log`、`/tmp/picow_eth_wifi_restored.json`。有線プロファイル撤去と旧autoconnect復元は**NASケーブル返却の明示確認まで待つ**。その完了前に復元全体が完了したとは言わない。

有線動画試験を終えたら、先に一時サーバー・source-based rule/routeを止めてPicoのサーバーIPを元の`.120`へ戻し、**ケーブルを抜いてから**一時プロファイルを削除する。その後、旧有線UUID `b33d5ba6-ceab-373c-aa5c-a9d8555c02d4`の`connection.autoconnect=yes`を元に戻す。これにより旧プロファイルが試験終了時に予期せず有線経路を追加することを避ける。Wi-Fiアドレス/既定経路/DNSを変更前記録と照合する。

適用したpolicy route/ruleは、Pico接続先復元前にruleを先に、次に専用tableのrouteを削除する。Wi-Fiのmain tableには触れない。

```sh
# 一時適用したrule/routeを終了時に削除する。
sudo ip rule del pref 5000 from 192.168.0.116/32 to 192.168.0.173/32 table 16151
sudo ip route del 192.168.0.173/32 dev eth0 src 192.168.0.116 table 16151
```

ケーブルを抜いた状態でのプロファイル復元コマンドは次のとおり。実行前に対象UUIDを再確認する。

```sh
sudo nmcli connection delete uuid 63a706d9-a9e7-41b5-9974-0e56339792cb
sudo nmcli connection modify uuid b33d5ba6-ceab-373c-aa5c-a9d8555c02d4 connection.autoconnect yes
```
