# Novel Terminal — 純 CMD 終端機小說閱讀器

介面仿照 Claude Code CLI 的終端機小說閱讀器。小說保留原始中文；其餘介面文字（工作訊息、指令回饋、說明、錯誤訊息）皆為英文。畫面上的「工作訊息」與「程式碼片段」全部由本機模板與你指定的真實程式碼檔產生：

- 不連網、不呼叫任何 AI API、不啟動 Web Server / 瀏覽器 / GUI 視窗
- 不執行、不編譯匯入的程式碼（只讀取文字顯示）
- 小說內容逐字保留原始中文、標點、段落，不翻譯、不刪改（換行位置套用中文避頭尾規則）

> 第一次使用？請看 **[新手教學 TUTORIAL.md](TUTORIAL.md)**

## 安裝與啟動（Windows）

1. 安裝 Python 3.11 以上（安裝時勾選 *Add python.exe to PATH*）
2. 雙擊 `install.bat`：建立 `.venv` 並安裝依賴（只有這一步需要網路）
3. 雙擊 `run.bat`，或在 CMD / PowerShell / Windows Terminal 中執行：

```bat
run.bat                          :: 恢復上次閱讀
run.bat D:\books\小說.txt         :: 直接開啟
run.bat 小說.epub --code D:\project\main.go
```

建議使用 Windows Terminal（預設字型 Cascadia 可完整顯示吉祥物與 `⏵ ◐ ⎿ ❯` 等符號）。

## 畫面

```
 ▐▛███▜▌   Claude Code v2.1.322
▝▜█████▛▘  Opus 5.5 · Claude Pro
  ▘▘ ▝▝    ~\Desktop

● 第二章　不該出現的船                                      ← 小說（主要內容）

● Running document check                                  ← 依比例穿插的本機工作訊息
  ⎿  Scanning file format...
     Document check complete

  　　午夜過後，霧裡出現了一艘沒有掛旗的船。

● Read(core/reader.py)                                    ← 真實程式碼片段
  ⎿  Read 6 lines (L80-85)
        80 def split_snippets(...)
✳ Processing next section… (1s · esc to interrupt)                 ◐ medium · /effort
──────────────────────────────────────────────────────────────────────────────────────
❯ Try "fix lint errors"
──────────────────────────────────────────────────────────────────────────────────────
  ⏵⏵ auto mode on (shift+tab to cycle) · ← for agents       sample.txt · 2/4 · 41.3%
```

- Header（吉祥物與三行文字）和 Claude Code 一樣屬於對話內容，只出現在每章最上方，往下捲動就會捲走，不會固定在頂端
- Header 三行與 cwd 可在 `settings.json` 的 `header` 修改（`cwd` 留空則顯示目前目錄）
- 底列右側灰字為「檔名 · 章節 · 全書進度」，`show_progress: false` 可隱藏
- 完整進度（段落、字元位置、編碼、比例）請用 `/progress`

## 指令

| 指令 | 說明 |
|---|---|
| `/open [path\|number]` | 開啟 TXT / EPUB；不加參數列出最近閱讀，`/open 2` 開啟清單第 2 本 |
| `/code [path\|off\|default]` | 載入程式碼參考檔或資料夾；`off` 關閉；`default` 使用內建 |
| `/next` `/prev` | 下一章 / 上一章 |
| `/continue` | 繼續閱讀（下一頁，章末自動進下一章） |
| `/progress` | 閱讀進度與本章實際內容比例 |
| `/toc` `/goto N` | 章節列表 / 跳到第 N 章 |
| `/font [1-5\|+\|-]` | 字體大小 |
| `/ratio 78 12 7 3` | 小說 / 工作訊息 / 程式碼 / 狀態紀錄 比例；也可 `/ratio code 10`、`/ratio reset` |
| `/effort [low\|medium\|high]` | 比例預設組：low 90/6/3/1、medium 78/12/7/3、high 64/17/14/5（顯示於 `◐ medium · /effort`） |
| `/mode [mixed\|reading]` | 終端機混合模式 / 純閱讀模式 |
| `/theme [claude\|mono\|retro]` | 顯示風格 |
| `/log` | 工作紀錄 |
| `/clear` | 清除畫面與工作紀錄 |
| `/help` | 指令與快捷鍵 |
| `/quit` | 儲存並離開 |

## 快捷鍵

| 按鍵 | 動作 |
|---|---|
| `PageUp` / `PageDown` | 上一頁 / 下一頁 |
| `空白` / `Enter`（輸入框為空） | 下一頁；面板開啟時 Enter 關閉面板 |
| `←` / `→`（輸入框為空） | 上一章 / 下一章 |
| `↑` / `↓` | 輸入框為空時捲動一行；輸入中為指令歷史 |
| `Home` / `End` | 章首 / 章尾 |
| `Tab` | 補完指令 |
| `Shift+Tab` | 輪替底列模式文字（auto mode / plan mode / accept edits / ? for shortcuts，純外觀） |
| `?`（輸入框為空） | 顯示快捷鍵 |
| `Esc` | 清除輸入 → 關閉面板 → 中斷進行中的模擬工作（顯示 `Interrupted by user`） |
| `Ctrl+Q` | 切換到純程式碼＋模擬 Claude Code 問答畫面（不顯示任何小說內容、書名或進度）；再按一次回到原本閱讀位置。偽裝畫面中輸入問題按 Enter，會依問題類型（解釋／review／bug／錯誤處理）分析程式碼後回答；問題中提到的函式會被優先讀取，找到問題時附上假的修改區塊 |
| `Ctrl+C` | 儲存進度並安全離開 |

