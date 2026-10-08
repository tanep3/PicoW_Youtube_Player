# CYW43 credit待ち損失の診断

状態: **同一Pico Wへ転送・RAW表示6fps実測済み。** 2026-10-08の観測ではcredit待ち、その待ちでのDATA破棄、TXバッファ変化はいずれも0。一方でTCP欠落・再送・2秒送信timeoutが再現した。共有SDK/driver、他サービスは変更していない。SSH、USBシリアル、新ioctl、callback内printfは使っていない。

## 実使用ソースの独立照合

- Pico SDK `9a4113fbbae65ee82d8cd6537963bc3d3b14bcca`、内包driver `c1075d4bc440422cf2b2fd12c64a1f53f77660ee`。共有driverのGit作業ツリーはclean。原本の `cyw43_ll.c` SHA256 `a4e6baa503b9332a0a445c8b22deb4bee62793c441dc74a200b0fe8065c397c7`、`cyw43_lwip.c` SHA256 `298b1b4a91f9790c5c130f8f398976d20141c21a19723af88a2ac6a911147fe3`。
- `pico_cyw43_arch_lwip_threadsafe_background` はこのdriverの `cyw43_ll.c`, `cyw43_lwip.c`, `cyw43_ctrl.c` を使う。Picoの `tcp_recved` が誘発するACKと毎秒のPWS3/PWS4は、lwIP `netif->linkoutput` → `cyw43_send_ethernet` → `cyw43_ll_send_ethernet` → `cyw43_sdpcm_send_common` のDATA送信経路に入る。初期化などのcontrol送信も同じ共通関数を使う。
- 原本 `cyw43_ll.c:640-685` はwireless flow controlまたは8bit TX credit待ちでRX FIFOをpollする。`:658-674` で `DATA_HEADER` を受けても `cyw43_cb_process_ethernet` を呼ばない。通常pollの `:1152-1176` とioctl待ちの `:1180-1207` はDATAを渡す。したがってこの待機経路に入った受信DATAはホスト側で失われ、lwIP pbuf/tcp.drop・アプリ受信callbackへ到達しない。待機や破棄が**今回実際に起きたか、初発損失だったかは未測定**。再入したままcallbackを呼ぶ修正はshared bufferとTX状態を壊し得るため行わない。
- 原本 `cyw43_ll.c:786-810` は送信Ethernetを `self->spid_buf[18..]` へ置き、共通送信関数へ同じバッファを渡す。credit待ちから呼ぶpollは `:1128` でRXを `self->spid_buf[0..]` に読み、共通送信は待機後にSDPCMヘッダーだけを書き直す（`:689-707`）。RXが18バイトを超えれば保留中のEthernetヘッダーやpayloadも上書きされ得る。送信退避・復元は原本内に見当たらない。ただし**実機でTX破損や、破損フレームが空中へ送られた事実は未確認**。タイムアウトで送信しなかった場合もある。

## 隔離した計装

`-DPLAYER_CYW43_DIAG=ON` の時だけ `diagnostics/pico/cyw43-driver/src/` のコピーと `diagnostics/pico/cyw43_diag.c` を使用する。`OFF` は共有SDK原本を使い、通常版のtext/data/BSSは変更前と同じ `317208/0/166068B` だった。コピーは上記driver SHAから採り、ライセンスを同梱。ファームウェアblobは選択済みSDK内へのローカルsymlinkで参照し、コピー・変更しない。共有SDKを編集しない。コピーの変更は [cyw43-driver.patch](../../diagnostics/pico/cyw43-driver.patch) でレビューできる。

待機中にだけ、送信元を ACKのみ / PWS3・PWS4状態 / その他・control に分類し、credit待ち回数・最大時間・1秒タイムアウトを数える。送信前後でEthernet先頭64バイトのfingerprintを比べる。SDPCM/BDCヘッダーは対象外。変化した場合だけイベントを残し、タイムアウト側のイベントは `tx_class` の上位bitを立てる。fingerprintは全payloadを保証せず、ハッシュ衝突の可能性もある。正常受信は通常pollとioctl待ちの双方で配送前に数え、lwIP入口、pbuf割当失敗、`netif->input`失敗も数える。SPI status/読取り/SDPCM形式エラーもカウントする。

