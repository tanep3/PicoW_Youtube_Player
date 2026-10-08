# Web動画プレーヤー

2026-10-08 JST。ユーザーのfirst commit `0fa8c38`を基準に実装。現在は承認された専用userサービスで稼働中。今回のWeb作業ではPicoの書込み・リセット・USBシリアル操作、ネットワーク設定や他サービスの変更はしていない。

## 現在の起動と操作

- Web: **http://192.168.0.120:16152**。Pi5のChromeでもこのIPを使う。固定IPへのbindなのでlocalhostはこのサービスの接続先にならない。
- Pico向けTCP待受もPi5の **192.168.0.120:16151**。Pico W `.173` が接続する。
- `picow-player.service` はtaneのuser managerで **enabled / active / running**。Web、TCP、取得ジョブを1つのPythonプロセスで担当する。
- 実設定はGit除外の `web-config.json`、保存先はプロジェクトの `data/`。既存本番16150（PID4805）はそのまま稼働している。
- 明示停止は保存した再生選択も解除する。サービスの正常終了・再起動では選択を保持し、検証済みキャッシュを先頭から再開する。専用サービスの実再起動で最後の選択の復元を確認した。Pi5本体の再起動試験は未実施。

通常の操作:

```bash
cd /home/tane/dev/PicoW/PicoW_Youtube_Player
systemctl --user status picow-player.service
journalctl --user -u picow-player.service -n 50 --no-pager
# コード・設定を変更した後、このアプリだけを再起動:
systemctl --user restart picow-player.service
# 自動起動も取り止める場合:
systemctl --user disable --now picow-player.service
```

RDPなどのシェルで `systemctl --user` が別のセッションD-Busへ接続して失敗する場合は、既存user managerのソケットをそのコマンドだけに指定する。今回の適用でもこの指定を使った。セッション設定自体は変更していない。

```bash
DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
XDG_RUNTIME_DIR=/run/user/1000 systemctl --user status picow-player.service
```

実unitは `~/.config/systemd/user/picow-player.service`。例は [user unit](../deploy/picow-player.user.service.example)。`ExecStart` は `/usr/bin/python3 -m server.web --config /home/tane/dev/PicoW/PicoW_Youtube_Player/web-config.json`。既に登録済みなので例を再コピーする必要はない。

既存のLinger=yesを利用しておりloginctlは変更していない。user managerのnetwork-online.targetに依存せず、起動時にPiのIPがまだなければbind失敗後3秒で再試行する。`Restart=on-failure`、`StartLimitIntervalSec=0`。通常停止はSIGINT、停止期限10秒。別の [system manager用例](../deploy/picow-player.service.example) も残すが登録していない。

## 実装したWeb操作

- 単一YouTube URLを直接指定。プレイリストとライブ配信は対象外。
- FPSは6 / 12 / 18 / 24 / 30、初期6。元動画から指定FPSへ変換する。
- 開始・終了は秒または `HH:MM:SS`。両方空欄は全編、終了だけ空欄なら最後まで。`0 ≤ 開始 < 終了 ≤ 動画長`を検証する。
- 取得・変換中は現在の動画を継続。完成キャッシュに切り替え、最初の送信フレームは連番0。その動画を繰り返す。TCP再接続は共有再生時刻から継続する。
- FPS変更も一致キャッシュを探し、なければ変換して先頭へ切替。
- サムネイル・タイトル・チャンネル・投稿者・元URL・完成キャッシュを履歴へ表示。JPEGと旧RAWの保存方式も表示する。
- 使用量は元動画、変換データ、画像、その他と空き容量。完成データを自動削除しない。
- 削除は確認した動画1件の全元動画（全編/部分）、全FPS/全区間の変換、画像、履歴。再生中は停止、処理中は取消し完了後に操作する。
- 取得・区間切出し/JPEG変換の段階と経過時間、失敗状態を表示する。1つのジョブを取消し可能。
- ダークモード。背景、履歴カード、入力、ダイアログをPi5の実Chromeで確認。390px幅で横はみ出しなし、JS実行例外0。

## 保存はJPEG、送信時にPi5で展開

```text
data/                         # Git除外
  library.sqlite3
  videos/<videoID>/
    thumbnail.jpg
    sources/<source-key>.<ext>
    converted/<conversion-key>/frame00000001.jpg
    converted/<conversion-key>/frame00000002.jpg
    ...
    converted/<legacy-key>.rgb565  # 既存旧キャッシュは保全
  work/<jobID>/                # そのジョブの未完ファイル
```

