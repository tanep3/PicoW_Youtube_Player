# 映像検証フェーズFix

2026-10-08。ユーザーの決定によりWi-Fi `.120` / RAW6fpsへ戻し、検証フェーズをFixする。有線化と30fps改訂はハブ到着後の別作業。YouTube本体の新実装はまだ開始していない。

## 確認できた成果

- 既存JPEG588枚・160×80・命名/欠番なしを確認し、元画像を変更せず再生した。
- Pico W + ST7735SのSPI0配線で映像描画、色補正、Yoffset24による全画面表示をユーザーが確認した。
- TCPの分割受信、エンドレス周回、切断後の再接続・共有動画時刻からの継続を実機確認した。
- 6.9秒級送信停止では、ゼロ受信窓ではなくTCP未ACK/再送・RTO指数バックオフを確認した。Pi側送信期限2秒で1回のsendall固着を抑制する。
- 同条件6fpsではPi5 Wi-Fi経路5.312fpsに対し、有線経路6.000fps・破棄0。限定ヘッダーcaptureでeth0の双方通過を確認し、ユーザーもカクつきの大幅減少を確認した。
- 現SPI設定のソース/分周から純転送理論76.3fps。76fps負荷では完成69.18fps/描画8.38fps、32fps負荷で今回最高の描画29.97fps。CPUを使うSPI書込みは受信負荷で延びるため、理論値を実描画の保証には使わない。
- 12fps確認は完成12.000fps、描画11.955fps、89秒でスロット破棄4。高fpsは元の6fps連番を速く送った容量試験。

## 未達・限界

- 復元先のWi-Fiでは再送/停止/フレーム破棄が残り、全フレームの安定6fps描画は保証しない。
- Wi-Fi問題をPi5本体、AP、電波、driverの一つに特定していない。Pi5無線区間を除くと改善したという経路比較の結論。
- 30fpsの無欠落継続、ネイティブ30fps動画、パネルの走査/ティアリング、長期間の安定性は未検証。
- 2秒sendall期限は最大表示停止を2秒にする仕様ではない。
- 音声、Web動画指定、YouTube取得/AI検索、自動ffmpeg変換、プレイリスト、常駐サービスは未実装。

## 現運用

Picoは試験前と同じSHA256の`.120`用UF2をVerify付きで再転送済み。Pi5は次の手動起動コマンドで既存動画を配信中。常駐サービスにはしていない。

```sh
cd /home/tane/dev/PicoW/PicoW_Youtube_Player
python3 -u server.py --host 192.168.0.120 --port 16151 \
  --frames /home/tane/Videos/voltesV_6frame --compensate-colors \
  --trace-motion --fps 6 --send-timeout 2 --mode raw-display
```

Pico `.173`からの接続、受信/描画増加、wlan0 In/Outを確認。Wi-Fi `.120`、IPv4/IPv6既定経路とDNSは変更前と一致。SSHコマンド/SSH設定変更、他サービス変更、共有SDK/driver変更、gitlink/remote設定/コミット/pushは行っていない。

**残作業:** NASケーブル返却の確認後、一時eth0プロファイルを削除し、保全していた旧有線プロファイルのautoconnectを元のyesへ戻す。限定policy ruleは撤去済み、table16151は空。現在eth0はNO-CARRIERでアドレス/経路なし。

詳細証拠と復元手順: [WIRED_ETH0_PREP](diagnostics/WIRED_ETH0_PREP.md)。次フェーズの棚卸し: [YOUTUBE_REQUIREMENTS_INVENTORY](YOUTUBE_REQUIREMENTS_INVENTORY.md)。