Ethernet II・IPv4・TCPの境界を検証したうえで、TCP seq、port、TCP payload長だけを取得する。IP断片の後続部分や不正長は読まない。診断用パーサがdriverの2048B SPIバッファ外を読まないよう、受信ポインタと長さを制限する。通常配送の `tcp_gap` は同じTCP接続で期待値より大きなseqを見た回数で、**後で埋まる再順序も含むため損失確定値ではない**。動画のPi→Pico TCP source port 16151のデータを対象とする。SSID、鍵、パケットpayloadは記録・表示しない。

PWS4は既存PWS3の80Bに20個のu32カウンタ（80B）と直近8イベント×20B（160B）を加えた固定320Bで毎秒1回送る。内部リングは16件。イベントは`serial, Pico単調ms, TCP seq, src/dst port, TCP payload長, type, 送信種類`。type 1=credit待ちDATA破棄、2=通常RXでTCP seq前方gap、3=保留TXバッファ変化、4=pbuf割当失敗。Piは通番欠落を警告し、最初のcredit破棄時刻とseqも累積欄に保持する。高速に8件超が1秒内で起きると個別イベントが欠け得るが累積数には残る。PWS4自体が従来より240B/s大きいため、タイミングへの微小な影響は排除できない。

## 初発損失の判定基準と限界

1. Pi側で最初に再送した**絶対TCP seq**と送出/再送時刻を許可済みpacket captureで記録し、PicoのPWS4イベントを時刻対応させる。Pi/Picoの時計は直接同期していないので、状態受信時刻だけの対応は遅延を含む。当初の一般権限のtcpdumpは `CAP_NET_RAW` 不足で失敗した。ユーザーの明示許可を受け管理者権限で限定ヘッダーcaptureに成功し、下記の絶対seq照合を実施した。
2. 初回再送対象のseq範囲が、**再送より前**のtype1 credit破棄イベントの `[seq, seq+payload_len)` に一致した場合、そのパケットはRX FIFOまでは来たが、ホストdriverでlwIPより前に捨てられたと判定する。通常配送数・lwIP入口数の増分とpbuf失敗数も照合する。再送後のtype1一致だけなら、初発原因ではなく再送の増幅経路にとどまる。
3. type1がなく通常RXのtype2 gapやpbuf失敗type4が初発seqと一致すればそれぞれ配送境界を絞る。SPI/SDPCMエラー増分が同時ならバス境界を優先する。どのイベントにも現れない場合、AP/空中/CYW43439 blob内での欠落も候補だが、リング上書き・観測外経路を除くまでは断定しない。
4. type3の送信バッファ変化がACK送信のcredit待ちと同時に出れば、保留ACK破損の実行可能性を強く示す。ただし待機タイムアウトで送られなかった場合と、実際に送出した場合を分け、Pi側captureのACK番号・checksumと突き合わせてから因果関係を判断する。

計装版を転送し、現在のRAW 6fpsをPWS4・Pi `ss`・限定TCPヘッダーで測定した。次の実験は下記の発生境界に基づいて選び、共有driverや無線設定の変更は原因を特定してから行う。

## ビルド・転送・実機結果

```sh
cd /home/tane/dev/PicoW/PicoW_Youtube_Player
PICO_SDK_PATH=/home/tane/dev/PicoW/pico-sdk cmake -S . -B /tmp/picow_cyw43_diag_build_exact -DPICO_BOARD=pico_w -DPLAYER_CYW43_DIAG=ON
cmake --build /tmp/picow_cyw43_diag_build_exact -j4
python3 -m unittest discover -s tests -q
```

このSDK/driverでビルド成功、19試験成功。計装版ELFのBSSは166,636B（通常版から+568B）、`__end__=0x20028fd4` から `__StackLimit=0x20040000` まで94,252B。UF2は `/tmp/picow_cyw43_credit_diag_unflashed.uf2`（641,536B、SHA256 `7be46fb51d43beb4c4cd095c9b309c7c16f5b0e95a4b00d8ab698b7022b81380`）。ユーザーがBOOTSEL接続した単一RP2040のFlash ID `0xE661640843239D21` を前回と照合し、`picotool load -v -x` でFlash Verify 100% OK、起動を確認。Pi5の本プロジェクト配信のみPWS4対応版へ切り替え、同じ588枚、RAW表示、6fps、色補正、2秒send timeoutで16151番配信を継続した。Picoの固定IPは `192.168.0.173`、SDK報告STA MACは `28:cd:c1:09:78:41`。

### 2026-10-08の実機観測

