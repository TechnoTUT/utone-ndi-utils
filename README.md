# utone-ndi-utils
NDIを活用することでDJイベント "The Utopia Tone" の映像伝送をIPネットワーク上に移行します。  
PythonとSDL2を使用してNDIソースを受信し全画面表示を行ったり、OpenCVを使用してNDIソースの送信を行います。また、FastAPIによるWeb APIおよびブラウザUIからの遠隔操作に対応しています。

## 使い方
動作にはPython3及びavahi-daemon、libgl1-mesa-dev、portaudio19-devが必要です。
以下のコマンドで必要なパッケージをインストールしてください。
```bash
# Debian/Ubuntu
$ sudo apt install git curl avahi-daemon libgl1-mesa-dev portaudio19-dev
# Fedora
$ sudo dnf install git curl avahi mesa-libGL-devel portaudio-devel
$ curl -LsSf https://astral.sh/uv/install.sh | sh
```

次に、リポジトリをクローンし、仮想環境を作成して依存関係をインストールします。
```bash
$ git clone https://github.com/TechnoTUT/utone-ndi-utils.git
$ cd utone-ndi-utils
$ uv venv
$ uv pip install -r requirements.txt
```

---

## 起動コマンド

統合CLI `main.py` から `rx` / `tx` / `web` の各機能を統一的に実行できます。

### 1. Web API / ブラウザUI
ブラウザや外部REST API経由でNDIソースの探索、受信（RX）の開始・ソース切り替え、送信（TX）の開始・停止などを遠隔操作できます。
```bash
$ uv run main.py web --host 0.0.0.0 --port 8000
```
- APIドキュメント（Swagger UI）: `http://localhost:8000/docs`

### 2. NDIソースの受信・全画面表示 (RX)
```bash
$ uv run main.py rx -s "<NDI Source Name>" --fullscreen
```
`<NDI Source Name>`を省略した場合は、ネットワーク上のNDIソースを自動検索し、対話式メニューから選択して起動できます。

### 3. NDIソースの送信 (TX)
```bash
$ uv run main.py tx
```
接続されているカメラ・マイクデバイスの確認:
```bash
$ uv run main.py tx --list-devices
```

---

## ディレクトリ構成
```
utone-ndi-utils/
├── core/                   # 低レベル共通コアロジック
│   ├── rx.py               # SDL2初期化、OpenGL描画、フレーム同期、NDI受信定義
│   └── tx.py               # カメラ取得スレッド、映像/音声NDI送信スレッド
├── cli/                    # コマンドラインUI定義
│   ├── menu.py             # 対話型NDIソース選択メニュー
│   ├── rx_cmd.py           # rx コマンド定義
│   └── tx_cmd.py           # tx コマンド定義
├── backend/                # FastAPI Web API & プロセス制御
│   ├── models.py           # Pydantic スキーマ
│   ├── ndi_scanner.py      # NDIソース自動探索サービス
│   ├── devices.py          # カメラ・オーディオデバイス検出
│   ├── rx_runner.py        # RXプロセスコントローラー
│   ├── tx_runner.py        # TXプロセスコントローラー
│   └── main.py             # REST APIエンドポイント
├── main.py                 # 統合CLIエントリーポイント (rx / tx / web)
├── requirements.txt
└── systemd-example/        # systemd用ユニット設定例
```

---

## 自動起動設定 (systemd)
Systemdを使用して自動起動する場合は、以下の手順を実行します。GUIなしの環境でも動作します。  
`ExecStart` と `WorkingDirectory` のパスを環境に合わせて設定してください。
```bash
$ mkdir -p ~/.config/systemd/user
$ cp systemd-example/ndi-rx.service ~/.config/systemd/user/
$ vim ~/.config/systemd/user/ndi-rx.service
```

自動起動を有効にします。
```bash
$ systemctl --user daemon-reload
$ systemctl --user enable --now ndi-rx.service
```

システム起動時にログインなしで自動起動する場合は、lingerを有効にします。
```bash
$ sudo loginctl enable-linger username
```