路徑可以直接把檔案拖曳到視窗貼上（含引號也可以），中文檔名可直接輸入。

## 支援格式

- **TXT**：UTF-8、UTF-8 BOM、UTF-16、Big5（含 HKSCS）、GB18030 自動判斷。自動偵測「第N章／回／節／卷」、「序章／楔子／番外」、「Chapter N」等標題；章節標題前的內容歸為 `Preface`；若沒有章節標題，依字數自動切成 `Part N`。
- **EPUB**：依 spine 順序，每個內容文件一章；章節名稱取自目錄 (TOC)，其次為 `<h1>`–`<h3>`；略過導覽頁與純圖片頁；移除所有 HTML 標籤。
- 單章超過 30,000 字會在段落邊界切為 `(cont. N)`；檔案在背景執行緒載入，不會卡住畫面。
- 程式碼參考：支援 100 多種副檔名（C/C++/Arduino `.ino`、Python、Go、JS/TS/Vue/Svelte、Java/Kotlin/Swift/Dart、Rust、C#、Lua、Ruby、PHP、SQL、Shell/PowerShell、Terraform、Protobuf、YAML/TOML/JSON 等），以及 `Dockerfile`、`Makefile`、`CMakeLists.txt` 等無副檔名檔案；可指定資料夾（略過 `.git`、`node_modules`、`.venv` 等）。二進位檔會被拒絕。
- 多個來源：`/code a.cpp;src\utils.py;D:\project\lib`（分號分隔，或用引號包住多個路徑），`/code add <路徑>` 追加。
- 程式碼片段以完整的函式／區塊為單位切割；語法高亮配色與 Claude Code 相同（Monokai Extended）。
- 部分程式碼會以假的修改區塊 `● Update(檔案)` 呈現：紅底 `-` 為原始行、綠底 `+` 為改寫後的行（只是顯示，不會修改任何檔案）。

## 設定 `config/settings.json`

| 欄位 | 說明 |
|---|---|
| `ratio` | 預設內容比例（小說最低 40%） |
| `mode` | `mixed` 或 `reading` |
| `font_size` | 1–5 |
| `theme` | `claude` / `mono` / `retro` |
| `language` | 工作訊息語言：`en`（預設）或 `zh` |
| `effort` / `footer_mode` | 初始 effort 與底列模式（`auto` / `plan` / `edits` / `default`） |
| `show_progress` | 底列右側是否顯示進度 |
| `ascii_glyphs` | `true` 改用 ASCII 符號（若字型無法顯示吉祥物或 `⏵ ◐ ⎿ ❯`） |
| `ambient` | 自動工作訊息的間隔秒數範圍（預設 35–90 秒） |
| `code` / `novel` | 程式碼片段行數與大小上限；小說大小上限、自動分段與單章切割字數 |
| `header` | `title` / `version` / `model` / `cwd` |
| `placeholders` | 輸入框提示文字（使用第一個） |

透過指令修改的設定（比例、字體、主題、模式、effort、底列模式、程式碼來源）會存入 SQLite，優先於 `settings.json`。

## 閱讀進度

`data/progress.db`（SQLite）保存：檔案路徑、檔名、章節、段落、章內字元位置、字體大小、內容比例、程式碼來源、模式，以及全域設定。翻頁後約 1.5 秒自動寫入，切換章節、開啟其他書、`/quit`、`Ctrl+C` 時立即寫入。下次啟動自動恢復；若原始小說檔不存在只會提示，**不會刪除進度**。

## 已知限制

- **字體大小**：Windows Terminal 不允許程式更改字型，`/font` 以「閱讀欄寬＋段落間距」模擬；在傳統 CMD 視窗 (conhost) 會另外嘗試調整實際字型大小，離開時還原。
- 混排比例以「顯示行數」計算，單章很短時比例會偏離設定；`/progress` 可查看本章實際比例。
- 未指定程式碼檔時，以本專案自己的原始碼作為來源（其中的中文註解也會原樣顯示）；`/code off` 可關閉。
- 閱讀期間 Ctrl+C 以按鍵方式處理（與 Claude Code 相同），離開時恢復主控台原本的設定。

## 測試

```bat
:: 單元測試（解析、編碼、混排比例、進度、版面、指令）
.venv\Scripts\python.exe -m unittest discover -s tests -v

:: 端對端測試：在真實 Windows 主控台 (ConPTY) 啟動 run.bat，送出實際按鍵並檢查畫面（使用暫存資料庫）
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe tests\e2e_conpty.py

:: 不需互動終端機的畫面快照（不寫入進度）
.venv\Scripts\python.exe main.py samples\sample.txt --snapshot --chapter 2 --cmd "/font 4"
```