- `ss -tin` を0.25秒刻みで125秒取得。約122.116秒のPWS4報告端点で表示+546枚（**4.47fps**）、画面2スロット満杯による破棄+65、通常RXでTCP seq前方gap+79。対象の4 TCP接続で再送バイトの接続別最大値の合計は**少なくとも1,318,200B**。サンプル475点で送信窓0は0点、RTO最大1,784ms、cwnd=1は43点。`normal_rx` と `lwip_seen` はともに9,856→22,436、pbuf割当失敗、`netif->input`失敗、SPI読取り・status・SDPCM異常はいずれも0。
- 測定中とその前後のPWS4で、**credit待ち0、待ち中DATA破棄0、送信バッファfingerprint変化0**。これらは追加した診断が有効に動き通常RXを数える同じファーム上の値である。2秒send timeoutと自動再接続が起きても0のままだったので、この観測期間の停止を上記credit待ち経路で説明する証拠はない。
- **カウンタの有効性・欠測**: 全827件のPWS4状態で`normal_rx`と`lwip_seen`は両方4,956→98,009、`event_serial`は37→779で、途中減少は0。接続し直してもPicoは再起動せず累積値を維持した。35回の`CYW43 event_serial_gap`表示は、サーバーのイベント既読番号がTCP接続ごとに0へ戻った最初の報告に各1回出たもの。接続内のイベント通番欠落は0。ただしTCP切断中には個別イベントがリングから流れ得るので、個別eventの網羅性は保証しない。credit待ち・破棄・TX変化の累積カウンタはこの欠測に依存せず0。
- ユーザーの明示許可後、`tcpdump`を管理者権限でPi5 `wlan0` の **`host 192.168.0.173 and tcp port 16151`** に限定し、snaplen54BでTCP固定ヘッダーだけ記録。実記録416.588秒、50,930 packet、kernel drop 0、17接続。ファイルは `/tmp/picow_16151_125s_headers.pcap`（3,565,124B）。125秒の外側timeoutはAppArmorのtcpdumpプロファイルに終了シグナルを送れず、同プロファイル/同UIDの対象PIDへSIGINTを送り終了したため、実記録が長くなった。
- **絶対seq照合例**: 接続Pico port63992でPi5が `1791430620.132199` にseq `3524899620:3524900960` を送出。同時バーストの後続seq `3524917040` をPicoの通常RX診断がgap event #296（Pico単調418,773ms）として記録。Pico→Pi5のACK `3524899620` が `1791430620.158127`、`.158218`、`.159911` に反復し、Pi5は `.159957` に欠けたseq `3524899620` を再送した。Picoが後続データを受けた時点で先行セグメントが通常RX順序に無かったことと、Pi5のfast retransmitは直接対応する。PWS4のcredit待ち・その破棄・pbuf不足はこの期間も0。
- 配信を維持した同じ約10秒にPi5 `wlan0` から各50回ICMPを送ると、Pico `.173` は39応答（22%損失）、ルーター `.1` は41応答（18%損失）。Pi5 `wlan0` の累積TX/RX errors/droppedは0。ルーターのICMP応答優先度や無線の時間変動があるため、この比較だけでPi5→AP区間を原因と断定しないが、動画受信やLCDに固有の問題ではない可能性を補強する。`iw`はPi5に未導入で、SSID/秘密値を読む操作はしていない。
- Pi5の`wlan0` captureはAPへ送る前のホスト側観測であり、空中送信・AP内部・CYW43439 blob内部のどこで最初のセグメントが消えたかは分けられない。`tcp_gap`には再順序も含み、pcap中の重複seq/overlap 2,723件は個別の損失個数ではない。共有driverのcredit待ち破棄を「コード上可能」とした静的所見は維持するが、今回の実測で**この停止の原因としては支持されない**。無線経路とCYW43 firmware側を次に切り分ける必要があり、ドライバ根本修正はまだ行っていない。

### Pi5送信経路の追加調査

