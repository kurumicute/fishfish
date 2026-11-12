# 新手教學：從下載到開始「摸魚」閱讀

這份教學帶你一步一步把 Novel Terminal 裝起來、打開第一本小說，並學會最常用的操作。
完整指令與設定請看 [README.md](README.md)。

---

## 1. 下載

### 方法 A：免安裝版（不用裝 Python，推薦一般使用者）

1. 到專案的 [Releases 頁面](https://github.com/kurumicute/fishfish/releases) 下載 `NovelTerminal-win64.zip`
2. 解壓縮到任意資料夾（例如 `D:\NovelTerminal`）
3. 雙擊資料夾裡的 `NovelTerminal.exe` 即可，直接跳到 [第 3 步](#3-打開第一本小說)

> 若 Windows 跳出「Windows 已保護您的電腦」，點「其他資訊 → 仍要執行」（未簽章的程式都會這樣）。

### 方法 B：原始碼版（需要 Python 3.11+）

**用 Git：**

```bat
git clone https://github.com/kurumicute/fishfish.git
cd fishfish
```

**不用 Git：** 在 GitHub 頁面點綠色的 `Code` → `Download ZIP`，解壓縮後進入資料夾。

---

## 2. 安裝（只有原始碼版需要）

1. 安裝 [Python 3.11 以上](https://www.python.org/downloads/)
   安裝畫面最下方務必勾選 **Add python.exe to PATH**
2. 雙擊 `install.bat`
   - 會自動建立 `.venv` 虛擬環境並安裝 `rich`、`ebooklib`、`beautifulsoup4`
   - 看到 `Done. Run run.bat to start reading.` 就完成了
3. 之後每次啟動都只要雙擊 `run.bat`

> 建議用 **Windows Terminal** 開啟（Win11 內建），符號與顏色顯示最完整。
> 如果看到方框或亂碼，到 `config/settings.json` 把 `ascii_glyphs` 改成 `true`。

---

## 3. 打開第一本小說

先用內附範例試試看：

```bat
run.bat samples\sample.txt
```

（免安裝版：`NovelTerminal.exe samples\sample.txt`）

開啟自己的小說有三種方式：

| 方式 | 做法 |
|---|---|
| 啟動時指定 | `run.bat D:\books\小說.txt` |
| 程式內開啟 | 在輸入框打 `/open ` 然後把檔案**拖曳**進視窗，按 Enter |
| 從最近閱讀 | 打 `/open` 看清單，再用 `/open 2` 開第 2 本 |

支援 **TXT**（UTF-8 / Big5 / GB18030 等自動判斷）與 **EPUB**，章節會自動切好。

---

## 4. 基本閱讀操作

| 想做的事 | 按鍵 / 指令 |
|---|---|
| 下一頁 | `空白鍵`、`Enter`、`PageDown` |
| 上一頁 | `PageUp` |
| 上 / 下一章 | `←` / `→` |
| 看目錄、跳章 | `/toc`、`/goto 12` |
| 調整字體大小 | `/font +`、`/font -`、`/font 3` |
| 查看進度 | `/progress` |
| 所有快捷鍵 | `?` 或 `/help` |
| 儲存並離開 | `Ctrl+C` 或 `/quit` |

進度會自動存檔，下次直接 `run.bat`（不加檔名）就會回到上次讀到的地方。

---

## 5. 摸魚必學

### 老闆來了：`Ctrl+Q`

按一下 `Ctrl+Q`，畫面立刻變成純程式碼 + AI 問答介面，**完全不顯示小說內容、書名與進度**。
你甚至可以在這個畫面輸入問題（例如 `review this function`），它會分析程式碼並回答。
再按一次 `Ctrl+Q` 回到原本的閱讀位置。

### 調整「偽裝濃度」

小說之間會穿插假的工作訊息與程式碼片段，濃度可調：

```text
/effort low       小說 90%，偶爾出現工作訊息（最好讀）
/effort medium    預設，78% 小說
/effort high      64% 小說，看起來最像在認真工作
/mode reading     關掉所有偽裝，純閱讀
/mode mixed       恢復混合模式
```

### 換成你自己的程式碼

讓穿插的程式碼片段變成你手上真實的專案，更不容易穿幫：

```text
/code D:\work\my-project
/code D:\work\main.cpp;D:\work\utils.py
/code off
```

程式只會**讀取文字**來顯示，不會執行或修改任何檔案。

---

## 6. 個人化設定

編輯 `config/settings.json`（用記事本即可）：

- `header`：最上方顯示的標題、版本、模型名稱、路徑
- `theme`：`claude` / `mono` / `retro`
- `show_progress`：底列是否顯示書名與進度（怕被看到可設 `false`）
- `language`：工作訊息語言 `en` 或 `zh`

用指令改過的設定會存在 `data/progress.db`，優先於 `settings.json`。

---

## 7. 常見問題

**Q：雙擊 install.bat 顯示 `python not found`？**
重新安裝 Python 並勾選 *Add python.exe to PATH*，然後重開 CMD。

**Q：出現 `Please run this in CMD / PowerShell / Windows Terminal`？**
請在真正的終端機視窗執行，不要在 IDE 的輸出面板或透過管線執行。

**Q：中文是亂碼？**
`run.bat` 會自動切換 UTF-8。若小說本身亂碼，通常是特殊編碼，先用記事本「另存新檔 → UTF-8」再開。

**Q：想清空所有進度？**
關閉程式後刪除 `data/progress.db`。

---

## 8. 自己打包 exe（進階）

```bat
build.bat
```

完成後在 `release/` 會產生 `NovelTerminal-win64.zip`（免安裝版）與 `novel-terminal-src.zip`（原始碼）。