新規変換は160×80のJPEG連番 `frame00000001.jpg` から、ffmpegの `-q:v 5 -pix_fmt yuvj420p` で生成し、普通のフォルダへ保存する。ZIPにはしない。ファイルマネージャーや画像ビューアーからそのまま確認できる。フォルダの公開は全フレームの検証後に行う。再生成で旧フォルダがある場合は、DB登録まで保全し、失敗時は戻す。

Pi5は送信する1枚だけをフォルダから読み、PillowでJPEGを展開してbig endian RGB565へ変換する。従来の反転＋R/B交換補正はその時に適用する。Picoへは既存PWF2の20Bヘッダーと25,600BのRGB565を送る。**ディスク保存量は減るが、TCP転送量は6fpsで153,720B/sのまま**。Picoの新しいJPEG経路へ切り替えたわけではない。音声は送らない。

旧RAWキャッシュの読取りは維持する。新規条件version3はJPEGフォルダ、切取りなし、縦横比維持と黒余白を含む。変換キーはvideoID、160×80、FPS、開始、終了、全変換条件の正規化JSONハッシュ。サイズ合計、連番、枚数を検証し、送信時にもJPEGの寸法を確認する。途中ファイルを再生しない。長い動画を全フレームRAMへ展開しない。

変更時点で残っていたZIP2本のJPEG全4,531枚は、内容を変えずに普通のフォルダへ展開・照合し、DBと保存済み選択を切り替えた。元ZIPとSQLiteを `/tmp/picow_jpeg_zip_backup_058ad04604f84f559d202c1a070ab9c1` に保全した。旧切出し画像は比較のために残し、履歴で「JPEG（旧切出し）」と表示する。新しい全体表示は「JPEG（全体）」で区別する。旧切出し履歴を選んだ場合も新条件のキャッシュを使い、なければ取得済み元動画から新条件で作る。ZIP読取りは互換性のためだけに残し、新規ZIPは作らない。

SQLiteには元データの範囲、全編フラグ、時刻原点、実測長、サイズ、変換枚数を記録する。部分データは範囲外を取得済みと扱わない。動画末尾ではメタデータの整数秒丸め差（1秒以内）を許容し、実測終端を保持してフレーム数を実長で検証する。途中区間の不足許容は0.1秒。元の要求が末尾までだった部分データだけ、丸めを考慮して再利用する。

ジョブ終了時にその未完stagingを片付ける。完成キャッシュは自動削除しない。強制終了で残ったstagingは使用量の「その他」に含む。動画削除ではフォルダーを同じ保存領域内にrenameし、DB失敗時は戻す。保存領域不足や取得失敗でも現在の再生を維持する。

## 取得・精密切出し・HTTP403

