# FFmpeg 9.0.2をHTTPS対応へ更新する手順

2026-10-08 JST。ユーザーが手動で行う手順。開発タスクからOS/パッケージ/サービスの変更や以下の再ビルドを実行していない。

## 現況

- `/usr/local/bin/ffmpeg`とffprobeは9.0.2。現在HTTPS/TLSなし。
- `/usr/bin/ffmpeg`とffprobeは6.1.1、HTTPS/TLSあり。旧版は削除しない。
- `pkg-config --modversion openssl`は3.0.13。開発用ライブラリを確認済みなのでAPT追加不要。
- 現ffmpegはGPL設定。現物configureがOpenSSL3との組み合わせに`--enable-version3`を要求するため、`--enable-openssl --enable-version3`を追加する。
- 確認済み公式ソースと既存codec設定を使う。TLSは[FFmpeg公式説明](https://ffmpeg.org/ffmpeg-protocols.html#tls)参照。

## 1. ビルド

各工程の成功を確認して次へ進む。`make distclean`はビルド生成物を消し、導入済み/usr/local/binや元動画は変更しない。新しいinstall先を使う。

```bash
cd /home/tane/Documents/Codex/2026-10-08/task-5/ffmpeg-9.0.2
make distclean
./configure \
  --prefix=/home/tane/Documents/Codex/2026-10-08/task-5/ffmpeg-9.0.2-https-install \
  --disable-doc --disable-debug --disable-ffplay \
  --enable-gpl --enable-version3 --enable-openssl \
  --enable-libx264 --enable-libx265 --enable-libmp3lame \
  --enable-libopus --enable-libvpx --enable-libaom --enable-libdav1d
make -j2
make install
```

## 2. 入替前の確認

```bash
/home/tane/Documents/Codex/2026-10-08/task-5/ffmpeg-9.0.2-https-install/bin/ffmpeg -hide_banner -protocols
/home/tane/Documents/Codex/2026-10-08/task-5/ffmpeg-9.0.2-https-install/bin/ffprobe -hide_banner -protocols
```

両方に`https`/`tls`があることを確認する。

## 3. 旧版保管と同じ版の組へ入替

動画取得/変換が終わった状態で行う。

```bash
sudo cp -a --update=none /usr/local/bin/ffmpeg /usr/local/bin/ffmpeg.before-https
sudo cp -a --update=none /usr/local/bin/ffprobe /usr/local/bin/ffprobe.before-https
sudo install -m 755 \
  /home/tane/Documents/Codex/2026-10-08/task-5/ffmpeg-9.0.2-https-install/bin/ffmpeg \
  /usr/local/bin/ffmpeg
sudo install -m 755 \
  /home/tane/Documents/Codex/2026-10-08/task-5/ffmpeg-9.0.2-https-install/bin/ffprobe \
  /usr/local/bin/ffprobe
/usr/local/bin/ffmpeg -version
/usr/local/bin/ffprobe -version
```

## 4. 許可された本人動画で区間取得

`https`一覧だけで完了とはしない。HTTPS経由で取得して、保存した映像をffprobeで確認する。

```bash
/usr/local/bin/yt-dlp \
  --ignore-config --no-playlist \
  --js-runtimes node:/home/tane/.nvm/versions/node/v24.20.0/bin/node \
  --ffmpeg-location /usr/local/bin \
  -f 'bv[height<=720][vcodec^=avc1]/b[height<=720][vcodec^=avc1]' \
  -S res:480 \
  --download-sections '*0-5' --force-keyframes-at-cuts \
  --downloader-args 'ffmpeg_o:-threads 2' \
  -o '/tmp/picow-https-check.%(ext)s' \
  'https://youtu.be/v2fEwXS0XeM'
/usr/local/bin/ffprobe -v error -select_streams v:0 \
  -show_entries stream=codec_name,width,height:format=duration \
  -of json /tmp/picow-https-check.mp4
```

完成条件はffmpeg/ffprobeが同じ9.0.2、両方HTTPS/TLSあり、区間取得成功、映像とおよそ5秒の長さを確認すること。Webの未取得動画で開始終了指定も別途再検証する。

## 戻す場合

```bash
sudo install -m 755 /usr/local/bin/ffmpeg.before-https /usr/local/bin/ffmpeg
sudo install -m 755 /usr/local/bin/ffprobe.before-https /usr/local/bin/ffprobe
```

代替案としてプロジェクト`web-config.json`の`ffmpeg`を`/usr/bin/ffmpeg`、`ffprobe`を`/usr/bin/ffprobe`へ**両方**指定できる。PATH全体の変更や9.0.2の削除は必要ない。最新版再ビルドを希望したユーザーの判断を優先し、本タスクからこの代替設定を勝手に適用していない。

## 更新後の実確認（2026-10-08 17:15 JST）

ユーザーの更新後、ffmpeg/ffprobeとも9.0.2、OpenSSL/version3設定、HTTPS/TLSあり、before-httpsバックアップ両方ありを確認した。Web APIで未キャッシュの本人動画5〜10秒を取得し、余白付き4〜11秒（7.0秒、PTS開始0）から160×80/6fps/30枚・768,000Bへ変換成功。同条件再要求のキャッシュ再利用と、部分元動画を全編と誤認しないことを確認。全32テストも成功。[実測結果](verification/https-section.json)。
