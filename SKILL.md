---
name: mycodo-scd41-dry-run
description: Inspect SCD41 data and produce dry-run plans only.
version: 0.1.0
author: Jeff Wu, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [mycodo, scd41, dry-run, safety]
    related_skills: []
---

# SCD41 唯讀／離線決策 Skill

針對 Jeff 的 A 箱：Windows 端標準函式庫 Python 讀取 SCD41 保存資料，或經核准使用 HTTPS GET。**此 skill 無任何致動能力；不可把計畫當成已執行。**

## When to Use

- 檢查 A 箱保存的 SCD41 API 報告、資料時間與缺欄位。
- 用明確標示的離線測試資料驗證 dry-run 限制。
- 操作者另外核准唯讀網路時，讀取 Mycodo 的指定 GET 路徑。
- 不適用：啟用控制、設定排程、操作 GPIO、讀取／控制 B 箱。

## Prerequisites

Python 3.10+。從專案根目錄執行，無第三方套件或安裝步驟。API key 只用 `getpass` 或 `MYCODO_API_KEY` 環境變數，不能進入命令列、對話、檔案或報告。未知參數回報固定錯誤代碼，不回顯內容。

## How to Run

使用 `terminal`，設定 workdir 為使用者指定的專案根目錄，不要猜本機路徑：

```python
terminal(command="python -m unittest discover -s tests -v", workdir=PROJECT)
terminal(command="python -m mycodo_scd41 replay --report fixtures/recorded-report.json --config config.example.json", workdir=PROJECT)
terminal(command="python -m mycodo_scd41 simulate --fixture fixtures/offline-test.json", workdir=PROJECT)
```

只有另獲使用者核准唯讀連線，才可：

```python
terminal(command="python -m mycodo_scd41 read --url https://your-pi.example --ca-pem trusted-ca.pem", workdir=PROJECT)
```

不能使用 `--execute`，即使操作者翻轉 config 亦不可；本版直接拒絕。無 POST／致動方法。

## Quick Reference

- `replay --report FILE [--config FILE]`：保存資料，不修改原始 timestamp。
- `simulate --fixture FILE`：離線 synthetic TEST，不是現在的 Pi 數據。
- `read --url HTTPS_ORIGIN [--ca-pem FILE] [--config FILE]`：固定 allowlist GET，TLS 驗證與拒絕 redirect。
- `--audit FILE`：追加去除原始錯誤文字的 JSONL。
- `--html FILE`：escaped HTML；自行建立目的資料夾。

## Procedure

1. 用 `read_file` 閱讀 README、config 與來源標示，確認 A 箱及 dry-run。
2. 核對 input UUID、CH0 ppm／CH1 C／CH2 percent／CH3 C／CH4 Pa；只允許固定霧化器 GPIO5、風扇 GPIO16，channel 0。
3. 執行保存資料 replay 或離線 fixture，必須確認 `source` 不是被誤當成現場資料。
4. 閱讀 `reading_status` 與 blockers。門檻、freshness、持續時間／冷卻未核准時，不得自行補值。
5. 確認 `executed_commands` 為空，再報告計畫或阻擋原因。未知輸出 state／缺 `output_id` 關聯不能用陣列索引猜。
6. 若操作者要求真控制，停止並閱讀 `docs/future-control-checklist.md`；本版無法啟用，不得另用 curl、SSH、pinctrl 或上游 shell 繞過。

## Pitfalls

- 本研究菇種統一為秀珍菇；公開 dry-run 設定仍要求參數來源與人工核准。禁止引用上游 Lion's Mane／oyster 門檻替代。
- A 箱只有 SCD41；無 SHT45、相機、多工器、繼電器或水位感測器。B 箱完全被動且人工紀錄。
- SCD41 已有 4.0 溫度偏移、self calibration false；不要變更或再扣偏移。
- 600 秒僅 API 查詢回溯範圍，不是安全 stale 設定。null freshness 阻擋計畫，但仍展示讀值。
- 不能宣稱 Pi fail-safe 已部署；安裝紀錄將後備規則列待辦。實際 InfluxDB 版本未驗證，不做版本／遷移聲明。
- 水量人工設定不等於硬體 interlock；冷卻未持久化、無並行執行保護，僅供 dry-run。

## Verification

全套 unittest 必須通過；每次報告執行指令數為 0。舊資料不改時間、不當現在；HTML 跳脫內容，審計不存 key。上游 Setasoma 與 MIT 授權見 `THIRD_PARTY`。禁止 GitHub publish、安裝或硬體網路呼叫，除非使用者另行明確授權。