- `ip route get`でPico `.173` と既存ルーター `.1` は両方 `192.168.0.120 dev wlan0`。配信PIDと調査シェルのnetwork namespaceは同一。`wlan0`はPi5内蔵SDIO `brcmfmac`（driver 7.45.234、firmware 01-996384e2）、MTU1380、bridge/bondのmasterなし。対象TCPのMSSは1340で、このMTUと一致する。Pico近隣MACはSDKが実機から報告した`28:cd:c1:09:78:41`と一致し、ルーターMAC`10:3c:59:36:fb:2d`と別。2回の確認でこの対応は安定しており、少なくとも観測時の重複IP/代理ARPの証拠はない。
- `wpa_cli signal_poll`だけでSSID/認証値を読まず、Pi5の無線リンクは5280MHz、80MHz幅、RSSI -55〜-48dBm、報告リンク速度260〜390Mbps。2回の60秒計測の前後で`wlan0`のTX/RX errors/droppedは0。`ethtool -S wlan0`はdriver統計未提供、`ethtool wlan0`の速度/duplexは権限エラー、`iw`未導入。`/sys/class/net/wlan0/device/power/control=auto`はSDIOのruntime PM設定であり、Wi-Fi firmwareの実効省電力モードを示さない。後続のWEXT読取専用ioctlとdebugfsで、下記の限定的な再送・PM指標を取得した。
- 既存の`eth0`はadmin UPだが**NO-CARRIER/state DOWN**、IPv4アドレス・eth0経路・通信カウンタは無し。PHYは最大1Gbpsをadvertiseするが、リンクが無いので実速度/duplexは不明。systemd-networkdではunmanaged、NetworkManagerではmanagedかつautoconnect=yes。ケーブルを接続するだけで自動DHCPや既定経路追加が起き得るため、本番Pi5ではユーザー/親の確認前に接続・設定変更しない。有線比較にはeth0物理接続と、既定経路/DNSを保持したまま本プロジェクトの通信だけeth0を通す計画が必要。Picoの現接続先はPi5 WLAN IP `.120`なので、比較時にはPico接続先変更または限定的な経路設計も必要になる。
- SSID/認証値を要求しない`SIOCGIWPOWER`のWEXT読取専用ioctlは`disabled=0`（legacy API上のPMは無効ではない）を返した。ただしfirmware内部の実効省電力状態は未検証。`SIOCGIWSTATS`の`discard.retries`（MAC再送上限到達で捨てた送信packet）は短時間に621,985→622,114と増えた。さらに動画配信中の**同じ12.019秒・同一TCP接続**でこのカウンタは622,309→622,418（+109）、Pi5 TCPの`bytes_retrans`は936,780→1,094,140B（+157,360B）。`wlan0`の通常TX errors/dropped=0でも、MAC再送限界に達した送信は起きている。ただしWEXTカウンタはinterface全体で本番通信も含み、+109個を動画TCPの各seqへ直接帰属できない。
- 既存brcmfmac debugfsのSDIO送信エラー`tx_sderrs=0`、`rx_badseq=85`は2回の読取で不変。`fws_stats`の送信分類・破棄は全て0で、この環境の有効なMAC再送計数には使えない。debugfsのshort/long retry limitは7/4（設定変更なし）。
- 各宛先1Hzで同時開始した60秒では、Pico/ルーターとも56/60応答で、欠けたICMP seqはどちらも3,18,26,55。対象TCPの`ss`再送バイト増分はこの60秒で694,340B。同時送信したprobeの相関であり、この一致だけをRF損失とは解釈しない。
- ルーターprobeを0.5秒遅らせた別の60秒では、Pico55/60応答、ルーター50/60応答で、欠落時刻は概ね異なった。対象TCP再送は598,440B増。両測定で動画TCP再送は継続するが平常時にも頻発しており、個々のICMP欠落とTCPの同一packet損失を結ぶ証拠ではない。ルーターのICMP応答制限、Pi5の送出・受信遅延、AP/無線経路をまだ区別できない。
- 直近10分のPi5 kernel logに`brcmfmac`/`wlan0`のerror/fail/timeout/disconnect/deauth行はなかった。`strace`を付けた3回のping試験は、トレース下で`SOCK_RAW: Operation not permitted`となり送出システムコール時刻を得られなかった。設定を変えずにPi5自身のICMP送出停滞まで除外することはできない。

追加ログは `/tmp/picow_route_probe_{pico,gateway}_ping.log`、`/tmp/picow_route_probe_tcp.log`、`/tmp/picow_route_probe_radio.log` と、同名の`picow_route_probe_stagger_*`。ローカルNICのoffload、PM、ルーターやAP設定は変更していない。

実機表示と配信は継続中。測定ログは `/tmp/picow_credit_diag_live.log`、`/tmp/picow_credit_diag_ss.log`。他サービス・ルータ設定・共有SDK/driverは変更していない。