既存のyt-dlp/ffmpeg/ffprobe/Nodeを使う。`--ignore-config --no-playlist`、既存Nodeを絶対パスで指定する。**ChromeやそのCookieは取得に使わない**。新規取得は `-f bv/b -S res:240,vcodec:h264` で240p相当を優先する。240p以下があれば優先し、それがなければ利用可能な最小解像度へ落ち着く。既存取得済み元動画を解像度変更だけのために再取得しない。[yt-dlpの形式選択](https://github.com/yt-dlp/yt-dlp#format-selection)

指定区間の前後最大1秒を余白にし、`--download-sections '*start-end' --force-keyframes-at-cuts`で取得する。全編取得へ置き換えない。再エンコードを伴う区間取得はネットワーク速度だけでは所要時間が決まらない。保存したsource.originを引いた相対時刻でaccurate seekと変換を行う。包含する既存元動画があれば取得せず切り出す。[yt-dlp取得オプション](https://github.com/yt-dlp/yt-dlp#download-options)、[ffmpeg seek](https://ffmpeg.org/ffmpeg.html#Main-options)

ユーザーの追加指定により、Web変換ではcropを廃止した。元動画全体を縦横比を保って160×80内へ縮小し、余白を黒で埋める。画面いっぱいに引き伸ばしたり、上下左右を切ったりしない。SARは正方画素へ変換し、JPEGのサブサンプリングに合わせて寸法を2の倍数へ丸める。音声は `-an` で除く。

```text
scale=160:80:flags=bicubic:force_original_aspect_ratio=decrease:force_divisible_by=2:reset_sar=1,
pad=160:80:(ow-iw)/2:(oh-ih)/2:color=black
```

実ffmpeg9.0.2のscaleフィルターで各オプションの対応を確認済み。既存JPEGに黒余白を付けるだけでは失われた画面を戻せないため、再変換は保存した元動画から行う。

ffmpeg/ffprobe9.0.2のHTTPS/TLS不足は、ユーザーによるOpenSSL対応再ビルドで解消済み。旧 `/usr/bin` 6.1.1と `/usr/local/bin/*.before-https` は保持。[更新手順](FFMPEG_HTTPS_REBUILD.md)、[HTTPS区間取得の確認](verification/https-section.json)。今回のHTTP403は別のエラーで、YouTubeが動画取得URLへアクセス拒否を返した。

HTTP403について確認した事実:

- 指定動画 `PG_YZZmrqV4` の240p format133をffmpegで取得しようとして403が発生した。
- 同じ動画の新しい取得URLで93秒位置を1フレーム読む試験は、HTTPS format133とHLS format229の両方で成功した。
- 新規取得に `--check-formats` を追加。403の時はジョブ自身の未完データだけを片付け、新たにURLを抽出して低解像度HLS代替を**1回だけ**試す。範囲や画質優先、現在再生は維持する。失敗を隠して無限再試行しない。
- 更新後、ユーザーの同じ区間 **1:34〜最後、6fps** は約74.94秒で取得・JPEG変換が成功。この実再試行ではHLSへの追加再試行は発生しなかった。
- 実取得はH264 **426×240**、余白付き93〜373.633333秒、280.633333秒、7,138,695B。メタデータ終端374秒との差0.366667秒を記録し、切出しは94秒から実終端まで。
- 完成したJPEGは **1,678枚、160×80、2,877,215B**。RAWなら42,956,800B。新キャッシュへ切り替わり、Pico接続と描画カウント増加を確認した。

新しいURLで成功したことから取得URLの間欠的な拒否が疑われるが、YouTube側の拒否条件は確定していない。今後の403を完全に防ぐ保証はない。公式にも間欠403の報告がある。[yt-dlp issue17395](https://github.com/yt-dlp/yt-dlp/issues/17395)。ログでは取得URLを伏せ、署名付きURLや資格情報を保存した検証資料へ載せない。

以前の同区間は約203.9秒後、取得段階の末尾検証で失敗した。その失敗時は実測終端が記録されておらず正確な不足量を遡って断定できない。現在は指定終端、実測終端、丸め許容をジョブへ記録する。この取得時間をJPEG変換単独の時間と混同しない。

## 変換時間と容量の以前の実測（ZIP方式）

JPEG保存導入時の記録。Pi5、既存取得済み本人動画59秒、H264 360×640。取得を含まず、以前のcrop・JPEG書出し・ZIP格納/fsyncを計測した。現在の全体表示・フォルダ方式の時間としては扱わない。

| FPS | 枚数 | JPEG保存量 | 変換時間 | 動画1分換算 | 旧RAW相当 |
|---|---:|---:|---:|---:|---:|
| 6 | 353 | 977,378B | 1.518秒 | 1.544秒 | 9,036,800B |
| 30 | 1,767 | 4,891,787B | 2.276秒 | 2.314秒 | 45,235,200B |

この素材ではJPEG保存はRAWの約10.8%。Pi5の1枚読取り＋JPEG展開＋RGB565/色補正は平均約14.3ms、p95約14.9ms。入力コーデック、解像度、ディスク負荷で変わるため一般保証ではない。ネット取得と区間取得時の再エンコード時間は別で、YouTube全処理の見積りには使わない。[実測JSON](verification/jpeg-benchmark.json)

## JPEGフォルダ・全体表示の実反映（2026-10-08 19時台JST）

現在ユーザーが選んだ小笠原動画 `5cNfpnmRcfU` を、その選択を維持して取得済み元動画から再変換した。新規ネット取得なし、再変換ジョブは4.390秒。元動画は256×144 / 16:9、JPEGは全体を160×80内へ収めて黒余白を付けた2,853枚、合計6,280,748B。専用サービスのみを再起動し、enabled/active、Pico再接続と描画カウント増加を確認。実画面の全体表示と黒余白はユーザー目視確認済み。

画像確認場所:

```text
/home/tane/dev/PicoW/PicoW_Youtube_Player/data/videos/5cNfpnmRcfU/converted/fe6d181e2e19d525192e68f7/
```

`frame00000001.jpg` から `frame00002853.jpg` が通常のJPEGファイルとして並ぶ。

## 実機・UI・ソフト検証

- 全既存19件＋Web/cache/trim/TCP23件の **42件成功（10.940秒）**。URL/範囲/キー、フォルダの欠損・余分なフレーム・寸法違い・使用量、旧ZIP/RAW読取り、横長と縦長動画の全四辺保持・黒余白、末尾丸めと不足拒否、HTTP403の1回再試行、取消し、削除保護、FPSキャッシュ、再起動選択、実TCPの切替/6fps間隔/再接続/周回を確認した。
- 合成long-GOP動画を実yt-dlp/HTTP Range/ffmpegで部分取得し、全編からの同区間と比較した。全FPSの1秒出力は6/12/18/24/30枚。
- 本人動画で新JPEG6fpsキャッシュを登録、Picoへ送信し、周回とPico描画カウント増加を確認。実サービス再起動後も保存済み選択が復元された。
- ユーザー指定動画も上記区間で新規取得・JPEG変換・配信成功。
- Pi5の既存Chrome154を専用/tmpプロファイル・headless/CDPで使い、ダーク色、履歴、入力、ダイアログ、390px幅を確認。通常プロファイルやCookieは読まない。検証後に専用Chromeを終了した。
- 通常/隔離診断Picoビルドの初期確認は成功済み。ただしWeb/JPEG保存の修正にPicoファームの変更・再転送は行っていない。

証拠: [42件テスト](verification/jpeg-folder-fit-tests.log)、[フォルダ・全体表示の実機記録](verification/jpeg-folder-fit.json)、[以前の39件テスト](verification/jpeg-cache-tests.log)、[常用サービス・指定動画](verification/web-service.json)、[403のURL更新読取り](verification/youtube-403-check.json)、[ダークUI検証](verification/dark-ui.json)、[デスクトップ](images/web-player-dark-desktop.png)、[モバイル](images/web-player-dark-mobile.png)。初期Web32件とHTTPS更新後32件の記録もverification/に残す。

その後のLCDガンマ比較でE0/E1一組を追加したB版を転送し、ユーザーが「いい！すごく良くなった。全然ちがうよ。」と目視改善を確認した。反転＋R/B補正、回転/オフセット、画像の明度/彩度は変更していない。Bのガンマを通常ビルド既定ONとして維持する。[比較と復帰記録](diagnostics/LCD_GAMMA_AB.md)を参照。Wi-Fi経路の通信変動があるため安定6fps表示、最大表示停止時間、24時間耐久は未証明。送信期限2秒はsendallの上限であり表示停止の上限ではない。NAS返却後の一時eth0設定の片付けは別作業で、完了確認できていない。

## 構成と再現手順

| ファイル | 内容 |
|---|---|
| `server/web.py` | 標準ライブラリHTTP、JSON API、操作 |
| `server/library.py` | SQLite、範囲別キャッシュ、使用量と確認削除 |
| `server/media.py` | 1本の取消し可能な取得・JPEG変換 |
| `server/frame_cache.py` | JPEGフォルダ（旧ZIP/RAW互換）読取り、送信時RGB565化 |
| `server/playback.py` | 1枚ずつPWF2 TCP配信 |
| `server/static/` | 日本語ダークUI、外部JS/CSS不要 |

依存は既存PillowとPython標準ライブラリ、外部yt-dlp/ffmpeg/ffprobe/Node。Flask等は追加していない。実設定は [設定例](../web-config.example.json) と同じ項目を使い、ffmpegとffprobeは同じ版、Nodeは絶対パス。Git除外の実設定を例で上書きしない。

```bash
cd /home/tane/dev/PicoW/PicoW_Youtube_Player
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
python3 -m server.web --help
```

通常は稼働中のサービスを使う。同じ16151/16152へ手動プロセスを二重起動しない。16150/8080は予約として起動を拒否する。独立試験はlocalhostの別ポートと別data_dirを指定する。認証キーは追加していない。信頼するLANで使い、JSON書込みは同一Originを検証、設定や任意ファイルはHTTP配信しない。


## FPS変更と合格目標

WebのFPS変更は同じ動画/区間について、指定FPSのキャッシュを再利用し、なければ保存済み元動画からJPEG連番へ変換する。完成後に先頭から切り替え、単調時計と指定FPSで送信する。PicoにはFPS固定の待ちを設けず、受信した完成フレームを表示する。FPS変更でPico再書込みは不要。ソフト試験は全5FPSのffmpeg出力枚数、6→12のキャッシュ切替、TCP切替/6fps間隔/再接続を確認済み。

ユーザーの合格目標はハブ導入後の**有線24fps安定描画**、30fpsは余力確認。本番JPEG保存/毎フレームPi5復号の経路に24/30を拒否する固定制限はないが、その有線実効fpsは未測定。既存の有線高fps試験は先にRGB565へ展開した別経路であり、本番性能の保証にはしない。Wi-Fi30fpsは今回の完成条件に含めない。

userサービスはenabled、既存Linger=yes、異常終了時3秒後再起動。実サービス再起動で保存済み選択復元/Pico再接続を確認済みだが、OS再起動後の復帰と24時間耐久は未実測。以前の有線試験の一時プロファイル/旧autoconnect後片付けは未完で、今回のローカルコミット作業ではネットワークを変更しない。
